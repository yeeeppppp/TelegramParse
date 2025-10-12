import configparser
import json
import asyncio
import random
import logging
from telethon import TelegramClient, connection
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendMessageRequest

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

class MultiAccountSender:
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

    async def send_mass_messages_multi(self):
        """Рассылка сообщений через все аккаунты"""
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

        message_text = input("Введите сообщение для рассылки: ")
        
        if not message_text.strip():
            logger.error("❌ Сообщение не может быть пустым!")
            return
        
        logger.info(f"📨 Начинаем рассылку через {len(self.active_accounts)} аккаунтов")

        # Распределяем пользователей по аккаунтам
        users_per_acc = len(users) // len(self.active_accounts)
        user_chunks = [users[i:i + users_per_acc] for i in range(0, len(users), users_per_acc)]
        
        tasks = []
        for i, account_data in enumerate(self.active_accounts):
            if i < len(user_chunks):
                chunk = user_chunks[i]
                task = self._send_messages_from_account(account_data, chunk, message_text, i+1)
                tasks.append(task)
        
        # Запускаем все рассылки параллельно
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Собираем статистику
        total_success = 0
        total_failed = 0
        
        for result in results:
            if isinstance(result, tuple):
                success, failed = result
                total_success += success
                total_failed += failed
        
        logger.info(f"\n📊 ОБЩАЯ СТАТИСТИКА РАССЫЛКИ:")
        logger.info(f"✅ Успешно отправлено: {total_success}")
        logger.info(f"❌ Не отправлено: {total_failed}")
        logger.info(f"📨 Всего пользователей: {len(users)}")

    async def _send_messages_from_account(self, account_data, users, message_text, account_num):
        """Рассылает сообщения с одного аккаунта"""
        client = account_data['client']
        success_count = 0
        fail_count = 0
        
        logger.info(f"👤 Аккаунт {account_num} ({account_data['name']}): начинаем рассылку для {len(users)} пользователей")
        
        for i, user in enumerate(users, 1):
            user_id = user.get('id')
            username_display = user.get('username') or user.get('first_name') or 'Unknown'
            
            if not user_id:
                logger.error(f"❌ [{account_num}] Нет ID у пользователя {username_display}")
                fail_count += 1
                continue
            
            try:
                await client(SendMessageRequest(
                    peer=user_id,
                    message=message_text
                ))
                success_count += 1
                logger.info(f"✅ [{account_num}] {i}/{len(users)} Отправлено: {username_display}")
                
            except FloodWaitError as e:
                logger.warning(f"⏳ [{account_num}] Ожидаем {e.seconds} сек...")
                await asyncio.sleep(e.seconds)
                # Пробуем снова
                try:
                    await client(SendMessageRequest(
                        peer=user_id,
                        message=message_text
                    ))
                    success_count += 1
                    logger.info(f"✅ [{account_num}] {i}/{len(users)} Отправлено после ожидания: {username_display}")
                except Exception as retry_e:
                    fail_count += 1
                    self._handle_send_error(retry_e, username_display, account_num, i, len(users))
            
            except Exception as e:
                fail_count += 1
                self._handle_send_error(e, username_display, account_num, i, len(users))
            
            # Случайная пауза между сообщениями
            await asyncio.sleep(random.uniform(2, 4))
        
        logger.info(f"👤 Аккаунт {account_num} завершил рассылку: ✅ {success_count}, ❌ {fail_count}")
        return success_count, fail_count

    def _handle_send_error(self, error, username, account_num, current, total):
        """Обрабатывает ошибки отправки"""
        error_msg = str(error)
        if "USER_IS_BLOCKED" in error_msg:
            logger.warning(f"🚫 [{account_num}] Пользователь заблокировал бота: {username}")
        elif "PEER_FLOOD" in error_msg:
            logger.error(f"❌ [{account_num}] Превышен лимит сообщений: {username}")
        elif "USER_BANNED" in error_msg:
            logger.warning(f"❌ [{account_num}] Пользователь забанен: {username}")
        elif "USER_PRIVACY_RESTRICTED" in error_msg:
            logger.warning(f"🔒 [{account_num}] Настройки приватности: {username}")
        elif "FLOOD_WAIT" in error_msg:
            logger.warning(f"⏳ [{account_num}] Ожидание из-за флуда: {username}")
        else:
            logger.error(f"❌ [{account_num}] Ошибка для {username}: {error_msg}")

    async def close_all(self):
        """Закрывает все соединения"""
        for account in self.active_accounts:
            await account['client'].disconnect()

# Основная функция
async def main():
    logger.info("🤖 Запуск Multi-Account рассылки...")
    
    sender = MultiAccountSender('config.ini')
    sender.load_accounts()
    
    try:
        await sender.initialize_accounts()
        
        if not sender.active_accounts:
            logger.error("❌ Нет активных аккаунтов!")
            return

        await sender.send_mass_messages_multi()
    
    finally:
        await sender.close_all()

if __name__ == "__main__":
    asyncio.run(main())