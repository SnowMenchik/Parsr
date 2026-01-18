import requests
import re
import os
import asyncio
import time
import json
from typing import List, Dict
from bs4 import BeautifulSoup
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, ChannelPrivateError, SessionPasswordNeededError
from telethon.tl.functions.messages import GetMessagesViewsRequest
import hashlib

class ConfigManager:
    """Менеджер конфигурации для хранения данных"""
    
    def __init__(self, initial_config=None):
        self.config_file = "config.json"
        self.config = {}
        self.initial_config = initial_config or {}
        self.load_config()
        
        # Если в конфиге нет данных из initial_config, добавляем их
        self._merge_initial_config()
    
    def _merge_initial_config(self):
        """Объединяет начальную конфигурацию с загруженной"""
        updated = False
        for key, value in self.initial_config.items():
            # Если ключа нет в конфиге ИЛИ значение пустое, а в initial_config не пустое
            if key not in self.config or (not self.config.get(key) and value):
                self.config[key] = value
                updated = True
        
        if updated:
            self.save_config()
    
    def load_config(self):
        """Загружает конфигурацию из файла"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                print(f"✓ Конфигурация загружена из {self.config_file}")
            except json.JSONDecodeError as e:
                print(f"✗ Ошибка чтения конфигурации: {e}")
                print("Создаю новую конфигурацию...")
                self.config = {}
            except Exception as e:
                print(f"✗ Ошибка загрузки конфигурации: {e}")
                self.config = {}
    
    def save_config(self):
        """Сохраняет конфигурацию в файл"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            print(f"✓ Конфигурация сохранена в {self.config_file}")
        except Exception as e:
            print(f"✗ Ошибка сохранения конфигурации: {e}")
    
    def get(self, key, default=None):
        """Получает значение из конфигурации"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """Устанавливает значение в конфигурации"""
        self.config[key] = value
        self.save_config()
    
    def has_telegram_creds(self):
        """Проверяет наличие Telegram данных"""
        api_id = self.get('telegram_api_id')
        api_hash = self.get('telegram_api_hash')
        phone = self.get('telegram_phone')
        
        # Проверяем, что все данные есть и не пустые
        if api_id and api_hash and phone:
            try:
                # Проверяем, что api_id можно преобразовать в число
                int(api_id)
                return True
            except (ValueError, TypeError):
                return False
        return False
    
    def has_vk_token(self):
        """Проверяет наличие VK токена"""
        token = self.get('vk_token')
        return bool(token and token.strip())
    
    def has_ok_creds(self):
        """Проверяет наличие OK.ru данных - для API нужны application_key и session_secret_key"""
        return all([
            self.get('ok_application_key'),
            self.get('ok_session_secret_key')
        ])
    
    def print_config_summary(self):
        """Выводит краткую информацию о конфигурации"""
        print("\nТекущая конфигурация:")
        print(f"  VK токен: {'✓ установлен' if self.has_vk_token() else '✗ отсутствует'}")
        print(f"  Telegram данные: {'✓ установлены' if self.has_telegram_creds() else '✗ отсутствуют'}")
        print(f"  OK.ru данные: {'✓ установлены' if self.has_ok_creds() else '✗ отсутствуют'}")
        
        # Показываем детали Telegram данных (скрывая чувствительную информацию)
        if self.has_telegram_creds():
            api_id = self.get('telegram_api_id')
            api_hash = self.get('telegram_api_hash')
            phone = self.get('telegram_phone')
            
            print(f"    API ID: {'*****' + str(api_id)[-3:] if api_id else 'не установлен'}")
            print(f"    API Hash: {api_hash[:8]}...{' (скрыто)' if api_hash and len(api_hash) > 8 else ''}")
            print(f"    Телефон: {'*****' + phone[-3:] if phone else 'не установлен'}")

class SocialMediaParser:
    """Парсер просмотров для постов из разных социальных сетей"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def read_links_from_file(self, filename: str = "links.txt") -> List[str]:
        """Читает ссылки из текстового файла"""
        try:
            with open(filename, 'r', encoding='utf-8') as file:
                links = [line.strip() for line in file if line.strip()]
            
            if not links:
                print(f"Файл '{filename}' пуст!")
                return []
            
            # Ограничение на количество обрабатываемых ссылок
            max_links = 100
            if len(links) > max_links:
                print(f"Внимание: ограничено до {max_links} первых ссылок")
                links = links[:max_links]
            
            return links
            
        except FileNotFoundError:
            print(f"Файл '{filename}' не найден! Создайте файл со ссылками.")
            return []
        except Exception as e:
            print(f"Ошибка при чтении файла: {e}")
            return []
    
    def extract_post_ids(self, links: List[str]) -> Dict[str, List[Dict]]:
        """
        Извлекает идентификаторов постов из ссылок разных соцсетей
        """
        vk_posts = []
        telegram_posts = []
        ok_posts = []
        
        for link in links:
            link_lower = link.lower()
            
            # VK посты
            if 'vk.com' in link_lower or link_lower.startswith('wall'):
                self._extract_vk_post(link_lower, link, vk_posts)
            
            # Telegram посты
            elif 't.me' in link_lower or 'telegram.me' in link_lower:
                self._extract_telegram_post(link_lower, link, telegram_posts)
            
            # Одноклассники (OK.ru)
            elif 'ok.ru' in link_lower:
                self._extract_ok_post(link_lower, link, ok_posts)
            
            else:
                print(f"Неизвестный формат ссылки: {link}")
        
        return {
            'vk': vk_posts,
            'telegram': telegram_posts,
            'ok': ok_posts
        }
    
    def _extract_vk_post(self, link: str, original_link: str, vk_posts: List[Dict]):
        """Извлекает данные VK поста"""
        patterns = [
            r'wall-?(\d+)_(\d+)',
            r'vk\.com/(?:wall)?(\d+_\d+)',
            r'vk\.com/(?:[\w\.]+)\?w=wall-(\d+_\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, link)
            if match:
                if pattern == patterns[0]:  # wall-owner_id_post_id
                    owner_id = match.group(1)
                    post_id = match.group(2)
                    if not owner_id.startswith('-'):
                        owner_id = f"-{owner_id}"
                    post_id_str = f"{owner_id}_{post_id}"
                else:
                    post_id_str = match.group(1)
                
                vk_posts.append({
                    'post_id': post_id_str,
                    'original_link': original_link
                })
                return
    
    def _extract_telegram_post(self, link: str, original_link: str, telegram_posts: List[Dict]):
        """Извлекает данные Telegram поста"""
        clean_link = link.split('?')[0].split('#')[0]
        
        patterns = [
            r'(?:t\.me|telegram\.me)/(?:s/)?([^/\?]+)/(\d+)',
            r'(?:t\.me|telegram\.me)/c/(\d+)/(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, clean_link)
            if match:
                channel = match.group(1)
                message_id = int(match.group(2))
                
                if channel.startswith('@'):
                    channel = channel[1:]
                
                telegram_posts.append({
                    'channel': channel,
                    'message_id': message_id,
                    'original_link': original_link
                })
                return
        
        print(f"Не удалось распознать ссылку Telegram: {original_link}")
    
    def _extract_ok_post(self, link: str, original_link: str, ok_posts: List[Dict]):
        """Извлекает данные OK.ru поста"""
        # Извлекаем группу и ID топика
        patterns = [
            r'ok\.ru/([^/\?]+)/topic/(\d+)',
            r'ok\.ru/([^/\?]+)/status/(\d+)',
            r'ok\.ru/(?:group)?(\d+)/topic/(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, link)
            if match:
                group = match.group(1)
                topic_id = match.group(2)
                
                # Определяем тип группы (числовой ID или строковый)
                if group.isdigit():
                    group_type = "group"
                else:
                    group_type = "profile"
                
                ok_posts.append({
                    'group': group,
                    'topic_id': topic_id,
                    'group_type': group_type,
                    'original_link': original_link
                })
                return
        
        print(f"Не удалось распознать ссылку OK.ru: {original_link}")

class VKParser:
    """Парсер для получения просмотров из VK"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.api_token = None
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def setup_token(self):
        """Запрашивает токен VK у пользователя"""
        print("\n" + "="*50)
        print("Для работы с VK требуется токен API")
        print("="*50)
        print("Получить токен можно здесь: https://vkhost.github.io/")
        print("Или через официальный метод получения токена VK")
        print("="*50)
        
        token = input("Введите ваш VK API токен: ").strip()
        if token:
            self.config.set('vk_token', token)
            self.api_token = token
            print("✓ Токен сохранен")
        else:
            print("✗ Токен не был введен")
    
    def get_views(self, vk_posts: List[Dict]) -> tuple[int, List[Dict]]:
        """Получает просмотры для постов VK через API"""
        if not vk_posts:
            return 0, []
        
        # Если токена нет, запрашиваем его
        if not self.config.has_vk_token():
            self.api_token = self.config.get('vk_token')
            if not self.api_token:
                self.setup_token()
                self.api_token = self.config.get('vk_token')
        else:
            self.api_token = self.config.get('vk_token')
        
        if not self.api_token:
            print("Внимание: VK API токен не установлен. VK посты не будут обработаны.")
            return 0, []
        
        total_views = 0
        vk_views_data = []
        
        print(f"\nПолучаю просмотры для {len(vk_posts)} VK постов...")
        
        try:
            post_ids = [post['post_id'] for post in vk_posts]
            
            response = self.session.post(
                'https://api.vk.com/method/wall.getById',
                params={
                    'access_token': self.api_token,
                    'v': '5.199',
                    'posts': ','.join(post_ids),
                    'extended': 0
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            if 'error' in data:
                print(f"Ошибка VK API: {data['error']['error_msg']}")
                return 0, []
            
            posts = data.get('response', {}).get('items', [])
            post_views = {}
            
            for post in posts:
                post_key = f"{post.get('owner_id', 0)}_{post.get('id', 0)}"
                views = post.get('views', {}).get('count', 0)
                post_views[post_key] = views
            
            for i, vk_post in enumerate(vk_posts, 1):
                post_id = vk_post['post_id']
                views = post_views.get(post_id, 0)
                total_views += views
                
                print(f"  [{i}/{len(vk_posts)}] VK: {vk_post['original_link']}: {views:,}")
                
                vk_views_data.append({
                    'link': vk_post['original_link'],
                    'views': views
                })
            
            return total_views, vk_views_data
            
        except Exception as e:
            print(f"Ошибка при получении данных VK: {e}")
            return 0, []

class TelegramParser:
    """Парсер для получения просмотров из Telegram"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.api_id = None
        self.api_hash = None
        self.phone = None
        self.session_name = "telegram_session"
        self.client = None
    
    def setup_credentials(self):
        """Запрашивает данные Telegram API у пользователя"""
        print("\n" + "="*50)
        print("Для работы с Telegram требуется API доступ")
        print("="*50)
        print("1. Перейдите на https://my.telegram.org")
        print("2. Войдите под своим аккаунтом")
        print("3. Создайте приложение и получите API ID и API Hash")
        print("="*50)
        
        api_id = input("Введите Telegram API ID: ").strip()
        api_hash = input("Введите Telegram API Hash: ").strip()
        phone = input("Введите номер телефона (в формате +79123456789): ").strip()
        
        if api_id and api_hash and phone:
            try:
                api_id = int(api_id)
                self.config.set('telegram_api_id', api_id)
                self.config.set('telegram_api_hash', api_hash)
                self.config.set('telegram_phone', phone)
                
                self.api_id = api_id
                self.api_hash = api_hash
                self.phone = phone
                
                print("✓ Данные Telegram сохранены")
                return True
            except ValueError:
                print("✗ API ID должен быть числом")
        else:
            print("✗ Все поля обязательны для заполнения")
        
        return False
    
    async def _connect(self):
        """Подключается к Telegram API"""
        try:
            print("Попытка подключения к Telegram...")
            
            # Создаем клиента
            self.client = TelegramClient(
                self.session_name, 
                self.api_id, 
                self.api_hash,
                device_model="iPhone 13 Pro Max",
                system_version="14.8.1",
                app_version="8.4",
                lang_code="en",
                system_lang_code="en-US"
            )
            
            # Подключаемся
            await self.client.connect()
            
            # Проверяем, авторизован ли уже
            if not await self.client.is_user_authorized():
                print("Требуется авторизация в Telegram...")
                print(f"Будет отправлен код на номер: {self.phone}")
                
                # Отправляем код
                await self.client.send_code_request(self.phone)
                
                # Запрашиваем код у пользователя
                code = input("Введите код, который пришел в Telegram: ").strip()
                
                # Пытаемся войти с кодом
                try:
                    await self.client.sign_in(self.phone, code)
                    print("✓ Успешная авторизация в Telegram")
                except SessionPasswordNeededError:
                    print("Требуется двухфакторная аутентификация.")
                    password = input("Введите пароль двухфакторной аутентификации: ")
                    await self.client.sign_in(password=password)
                    print("✓ Успешная авторизация с двухфакторной аутентификацией")
            else:
                print("✓ Уже авторизован в Telegram")
            
            return True
                
        except Exception as e:
            print(f"Ошибка подключения к Telegram: {e}")
            return False
    
    async def get_views_async(self, telegram_posts: List[Dict]) -> tuple[int, List[Dict]]:
        """Асинхронное получение просмотров для Telegram постов"""
        if not telegram_posts:
            return 0, []
        
        # Загружаем данные из конфига
        self.api_id = self.config.get('telegram_api_id')
        self.api_hash = self.config.get('telegram_api_hash')
        self.phone = self.config.get('telegram_phone')
        
        # Проверяем данные
        if not self.config.has_telegram_creds():
            print("Внимание: Данные Telegram API не установлены или неполны.")
            print("Пожалуйста, введите данные для Telegram.")
            
            if not self.setup_credentials():
                print("Не удалось настроить данные Telegram API. Telegram посты не будут обработаны.")
                return 0, []
            
            # Обновляем данные из конфига
            self.api_id = self.config.get('telegram_api_id')
            self.api_hash = self.config.get('telegram_api_hash')
            self.phone = self.config.get('telegram_phone')
        
        # Преобразуем api_id в число
        try:
            self.api_id = int(self.api_id)
        except (ValueError, TypeError):
            print("✗ Telegram API ID должен быть числом")
            return 0, []
        
        print(f"\nПодготовка к подключению Telegram:")
        print(f"  API ID: {self.api_id}")
        print(f"  API Hash: {'*' * 8}...")
        print(f"  Телефон: {'*' * len(str(self.phone))[:-3]}...")
        print(f"  Файл сессии: {self.session_name}.session")
        
        # Проверяем наличие файла сессии
        if os.path.exists(f"{self.session_name}.session"):
            print("✓ Найден файл сессии Telegram")
            
            # Пробуем подключиться с существующей сессией
            try:
                self.client = TelegramClient(
                    self.session_name, 
                    self.api_id, 
                    self.api_hash,
                    device_model="iPhone 13 Pro Max",
                    system_version="14.8.1",
                    app_version="8.4",
                    lang_code="en",
                    system_lang_code="en-US"
                )
                
                await self.client.connect()
                
                # Проверяем, авторизован ли пользователь
                if await self.client.is_user_authorized():
                    print("✓ Успешное подключение к Telegram с использованием сессии")
                else:
                    print("✗ Файл сессии недействителен или устарел")
                    print("Пожалуйста, удалите файл 'telegram_session.session' и перезапустите программу")
                    return 0, []
                    
            except Exception as e:
                print(f"✗ Ошибка при использовании сессии: {e}")
                print("Пожалуйста, удалите файл 'telegram_session.session' и перезапустите программу")
                return 0, []
        else:
            # Если файла сессии нет, подключаемся обычным способом
            if not await self._connect():
                print("Не удалось подключиться к Telegram")
                return 0, []
        
        total_views = 0
        telegram_views_data = []
        
        print(f"\nПолучаю просмотры для {len(telegram_posts)} Telegram постов...")
        
        for i, post_info in enumerate(telegram_posts, 1):
            try:
                print(f"  [{i}/{len(telegram_posts)}] Обработка: {post_info['original_link']}")
                
                channel = post_info['channel']
                message_id = post_info['message_id']
                
                # Пробуем разные форматы канала
                try:
                    # Сначала пробуем как числовой ID
                    if channel.isdigit() or (channel.startswith('-') and channel[1:].isdigit()):
                        channel_entity = await self.client.get_entity(int(channel))
                    else:
                        # Пробуем как username (с @ или без)
                        if not channel.startswith('@'):
                            channel = f"@{channel}"
                        channel_entity = await self.client.get_entity(channel)
                    
                    # Получаем сообщение
                    message = await self.client.get_messages(channel_entity, ids=message_id)
                    
                    if message:
                        views = getattr(message, 'views', 0) or 0
                        total_views += views
                        print(f"     Найдено: {views:,} просмотров")
                    else:
                        print(f"     Не удалось найти сообщение")
                        views = 0
                    
                except ValueError as e:
                    print(f"     Ошибка при получении канала: {e}")
                    views = 0
                
                telegram_views_data.append({
                    'link': post_info['original_link'],
                    'views': views
                })
                
            except FloodWaitError as e:
                print(f"  [{i}/{len(telegram_posts)}] Лимит запросов. Ожидание {e.seconds} секунд...")
                await asyncio.sleep(e.seconds)
                # Повторяем попытку
                i -= 1  # Уменьшаем счетчик для повторной обработки
                continue
            except ChannelPrivateError:
                print(f"  [{i}/{len(telegram_posts)}] Канал является приватным или вы не подписаны на него")
                telegram_views_data.append({
                    'link': post_info['original_link'],
                    'views': 0
                })
            except Exception as e:
                print(f"  [{i}/{len(telegram_posts)}] Ошибка: {type(e).__name__}: {str(e)[:100]}...")
                telegram_views_data.append({
                    'link': post_info['original_link'],
                    'views': 0
                })
            
            # Задержка между запросами
            await asyncio.sleep(1)
        
        # Отключаемся
        if self.client:
            await self.client.disconnect()
            print("✓ Отключились от Telegram")
        
        return total_views, telegram_views_data
    
    def get_views(self, telegram_posts: List[Dict]) -> tuple[int, List[Dict]]:
        """Синхронная обертка для асинхронной функции"""
        try:
            return asyncio.run(self.get_views_async(telegram_posts))
        except KeyboardInterrupt:
            print("\nПрервано пользователем")
            return 0, []
        except Exception as e:
            print(f"Ошибка при работе с Telegram: {e}")
            return 0, []

class OKParser:
    """Парсер для получения просмотров из Одноклассников"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        self.application_key = None
        self.access_token = None
        self.session_secret_key = None
        self.application_id = None
        self.setup_api_credentials()
    
    def setup_api_credentials(self):
        """Запрашивает данные API OK.ru у пользователя"""
        # Загружаем данные из конфига
        self.application_key = self.config.get('ok_application_key')
        self.access_token = self.config.get('ok_access_token')
        self.session_secret_key = self.config.get('ok_session_secret_key')
        self.application_id = self.config.get('ok_application_id')
        
        if self.config.has_ok_creds():
            print("✓ Данные OK.ru API загружены из конфига")
            return
        
        # Если нет данных, спрашиваем пользователя
        print("\n" + "="*50)
        print("Для использования API OK.ru требуются учетные данные")
        print("="*50)
        print("Получить их можно на https://apiok.ru/")
        print("1. Зарегистрируйте приложение")
        print("2. Получите Application Key, Session Secret Key и Application ID")
        print("3. Access Token может быть пустым для публичных данных")
        print("="*50)
        
        choice = input("Хотите ввести данные API OK.ru? (y/n): ").strip().lower()
        
        if choice == 'y':
            app_key = input("Введите Application Key (Сервисный ключ): ").strip()
            access_token = input("Введите Access Token (можно оставить пустым): ").strip()
            session_secret = input("Введите Session Secret Key (Защищённый ключ): ").strip()
            app_id = input("Введите Application ID (ID приложения): ").strip()
            
            if app_key and session_secret:
                self.config.set('ok_application_key', app_key)
                self.config.set('ok_access_token', access_token)
                self.config.set('ok_session_secret_key', session_secret)
                self.config.set('ok_application_id', app_id)
                
                self.application_key = app_key
                self.access_token = access_token
                self.session_secret_key = session_secret
                self.application_id = app_id
                
                print("✓ Данные OK.ru API сохранены в конфиг")
            else:
                print("✗ Application Key и Session Secret Key обязательны")
        else:
            print("Будет использован только парсинг HTML")
    
    def get_views(self, ok_posts: List[Dict]) -> tuple[int, List[Dict]]:
        """Получает просмотры для постов OK.ru"""
        if not ok_posts:
            return 0, []
        
        total_views = 0
        ok_views_data = []
        
        print(f"\nПолучаю просмотры для {len(ok_posts)} OK.ru постов...")
        
        # Определяем, использовать ли API или только парсинг
        use_api = self.config.has_ok_creds()
        
        if use_api:
            print("Используется API OK.ru...")
        else:
            print("API не настроен, используется только парсинг HTML...")
        
        for i, ok_post in enumerate(ok_posts, 1):
            url = ok_post['original_link']
            views = 0
            
            try:
                print(f"  [{i}/{len(ok_posts)}] Обработка: {url}")
                
                # Сначала пробуем API, если настроено
                if use_api:
                    views = self._get_views_via_api(ok_post)
                
                # Если API не сработал или не настроен, пробуем парсинг
                if views == 0:
                    views = self._get_views_via_parsing(url)
                
                print(f"     Найдено: {views:,} просмотров")
                
            except Exception as e:
                print(f"     Ошибка: {e}")
            
            total_views += views
            ok_views_data.append({
                'link': url,
                'views': views
            })
            
            # Задержка между запросами
            time.sleep(2)
        
        return total_views, ok_views_data
    
    def _get_views_via_api(self, ok_post: Dict) -> int:
        """Получает просмотры через API OK.ru"""
        try:
            group = ok_post['group']
            topic_id = ok_post['topic_id']
            
            # Создаем сигнатуру запроса (подпись)
            params = {
                'application_key': self.application_key,
                'format': 'json',
                'method': 'mediatopic.get',
                'access_token': self.access_token or '',  # Может быть пустым
                'ids': f"{topic_id}",
            }
            
            # Если группа числовая, добавляем group_id
            if ok_post['group_type'] == 'group' and group.isdigit():
                params['gid'] = group
            
            # Генерируем подпись
            sig = self._generate_signature(params)
            params['sig'] = sig
            
            response = self.session.post(
                'https://api.ok.ru/fb.do',
                data=params,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Логируем ответ для отладки
                if data:
                    print(f"     API ответ получен (длина: {len(str(data))} символов)")
                
                if isinstance(data, dict):
                    # Ищем просмотры в разных полях ответа
                    for key in ['views', 'view_count', 'visitors', 'visits']:
                        if key in data and data[key]:
                            try:
                                views = int(data[key])
                                if views > 0:
                                    return views
                            except:
                                continue
                    
                    # Ищем вложенные объекты
                    if 'media' in data and isinstance(data['media'], list) and len(data['media']) > 0:
                        media = data['media'][0]
                        for key in ['views', 'view_count', 'visitors', 'visits']:
                            if key in media and media[key]:
                                try:
                                    views = int(media[key])
                                    if views > 0:
                                        return views
                                except:
                                    continue
                
            return 0
            
        except Exception as e:
            print(f"     Ошибка API: {e}")
            return 0
    
    def _generate_signature(self, params: Dict) -> str:
        """Генерирует подпись для запроса OK API"""
        try:
            # Сортируем параметры по алфавиту
            sorted_params = sorted(params.items())
            
            # Создаем строку для подписи
            sig_string = ''
            for key, value in sorted_params:
                if value:  # Пропускаем пустые значения
                    sig_string += f"{key}={value}"
            
            # Добавляем session_secret_key
            sig_string += self.session_secret_key
            
            # Вычисляем MD5 хэш
            md5_hash = hashlib.md5(sig_string.encode('utf-8')).hexdigest()
            
            return md5_hash.lower()
        except:
            return ""
    
    def _get_views_via_parsing(self, url: str) -> int:
        """Парсит просмотры со страницы"""
        try:
            response = self.session.get(url, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Метод 1: Ищем элементы с классами, содержащими "count", "view", "stats"
                count_selectors = [
                    {'class_': re.compile(r'media-layer_stats', re.I)},
                    {'class_': re.compile(r'topic-stats', re.I)},
                    {'class_': re.compile(r'stats-layer', re.I)},
                    {'class_': re.compile(r'media-layer__stats', re.I)},
                    {'class_': re.compile(r'widget_count', re.I)},
                    {'class_': re.compile(r'navMenuCount', re.I)},
                ]
                
                for selector in count_selectors:
                    elements = soup.find_all(**selector)
                    for elem in elements:
                        text = elem.get_text(strip=True)
                        # Ищем числа в тексте
                        numbers = re.findall(r'\d+', text.replace(' ', ''))
                        for num_str in numbers:
                            try:
                                num = int(num_str)
                                # Фильтруем: просмотры обычно > 10 и < 10 000 000
                                if 10 <= num <= 10000000:
                                    return num
                            except:
                                continue
                
                # Метод 2: Ищем по текстовым паттернам во всем HTML
                html_text = str(soup)
                
                # Паттерны для поиска просмотров
                patterns = [
                    r'(\d+(?:\s*\d+)*)\s*просмотр[а-я]{0,4}',
                    r'(\d+(?:\s*\d+)*)\s*просмотров',
                    r'(\d+(?:\s*\d+)*)\s*просмотра',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, html_text, re.IGNORECASE)
                    for match in matches:
                        try:
                            clean_num = int(match.replace(' ', '').replace(',', ''))
                            # Фильтруем маленькие числа
                            if 100 <= clean_num <= 10000000:
                                return clean_num
                        except:
                            continue
                
                # Метод 3: Анализируем все числа на странице
                all_numbers = []
                
                # Ищем все элементы с числами
                number_elements = soup.find_all(string=re.compile(r'\d+'))
                for elem in number_elements:
                    text = str(elem).strip()
                    if text and len(text) < 100:
                        # Извлекаем числа
                        numbers = re.findall(r'\d+', text.replace(' ', ''))
                        for num_str in numbers:
                            if num_str.isdigit():
                                num = int(num_str)
                                # Отсеиваем очевидно неподходящие числа
                                if 100 <= num <= 1000000:
                                    all_numbers.append(num)
                
                # Если нашли подходящие числа, берем медиану
                if all_numbers:
                    all_numbers.sort()
                    median_index = len(all_numbers) // 2
                    return all_numbers[median_index]
                
                return 0
            else:
                return 0
                
        except Exception as e:
            print(f"     Ошибка парсинга: {e}")
            return 0

def main():
    """Основная функция программы"""
    print("="*50)
    print("ПАРСЕР ПРОСМОТРОВ ДЛЯ VK, TELEGRAM И OK.RU")
    print("="*50)
    
    # Инициализация менеджера конфигурации с пустыми данными
    initial_config = {
        "telegram_api_id": "",
        "telegram_api_hash": "",
        "telegram_phone": "",
        "vk_token": "",
        "ok_application_key": "",
        "ok_access_token": "",
        "ok_session_secret_key": "",
        "ok_application_id": ""
    }
    
    config = ConfigManager(initial_config)
    config.print_config_summary()
    
    # Инициализация парсеров
    social_parser = SocialMediaParser(config)
    vk_parser = VKParser(config)
    telegram_parser = TelegramParser(config)
    ok_parser = OKParser(config)
    
    # Чтение ссылок из файла
    links = social_parser.read_links_from_file("links.txt")
    if not links:
        return
    
    print(f"\nНайдено {len(links)} ссылок для обработки")
    
    # Извлечение идентификаторов постов
    posts_data = social_parser.extract_post_ids(links)
    
    vk_posts = posts_data['vk']
    telegram_posts = posts_data['telegram']
    ok_posts = posts_data['ok']
    
    print(f"\nРаспределение по платформам:")
    print(f"  VK: {len(vk_posts)} постов")
    print(f"  Telegram: {len(telegram_posts)} постов")
    print(f"  OK.ru: {len(ok_posts)} постов")
    
    # Сбор данных о просмотрах
    total_views = 0
    detailed_results = []
    
    # VK (только если есть VK посты)
    if vk_posts:
        vk_views, vk_details = vk_parser.get_views(vk_posts)
        total_views += vk_views
        detailed_results.extend(vk_details)
    
    # Telegram (только если есть Telegram посты)
    if telegram_posts:
        print(f"\n{'='*50}")
        print("ОБРАБОТКА TELEGRAM")
        print(f"{'='*50}")
        print("Внимание: При первом запуске потребуется вход в Telegram!")
        print("Следуйте инструкциям на экране.")
        print(f"{'='*50}")
        
        tg_views, tg_details = telegram_parser.get_views(telegram_posts)
        total_views += tg_views
        detailed_results.extend(tg_details)
    
    # OK.ru (только если есть OK.ru посты)
    if ok_posts:
        ok_views, ok_details = ok_parser.get_views(ok_posts)
        total_views += ok_views
        detailed_results.extend(ok_details)
    
    # Вывод результата
    print("\n" + "="*50)
    
    if total_views > 0:
        # Форматируем вывод в формате xx,x
        total_in_k = total_views / 1000
        # Заменяем точку на запятую
        formatted_total = f"{total_in_k:.1f}".replace('.', ',')
        print(f"Всего просмотров: {formatted_total}")
        
        # Сохраняем детальные результаты в файл
        try:
            with open('results.json', 'w', encoding='utf-8') as f:
                json.dump({
                    'total_views': total_views,
                    'formatted_total': formatted_total,
                    'detailed_results': detailed_results,
                    'timestamp': time.time()
                }, f, ensure_ascii=False, indent=2)
            print(f"\nДетальные результаты сохранены в файл 'results.json'")
        except Exception as e:
            print(f"Не удалось сохранить результаты: {e}")
    else:
        print("Не удалось получить данные по просмотрам")

if __name__ == "__main__":
    main()