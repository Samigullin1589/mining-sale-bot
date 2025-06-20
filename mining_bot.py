# -*- coding: utf-8 -*-

# ========================================================================================
# 1. ИМПОРТЫ
# ========================================================================================
import os
import asyncio
import logging
import random
import json
import re
import io
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Tuple

# Основные библиотеки для асинхронности и Telegram
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ForceReply, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest

# Вспомогательные библиотеки
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from cachetools import TTLCache, cached
from dotenv import load_dotenv
from fuzzywuzzy import process, fuzz
import feedparser
from dateutil import parser as date_parser
import bleach
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from openai import AsyncOpenAI

# Загрузка переменных окружения из файла .env
load_dotenv()

# ========================================================================================
# 2. КОНФИГУРАЦИЯ И КОНСТАНТЫ
# ========================================================================================
class Config:
    """Класс для хранения всех настроек, ключей API и констант."""
    # --- Ключи API и основные настройки (из переменных окружения) ---
    BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    CMC_API_KEY = os.getenv("CMC_API_KEY") # CoinMarketCap
    CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")
    NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
    
    # --- ID чатов ---
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
    NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")

    # --- Настройки вебхука (для Render/Heroku) ---
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    WEBHOOK_PATH = "/webhook"
    
    # --- Файлы для хранения данных ---
    GAME_DATA_FILE = "game_data.json"
    PROFILES_DATA_FILE = "user_profiles.json"
    ASIC_CACHE_FILE = "asic_data_cache.json" # Аварийный кэш на диске
    DYNAMIC_KEYWORDS_FILE = "dynamic_keywords.json"

    # --- Игровые константы ---
    LEVEL_MULTIPLIERS = {1: 1, 2: 1.5, 3: 2.2, 4: 3.5, 5: 5}
    UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1}
    STREAK_BONUS_MULTIPLIER = 0.05
    QUIZ_REWARD = 0.0001
    QUIZ_MIN_CORRECT_FOR_REWARD = 3
    SHOP_ITEMS = {
        'boost': {'name': '⚡️ Буст х2 (24ч)', 'cost': 0.0005},
        'overclock': {'name': '⚙️ Оверклокинг-чип (+5% навсегда)', 'cost': 0.002, 'effect': 0.05}
    }
    RANDOM_EVENT_CHANCE = 0.1
    HALVING_INTERVAL = 210000

    # --- Контент бота ---
    CRYPTO_TERMS = ["Блокчейн", "Газ (Gas)", "Халвинг", "ICO", "DeFi", "NFT", "Сатоши", "Кит (Whale)", "HODL", "DEX", "Смарт-контракт"]
    BOT_HINTS = [
        "💡 Узнайте курс любой монеты, просто написав ее тикер!", "⚙️ Посмотрите на самые доходные ASIC",
        "⛏️ Рассчитайте прибыль с помощью 'Калькулятора'", "📰 Хотите свежие крипто-новости?",
        "🤑 Попробуйте наш симулятор майнинга!", "😱 Проверьте Индекс Страха и Жадности",
        "🏆 Сравните себя с лучшими в таблице лидеров", "🎓 Что такое 'HODL'? Узнайте, написав /word",
        "🧠 Проверьте знания и заработайте в /quiz", "🛍️ Загляните в магазин улучшений"
    ]
    PARTNER_URL = os.getenv("PARTNER_URL", "https://cutt.ly/5rWGcgYL")
    PARTNER_BUTTON_TEXT_OPTIONS = ["🎁 Узнать спеццены", "🔥 Эксклюзивное предложение", "💡 Получить консультацию", "💎 Прайс от экспертов"]
    PARTNER_AD_TEXT_OPTIONS = [
        "Хотите превратить виртуальные BTC в реальные? Для этого нужно настоящее оборудование! Наши партнеры предлагают лучшие условия для старта.",
        "Виртуальный майнинг - это только начало. Готовы к реальной добыче? Ознакомьтесь с предложениями от проверенных поставщиков.",
    ]
    TICKER_ALIASES = {'бтк': 'BTC', 'биткоин': 'BTC', 'биток': 'BTC', 'eth': 'ETH', 'эфир': 'ETH', 'эфириум': 'ETH', 'sol': 'SOL', 'солана': 'SOL', 'ltc': 'LTC', 'лайткоин': 'LTC', 'лайт': 'LTC', 'doge': 'DOGE', 'доги': 'DOGE', 'дог': 'DOGE', 'kas': 'KAS', 'каспа': 'KAS', 'алео': 'ALEO'}
    POPULAR_TICKERS = ['BTC', 'ETH', 'SOL', 'TON', 'KAS']

    # --- Анти-спам ---
    WARN_LIMIT = 3
    MUTE_DURATION_HOURS = 24
    SPAM_KEYWORDS = ['p2p', 'арбитраж', 'обмен', 'сигналы', 'обучение', 'заработок', 'инвестиции', 'вложения', 'схема', 'связка']
    
    # --- Кэширование ---
    CACHE_TTL_SHORT = 60      # 1 минута для часто меняющихся данных (курсы)
    CACHE_TTL_MEDIUM = 300    # 5 минут для калькуляторов и статуса сети
    CACHE_TTL_LONG = 3600     # 1 час для данных по ASIC и новостей
    CACHE_TTL_XLONG = 14400   # 4 часа для индекса страха и жадности
    
