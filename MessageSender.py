import configparser
import json
import asyncio
from telethon import TelegramClient
from telethon.errors import FloodWaitError

config = configparser.ConfigParser()
config.read("config.ini")

api_id = config['Telegram']['api_id']
api_hash = config['Telegram']['api_hash']
username = config['Telegram']['username']

client = TelegramClient(username, api_id, api_hash)

async def send_mass_messages():

    try:
        with open('channel_users.json', 'r', encoding='utf-8') as file:
            users = json.load(file)
    except FileNotFoundError:
        print("❌ Файл channel_users.json не найден!")
        print("Сначала запусти парсер чтобы получить список пользователей")
        return
    except Exception as e:
        print(f"❌ Ошибка чтения файла: {e}")
        return
    
    print(f"📊 Загружено {len(users)} пользователей из channel_users.json")

    message_text = input("Введите сообщение для рассылки: ")
    
    if not message_text.strip():
        print("❌ Сообщение не может быть пустым!")
        return
    
    print(f"📨 Начинаем рассылку сообщения: '{message_text}'")
    print("⏳ Это может занять некоторое время...")
    
    success_count = 0
    fail_count = 0
    
    for i, user in enumerate(users, 1):
        user_id = user.get('id')
        username = user.get('username', user.get('first_name', f'user_{user_id}'))
        
        if not user_id:
            print(f"❌ [{i}/{len(users)}] Нет ID у пользователя")
            fail_count += 1
            continue
        
        try:
            await client.send_message(user_id, message_text)
            success_count += 1
            print(f"✅ [{i}/{len(users)}] Отправлено пользователю: {username}")
            
        except FloodWaitError as e:
            print(f"⏳ [{i}/{len(users)}] Ожидаем {e.seconds} секунд...")
            await asyncio.sleep(e.seconds)
            try:
                await client.send_message(user_id, message_text)
                success_count += 1
                print(f"✅ [{i}/{len(users)}] Отправлено после ожидания: {username}")
            except Exception as retry_e:
                fail_count += 1
                print(f"❌ [{i}/{len(users)}] Ошибка после ожидания для {username}: {retry_e}")
                
        except Exception as e:
            fail_count += 1
            error_msg = str(e)
            if "USER_IS_BLOCKED" in error_msg:
                print(f"❌ [{i}/{len(users)}] Пользователь {username} заблокировал бота")
            elif "PEER_FLOOD" in error_msg:
                print(f"❌ [{i}/{len(users)}] Превышен лимит сообщений для {username}")
                break
            elif "USER_BANNED" in error_msg:
                print(f"❌ [{i}/{len(users)}] Пользователь {username} забанен")
            else:
                print(f"❌ [{i}/{len(users)}] Ошибка для {username}: {error_msg}")

        await asyncio.sleep(2)

    print(f"\n📊 РАССЫЛКА ЗАВЕРШЕНА:")
    print(f"✅ Успешно отправлено: {success_count}")
    print(f"❌ Не отправлено: {fail_count}")
    print(f"📨 Всего пользователей: {len(users)}")

async def main():
    print("🤖 Запуск UserBot для рассылки...")

    try:
        await client.start()
        me = await client.get_me()
        print(f"✅ Авторизован как: {me.first_name} (@{me.username})")
    except Exception as e:
        print(f"❌ Ошибка авторизации: {e}")
        return

    await send_mass_messages()

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())