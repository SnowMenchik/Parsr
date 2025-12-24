import requests
import re
import os
import asyncio
import time
import json
from typing import List, Dict
from bs4 import BeautifulSoup
from telethon import TelegramClient
from telethon.errors import FloodWaitError, ChannelPrivateError

class ConfigManager:
    """Менеджер конфигурации для хранения данных"""
    
    def __init__(self):
        self.config_file = "config.json"
        self.config = {}
        self.load_config()
    
    def load_config(self):
        """Загружает конфигурацию из файла"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            except:
                self.config = {}
    
    def save_config(self):
        """Сохраняет конфигурацию в файл"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения конфигурации: {e}")
    
    def get(self, key, default=None):
        """Получает значение из конфигурации"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """Устанавливает значение в конфигурации"""
        self.config[key] = value
        self.save_config()
    
    def has_telegram_creds(self):
        """Проверяет наличие Telegram данных"""
        return all([
            self.get('telegram_api_id'),
            self.get('telegram_api_hash'), 
            self.get('telegram_phone')
        ])
    
    def has_vk_token(self):
        """Проверяет наличие VK токена"""
        return bool(self.get('vk_token'))

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
        Извлекает идентификаторы постов из ссылок разных соцсетей
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
        patterns = [
            r'ok\.ru/([^/\?]+)/topic/(\d+)',
            r'ok\.ru/([^/\?]+)/status/(\d+)',
            r'ok\.ru/(?:group)?(\d+)/topic/(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, link)
            if match:
                group_name = match.group(1)
                topic_id = match.group(2)
                
                ok_posts.append({
                    'group_name': group_name,
                    'topic_id': topic_id,
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
        self.session_name = "session"
    
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
            except ValueError:
                print("✗ API ID должен быть числом")
        else:
            print("✗ Все поля обязательны для заполнения")
    
    async def _connect(self):
        """Подключается к Telegram API"""
        try:
            self.client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            await self.client.start(phone=self.phone)
            return True
        except Exception as e:
            print(f"Ошибка подключения к Telegram: {e}")
            return False
    
    async def get_views_async(self, telegram_posts: List[Dict]) -> tuple[int, List[Dict]]:
        """Асинхронное получение просмотров для Telegram постов"""
        if not telegram_posts:
            return 0, []
        
        # Если данных нет, запрашиваем их
        if not self.config.has_telegram_creds():
            self.api_id = self.config.get('telegram_api_id')
            self.api_hash = self.config.get('telegram_api_hash')
            self.phone = self.config.get('telegram_phone')
            
            if not all([self.api_id, self.api_hash, self.phone]):
                self.setup_credentials()
                self.api_id = self.config.get('telegram_api_id')
                self.api_hash = self.config.get('telegram_api_hash')
                self.phone = self.config.get('telegram_phone')
        
        if not all([self.api_id, self.api_hash, self.phone]):
            print("Внимание: Данные Telegram API не установлены. Telegram посты не будут обработаны.")
            return 0, []
        
        if not await self._connect():
            print("Не удалось подключиться к Telegram")
            return 0, []
        
        total_views = 0
        telegram_views_data = []
        
        print(f"\nПолучаю просмотры для {len(telegram_posts)} Telegram постов...")
        
        for i, post_info in enumerate(telegram_posts, 1):
            try:
                message = await self.client.get_messages(
                    post_info['channel'], 
                    ids=post_info['message_id']
                )
                
                views = getattr(message, 'views', 0) or 0
                total_views += views
                
                print(f"  [{i}/{len(telegram_posts)}] Telegram: {post_info['original_link']}: {views:,}")
                
                telegram_views_data.append({
                    'link': post_info['original_link'],
                    'views': views
                })
                
            except FloodWaitError as e:
                print(f"  [{i}/{len(telegram_posts)}] Лимит запросов. Ожидание {e.seconds} секунд...")
                await asyncio.sleep(e.seconds)
            except (ChannelPrivateError, Exception) as e:
                print(f"  [{i}/{len(telegram_posts)}] Telegram: {post_info['original_link']}: ошибка - {type(e).__name__}")
                telegram_views_data.append({
                    'link': post_info['original_link'],
                    'views': 0
                })
            
            await asyncio.sleep(0.5)
        
        await self.client.disconnect()
        return total_views, telegram_views_data
    
    def get_views(self, telegram_posts: List[Dict]) -> tuple[int, List[Dict]]:
        """Синхронная обертка для асинхронной функции"""
        return asyncio.run(self.get_views_async(telegram_posts))

class OKParser:
    """Парсер для получения просмотров из Одноклассников"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_views(self, ok_posts: List[Dict]) -> tuple[int, List[Dict]]:
        """Получает просмотры для постов OK.ru через парсинг HTML"""
        if not ok_posts:
            return 0, []
        
        total_views = 0
        ok_views_data = []
        
        print(f"\nПолучаю просмотры для {len(ok_posts)} OK.ru постов...")
        
        for i, ok_post in enumerate(ok_posts, 1):
            url = ok_post['original_link']
            views = 0
            
            try:
                print(f"  [{i}/{len(ok_posts)}] Парсинг OK.ru: {url}")
                response = self.session.get(url, timeout=15)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    views = self._extract_views_from_html(soup)
                    print(f"     Найдено: {views:,} просмотров")
                else:
                    print(f"     Ошибка HTTP: {response.status_code}")
                    
            except Exception as e:
                print(f"     Ошибка: {e}")
            
            total_views += views
            ok_views_data.append({
                'link': url,
                'views': views
            })
            
            time.sleep(2)  # Задержка для избежания блокировки
        
        return total_views, ok_views_data
    
    def _extract_views_from_html(self, soup: BeautifulSoup) -> int:
        """Извлекает количество просмотров из HTML"""
        view_selectors = [
            {'class_': re.compile(r'view', re.I)},
            {'class_': re.compile(r'count', re.I)},
            {'class_': re.compile(r'visitors', re.I)},
            {'data-l': re.compile(r'.*view.*', re.I)},
            {'data-module': re.compile(r'.*like.*', re.I)},
        ]
        
        all_numbers = []
        
        # Поиск в элементах с классами
        for selector in view_selectors:
            elements = soup.find_all(**selector)
            for elem in elements:
                text = elem.get_text()
                numbers = re.findall(r'\d+', text.replace(' ', '').replace(',', ''))
                all_numbers.extend([int(n) for n in numbers if 10 < int(n) < 1000000])
        
        # Поиск в строкой с текстом про просмотры
        text_elements = soup.find_all(string=re.compile(r'\d+\s*(?:просмотр|лайк|участник)', re.I))
        for text in text_elements:
            numbers = re.findall(r'\d+', text)
            all_numbers.extend([int(n) for n in numbers if 10 < int(n) < 1000000])
        
        # Поиск в мета-тегах
        for meta in soup.find_all('meta'):
            content = meta.get('content', '')
            if 'просмотр' in content.lower():
                numbers = re.findall(r'\d+', content)
                all_numbers.extend([int(n) for n in numbers if 10 < int(n) < 1000000])
        
        return max(all_numbers) if all_numbers else 0