# --- Настройка журналирования ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Проверка критически важной конфигурации ---
if not Config.BOT_TOKEN:
    logger.critical("Критическая ошибка: TG_BOT_TOKEN не установлен. Бот не может быть запущен.")
    raise ValueError("Критическая ошибка: TG_BOT_TOKEN не установлен")

# --- Инициализация основных компонентов ---
bot = Bot(token=Config.BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")
openai_client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY) if Config.OPENAI_API_KEY else None

# --- Хранилища данных в памяти (кэши) ---
asic_cache = TTLCache(maxsize=1, ttl=Config.CACHE_TTL_LONG)
crypto_price_cache = TTLCache(maxsize=500, ttl=Config.CACHE_TTL_SHORT)
fear_greed_cache = TTLCache(maxsize=10, ttl=Config.CACHE_TTL_XLONG)
btc_status_cache = TTLCache(maxsize=10, ttl=Config.CACHE_TTL_MEDIUM)
halving_cache = TTLCache(maxsize=1, ttl=Config.CACHE_TTL_LONG)
news_cache = TTLCache(maxsize=1, ttl=Config.CACHE_TTL_LONG)

# --- Временные хранилища ---
user_quiz_states = {}
temp_user_choices = {}


# ========================================================================================
# 3. УНИВЕРСАЛЬНЫЕ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ========================================================================================
def sanitize_html(text: str) -> str:
    """Полностью удаляет все HTML-теги и атрибуты, оставляя только обычный текст."""
    if not text:
        return ""
    # Используем bleach для надежной очистки от потенциально вредного HTML
    return bleach.clean(text, tags=[], attributes={}, strip=True).strip()

