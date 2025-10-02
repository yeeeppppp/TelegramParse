import configparser
import json
import asyncio
import random
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import InputPeerUser

# ------------------ ЧТЕНИЕ КОНФИГА ------------------
config = configparser.ConfigParser()
config.read("config.ini")

api_id = config['Telegram']['api_id']
api_hash = config['Telegram']['api_hash']
username = config['Telegram']['username']
client = TelegramClient(username, api_id, api_hash)


# ------------------ СБОР УЧАСТНИКОВ ------------------
async def collect_users(source_link):
    print(f"📥 Получаем участников из: {source_link}")
    participants = await client.get_participants(source_link)

    data = []
    for p in participants:
        data.append({
            "id": p.id,
            "access_hash": p.access_hash,
            "username": p.username,
            "first_name": p.first_name
        })

    with open("channel_users.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✅ Сохранено {len(data)} пользователей в channel_users.json")


# ------------------ ДОБАВЛЕНИЕ В КАНАЛ ------------------
async def add_users_to_channel():
    with open('channel_users.json', 'r', encoding='utf-8') as file:
        users = json.load(file)

    print(f"📊 Загружено {len(users)} пользователей")

    target_channel_input = input("Введите ссылку на канал куда добавлять: ")

    target_channel = None
    try:
        target_channel = await client.get_entity(target_channel_input)
        print(f"✅ Уже участник канала: {target_channel.title}")
    except ValueError:
        print("🤝 Вступаем в канал...")
        try:
            if "t.me/+" in target_channel_input:
                hash = target_channel_input.split("+")[1]
                await client(ImportChatInviteRequest(hash))
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

    random.shuffle(users)

    for i, user in enumerate(users, 1):
        user_id = user.get('id')
        access_hash = user.get('access_hash')
        username_display = user.get('username') or user.get('first_name') or "Unknown"

        if not user_id or not access_hash:
            print(f"❌ [{i}/{len(users)}] Нет access_hash у {username_display}")
            fail_count += 1
            continue

        me = await client.get_me()
        if user_id == me.id:
            print(f"⚠️ [{i}/{len(users)}] Пропускаем себя: {username_display}")
            skip_count += 1
            continue

        try:
            user_entity = InputPeerUser(user_id, access_hash)

            await client(InviteToChannelRequest(
                channel=target_channel,
                users=[user_entity]
            ))

            success_count += 1
            print(f"✅ [{i}/{len(users)}] Добавлен: {username_display}")

        except FloodWaitError as e:
            print(f"⏳ Ожидаем {e.seconds} секунд...")
            await asyncio.sleep(e.seconds)
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

        except Exception as e:
            fail_count += 1
            _handle_add_error(e, username_display, i, len(users))

        # Паузы, чтобы не словить бан
        if success_count > 0 and success_count % 10 == 0:
            long_pause = random.randint(15, 35)
            print(f"⏸️ Длинная пауза {long_pause} сек после {success_count} добавлений...")
            await asyncio.sleep(long_pause)
        else:
            pause = random.randint(5, 15)
            await asyncio.sleep(pause)

    print(f"\n📊 ИТОГ:")
    print(f"✅ Успешно добавлено: {success_count}")
    print(f"⚠️ Пропущено: {skip_count}")
    print(f"❌ Не добавлено: {fail_count}")


# ------------------ ОБРАБОТКА ОШИБОК ------------------
def _handle_add_error(error, username, current, total):
    error_msg = str(error)
    if "USER_ALREADY_PARTICIPANT" in error_msg:
        print(f"⚠️ [{current}/{total}] Уже в канале: {username}")
    elif "CHAT_ADMIN_REQUIRED" in error_msg:
        print(f"❌ [{current}/{total}] Нет прав администратора для добавления: {username}")
    elif "USER_PRIVACY_RESTRICTED" in error_msg:
        print(f"❌ [{current}/{total}] Настройки приватности: {username}")
    elif "FLOOD_WAIT" in error_msg:
        print(f"⏳ [{current}/{total}] Ожидание из-за флуда: {username}")
    else:
        print(f"❌ [{current}/{total}] Ошибка для {username}: {error_msg}")


# ------------------ MAIN ------------------
async def main():
    await client.start()
    me = await client.get_me()
    print(f"✅ Авторизован как: {me.first_name}")

    mode = input("Выберите режим: [1] Сбор пользователей, [2] Добавление в канал: ")

    if mode == "1":
        source = input("Введите ссылку на чат/канал для сбора: ")
        await collect_users(source)
    elif mode == "2":
        await add_users_to_channel()
    else:
        print("❌ Неверный выбор")


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