def main():
    """Основная функция программы"""
    print("="*50)
    print("ПАРСЕР ПРОСМОТРОВ ДЛЯ VK, TELEGRAM И OK.RU")
    print("="*50)
    
    # Инициализация менеджера конфигурации
    config = ConfigManager()
    
    # Инициализация парсеров
    social_parser = SocialMediaParser(config)
    vk_parser = VKParser(config)
    telegram_parser = TelegramParser(config)
    ok_parser = OKParser()
    
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
    
    # VK (только если есть VK посты)
    if vk_posts:
        vk_views, _ = vk_parser.get_views(vk_posts)
        total_views += vk_views
    
    # Telegram (только если есть Telegram посты)
    if telegram_posts:
        tg_views, _ = telegram_parser.get_views(telegram_posts)
        total_views += tg_views
    
    # OK.ru (только если есть OK.ru посты)
    if ok_posts:
        ok_views, _ = ok_parser.get_views(ok_posts)
        total_views += ok_views
    
    # Вывод результата
    print("\n" + "="*50)
    
    if total_views > 0:
        # Форматируем вывод в формате xx,x
        total_in_k = total_views / 1000
        # Заменяем точку на запятую
        formatted_total = f"{total_in_k:.1f}".replace('.', ',')
        print(f"Всего просмотров: {formatted_total}")
    else:
        print("Не удалось получить данные по просмотрам")

if __name__ == "__main__":
    main()