async def resilient_request(session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> Optional[Dict[str, Any]]:
    """Выполняет отказоустойчивый асинхронный HTTP-запрос с обработкой ошибок."""
    try:
        async with session.request(method, url, timeout=15, **kwargs) as response:
            if response.status == 429:
                logger.warning(f"Слишком много запросов к {url}. Статус 429.")
                return None # Явный возврат None при rate limiting
            response.raise_for_status()
            if "application/json" in response.content_type:
                return await response.json()
            else: # для XML (RSS) или простого текста
                return {"text_content": await response.text()}
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка сетевого запроса к {url}: {e}")
    except asyncio.TimeoutError:
        logger.error(f"Тайм-аут при запросе к {url}")
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка декодирования JSON от {url}: {e}")
    return None

def get_main_keyboard():
    """Возвращает основную клавиатуру с кнопками."""
    buttons = [
        [KeyboardButton(text="💹 Курс"), KeyboardButton(text="⚙️ Топ ASIC")],
        [KeyboardButton(text="⛏️ Калькулятор"), KeyboardButton(text="📰 Новости")],
        [KeyboardButton(text="😱 Индекс Страха"), KeyboardButton(text="⏳ Халвинг")],
        [KeyboardButton(text="📡 Статус BTC"), KeyboardButton(text="🧠 Викторина")],
        [KeyboardButton(text="🕹️ Виртуальный Майнинг")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

async def send_message_with_partner_button(chat_id: int, text: str, reply_markup: Optional[types.InlineKeyboardMarkup] = None):
    """Отправляет сообщение с партнерской кнопкой и случайной подсказкой."""
    try:
        if not reply_markup:
            builder = InlineKeyboardBuilder()
            builder.button(text=random.choice(Config.PARTNER_BUTTON_TEXT_OPTIONS), url=Config.PARTNER_URL)
            reply_markup = builder.as_markup()

        full_text = f"{text}\n\n---\n<i>{random.choice(Config.BOT_HINTS)}</i>"
        
        await bot.send_message(chat_id, full_text, reply_markup=reply_markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "can't parse entities" in str(e):
            logger.error(f"Ошибка парсинга HTML. Отправляю текст без форматирования. {e}")
            cleaned_text = sanitize_html(text) # Используем bleach для очистки
            full_text = f"{cleaned_text}\n\n---\n<i>{random.choice(Config.BOT_HINTS)}</i>"
            await bot.send_message(chat_id, full_text, reply_markup=reply_markup, disable_web_page_preview=True)
        else:
            logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")
            
async def send_photo_with_partner_button(chat_id: int, photo: io.BytesIO, caption: str):
    """Отправляет фото с партнерской кнопкой и подсказкой."""
    try:
        if not photo or not isinstance(photo, io.BytesIO):
            raise ValueError("Объект фото пустой или имеет неверный тип")
        
        photo.seek(0) # Убедимся, что указатель в начале файла
        
        hint = f"\n\n---\n<i>{random.choice(Config.BOT_HINTS)}</i>"
        # Telegram имеет лимит в 1024 символа для подписи к фото
        if len(caption) + len(hint) > 1024:
            caption = caption[:1024 - len(hint) - 3] + "..."

        final_caption = f"{caption}{hint}"
        
        builder = InlineKeyboardBuilder()
        builder.button(text=random.choice(Config.PARTNER_BUTTON_TEXT_OPTIONS), url=Config.PARTNER_URL)
        markup = builder.as_markup()

        await bot.send_photo(chat_id, types.BufferedInputFile(photo.read(), filename="image.png"), caption=final_caption, reply_markup=markup)
    except Exception as e:
        logger.error(f"Не удалось отправить фото: {e}. Отправляю текстом.")
        await send_message_with_partner_button(chat_id, caption)

# ========================================================================================
# 4. КЛАСС ApiHandler - СЕРДЦЕ СБОРА ДАННЫХ
# ========================================================================================
class ApiHandler:
    """
    Класс для асинхронного сбора и обработки данных из множества внешних API.
    Использует aiohttp для параллельных запросов и cachetools для кэширования.
    """
    
    def __init__(self):
        # Словари для хранения URL и парсеров для каждого типа данных
        self.price_sources = self._get_price_sources()
        self.news_sources = self._get_news_sources()
        self.fear_greed_sources = self._get_fear_greed_sources()
        self.btc_status_sources = self._get_btc_status_sources()
        self.halving_sources = self._get_halving_sources()
        self.asic_sources = self._get_asic_sources()

    # --- Методы для инициализации источников ---
    def _get_price_sources(self):
        # Более 10 источников для курсов криптовалют
        return {
            'coingecko': {'url': 'https://api.coingecko.com/api/v3/simple/price?ids={id}&vs_currencies=usd', 'parser': self._parse_coingecko_price},
            'coinmarketcap': {'url': 'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?symbol={ticker}', 'headers': {'X-CMC_PRO_API_KEY': Config.CMC_API_KEY}, 'parser': self._parse_cmc_price},
            'binance': {'url': 'https://api.binance.com/api/v3/ticker/price?symbol={ticker}USDT', 'parser': self._parse_binance_price},
            'kraken': {'url': 'https://api.kraken.com/0/public/Ticker?pair={ticker}USD', 'parser': self._parse_kraken_price},
            'coinbase': {'url': 'https://api.coinbase.com/v2/prices/{ticker}-USD/spot', 'parser': self._parse_coinbase_price},
            'kucoin': {'url': 'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={ticker}-USDT', 'parser': self._parse_kucoin_price},
            'cryptocompare': {'url': 'https://min-api.cryptocompare.com/data/price?fsym={ticker}&tsyms=USD', 'headers': {'authorization': f'Apikey {Config.CRYPTOCOMPARE_API_KEY}'}, 'parser': self._parse_cryptocompare_price},
            'bitfinex': {'url': 'https://api-pub.bitfinex.com/v2/ticker/t{ticker}USD', 'parser': self._parse_bitfinex_price},
            'gateio': {'url': 'https://api.gateio.ws/api/v4/spot/tickers?currency_pair={ticker}_USDT', 'parser': self._parse_gateio_price},
            'coincap': {'url': 'https://api.coincap.io/v2/assets/{id}', 'parser': self._parse_coincap_price},
        }

    def _get_news_sources(self):
        # Более 10 источников для новостей (RSS и API)
        return {
            'cryptopanic': {'url': f'https://cryptopanic.com/api/v1/posts/?auth_token={os.getenv("CRYPTOPANIC_API_KEY")}&public=true', 'parser': self._parse_cryptopanic_news, 'type': 'api'},
            'newsapi': {'url': f'https://newsapi.org/v2/everything?q=crypto&sortBy=publishedAt&language=en&apiKey={Config.NEWSAPI_KEY}', 'parser': self._parse_newsapi_news, 'type': 'api'},
            'cointelegraph_rss': {'url': 'https://cointelegraph.com/rss/tag/russia', 'parser': self._parse_rss, 'type': 'rss'},
            'forklog_rss': {'url': 'https://forklog.com/feed', 'parser': self._parse_rss, 'type': 'rss'},
            'rbc_crypto_rss': {'url': 'https://www.rbc.ru/crypto/feed', 'parser': self._parse_rss, 'type': 'rss'},
            'bitsmedia_rss': {'url': 'https://bits.media/rss/', 'parser': self._parse_rss, 'type': 'rss'},
            'beincrypto_rss': {'url': 'https://beincrypto.ru/feed/', 'parser': self._parse_rss, 'type': 'rss'},
            'coindesk_rss': {'url': 'https://www.coindesk.com/arc/outboundfeeds/rss/', 'parser': self._parse_rss, 'type': 'rss'},
            'decrypt_rss': {'url': 'https://decrypt.co/feed', 'parser': self._parse_rss, 'type': 'rss'},
            'theblock_rss': {'url': 'https://www.theblock.co/rss.xml', 'parser': self._parse_rss, 'type': 'rss'},
        }
        
    def _get_fear_greed_sources(self):
        return {
            'alternative.me': {'url': 'https://api.alternative.me/fng/?limit=1', 'parser': self._parse_alternative_me_fg},
            'coinmarketcap': {'url': 'https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical?limit=1', 'headers': {'X-CMC_PRO_API_KEY': Config.CMC_API_KEY}, 'parser': self._parse_cmc_fg},
            # Дополнительные источники можно добавить скрапингом, но API надежнее
        }

    def _get_btc_status_sources(self):
        return {
            'mempool.space': {'parser': self._parse_mempool_status},
            'blockchain.info': {'parser': self._parse_blockchain_info_status},
            'blockchair': {'parser': self._parse_blockchair_status},
            'blockcypher': {'parser': self._parse_blockcypher_status},
            'btc.com': {'parser': self._parse_btccom_status},
        }
        
    def _get_halving_sources(self):
         return {
            'mempool.space': {'url': 'https://mempool.space/api/blocks/tip/height', 'parser': self._parse_block_height},
            'blockchain.info': {'url': 'https://blockchain.info/q/getblockcount', 'parser': self._parse_block_height},
            'blockchair': {'url': 'https://api.blockchair.com/bitcoin/stats', 'parser': self._parse_blockchair_height},
            'blockcypher': {'url': 'https://api.blockcypher.com/v1/btc/main', 'parser': self._parse_blockcypher_height},
        }
        
    def _get_asic_sources(self):
        return {
            'minerstat': self._get_asics_from_minerstat,
            'whattomine_scrape': self._scrape_asics_from_whattomine,
            'asicminervalue_scrape': self._scrape_asics_from_asicminervalue,
        }

    # --- Методы-парсеры для каждого источника ---
    # (Здесь должны быть все функции парсинга, например, _parse_coingecko_price, _parse_cmc_price и т.д.)
    # Для краткости они будут определены внутри основных методов сбора данных

    async def _run_tasks_and_get_first_valid(self, tasks: List) -> Any:
        """Запускает задачи параллельно и возвращает первый успешный результат."""
        for future in asyncio.as_completed(tasks):
            result = await future
            if result is not None:
                return result
        return None

    # --- ОСНОВНЫЕ МЕТОДЫ СБОРА ДАННЫХ ---
    
    @cached(crypto_price_cache)
    async def get_crypto_price(self, ticker: str) -> Optional[Dict[str, Any]]:
        ticker_upper = ticker.strip().upper()
        # Поиск ID монеты для API, которые его требуют (CoinGecko, CoinCap)
        coin_id = 'bitcoin' # По умолчанию для BTC
        try:
            async with aiohttp.ClientSession() as session:
                res = await resilient_request(session, 'get', f'https://api.coingecko.com/api/v3/search?query={ticker.lower()}')
                if res and res.get('coins'):
                    # Ищем точное совпадение по тикеру
                    for coin in res['coins']:
                        if coin.get('symbol', '').upper() == ticker_upper:
                            coin_id = coin.get('id')
                            break
                    else: # если не нашли точного совпадения, берем первое
                        coin_id = res['coins'][0].get('id', ticker.lower())
        except Exception:
            coin_id = ticker.lower()
            
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            # Парсеры для каждого источника
            def _parse_coingecko_price(data): return data.get(coin_id, {}).get('usd')
            def _parse_cmc_price(data): return data.get('data', {}).get(ticker_upper, [{}])[0].get('quote', {}).get('USD', {}).get('price')
            def _parse_binance_price(data): return data.get('price')
            def _parse_kraken_price(data):
                key = next(iter(data.get('result', {})), None)
                return data['result'][key]['c'][0] if key else None
            def _parse_coinbase_price(data): return data.get('data', {}).get('amount')
            def _parse_kucoin_price(data): return data.get('data', {}).get('price')
            def _parse_cryptocompare_price(data): return data.get('USD')
            def _parse_bitfinex_price(data): return data[6] if isinstance(data, list) and len(data) > 6 else None
            def _parse_gateio_price(data): return data[0].get('last') if isinstance(data, list) and data else None
            def _parse_coincap_price(data): return data.get('data', {}).get('priceUsd')

            sources = {
                'CoinGecko': {'url': f'https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd', 'parser': _parse_coingecko_price},
                'CoinMarketCap': {'url': f'https://pro-api.coinmarketcap.com/v2/cryptocurrency/quotes/latest?symbol={ticker_upper}', 'headers': {'X-CMC_PRO_API_KEY': Config.CMC_API_KEY}, 'parser': _parse_cmc_price},
                'Binance': {'url': f'https://api.binance.com/api/v3/ticker/price?symbol={ticker_upper}USDT', 'parser': _parse_binance_price},
                'Kraken': {'url': f'https://api.kraken.com/0/public/Ticker?pair={ticker_upper}USD', 'parser': _parse_kraken_price},
                'Coinbase': {'url': f'https://api.coinbase.com/v2/prices/{ticker_upper}-USD/spot', 'parser': _parse_coinbase_price},
                'KuCoin': {'url': f'https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={ticker_upper}-USDT', 'parser': _parse_kucoin_price},
                'CryptoCompare': {'url': f'https://min-api.cryptocompare.com/data/price?fsym={ticker_upper}&tsyms=USD', 'headers': {'authorization': f'Apikey {Config.CRYPTOCOMPARE_API_KEY}'}, 'parser': _parse_cryptocompare_price},
                'Bitfinex': {'url': f'https://api-pub.bitfinex.com/v2/ticker/t{ticker_upper}USD', 'parser': _parse_bitfinex_price},
                'Gate.io': {'url': f'https://api.gateio.ws/api/v4/spot/tickers?currency_pair={ticker_upper}_USDT', 'parser': _parse_gateio_price},
                'CoinCap': {'url': f'https://api.coincap.io/v2/assets/{coin_id}', 'parser': _parse_coincap_price},
            }

            async def fetch(name, params):
                try:
                    data = await resilient_request(session, 'get', params['url'], headers=params.get('headers'))
                    if data:
                        price = params['parser'](data)
                        if price:
                            logger.info(f"Цена для {ticker_upper} получена с {name}: {price}")
                            return {'price': float(price), 'source': name, 'ticker': ticker_upper}
                except Exception as e:
                    logger.debug(f"Ошибка при получении цены с {name}: {e}")
                return None
                
            for name, params in sources.items():
                if "{ticker}" in params['url'] or "{id}" in params['url']:
                    tasks.append(fetch(name, params))
            
            result = await self._run_tasks_and_get_first_valid(tasks)
            return result
            
    @cached(news_cache)
    async def get_crypto_news(self) -> List[Dict[str, str]]:
        """Собирает новости из всех источников параллельно."""
        all_news = []
        async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
            tasks = []
            
            # --- Парсеры ---
            def _parse_rss(data, source_name):
                news_list = []
                feed = feedparser.parse(data.get("text_content", ""))
                if feed.bozo:
                    logger.warning(f"Лента {source_name} может быть некорректной: {feed.bozo_exception}")
                for entry in feed.entries:
                    if hasattr(entry, 'published_parsed') and hasattr(entry, 'title') and hasattr(entry, 'link'):
                        news_list.append({
                            'title': sanitize_html(entry.title),
                            'link': entry.link,
                            'published': date_parser.parse(entry.published).replace(tzinfo=None) if hasattr(entry, 'published') else datetime.now()
                        })
                return news_list

            def _parse_cryptopanic_news(data, source_name):
                news_list = []
                for post in data.get('results', []):
                    news_list.append({
                        'title': sanitize_html(post['title']),
                        'link': post['url'],
                        'published': datetime.strptime(post['created_at'], '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
                    })
                return news_list

            def _parse_newsapi_news(data, source_name):
                news_list = []
                for article in data.get('articles', []):
                    news_list.append({
                        'title': sanitize_html(article['title']),
                        'link': article['url'],
                        'published': date_parser.parse(article['publishedAt']).replace(tzinfo=None)
                    })
                return news_list

            sources = {
                'CryptoPanic': {'url': f'https://cryptopanic.com/api/v1/posts/?auth_token={os.getenv("CRYPTOPANIC_API_KEY")}&public=true', 'parser': _parse_cryptopanic_news},
                'NewsAPI': {'url': f'https://newsapi.org/v2/everything?q=cryptocurrency&sortBy=publishedAt&language=ru&apiKey={Config.NEWSAPI_KEY}', 'parser': _parse_newsapi_news},
                'CoinTelegraph': {'url': 'https://cointelegraph.com/rss/tag/russia', 'parser': _parse_rss},
                'Forklog': {'url': 'https://forklog.com/feed', 'parser': _parse_rss},
                # ... добавьте остальные RSS источники
            }

            async def fetch_news(name, params):
                try:
                    data = await resilient_request(session, 'get', params['url'])
                    if data:
                        return params['parser'](data, name)
                except Exception as e:
                    logger.warning(f"Не удалось получить новости из {name}: {e}")
                return []

            for name, params in sources.items():
                tasks.append(fetch_news(name, params))
            
            results = await asyncio.gather(*tasks)
            for news_list in results:
                if news_list:
                    all_news.extend(news_list)

        # Сортировка и удаление дубликатов
        if not all_news:
            return []
        all_news.sort(key=lambda x: x['published'], reverse=True)
        seen_titles = set()
        unique_news = [item for item in all_news if item['title'].strip().lower() not in seen_titles and not seen_titles.add(item['title'].strip().lower())]
        
        return unique_news[:15] # Возвращаем 15 самых свежих новостей

    @cached(fear_greed_cache)
    async def get_fear_and_greed_index(self) -> Optional[Dict[str, Any]]:
        # Реализация сбора данных из нескольких источников для индекса страха и жадности
        async with aiohttp.ClientSession() as session:
            tasks = []
            
            async def fetch_alternative(s):
                data = await resilient_request(s, 'get', 'https://api.alternative.me/fng/?limit=1')
                if data and data.get('data'):
                    val = data['data'][0]
                    return {'value': int(val['value']), 'classification': val['value_classification'], 'source': 'Alternative.me'}
                return None
                
            async def fetch_cmc(s):
                if not Config.CMC_API_KEY: return None
                headers = {'X-CMC_PRO_API_KEY': Config.CMC_API_KEY}
                data = await resilient_request(s, 'get', 'https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical?limit=1', headers=headers)
                if data and data.get('data'):
                    val = data['data'][0]
                    return {'value': int(val['value']), 'classification': val['value_classification'], 'source': 'CoinMarketCap'}
                return None

            tasks.append(fetch_alternative(session))
            tasks.append(fetch_cmc(session))
            
            return await self._run_tasks_and_get_first_valid(tasks)

    # ... другие методы сбора данных (get_btc_network_status, get_halving_info, get_top_asics) ...
    # Они будут реализованы по тому же принципу: параллельные запросы к нескольким источникам.
    # Для краткости, полная реализация всех 10+ источников для каждой функции опущена,
    # но структура остается той же.

    @cached(halving_cache)
    async def get_halving_info(self) -> Optional[int]:
        """Получает высоту текущего блока из нескольких источников."""
        async with aiohttp.ClientSession() as session:
            
            async def fetch(url):
                data = await resilient_request(session, 'get', url)
                if data and data.get('text_content', '').isdigit():
                    return int(data['text_content'])
                # Парсеры для более сложных ответов
                if data and 'blocks' in data: return data['blocks'] # blockchair
                if data and 'height' in data: return data['height'] # blockcypher
                return None

            tasks = [fetch(p['url']) for p in self.halving_sources.values() if 'url' in p]
            return await self._run_tasks_and_get_first_valid(tasks)

    async def ask_gpt(self, prompt: str, model: str = "gpt-4o"):
        if not openai_client:
            return "[❌ Ошибка: Клиент OpenAI не инициализирован.]"
        try:
            res = await openai_client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "Ты — полезный ассистент, отвечающий на русском языке."},
                    {"role": "user", "content": prompt}
                ],
                timeout=40.0
            )
            return sanitize_html(res.choices[0].message.content.strip())
        except Exception as e:
            logger.error(f"Ошибка вызова OpenAI API: {e}")
            return "[❌ Ошибка GPT.]"


# ========================================================================================
# 5. ИГРОВАЯ ЛОГИКА, АНТИ-СПАМ И ДРУГИЕ КЛАССЫ
# (Сохранено из оригинального кода с адаптацией под async)
# ========================================================================================
# ... Классы GameLogic и SpamAnalyzer должны быть здесь ...
# Их код очень большой, поэтому для краткости он не приводится, 
# но он должен быть скопирован из вашего оригинального файла
# с заменой синхронных вызовов `api._load_json_file` и т.д. на
# асинхронные аналоги или запуск в executor'е, чтобы не блокировать бота.
class DummyGameLogic: # Заглушка для демонстрации
    def get_rig_info(self, user_id, user_name):
        return "🕹️ Функциональность виртуального майнинга в разработке.", None
    def get_top_miners(self):
        return "🏆 Таблица лидеров пока пуста."
        
class DummySpamAnalyzer: # Заглушка для демонстрации
    async def process_message(self, msg: types.Message):
        # В реальной реализации здесь будет логика анализа спама
        pass

# ========================================================================================
# 6. ИНИЦИАЛИЗАЦИЯ ГЛОБАЛЬНЫХ ОБЪЕКТОВ
# ========================================================================================
api = ApiHandler()
game = DummyGameLogic() # Замените на ваш адаптированный класс GameLogic
spam_analyzer = DummySpamAnalyzer() # Замените на ваш адаптированный класс SpamAnalyzer


# ========================================================================================
# 7. ОБРАБОТЧИКИ КОМАНД И КОЛБЭКОВ (HANDLERS)
# ========================================================================================
@dp.message(CommandStart())
async def handle_start(message: Message):
    await message.answer(
        "👋 Привет! Я ваш крипто-помощник.\n\nИспользуйте кнопки для навигации или введите команду.",
        reply_markup=get_main_keyboard()
    )

@dp.message(F.text == "💹 Курс")
async def handle_price_button(message: Message):
    builder = InlineKeyboardBuilder()
    for ticker in Config.POPULAR_TICKERS:
        builder.button(text=ticker, callback_data=f"price_{ticker}")
    builder.button(text="➡️ Другая монета", callback_data="price_other")
    builder.adjust(3, 2)
    await message.answer("Курс какой криптовалюты вас интересует?", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("price_"))
async def handle_price_callback(callback: CallbackQuery):
    await callback.answer()
    action = callback.data.split('_')[1]
    
    if action == "other":
        await callback.message.answer("Введите тикер монеты (например: Aleo, XRP):", reply_markup=ForceReply(selective=True))
        # Здесь нужен FSM для ожидания ответа, для простоты опустим
        return

    await bot.send_chat_action(callback.message.chat.id, 'typing')
    price_data = await api.get_crypto_price(action)
    
    if price_data:
        text = f"💹 Курс {price_data['ticker'].upper()}/USD: <b>${price_data['price']:,.4f}</b>\n<i>(Данные от {price_data['source']})</i>"
        # Логика подбора ASIC
    else:
        text = f"❌ Не удалось получить курс для {action.upper()}."
        
    await send_message_with_partner_button(callback.message.chat.id, text)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass # Сообщение не было изменено, это нормально

@dp.message(F.text == "📰 Новости")
async def handle_news_button(message: Message):
    await bot.send_chat_action(message.chat.id, 'typing')
    news_list = await api.get_crypto_news()
    if not news_list:
        await send_message_with_partner_button(message.chat.id, "[🧐 Свежих новостей не найдено.]")
        return

    items_to_summarize = news_list[:4] # Берем 4 новости для саммари
    tasks = []
    for p in items_to_summarize:
        prompt = f"Сделай очень краткое саммари новости в одно предложение на русском языке: '{p['title']}'"
        tasks.append(api.ask_gpt(prompt, "gpt-4o-mini"))
        
    summaries = await asyncio.gather(*tasks)
    
    items_text = []
    for i, summary in enumerate(summaries):
        if "Ошибка GPT" not in summary:
            link = items_to_summarize[i]['link']
            items_text.append(f"🔹 <a href=\"{link}\">{summary}</a>")

    if not items_text:
        await send_message_with_partner_button(message.chat.id, "[🧐 Не удалось обработать новости.]")
        return

    final_text = "📰 <b>Последние крипто-новости:</b>\n\n" + "\n\n".join(items_text)
    await send_message_with_partner_button(message.chat.id, final_text)

@dp.message(F.text == "😱 Индекс Страха")
async def handle_fear_greed_button(message: Message):
    await bot.send_chat_action(message.chat.id, 'typing')
    index_data = await api.get_fear_and_greed_index()
    
    if not index_data:
        await send_message_with_partner_button(message.chat.id, "[❌ Ошибка при получении индекса]")
        return
        
    value = index_data['value']
    classification = index_data['classification']
    source = index_data['source']

    # Генерация изображения
    try:
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(8, 4.5), subplot_kw={'projection': 'polar'})
        ax.set_yticklabels([])
        ax.set_xticklabels([])
        ax.grid(False)
        ax.spines['polar'].set_visible(False)
        ax.set_ylim(0, 1)
        colors = ['#d94b4b', '#e88452', '#ece36a', '#b7d968', '#73c269']
        for i in range(100):
            ax.barh(1, 0.0314, left=3.14 - (i * 0.0314), height=0.3, color=colors[min(len(colors) - 1, int(i / 25))])
        angle = 3.14 - (value * 0.0314)
        ax.annotate('', xy=(angle, 1), xytext=(0, 0), arrowprops=dict(facecolor='white', shrink=0.05, width=4, headwidth=10))
        fig.text(0.5, 0.5, f"{value}", ha='center', va='center', fontsize=48, color='white', weight='bold')
        fig.text(0.5, 0.35, classification, ha='center', va='center', fontsize=20, color='white')
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, transparent=True)
        buf.seek(0)
        plt.close(fig)
        
        explanation_prompt = f"Кратко объясни для майнера, как 'Индекс страха и жадности' со значением '{value} ({classification})' влияет на рынок. Не более 2-3 предложений."
        explanation = await api.ask_gpt(explanation_prompt)
        caption = f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>\n(Данные от {source})\n\n{explanation}"
        
        await send_photo_with_partner_button(message.chat.id, buf, caption)
    except Exception as e:
        logger.error(f"Ошибка при создании графика индекса страха: {e}")
        await send_message_with_partner_button(message.chat.id, "[❌ Ошибка при создании изображения индекса]")
        
