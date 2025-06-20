# -*- coding: utf-8 -*-

# ==============================================================================
# 1. ИМПОРТЫ И НАЧАЛЬНАЯ НАСТРОЙКА
# ==============================================================================
import asyncio
import logging
import os
import random
import re
import json
import io
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Tuple

# Сторонние библиотеки
import aiohttp
import feedparser
import bleach
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, ForceReply
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from cachetools import TTLCache, AIOK, async_cached
from dotenv import load_dotenv
from fuzzywuzzy import process, fuzz
from openai import AsyncOpenAI

# ==============================================================================
# 2. КОНФИГУРАЦИЯ И КОНСТАНТЫ
# ==============================================================================
# Загрузка переменных окружения из файла .env
# Создайте файл .env в корне проекта и добавьте в него ваши ключи
# Пример .env.example:
# BOT_TOKEN="12345:ABC-DEF12345"
# OPENAI_API_KEY="sk-..."
# ADMIN_CHAT_ID="12345678"
# NEWS_CHAT_ID="-10012345678"
# WEBHOOK_URL="https://your-app-name.onrender.com"

load_dotenv()

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


# --- Модели данных (Dataclasses) ---
@dataclass
class AsicMiner:
    """Каноническая модель данных для одного ASIC-майнера."""
    name: str
    profitability: float  # в USD/день
    algorithm: Optional[str] = None
    hashrate: Optional[str] = None
    power: Optional[int] = None  # в Ваттах
    source: Optional[str] = None

@dataclass
class CryptoCoin:
    """Модель данных для криптовалюты с ценой и алгоритмом."""
    id: str
    symbol: str
    name: str
    price: float
    algorithm: Optional[str] = None
    price_change_24h: Optional[float] = None


# --- Основной класс конфигурации ---
class Config:
    """Класс для хранения всех настроек и констант."""
    # --- Ключи API и токены ---
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
    NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")

    # --- Настройки планировщика и новостей ---
    NEWS_RSS_FEEDS = [
        "https://forklog.com/feed",
        "https://bits.media/rss/",
        "https://www.rbc.ru/crypto/feed",
        "https://beincrypto.ru/feed/",
        "https://cointelegraph.com/rss/tag/russia"
    ]
    NEWS_INTERVAL_HOURS = 3

    # --- Алиасы и популярные тикеры ---
    TICKER_ALIASES = {'бтк': 'BTC', 'биткоин': 'BTC', 'биток': 'BTC', 'eth': 'ETH', 'эфир': 'ETH', 'эфириум': 'ETH'}
    POPULAR_TICKERS = ['BTC', 'ETH', 'SOL', 'TON', 'KAS']

    # --- Аварийный список ASIC ---
    # Используется, если ни один источник данных не доступен
    FALLBACK_ASICS: List[Dict[str, Any]] = [
        {'name': 'Antminer S21 200T', 'hashrate': '200 TH/s', 'power': 3550, 'profitability': 11.50, 'algorithm': 'SHA-256'},
        {'name': 'Antminer T21 190T', 'hashrate': '190 TH/s', 'power': 3610, 'profitability': 10.80, 'algorithm': 'SHA-256'},
        {'name': 'Antminer L7 9500M', 'hashrate': '9.5 GH/s', 'power': 3425, 'profitability': 12.00, 'algorithm': 'Scrypt'},
    ]

# ==============================================================================
# 3. ИНИЦИАЛИЗАЦИЯ ОСНОВНЫХ КОМПОНЕНТОВ
# ==============================================================================
if not Config.BOT_TOKEN:
    logger.critical("Критическая ошибка: BOT_TOKEN не установлен. Проверьте ваш .env файл.")
    exit()

bot = Bot(token=Config.BOT_TOKEN, parse_mode='HTML')
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")
openai_client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY) if Config.OPENAI_API_KEY else None

# ==============================================================================
# 4. НАСТРОЙКА КЭШИРОВАНИЯ
# ==============================================================================
# TTLs: ASIC=1 час, Price=5 минут, F&G=4 часа, News=30 минут
asic_cache = TTLCache(maxsize=5, ttl=3600)
price_cache = TTLCache(maxsize=100, ttl=300)
fear_greed_cache = TTLCache(maxsize=2, ttl=14400)
news_cache = TTLCache(maxsize=5, ttl=1800)
coin_list_cache = TTLCache(maxsize=1, ttl=86400) # Кэш для списка всех монет и их алгоритмов

