import configparser
import json
import asyncio
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import AddChatUserRequest, ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest, InviteToChannelRequest
from telethon.tl.types import InputPeerUser

config = configparser.ConfigParser()
config.read("config.ini")

api_id = config['Telegram']['api_id']
api_hash = config['Telegram']['api_hash']
username = config['Telegram']['username']
client = TelegramClient(username, api_id, api_hash)

async def add_users_to_chat():
    with open('channel_users.json', 'r', encoding='utf-8') as file:
        users = json.load(file)
    
    print(f"📊 Загружено {len(users)} пользователей")

    target_chat_input = input("Введите ссылку на чат куда добавлять: ")
    
    try:
        target_chat = await client.get_entity(target_chat_input)
    except ValueError:
        print("🤝 Вступаем в чат...")
        if "t.me/+" in target_chat_input:
            hash = target_chat_input.split("+")[1]
            target_chat = await client(ImportChatInviteRequest(hash))
        else:
            target_chat = await client(JoinChannelRequest(target_chat_input))
    
    success_count = 0
    fail_count = 0
    
    for i, user in enumerate(users, 1):
        user_id = user.get('id')
        username_display = user.get('username', user.get('first_name', 'Unknown'))
        
        if not user_id:
            print(f"❌ Нет ID у пользователя {username_display}")
            fail_count += 1
            continue

        me = await client.get_me()
        if user_id == me.id:
            print(f"⚠️ [{i}/{len(users)}] Пропускаем себя: {username_display}")
            continue
        
        try:
            user_entity = await client.get_entity(user_id)

            await client(AddChatUserRequest(
                chat_id=target_chat.id,
                user_id=user_entity,
                fwd_limit=0
            ))
                
            success_count += 1
            print(f"✅ [{i}/{len(users)}] Добавлен: {username_display}")
            
        except FloodWaitError as e:
            print(f"⏳ Ожидаем {e.seconds} секунд...")
            await asyncio.sleep(e.seconds)
            try:
                user_entity = await client.get_entity(user_id)
                await client(AddChatUserRequest(
                    chat_id=target_chat.id,
                    user_id=user_entity,
                    fwd_limit=0
                ))
                success_count += 1
                print(f"✅ [{i}/{len(users)}] Добавлен после ожидания: {username_display}")
            except Exception as retry_e:
                fail_count += 1
                print(f"❌ [{i}/{len(users)}] Ошибка после ожидания: {retry_e}")
            
        except Exception as e:
            fail_count += 1
            error_msg = str(e)
            if "USER_ALREADY_PARTICIPANT" in error_msg:
                print(f"⚠️ [{i}/{len(users)}] Уже в чате: {username_display}")
            elif "USER_NOT_MUTUAL_CONTACT" in error_msg:
                print(f"❌ [{i}/{len(users)}] Нет взаимного контакта: {username_display}")
            elif "USER_PRIVACY_RESTRICTED" in error_msg:
                print(f"❌ [{i}/{len(users)}] Настройки приватности: {username_display}")
            elif "CHAT_ADMIN_REQUIRED" in error_msg:
                print(f"❌ [{i}/{len(users)}] Нужны права администратора")
                break
            elif "The user cannot" in error_msg:
                print(f"❌ [{i}/{len(users)}] Нельзя добавить этого пользователя: {username_display}")
            elif "Invalid object ID" in error_msg:
                print(f"❌ [{i}/{len(users)}] Неверный ID пользователя: {username_display}")
            else:
                print(f"❌ [{i}/{len(users)}] Ошибка для {username_display}: {error_msg}")
        
        await asyncio.sleep(3)
    
    print(f"\n📊 ИТОГ:")
    print(f"✅ Успешно добавлено: {success_count}")
    print(f"❌ Не добавлено: {fail_count}")

async def main():
    await client.start()
    me = await client.get_me()
    print(f"✅ Авторизован как: {me.first_name}")
    await add_users_to_chat()

if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())