# --- Обработчик для всех остальных текстовых сообщений (потенциально тикеров или вопросов к GPT) ---
@dp.message(F.text)
async def handle_any_text(message: Message):
    # Пропускаем обработку, если текст - это одна из кнопок
    button_texts = ["💹 Курс", "⚙️ Топ ASIC", "⛏️ Калькулятор", "📰 Новости", "😱 Индекс Страха", "⏳ Халвинг", "📡 Статус BTC", "🧠 Викторина", "🕹️ Виртуальный Майнинг"]
    if message.text in button_texts:
        return
        
    await spam_analyzer.process_message(message)
    await bot.send_chat_action(message.chat.id, 'typing')
    
    # Сначала пытаемся распознать как тикер
    price_data = await api.get_crypto_price(message.text)
    if price_data:
        text = f"💹 Курс {price_data['ticker'].upper()}/USD: <b>${price_data['price']:,.4f}</b>\n<i>(Данные от {price_data['source']})</i>"
        await send_message_with_partner_button(message.chat.id, text)
    else:
        # Если не тикер, отправляем в GPT
        response = await api.ask_gpt(message.text)
        await send_message_with_partner_button(message.chat.id, response)


# ========================================================================================
# 8. ЗАПУСК БОТА И ПЛАНИРОВЩИКА
# ========================================================================================
async def auto_send_news():
    """Задача для периодической отправки новостей."""
    if not Config.NEWS_CHAT_ID:
        logger.warning("NEWS_CHAT_ID не установлен, автоматическая отправка новостей отключена.")
        return
    
    logger.info("ПЛАНИРОВЩИК: Запускаю отправку новостей...")
    try:
        # Логика аналогична обработчику кнопки новостей
        news_list = await api.get_crypto_news()
        if not news_list or len(news_list) < 4:
            logger.warning("Недостаточно новостей для авто-отправки.")
            return

        items_to_summarize = news_list[:4]
        tasks = [api.ask_gpt(f"Сделай очень краткое саммари новости в одно предложение на русском языке: '{p['title']}'", "gpt-4o-mini") for p in items_to_summarize]
        summaries = await asyncio.gather(*tasks)

        items_text = [f"🔹 <a href=\"{items_to_summarize[i]['link']}\">{summary}</a>" for i, summary in enumerate(summaries) if "Ошибка" not in summary]
        
        if items_text:
            final_text = "📰 <b>Последние крипто-новости (авто):</b>\n\n" + "\n\n".join(items_text)
            await send_message_with_partner_button(int(Config.NEWS_CHAT_ID), final_text)
            logger.info("Новости успешно отправлены по расписанию.")
        else:
            logger.warning("Не удалось получить саммари новостей для авто-отправки.")
            
    except Exception as e:
        logger.error(f"Ошибка в задаче auto_send_news: {e}", exc_info=True)
        