# ==============================================================================
# 5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И УТИЛИТЫ
# ==============================================================================
def sanitize_html(text: str) -> str:
    """Полностью удаляет все HTML-теги и атрибуты, оставляя только обычный текст."""
    return bleach.clean(text, tags=[], attributes={}, strip=True).strip()

async def make_request(session: aiohttp.ClientSession, url: str, response_type='json', **kwargs) -> Optional[Any]:
    """Выполняет асинхронный GET-запрос с обработкой ошибок."""
    try:
        async with session.get(url, timeout=15, **kwargs) as response:
            response.raise_for_status()
            if response_type == 'json':
                return await response.json()
            elif response_type == 'text':
                return await response.text()
            elif response_type == 'bytes':
                return await response.read()
    except aiohttp.ClientError as e:
        logger.warning(f"Сетевая ошибка при запросе к {url}: {e}")
    except asyncio.TimeoutError:
        logger.warning(f"Тайм-аут при запросе к {url}")
    except json.JSONDecodeError as e:
        logger.warning(f"Ошибка декодирования JSON с {url}: {e}")
    return None

def parse_power(power_str: str) -> Optional[int]:
    """Преобразует строку мощности (e.g., '3400W') в целое число."""
    cleaned = re.sub(r'[^0-9]', '', str(power_str))
    return int(cleaned) if cleaned.isdigit() else None

def parse_profitability(profit_str: str) -> float:
    """Преобразует строку прибыльности (e.g., '$5.12/day') в число."""
    cleaned = re.sub(r'[^\d.]', '', str(profit_str))
    return float(cleaned) if cleaned else 0.0

# ==============================================================================
# 6. ЯДРО ЛОГИКИ: СБОР И ОБРАБОТКА ДАННЫХ
# ==============================================================================

# --- Агрегатор данных по ASIC-майнерам ---

async def scrape_asicminervalue(session: aiohttp.ClientSession) -> List[AsicMiner]:
    """Скрапит данные с AsicMinerValue.com."""
    miners = []
    html = await make_request(session, 'https://www.asicminervalue.com/', 'text')
    if not html:
        return miners
    
    logger.info("Получены данные с AsicMinerValue.")
    soup = BeautifulSoup(html, 'lxml')
    table = soup.find('table', {'id': 'datatable'})
    if not table:
        return miners
    
    for row in table.find('tbody').find_all('tr'):
        cols = row.find_all('td')
        if len(cols) > 4:
            try:
                name = cols[1].find('a').text.strip()
                profit_str = cols[3].text.strip()
                profitability = parse_profitability(profit_str)
                power_str = cols[4].text
                power = parse_power(power_str)
                
                if profitability > 0:
                    miners.append(AsicMiner(
                        name=name,
                        profitability=profitability,
                        power=power,
                        source='AsicMinerValue'
                    ))
            except Exception:
                continue
    return miners

async def fetch_whattomine_asics(session: aiohttp.ClientSession) -> List[AsicMiner]:
    """Получает данные с WhatToMine.com."""
    miners = []
    data = await make_request(session, 'https://whattomine.com/asics.json')
    if not data or 'asics' not in data:
        return miners
        
    logger.info("Получены данные с WhatToMine.")
    for name, asic_data in data['asics'].items():
        if asic_data.get('status') == 'Active' and 'revenue' in asic_data:
            profit = parse_profitability(asic_data['revenue'])
            if profit > 0:
                miners.append(AsicMiner(
                    name=name,
                    profitability=profit,
                    algorithm=asic_data.get('algorithm'),
                    hashrate=str(asic_data.get('hashrate')),
                    power=parse_power(str(asic_data.get('power', 0))),
                    source='WhatToMine'
                ))
    return miners

