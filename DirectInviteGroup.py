import configparser
import json
import asyncio
import random
from telethon import TelegramClient
from telethon.errors import FloodWaitError, UserIdInvalidError, PeerIdInvalidError
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import InputPeerUser

# ------------------ ЧТЕНИЕ КОНФИГА ------------------
config = configparser.ConfigParser()
config.read("config.ini")

api_id = int(config['Telegram']['api_id'])
api_hash = config['Telegram']['api_hash']
username = config['Telegram']['username']
client = TelegramClient(username, api_id, api_hash)

# ------------------ СБОР УЧАСТНИКОВ ------------------
async def collect_users(source_link):
    print(f"📥 Получаем участников из: {source_link}")
    try:
        if source_link.startswith('@'):
            source_link = source_link[1:]
        entity = await client.get_entity(source_link)
        participants = await client.get_participants(entity, aggressive=True)

        data = []
        for p in participants:
            if p.id and p.access_hash:  # Проверяем наличие базовых данных
                data.append({
                    "id": p.id,
                    "access_hash": p.access_hash,
                    "username": p.username,
                    "first_name": p.first_name
                })

        with open("channel_users.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"✅ Сохранено {len(data)} пользователей в channel_users.json")
    except Exception as e:
        print(f"❌ Ошибка при сборе пользователей: {e}")

# ------------------ ДОБАВЛЕНИЕ В КАНАЛ ------------------
async def add_users_to_channel():
    try:
        with open('channel_users.json', 'r', encoding='utf-8') as file:
            users = json.load(file)
    except FileNotFoundError:
        print("❌ Файл channel_users.json не найден! Запустите сбор пользователей (режим 1).")
        return
    except json.JSONDecodeError:
        print("❌ Ошибка чтения channel_users.json: некорректный формат JSON")
        return

    print(f"📊 Загружено {len(users)} пользователей")

    target_channel_input = input("Введите ссылку на канал куда добавлять: ").strip()

    target_channel = None
    try:
        target_channel = await client.get_entity(target_channel_input)
        print(f"✅ Уже участник канала: {target_channel.title}")
    except (ValueError, PeerIdInvalidError):
        print("🤝 Вступаем в канал...")
        try:
            if "t.me/+" in target_channel_input:
                hash_value = target_channel_input.split("+")[1]
                await client(ImportChatInviteRequest(hash_value))
                print("✅ Успешно вступили в приватный канал")
            elif "t.me/joinchat/" in target_channel_input:
                hash_value = target_channel_input.split("joinchat/")[1]
                await client(ImportChatInviteRequest(hash_value))
                print("✅ Успешно вступили в приватный канал")
            else:
                await client(JoinChannelRequest(target_channel_input))
                print("✅ Успешно вступили в публичный канал")
            target_channel = await client.get_entity(target_channel_input)
        except Exception as e:
            print(f"❌ Ошибка вступления в канал: {e}")
            return

    if target_channel is None:
        print("❌ Не удалось получить информацию о канале!")
        return

    print(f"🎯 Целевой канал: {target_channel.title}")

    success_count = 0
    fail_count = 0
    skip_count = 0

    for i, user in enumerate(users, 1):  # Убрано random.shuffle
        user_id = user.get('id')
        access_hash = user.get('access_hash')
        username_display = user.get('username') or user.get('first_name') or "Unknown"

        if not user_id or not access_hash:
            print(f"❌ [{i}/{len(users)}] Нет user_id или access_hash у {username_display}")
            fail_count += 1
            continue

        # Проверка типа данных
        try:
            user_id = int(user_id)
            access_hash = int(access_hash)
        except (TypeError, ValueError):
            print(f"❌ [{i}/{len(users)}] Неверный формат user_id или access_hash для {username_display}")
            fail_count += 1
            continue

        me = await client.get_me()
        if user_id == me.id:
            print(f"⚠️ [{i}/{len(users)}] Пропускаем себя: {username_display}")
            skip_count += 1
            continue

        try:
            user_entity = InputPeerUser(user_id, access_hash)
            # Проверка валидности перед добавлением
            await client.get_entity(user_entity)
            await client(InviteToChannelRequest(
                channel=target_channel,
                users=[user_entity]
            ))
            success_count += 1
            print(f"✅ [{i}/{len(users)}] Добавлен: {username_display}")

        except FloodWaitError as e:
            print(f"⏳ [{i}/{len(users)}] Ожидаем {e.seconds} секунд...")
            await asyncio.sleep(e.seconds + 1)
            try:
                await client(InviteToChannelRequest(
                    channel=target_channel,
                    users=[user_entity]
                ))
                success_count += 1
                print(f"✅ [{i}/{len(users)}] Добавлен после ожидания: {username_display}")
            except Exception as retry_e:
                fail_count += 1
                _handle_add_error(retry_e, username_display, i, len(users))

        except (UserIdInvalidError, PeerIdInvalidError) as e:
            print(f"❌ [{i}/{len(users)}] Неверный ID или доступ пользователя: {username_display} - {str(e)}")
            fail_count += 1
        except Exception as e:
            fail_count += 1
            _handle_add_error(e, username_display, i, len(users))

        # Анти-бан паузы
        if success_count > 0 and success_count % 10 == 0:
            long_pause = random.randint(20, 40)
            print(f"⏸️ Длинная пауза {long_pause} сек после {success_count} добавлений...")
            await asyncio.sleep(long_pause)
        else:
            pause = random.uniform(1.5, 2.0)  # Фиксированная задержка 1.5-2 секунды
            await asyncio.sleep(pause)

    print(f"\n📊 ИТОГ:")
    print(f"✅ Успешно добавлено: {success_count}")
    print(f"⚠️ Пропущено: {skip_count}")
    print(f"❌ Не добавлено: {fail_count}")

# ------------------ ОБРАБОТКА ОШИБОК ------------------
def _handle_add_error(error, username, current, total):
    error_msg = str(error).upper()
    if "USER_ALREADY_PARTICIPANT" in error_msg:
        print(f"⚠️ [{current}/{total}] Уже в канале: {username}")
    elif "CHAT_ADMIN_REQUIRED" in error_msg:
        print(f"❌ [{current}/{total}] Нет прав администратора для добавления: {username}")
    elif "USER_PRIVACY_RESTRICTED" in error_msg:
        print(f"❌ [{current}/{total}] Настройки приватности: {username}")
    elif "FLOOD_WAIT" in error_msg or "FLOOD" in error_msg:
        print(f"⏳ [{current}/{total}] Ограничение по флуду: {username}")
    elif "USER_NOT_MUTUAL_CONTACT" in error_msg:
        print(f"❌ [{current}/{total}] Нет взаимного контакта: {username}")
    else:
        print(f"❌ [{current}/{total}] Ошибка для {username}: {str(error)}")

# ------------------ MAIN ------------------
async def main():
    await client.start()
    me = await client.get_me()
    print(f"✅ Авторизован как: {me.first_name} (@{me.username})")

    mode = input("Выберите режим: [1] Сбор пользователей, [2] Добавление в канал: ").strip()

    if mode == "1":
        source = input("Введите ссылку на чат/канал для сбора: ").strip()
        await collect_users(source)
    elif mode == "2":
        await add_users_to_channel()
    else:
        print("❌ Неверный выбор")

if __name__ == "__main__":
    asyncio.run(main())