async def main():
    """Основная функция для запуска бота, планировщика и вебхука (если требуется)."""
    
    # Добавление задач в планировщик
    scheduler.add_job(auto_send_news, 'interval', hours=3, id='auto_news_sender')
    # Можно добавить другие задачи, например, для принудительного обновления кэшей
    # scheduler.add_job(api.get_top_asics, 'interval', hours=1, args=[True])
    
    scheduler.start()
    logger.info("Планировщик запущен.")

    # Удаление старого вебхука перед запуском
    await bot.delete_webhook(drop_pending_updates=True)
    
    if Config.WEBHOOK_URL:
        # Запуск в режиме вебхука (для Render)
        logger.info(f"Режим: вебхук. URL: {Config.WEBHOOK_URL}")
        await bot.set_webhook(f"{Config.WEBHOOK_URL.rstrip('/')}{Config.WEBHOOK_PATH}")
        # Здесь должен быть запуск веб-сервера, например aiohttp.web
        # Эта часть зависит от вашей инфраструктуры и здесь опущена для простоты.
        # Для Render обычно требуется запустить веб-сервер, который будет слушать порт.
    else:
        # Запуск в режиме long-polling (для локальной разработки)
        logger.info("Режим: long-polling.")
        await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    finally:
        if scheduler.running:
            scheduler.shutdown()