@async_cached(cache=asic_cache)
async def get_profitable_asics() -> List[AsicMiner]:
    """Агрегирует данные по ASIC из нескольких источников."""
    logger.info("Обновление кэша ASIC-майнеров...")
    async with aiohttp.ClientSession() as session:
        tasks = [
            scrape_asicminervalue(session),
            fetch_whattomine_asics(session)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_miners = []
    for res in results:
        if isinstance(res, list):
            all_miners.extend(res)

    if not all_miners:
        logger.warning("Не удалось получить данные по ASIC. Используется аварийный список.")
        return [AsicMiner(**asic) for asic in Config.FALLBACK_ASICS]

    # --- Слияние и дедупликация ---
    final_miners: Dict[str, AsicMiner] = {}
    sorted_by_name = sorted(all_miners, key=lambda m: m.name)

    for miner in sorted_by_name:
        # Ищем наилучшее совпадение по имени
        best_match_key, score = process.extractOne(miner.name, final_miners.keys(), scorer=fuzz.token_set_ratio) if final_miners else (None, 0)
        
        if score > 90 and best_match_key:
            # Нашли дубликат, обновляем данные
            existing_miner = final_miners[best_match_key]
            if miner.profitability > existing_miner.profitability:
                existing_miner.profitability = miner.profitability
            existing_miner.algorithm = existing_miner.algorithm or miner.algorithm
            existing_miner.hashrate = existing_miner.hashrate or miner.hashrate
            existing_miner.power = existing_miner.power or miner.power
        else:
            # Уникальный майнер
            final_miners[miner.name] = miner
    
    sorted_list = sorted(final_miners.values(), key=lambda m: m.profitability, reverse=True)
    logger.info(f"Кэш ASIC-майнеров обновлен. Найдено {len(sorted_list)} уникальных устройств.")
    return sorted_list


# --- Модуль для получения данных по криптовалютам ---
@async_cached(cache=coin_list_cache)
async def get_coin_list() -> Dict[str, str]:
    """Получает и кэширует полный список монет с их алгоритмами из Minerstat."""
    logger.info("Обновление кэша списка монет с алгоритмами...")
    coin_algo_map = {}
    async with aiohttp.ClientSession() as session:
        data = await make_request(session, "https://api.minerstat.com/v2/coins")
        if data:
            for coin_data in data:
                symbol = coin_data.get('coin')
                algorithm = coin_data.get('algorithm')
                if symbol and algorithm:
                    coin_algo_map[symbol.upper()] = algorithm
    logger.info(f"Кэш списка монет обновлен. Загружено {len(coin_algo_map)} монет.")
    return coin_algo_map

@async_cached(price_cache, key=AIOK.REPR)
async def get_crypto_price(query: str) -> Optional[CryptoCoin]:
    """Получает цену и алгоритм для криптовалюты, используя CoinGecko."""
    query = query.strip().lower()
    query = Config.TICKER_ALIASES.get(query, query)
    
    async with aiohttp.ClientSession() as session:
        search_url = f"https://api.coingecko.com/api/v3/search?query={query}"
        search_data = await make_request(session, search_url)
        if not search_data or not search_data.get('coins'):
            return None

        coin_info = search_data['coins'][0]
        coin_id = coin_info.get('id')
        
        market_url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={coin_id}"
        market_data_list = await make_request(session, market_url)
        if not market_data_list:
            return None
        
        market_data = market_data_list[0]
        symbol = market_data.get('symbol', '').upper()
        
        coin_algo_map = await get_coin_list()
        algorithm = coin_algo_map.get(symbol)

        return CryptoCoin(
            id=market_data.get('id'),
            symbol=symbol,
            name=market_data.get('name'),
            price=market_data.get('current_price', 0.0),
            price_change_24h=market_data.get('price_change_percentage_24h'),
            algorithm=algorithm
        )

# --- Модуль "Индекс страха и жадности" ---
@async_cached(fear_greed_cache)
async def get_fear_and_greed_index() -> Optional[Dict]:
    """Получает "Индекс страха и жадности"."""
    async with aiohttp.ClientSession() as session:
        data = await make_request(session, "https://api.alternative.me/fng/?limit=1")
        if data and 'data' in data and data['data']:
            return data['data'][0]
    return None

# --- Модуль новостей ---
@async_cached(cache=news_cache)
async def fetch_latest_news() -> List[Dict]:
    """Парсит RSS-ленты и возвращает список последних новостей."""
    all_news = []
    
    async def parse_feed(session, url):
        try:
            response_text = await make_request(session, url, 'text')
            if response_text:
                feed = feedparser.parse(response_text)
                for entry in feed.entries:
                    all_news.append({
                        'title': entry.title,
                        'link': entry.link,
                        'published': getattr(entry, 'published_parsed', None)
                    })
        except Exception as e:
            logger.warning(f"Не удалось спарсить RSS-ленту {url}: {e}")

    async with aiohttp.ClientSession() as session:
        tasks = [parse_feed(session, url) for url in Config.NEWS_RSS_FEEDS]
        await asyncio.gather(*tasks)

    all_news.sort(key=lambda x: x['published'] or (0,), reverse=True)
    
    seen_titles = set()
    unique_news = []
    for item in all_news:
        if item['title'].lower() not in seen_titles:
            unique_news.append(item)
            seen_titles.add(item['title'].lower())

    return unique_news[:5]

# --- Модули статуса сети ---
async def get_halving_info() -> str:
    """Получает информацию о халвинге Bitcoin."""
    async with aiohttp.ClientSession() as s:
        height_str = await make_request(s, "https://mempool.space/api/blocks/tip/height", 'text')
        if not height_str or not height_str.isdigit():
            return "❌ Не удалось получить данные о халвинге."
        
        current_block = int(height_str)
        halving_interval = 210000
        blocks_left = halving_interval - (current_block % halving_interval)
        days = blocks_left / 144  # Приблизительно 144 блока в день
        return f"⏳ <b>До халвинга Bitcoin осталось:</b>\n\n🧱 <b>Блоков:</b> <code>{blocks_left:,}</code>\n🗓 <b>Примерно дней:</b> <code>{days:.1f}</code>"

async def get_btc_network_status() -> str:
    """Получает статус сети Bitcoin."""
    async with aiohttp.ClientSession() as s:
        fees_url = "https://mempool.space/api/v1/fees/recommended"
        mempool_url = "https://mempool.space/api/mempool"
        fees, mempool = await asyncio.gather(make_request(s, fees_url), make_request(s, mempool_url))

        if not fees or not mempool:
            return "❌ Не удалось получить статус сети BTC."

        return (f"📡 <b>Статус сети Bitcoin:</b>\n\n"
                f"📈 <b>Транзакций в мемпуле:</b> <code>{mempool.get('count', 'N/A'):,}</code>\n\n"
                f"💸 <b>Рекомендуемые комиссии (sat/vB):</b>\n"
                f"  - 🚀 Высокий приоритет: <code>{fees.get('fastestFee', 'N/A')}</code>\n"
                f"  - 🚶‍♂️ Средний приоритет: <code>{fees.get('halfHourFee', 'N/A')}</code>\n"
                f"  - 🐢 Низкий приоритет: <code>{fees.get('hourFee', 'N/A')}</code>")


# --- Модуль викторины с GPT ---
async def generate_quiz_question() -> Optional[Dict]:
    """Генерирует вопрос для викторины с помощью OpenAI."""
    if not openai_client:
        logger.warning("Ключ OpenAI не установлен. Викторина недоступна.")
        return None

    logger.info("Генерация вопроса для викторины...")
    prompt = ('Создай 1 интересный вопрос для викторины на тему криптовалют или майнинга. '
              'Вопрос должен быть среднего уровня сложности. '
              'Ответ верни строго в формате JSON-объекта с ключами: "question" (строка), '
              '"options" (массив из 4 строк) и "correct_option_index" (число от 0 до 3). '
              'Без лишних слов и markdown-форматирования.')
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.8,
        )
        quiz_data = json.loads(response.choices[0].message.content)
        # Валидация
        if all(k in quiz_data for k in ['question', 'options', 'correct_option_index']) and len(quiz_data['options']) == 4:
            logger.info("Вопрос для викторины успешно сгенерирован.")
            return quiz_data
        else:
            logger.warning(f"GPT вернул некорректный формат JSON: {quiz_data}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при генерации вопроса викторины через OpenAI: {e}", exc_info=True)
        return None

