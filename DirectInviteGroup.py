import configparser
import json
import asyncio
import random
import logging
from telethon import TelegramClient, connection
from telethon.errors import FloodWaitError, UserIdInvalidError, PeerIdInvalidError
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import InputPeerUser

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

    async def collect_users_multi(self, source_link):
        """Сбор пользователей через случайный аккаунт"""
        if not self.active_accounts:
            logger.error("❌ Нет активных аккаунтов!")
            return
        
        client_data = random.choice(self.active_accounts)
        client = client_data['client']
        
        logger.info(f"📥 Собираем пользователей через: {client_data['name']}")
        
        try:
            if source_link.startswith('@'):
                source_link = source_link[1:]
            entity = await client.get_entity(source_link)
            participants = await client.get_participants(entity, aggressive=True)

            data = []
            for p in participants:
                if p.id and p.access_hash:
                    data.append({
                        "id": p.id,
                        "access_hash": p.access_hash,
                        "username": p.username,
                        "first_name": p.first_name
                    })

            with open("channel_users.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.info(f"✅ Сохранено {len(data)} пользователей в channel_users.json")
        except Exception as e:
            logger.error(f"❌ Ошибка при сборе пользователей: {e}")

    async def add_users_to_channel_multi(self):
        """Добавление пользователей через все аккаунты"""
        if not self.active_accounts:
            logger.error("❌ Нет активных аккаунтов!")
            return
        
        try:
            with open('channel_users.json', 'r', encoding='utf-8') as file:
                users = json.load(file)
        except FileNotFoundError:
            logger.error("❌ Файл channel_users.json не найден! Запустите сбор пользователей.")
            return
        except json.JSONDecodeError:
            logger.error("❌ Ошибка чтения channel_users.json")
            return

        logger.info(f"📊 Загружено {len(users)} пользователей")

        target_channel_input = input("Введите ссылку на канал куда добавлять: ").strip()

        # Распределяем пользователей по аккаунтам
        users_per_acc = len(users) // len(self.active_accounts)
        user_chunks = [users[i:i + users_per_acc] for i in range(0, len(users), users_per_acc)]
        
        tasks = []
        for i, account_data in enumerate(self.active_accounts):
            if i < len(user_chunks):
                chunk = user_chunks[i]
                task = self._add_users_from_account(account_data, chunk, target_channel_input, i+1)
                tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_success = 0
        total_failed = 0
        
        for result in results:
            if isinstance(result, tuple):
                success, failed = result
                total_success += success
                total_failed += failed
        
        logger.info(f"\n📊 ОБЩАЯ СТАТИСТИКА:")
        logger.info(f"✅ Успешно добавлено: {total_success}")
        logger.info(f"❌ Не добавлено: {total_failed}")

    async def _add_users_from_account(self, account_data, users, target_channel_input, account_num):
        """Добавляет пользователей с одного аккаунта"""
        client = account_data['client']
        success_count = 0
        fail_count = 0
        
        logger.info(f"👤 Аккаунт {account_num} ({account_data['name']}): начинаем добавление {len(users)} пользователей")
        
        # Получаем entity целевого канала
        try:
            target_channel = await client.get_entity(target_channel_input)
            logger.info(f"🎯 Аккаунт {account_num}: подключен к каналу {target_channel.title}")
        except Exception as e:
            logger.error(f"❌ Аккаунт {account_num}: ошибка получения канала: {e}")
            return 0, len(users)
        
        for i, user in enumerate(users, 1):
            user_id = user.get('id')
            access_hash = user.get('access_hash')
            username_display = user.get('username') or user.get('first_name') or "Unknown"

            if not user_id or not access_hash:
                fail_count += 1
                continue

            try:
                user_id = int(user_id)
                access_hash = int(access_hash)
            except (TypeError, ValueError):
                fail_count += 1
                continue

            me = await client.get_me()
            if user_id == me.id:
                fail_count += 1
                continue

            try:
                user_entity = InputPeerUser(user_id, access_hash)
                await client.get_entity(user_entity)
                await client(InviteToChannelRequest(
                    channel=target_channel,
                    users=[user_entity]
                ))
                success_count += 1
                logger.info(f"✅ [{account_num}] {i}/{len(users)} Добавлен: {username_display}")

            except FloodWaitError as e:
                logger.warning(f"⏳ [{account_num}] Ожидаем {e.seconds} сек...")
                await asyncio.sleep(e.seconds + 1)
                try:
                    await client(InviteToChannelRequest(
                        channel=target_channel,
                        users=[user_entity]
                    ))
                    success_count += 1
                    logger.info(f"✅ [{account_num}] {i}/{len(users)} Добавлен после ожидания: {username_display}")
                except Exception as retry_e:
                    fail_count += 1
                    self._handle_add_error(retry_e, username_display, account_num, i, len(users))

            except Exception as e:
                fail_count += 1
                self._handle_add_error(e, username_display, account_num, i, len(users))

            # Пауза
            if success_count > 0 and success_count % 10 == 0:
                await asyncio.sleep(random.randint(20, 40))
            else:
                await asyncio.sleep(random.uniform(1.5, 2.0))
        
        logger.info(f"👤 Аккаунт {account_num} завершил: ✅ {success_count}, ❌ {fail_count}")
        return success_count, fail_count

    def _handle_add_error(self, error, username, account_num, current, total):
        """Обрабатывает ошибки добавления"""
        error_msg = str(error).upper()
        if "USER_ALREADY_PARTICIPANT" in error_msg:
            logger.info(f"⚠️ [{account_num}] Уже в канале: {username}")
        elif "CHAT_ADMIN_REQUIRED" in error_msg:
            logger.error(f"❌ [{account_num}] Нет прав администратора: {username}")
        elif "USER_PRIVACY_RESTRICTED" in error_msg:
            logger.warning(f"🔒 [{account_num}] Настройки приватности: {username}")
        elif "FLOOD_WAIT" in error_msg:
            logger.warning(f"⏳ [{account_num}] Ограничение по флуду: {username}")
        elif "USER_NOT_MUTUAL_CONTACT" in error_msg:
            logger.warning(f"❌ [{account_num}] Нет взаимного контакта: {username}")
        else:
            logger.error(f"❌ [{account_num}] Ошибка для {username}: {str(error)}")

    async def close_all(self):
        """Закрывает все соединения"""
        for account in self.active_accounts:
            await account['client'].disconnect()

# Основная функция
async def main():
    inviter = MultiAccountInviter('config.ini')
    inviter.load_accounts()
    
    try:
        await inviter.initialize_accounts()
        
        if not inviter.active_accounts:
            logger.error("❌ Нет активных аккаунтов!")
            return
        
        mode = input("Выберите режим: [1] Сбор пользователей, [2] Добавление в канал: ").strip()

        if mode == "1":
            source = input("Введите ссылку на чат/канал для сбора: ").strip()
            await inviter.collect_users_multi(source)
        elif mode == "2":
            await inviter.add_users_to_channel_multi()
        else:
            print("❌ Неверный выбор")
    
    finally:
        await inviter.close_all()

if __name__ == "__main__":
    asyncio.run(main())