import configparser
import json
import asyncio
import random
import logging
from telethon import TelegramClient, connection
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import AddChatUserRequest, ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

class MultiAccountInviter:
    def __init__(self, config_file='config.ini'):
        self.config = configparser.ConfigParser()
        self.config.read(config_file)
        self.accounts = []
        self.active_accounts = []
        
    def load_accounts(self):
        """Загружает все аккаунты из конфига"""
        for section in self.config.sections():
            if section.startswith('Account'):
                account_config = dict(self.config[section])
                # Парсим прокси если есть
                if account_config.get('proxy'):
                    proxy_data = self._parse_proxy(account_config['proxy'])
                    account_config['proxy'] = proxy_data
                else:
                    account_config['proxy'] = None
                
                self.accounts.append(account_config)
                logger.info(f"✅ Загружен аккаунт: {account_config.get('username', 'Unknown')}")
        
        logger.info(f"📊 Всего загружено аккаунтов: {len(self.accounts)}")
    
    def _parse_proxy(self, proxy_str):
        """Парсит строку прокси"""
        if proxy_str.startswith('http'):
            from telethon.network import HTTPProxy
            import re
            match = re.match(r'http://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)', proxy_str)
            if match:
                user, password, host, port = match.groups()
                return HTTPProxy(host, int(port), username=user, password=password)
        elif proxy_str.startswith('socks5'):
            from telethon.network import SOCKS5Proxy
            import re
            match = re.match(r'socks5://(?:([^:]+):([^@]+)@)?([^:]+):(\d+)', proxy_str)
            if match:
                user, password, host, port = match.groups()
                return SOCKS5Proxy(host, int(port), username=user, password=password)
        return None
    
    async def initialize_accounts(self):
        """Инициализирует все аккаунты"""
        clients = []
        for account in self.accounts:
            try:
                client = TelegramClient(
                    session=account.get('session_file', account['username']),
                    api_id=int(account['api_id']),
                    api_hash=account['api_hash'],
                    proxy=account.get('proxy'),
                    connection=connection.ConnectionTcpMTProxy if account.get('proxy') else None
                )
                
                await client.start(phone=lambda: account.get('phone', ''))
                me = await client.get_me()
                logger.info(f"✅ Авторизован: {me.first_name} (@{me.username})")
                
                clients.append({
                    'client': client,
                    'username': account['username'],
                    'name': me.first_name,
                    'is_active': True
                })
                
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации {account.get('username')}: {e}")
                continue
        
        self.active_accounts = clients
        return clients

    async def add_users_to_chat_multi(self):
        """Добавление пользователей в чат через все аккаунты"""
        if not self.active_accounts:
            logger.error("❌ Нет активных аккаунтов!")
            return
        
        # Читаем пользователей
        try:
            with open('channel_users.json', 'r', encoding='utf-8') as file:
                users = json.load(file)
        except FileNotFoundError:
            logger.error("❌ Файл channel_users.json не найден!")
            return
        except Exception as e:
            logger.error(f"❌ Ошибка чтения файла: {e}")
            return
        
        logger.info(f"📊 Загружено {len(users)} пользователей")

        target_chat_input = input("Введите ссылку на чат куда добавлять: ")
        
        # Распределяем пользователей по аккаунтам
        users_per_acc = len(users) // len(self.active_accounts)
        user_chunks = [users[i:i + users_per_acc] for i in range(0, len(users), users_per_acc)]
        
        tasks = []
        for i, account_data in enumerate(self.active_accounts):
            if i < len(user_chunks):
                chunk = user_chunks[i]
                task = self._add_users_to_chat_from_account(account_data, chunk, target_chat_input, i+1)
                tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_success = 0
        total_failed = 0
        
        for result in results:
            if isinstance(result, tuple):
                success, failed = result
                total_success += success
                total_failed += failed
        
        logger.info(f"\n📊 ОБЩАЯ СТАТИСТИКА ДОБАВЛЕНИЯ:")
        logger.info(f"✅ Успешно добавлено: {total_success}")
        logger.info(f"❌ Не добавлено: {total_failed}")

    async def _add_users_to_chat_from_account(self, account_data, users, target_chat_input, account_num):
        """Добавляет пользователей в чат с одного аккаунта"""
        client = account_data['client']
        success_count = 0
        fail_count = 0
        
        logger.info(f"👤 Аккаунт {account_num} ({account_data['name']}): начинаем добавление {len(users)} пользователей")
        
        # Получаем entity целевого чата
        target_chat = None
        try:
            target_chat = await client.get_entity(target_chat_input)
            logger.info(f"🎯 Аккаунт {account_num}: подключен к чату {getattr(target_chat, 'title', 'Unknown')}")
        except ValueError:
            logger.info(f"🤝 Аккаунт {account_num}: вступаем в чат...")
            try:
                if "t.me/+" in target_chat_input:
                    hash = target_chat_input.split("+")[1]
                    target_chat = await client(ImportChatInviteRequest(hash))
                else:
                    target_chat = await client(JoinChannelRequest(target_chat_input))
                logger.info(f"✅ Аккаунт {account_num}: успешно вступил в чат")
            except Exception as e:
                logger.error(f"❌ Аккаунт {account_num}: ошибка вступления в чат: {e}")
                return 0, len(users)
        
        if target_chat is None:
            logger.error(f"❌ Аккаунт {account_num}: не удалось получить информацию о чате!")
            return 0, len(users)
        
        for i, user in enumerate(users, 1):
            user_id = user.get('id')
            username_display = user.get('username', user.get('first_name', 'Unknown'))
            
            if not user_id:
                logger.error(f"❌ [{account_num}] Нет ID у пользователя {username_display}")
                fail_count += 1
                continue

            me = await client.get_me()
            if user_id == me.id:
                logger.info(f"⚠️ [{account_num}] Пропускаем себя: {username_display}")
                continue
            
            try:
                user_entity = await client.get_entity(user_id)

                await client(AddChatUserRequest(
                    chat_id=target_chat.id,
                    user_id=user_entity,
                    fwd_limit=0
                ))
                    
                success_count += 1
                logger.info(f"✅ [{account_num}] {i}/{len(users)} Добавлен: {username_display}")
                
            except FloodWaitError as e:
                logger.warning(f"⏳ [{account_num}] Ожидаем {e.seconds} сек...")
                await asyncio.sleep(e.seconds)
                try:
                    user_entity = await client.get_entity(user_id)
                    await client(AddChatUserRequest(
                        chat_id=target_chat.id,
                        user_id=user_entity,
                        fwd_limit=0
                    ))
                    success_count += 1
                    logger.info(f"✅ [{account_num}] {i}/{len(users)} Добавлен после ожидания: {username_display}")
                except Exception as retry_e:
                    fail_count += 1
                    self._handle_add_error(retry_e, username_display, account_num, i, len(users))
                
            except Exception as e:
                fail_count += 1
                self._handle_add_error(e, username_display, account_num, i, len(users))
            
            # Пауза между добавлениями
            await asyncio.sleep(random.uniform(3, 6))
        
        logger.info(f"👤 Аккаунт {account_num} завершил добавление: ✅ {success_count}, ❌ {fail_count}")
        return success_count, fail_count

    def _handle_add_error(self, error, username, account_num, current, total):
        """Обрабатывает ошибки добавления"""
        error_msg = str(error)
        if "USER_ALREADY_PARTICIPANT" in error_msg:
            logger.info(f"⚠️ [{account_num}] Уже в чате: {username}")
        elif "USER_NOT_MUTUAL_CONTACT" in error_msg:
            logger.warning(f"❌ [{account_num}] Нет взаимного контакта: {username}")
        elif "USER_PRIVACY_RESTRICTED" in error_msg:
            logger.warning(f"🔒 [{account_num}] Настройки приватности: {username}")
        elif "CHAT_ADMIN_REQUIRED" in error_msg:
            logger.error(f"❌ [{account_num}] Нужны права администратора: {username}")
        elif "The user cannot" in error_msg:
            logger.warning(f"❌ [{account_num}] Нельзя добавить этого пользователя: {username}")
        elif "Invalid object ID" in error_msg:
            logger.error(f"❌ [{account_num}] Неверный ID пользователя: {username}")
        elif "Could not find the input entity" in error_msg:
            logger.warning(f"🚫 [{account_num}] Скрытый профиль: {username}")
        else:
            logger.error(f"❌ [{account_num}] Ошибка для {username}: {error_msg}")

    async def close_all(self):
        """Закрывает все соединения"""
        for account in self.active_accounts:
            await account['client'].disconnect()

# Основная функция
async def main():
    logger.info("🤖 Запуск Multi-Account добавления в чаты...")
    
    inviter = MultiAccountInviter('config.ini')
    inviter.load_accounts()
    
    try:
        await inviter.initialize_accounts()
        
        if not inviter.active_accounts:
            logger.error("❌ Нет активных аккаунтов!")
            return

        await inviter.add_users_to_chat_multi()
    
    finally:
        await inviter.close_all()

if __name__ == "__main__":
    asyncio.run(main())