# ==============================================================================
# 7. ОБРАБОТЧИКИ КОМАНД И КОЛБЭКОВ TELEGRAM
# ==============================================================================

def get_main_menu_keyboard():
    """Создает основную клавиатуру меню."""
    builder = InlineKeyboardBuilder()
    buttons = {
        "💹 Курс": "menu_price",
        "⚙️ Топ ASIC": "menu_asics",
        "⛏️ Калькулятор": "menu_calculator",
        "📰 Новости": "menu_news",
        "😱 Индекс Страха": "menu_fear_greed",
        "⏳ Халвинг": "menu_halving",
        "📡 Статус BTC": "menu_btc_status",
        "🧠 Викторина": "menu_quiz",
    }
    for text, data in buttons.items():
        builder.button(text=text, callback_data=data)
    builder.adjust(2)
    return builder.as_markup()

@dp.message(CommandStart())
async def handle_start(message: Message):
    await message.answer(
        "👋 Привет! Я ваш крипто-помощник.\n\nИспользуйте кнопки для навигации.",
        reply_markup=get_main_menu_keyboard()
    )

@dp.message(Command('menu'))
async def handle_menu_command(message: Message):
    await message.answer("Главное меню:", reply_markup=get_main_menu_keyboard())

# --- Обработчики кнопок главного меню ---

@dp.callback_query(F.data == "menu_asics")
async def handle_asics_menu(call: CallbackQuery):
    await call.message.edit_text("⏳ Загружаю актуальный список со всех источников...")
    asics = await get_profitable_asics()
    if not asics:
        await call.message.edit_text("Не удалось получить данные об ASIC.", reply_markup=get_main_menu_keyboard())
        return

    response_text = "🏆 <b>Топ-10 доходных ASIC на сегодня:</b>\n\n"
    for miner in asics[:10]:
        response_text += (
            f"<b>{sanitize_html(miner.name)}</b>\n"
            f"  Доход: <b>${miner.profitability:.2f}/день</b>"
            f"{f' | Алгоритм: {miner.algorithm}' if miner.algorithm else ''}"
            f"{f' | Мощность: {miner.power}W' if miner.power else ''}\n"
        )
    
    await call.message.edit_text(response_text, reply_markup=get_main_menu_keyboard())
    await call.answer()

@dp.callback_query(F.data == "menu_price")
async def handle_price_menu(call: CallbackQuery):
    builder = InlineKeyboardBuilder()
    for ticker in Config.POPULAR_TICKERS:
        builder.button(text=ticker, callback_data=f"price_{ticker}")
    builder.adjust(len(Config.POPULAR_TICKERS))
    builder.row(types.InlineKeyboardButton(text="➡️ Другая монета", callback_data="price_other"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main_menu"))
    await call.message.edit_text("Курс какой криптовалюты вас интересует?", reply_markup=builder.as_markup())
    await call.answer()

@dp.callback_query(F.data == "back_to_main_menu")
async def handle_back_to_main(call: CallbackQuery):
    await call.message.edit_text("Главное меню:", reply_markup=get_main_menu_keyboard())
    await call.answer()
    
async def send_price_info(message: types.Message, query: str):
    """Общая функция для отправки информации о цене."""
    await message.answer("⏳ Ищу информацию...")
    coin = await get_crypto_price(query)
    if not coin:
        await message.answer(f"❌ Не удалось найти информацию по запросу '{query}'.")
        return

    change_24h = coin.price_change_24h or 0
    emoji = "📈" if change_24h >= 0 else "📉"
    response_text = (
        f"<b>{coin.name} ({coin.symbol})</b>\n"
        f"💹 Курс: <b>${coin.price:,.4f}</b>\n"
        f"{emoji} Изменение за 24ч: <b>{change_24h:.2f}%</b>\n"
    )
    if coin.algorithm:
        response_text += f"⚙️ Алгоритм: <code>{coin.algorithm}</code>"
    
    await message.answer(response_text)

@dp.callback_query(F.data.startswith("price_"))
async def handle_price_callback(call: CallbackQuery):
    action = call.data.split('_')[1]
    if action == "other":
        await call.message.answer("Введите тикер монеты (например, Aleo, XRP):", reply_markup=ForceReply())
    else:
        await call.message.delete()
        await send_price_info(call.message, action)
        await handle_menu_command(call.message) # Показываем меню снова
    await call.answer()

@dp.callback_query(F.data == "menu_news")
async def handle_news_menu(call: CallbackQuery):
    await call.message.edit_text("⏳ Загружаю последние новости...")
    news = await fetch_latest_news()
    if not news:
        await call.message.edit_text("Не удалось загрузить новости.", reply_markup=get_main_menu_keyboard())
        return

    text = "📰 <b>Последние крипто-новости:</b>\n\n" + "\n".join(
        [f"🔹 <a href=\"{n['link']}\">{sanitize_html(n['title'])}</a>" for n in news]
    )
    
    # Отправляем новым сообщением, так как в edit_message могут быть проблемы с превью ссылок
    await call.message.delete()
    await call.message.answer(text, disable_web_page_preview=True)
    await call.message.answer("Главное меню:", reply_markup=get_main_menu_keyboard())
    await call.answer()
    
@dp.callback_query(F.data == "menu_fear_greed")
async def handle_fear_greed_menu(call: CallbackQuery):
    await call.message.edit_text("⏳ Получаю индекс...")
    index = await get_fear_and_greed_index()
    if not index:
        await call.message.edit_text("Не удалось получить индекс.", reply_markup=get_main_menu_keyboard())
        return

    value = int(index['value'])
    classification = index['value_classification']
    
    # Генерация изображения
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
    
    caption = f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>"
    
    await call.message.delete()
    await call.message.answer_photo(types.BufferedInputFile(buf.read(), "fng.png"), caption=caption)
    await call.message.answer("Главное меню:", reply_markup=get_main_menu_keyboard())
    await call.answer()

@dp.callback_query(F.data.in_({"menu_halving", "menu_btc_status", "menu_calculator"}))
async def handle_info_callbacks(call: CallbackQuery):
    await call.message.edit_text("⏳ Обрабатываю запрос...")
    text = "❌ Произошла ошибка."
    if call.data == "menu_halving":
        text = await get_halving_info()
    elif call.data == "menu_btc_status":
        text = await get_btc_network_status()
    elif call.data == "menu_calculator":
        await call.message.answer("💡 Введите стоимость электроэнергии в <b>рублях</b> за кВт/ч:", reply_markup=ForceReply())
        await call.answer()
        return

    await call.message.edit_text(text, reply_markup=get_main_menu_keyboard())
    await call.answer()

@dp.callback_query(F.data == "menu_quiz")
async def handle_quiz_menu(call: CallbackQuery):
    await call.message.edit_text("⏳ Генерирую уникальный вопрос...")
    quiz_data = await generate_quiz_question()
    if not quiz_data:
        await call.message.edit_text("😕 Не удалось сгенерировать вопрос. Попробуйте позже.", reply_markup=get_main_menu_keyboard())
        return

    await call.message.delete()
    await call.message.answer_poll(
        question=quiz_data['question'],
        options=quiz_data['options'],
        type='quiz',
        correct_option_id=quiz_data['correct_option_index'],
        is_anonymous=False,
        reply_markup=InlineKeyboardBuilder().button(text="Следующий вопрос", callback_data="menu_quiz").as_markup()
    )
    await call.answer()

@dp.poll_answer()
async def handle_poll_answer(poll_answer: types.PollAnswer):
    # Здесь можно добавить логику для сохранения результатов викторины
    logger.info(f"Пользователь {poll_answer.user.id} ответил на викторину.")


# --- Обработчик текстовых сообщений ---
@dp.message(F.text)
async def handle_text_message(message: Message):
    # Проверяем, является ли сообщение ответом на запрос ввода
    if message.reply_to_message and message.reply_to_message.from_user.id == bot.id:
        # Ответ на "Введите тикер"
        if "Введите тикер монеты" in message.reply_to_message.text:
            await message.delete()
            await message.reply_to_message.delete()
            await send_price_info(message, message.text)
            await handle_menu_command(message) # Показываем меню снова
        # Ответ на "Введите стоимость электроэнергии"
        elif "стоимость электроэнергии" in message.reply_to_message.text:
            try:
                cost_rub = float(message.text.replace(',', '.'))
                # Заглушка для курса, в реальном приложении нужно получать актуальный
                rate_usd_rub = 90.0 
                cost_usd = cost_rub / rate_usd_rub
                
                asics = await get_profitable_asics()
                if not asics:
                    await message.answer("❌ Не удалось получить данные о доходности ASIC.")
                    return

                res = [f"💰 <b>Расчет профита (розетка {cost_rub:.2f} ₽/кВтч)</b>\n"]
                for asic in asics[:10]:
                    if asic.power:
                        daily_cost = (asic.power / 1000) * 24 * cost_usd
                        profit = asic.profitability - daily_cost
                        res.append(f"<b>{sanitize_html(asic.name)}</b>: ${profit:.2f}/день")
                await message.answer("\n".join(res))
                await handle_menu_command(message) # Показываем меню снова

            except (ValueError, TypeError):
                await message.answer("❌ Неверный формат. Введите число (например: 4.5).")
            await message.reply_to_message.delete()
            await message.delete()
    else:
        # Если это не ответ, считаем, что пользователь хочет узнать курс
        await send_price_info(message, message.text)


# ==============================================================================
# 8. ЗАПУСК ПЛАНИРОВЩИКА И БОТА
# ==============================================================================
async def send_news_job():
    """Задача для APScheduler: получает новости и отправляет их."""
    if not Config.NEWS_CHAT_ID:
        logger.warning("Переменная NEWS_CHAT_ID не установлена. Авто-отправка новостей отключена.")
        return

    logger.info("Запуск задачи по отправке новостей...")
    try:
        news = await fetch_latest_news()
        if not news:
            logger.info("Новых новостей для отправки не найдено.")
            return

        text = "📰 <b>Последние крипто-новости (авто-рассылка):</b>\n\n" + "\n".join(
            [f"🔹 <a href=\"{n['link']}\">{sanitize_html(n['title'])}</a>" for n in news]
        )
        await bot.send_message(Config.NEWS_CHAT_ID, text, disable_web_page_preview=True)
        logger.info(f"Новости успешно отправлены в чат {Config.NEWS_CHAT_ID}.")
    except Exception as e:
        logger.error(f"Ошибка при выполнении задачи отправки новостей: {e}", exc_info=True)


async def main():
    """Основная функция для запуска бота и планировщика."""
    # Добавление задачи в планировщик
    if Config.NEWS_CHAT_ID:
        scheduler.add_job(send_news_job, 'interval', hours=Config.NEWS_INTERVAL_HOURS, misfire_grace_time=60)
        scheduler.start()
        logger.info(f"Задача по отправке новостей запланирована каждые {Config.NEWS_INTERVAL_HOURS} часа.")
    else:
        logger.warning("NEWS_CHAT_ID не указан, автоматическая отправка новостей отключена.")

    # Предварительный прогрев кэша
    logger.info("Предварительный прогрев кэша...")
    await asyncio.gather(
        get_profitable_asics(),
        get_coin_list(),
        return_exceptions=True
    )
    logger.info("Кэш прогрет.")
    
    # Удаление вебхука перед запуском
    await bot.delete_webhook(drop_pending_updates=True)

    if Config.WEBHOOK_URL:
        # Запуск в режиме вебхука (для продакшена)
        # Убедитесь, что ваше приложение может обрабатывать входящие запросы на /webhook
        # и что порт 8080 (или другой) открыт.
        logger.info(f"Запуск в режиме вебхука. URL: {Config.WEBHOOK_URL}")
        # Здесь должен быть код для запуска веб-сервера (например, aiohttp.web)
        # Этот код здесь не приводится для простоты, так как он зависит от хостинга
        # await bot.set_webhook(url=Config.WEBHOOK_URL)
        logger.warning("Для режима вебхука требуется дополнительная настройка веб-сервера (aiohttp, FastAPI). Запускаюсь в режиме опроса.")
        await dp.start_polling(bot)

    else:
        # Запуск в режиме long-polling (для разработки)
        logger.info("Запуск в режиме long-polling.")
        await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
    finally:
        if scheduler.running:
            scheduler.shutdown()
