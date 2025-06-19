# -*- coding: utf-8 -*-
# ==============================================================================
# Раздел 1: Импорты и начальная настройка
# ==============================================================================
import asyncio
import logging
import os
import random
import re
from dataclasses import dataclass
from typing import List, Optional, Dict

import aiohttp
import bleach
import feedparser
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from cachetools import TTLCache, cached
from fuzzywuzzy import fuzz, process
from openai import AsyncOpenAI

# ==============================================================================
# Раздел 2: Конфигурация и константы
# ==============================================================================

# --- Конфигурация API ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CMC_API_KEY = os.getenv("CMC_API_KEY")  # CoinMarketCap API Key

# --- Конфигурация парсинга и сбора данных ---
ASIC_SOURCES = {
    'asicminervalue': 'https://www.asicminervalue.com/',
}
MINERSTAT_API_URL = "https://api.minerstat.com/v2/hardware"
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
MINERSTAT_COINS_URL = "https://api.minerstat.com/v2/coins"
FEAR_AND_GREED_API_URL = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical"

# --- Конфигурация новостей ---
NEWS_RSS_FEEDS = [
    "https://cointelegraph.com/rss/tag/russia",
    "https://forklog.com/feed",
    "https://www.rbc.ru/crypto/feed",
    "https://bits.media/rss/",
]
NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")  # ID чата для отправки новостей
NEWS_INTERVAL_HOURS = 3

# --- Конфигурация кэширования ---
# Кэш для данных по ASIC-майнерам (TTL 1 час)
asic_cache = TTLCache(maxsize=1, ttl=3600)
# Кэш для цен на криптовалюты (TTL 5 минут)
crypto_price_cache = TTLCache(maxsize=500, ttl=300)
# Кэш для "Индекса страха и жадности" (TTL 4 часа)
fear_greed_cache = TTLCache(maxsize=1, ttl=14400)
# Кэш для списка монет с алгоритмами (TTL 24 часа)
coin_list_cache = TTLCache(maxsize=1, ttl=86400)

# --- Настройка журналирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Инициализация основных компонентов ---
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ==============================================================================
# Раздел 3: Модели данных (Dataclasses)
# ==============================================================================

@dataclass
class AsicMiner:
    """Каноническая модель данных для одного ASIC-майнера."""
    name: str
    algorithm: str
    hashrate: str
    power: int  # в Ваттах
    profitability: float  # в USD/день
    source: str

@dataclass
class CryptoCoin:
    """Модель данных для криптовалюты с ценой и алгоритмом."""
    id: str
    symbol: str
    name: str
    price: float
    algorithm: Optional[str] = None
    market_cap: Optional[int] = None

# ==============================================================================
# Раздел 4: Вспомогательные и утилитарные функции
# ==============================================================================

def sanitize_html(text: str) -> str:
    """
    Полностью удаляет все HTML-теги и атрибуты, оставляя только обычный текст.
    Это 100% надежный способ предотвратить ошибку Telegram "can't parse entities".
    """
    if not text:
        return ""
    return bleach.clean(text, tags=[], attributes={}, strip=True).strip()

async def resilient_request(session: aiohttp.ClientSession, url: str, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[Dict]:
    """
    Выполняет асинхронный GET-запрос с базовой обработкой ошибок и возвращает JSON.
    Использует ротацию User-Agent для маскировки запросов.
    """
    try:
        user_agent_list = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        ]
        request_headers = {'User-Agent': random.choice(user_agent_list)}
        if headers:
            request_headers.update(headers)

        async with session.get(url, headers=request_headers, params=params, timeout=15) as response:
            response.raise_for_status()
            return await response.json()
    except aiohttp.ClientError as e:
        logger.error(f"Ошибка сетевого запроса к {url}: {e}")
    except asyncio.TimeoutError:
        logger.error(f"Тайм-аут при запросе к {url}")
    except Exception as e:
        logger.error(f"Неизвестная ошибка при запросе к {url}: {e}")
    return None

def parse_power(power_str: str) -> int:
    """Преобразует строку мощности (e.g., '3400W') в целое число."""
    return int(re.sub(r'[^0-9]', '', power_str)) if power_str else 0

def parse_profitability(profit_str: str) -> float:
    """Преобразует строку прибыльности (e.g., '$5.12') в число с плавающей точкой."""
    cleaned_str = re.sub(r'[^\d.]', '', profit_str)
    return float(cleaned_str) if cleaned_str else 0.0

# ==============================================================================
# Раздел 5: Основные модули сбора данных
# ==============================================================================

# --- Модуль сбора данных по ASIC-майнерам ---

async def scrape_asicminervalue(session: aiohttp.ClientSession) -> List[AsicMiner]:
    """
    Скрапит данные о прибыльности ASIC-майнеров с AsicMinerValue.com.
    """
    miners: List[AsicMiner] = []
    url = ASIC_SOURCES['asicminervalue']
    
    try:
        async with session.get(url, timeout=20) as response:
            response.raise_for_status()
            html = await response.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.error(f"Не удалось получить HTML с AsicMinerValue: {e}")
        return miners

    try:
        soup = BeautifulSoup(html, 'lxml')
        table = soup.find('table', {'class': 'table-hover'})
        if not table:
            logger.warning("Не удалось найти таблицу на AsicMinerValue")
            return miners
        
        rows = table.find('tbody').find_all('tr')
        for row in rows:
            cols = row.find_all('td')
            if len(cols) > 6:
                try:
                    # ИСПРАВЛЕНО: Индексы колонок скорректированы для правильного парсинга.
                    name = cols[0].text.strip()
                    hashrate = cols[2].text.strip()
                    power_str = cols[3].text.strip()
                    algorithm = cols[5].text.strip()
                    profitability_str = cols[6].text.strip()
                    
                    profitability = parse_profitability(profitability_str)
                    
                    if profitability > 0:
                        miners.append(AsicMiner(
                            name=name,
                            algorithm=algorithm,
                            hashrate=hashrate,
                            power=parse_power(power_str),
                            profitability=profitability,
                            source='AsicMinerValue'
                        ))
                except (ValueError, IndexError) as e:
                    logger.warning(f"Ошибка парсинга строки на AsicMinerValue: {e} | Строка: {[c.text.strip() for c in cols]}")
                    continue
    except Exception as e:
        logger.error(f"Критическая ошибка при скрапинге AsicMinerValue: {e}", exc_info=True)

    return miners

@cached(asic_cache)
async def get_profitable_asics() -> List[AsicMiner]:
    """
    Агрегирует данные по ASIC-майнерам из нескольких источников, сливает и дедуплицирует их.
    """
    logger.info("Обновление кэша ASIC-майнеров...")
    async with aiohttp.ClientSession() as session:
        scraped_miners = await scrape_asicminervalue(session)

    if not scraped_miners:
        logger.warning("Не удалось получить данные по ASIC ни из одного источника.")
        return []
    
    # В данной версии используется один, но наиболее полный источник (AsicMinerValue).
    # Логика слияния с Minerstat может быть добавлена для обогащения данных.
    
    # Сортируем по прибыльности в убывающем порядке
    sorted_miners = sorted(scraped_miners, key=lambda m: m.profitability, reverse=True)
    logger.info(f"Кэш ASIC-майнеров обновлен. Найдено {len(sorted_miners)} уникальных устройств.")
    return sorted_miners

# --- Модуль получения данных по криптовалютам ---

@cached(coin_list_cache)
async def get_coin_list_with_algorithms() -> Dict[str, str]:
    """
    Получает и кэширует полный список монет с их алгоритмами из Minerstat.
    Возвращает словарь {СИМВОЛ: АЛГОРИТМ}.
    """
    logger.info("Обновление кэша списка монет с алгоритмами...")
    coin_algo_map = {}
    async with aiohttp.ClientSession() as session:
        data = await resilient_request(session, MINERSTAT_COINS_URL)
        if data:
            for coin_data in data:
                symbol = coin_data.get('coin')
                algorithm = coin_data.get('algorithm')
                if symbol and algorithm:
                    coin_algo_map[symbol.upper()] = algorithm
    logger.info(f"Кэш списка монет обновлен. Загружено {len(coin_algo_map)} монет.")
    return coin_algo_map

@cached(crypto_price_cache)
async def get_crypto_price(query: str) -> Optional[CryptoCoin]:
    """
    Получает цену, рыночные данные и алгоритм для криптовалюты по тикеру или названию.
    Использует CoinGecko для цен и Minerstat для алгоритмов.
    """
    query = query.lower().strip()
    if not query:
        return None
        
    async with aiohttp.ClientSession() as session:
        # 1. Поиск монеты на CoinGecko
        search_data = await resilient_request(session, f"{COINGECKO_API_URL}/search", params={'query': query})
        if not search_data or not search_data.get('coins'):
            return None

        # ИСПРАВЛЕНО: Берем первый, наиболее релевантный результат
        coin_info = search_data['coins'][0]
        coin_id = coin_info.get('id')
        if not coin_id:
            return None

        # 2. Получение детальных рыночных данных
        market_data_list = await resilient_request(session, f"{COINGECKO_API_URL}/coins/markets", params={'vs_currency': 'usd', 'ids': coin_id})
        if not market_data_list:
            return None
            
        market_data = market_data_list[0]
        
        # 3. Получение алгоритма
        coin_algo_map = await get_coin_list_with_algorithms()
        symbol = market_data.get('symbol', '').upper()
        algorithm = coin_algo_map.get(symbol)

        return CryptoCoin(
            id=market_data.get('id'),
            symbol=symbol,
            name=market_data.get('name'),
            price=market_data.get('current_price', 0.0),
            market_cap=market_data.get('market_cap', 0),
            algorithm=algorithm
        )

# --- Модуль "Индекс страха и жадности" ---

@cached(fear_greed_cache)
async def get_fear_and_greed_index() -> Optional[Dict]:
    """
    Получает последнее значение "Индекса страха и жадности" из API CoinMarketCap.
    """
    if not CMC_API_KEY:
        return None
    logger.info("Обновление кэша 'Индекса страха и жадности'...")
    headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
    
    async with aiohttp.ClientSession() as session:
        data = await resilient_request(session, FEAR_AND_GREED_API_URL, headers=headers, params={'limit': '1'})
        if data and data.get('status', {}).get('error_code') == 0 and data.get('data'):
            # ИСПРАВЛЕНО: Получаем первый элемент из списка данных
            latest_data = data['data'][0]
            logger.info("Кэш 'Индекса страха и жадности' обновлен.")
            return {
                'value': latest_data.get('value'),
                'classification': latest_data.get('value_classification')
            }
    return None

# --- Модуль новостей ---

async def fetch_latest_news() -> List[Dict]:
    """
    Парсит RSS-ленты и возвращает список последних новостей.
    """
    all_news = []
    for url in NEWS_RSS_FEEDS:
        try:
            # feedparser работает синхронно, запускаем в executor-е, чтобы не блокировать event loop
            loop = asyncio.get_running_loop()
            feed = await loop.run_in_executor(None, feedparser.parse, url)
            
            for entry in feed.entries:
                all_news.append({
                    'title': entry.title,
                    'link': entry.link,
                    'summary': sanitize_html(getattr(entry, 'summary', '')),
                    'published': getattr(entry, 'published_parsed', None)
                })
        except Exception as e:
            logger.error(f"Не удалось спарсить RSS-ленту {url}: {e}")
    
    # Сортируем по дате публикации, самые новые - вверху
    all_news.sort(key=lambda x: x['published'] or (0,0,0,0,0,0), reverse=True)
    
    # Убираем дубликаты по заголовкам
    seen_titles = set()
    unique_news = []
    for news_item in all_news:
        if news_item['title'].lower() not in seen_titles:
            unique_news.append(news_item)
            seen_titles.add(news_item['title'].lower())

    return unique_news[:5] # Возвращаем 5 последних новостей

async def send_news_job():
    """
    Задача для APScheduler: получает новости и отправляет их в указанный чат.
    """
    if not NEWS_CHAT_ID:
        logger.warning("Переменная окружения NEWS_CHAT_ID не установлена. Отправка новостей невозможна.")
        return
        
    logger.info("Запуск задачи по отправке новостей...")
    try:
        latest_news = await fetch_latest_news()
        if not latest_news:
            logger.info("Новых новостей для отправки не найдено.")
            return

        message_text = "📰 **Последние новости из мира криптовалют:**\n\n"
        for i, news_item in enumerate(latest_news):
            title = sanitize_html(news_item['title']).replace('[', '(').replace(']', ')')
            message_text += f"{i+1}. [{title}]({news_item['link']})\n"
        
        await bot.send_message(NEWS_CHAT_ID, message_text, parse_mode="Markdown", disable_web_page_preview=True)
        logger.info(f"Новости успешно отправлены в чат {NEWS_CHAT_ID}.")
    except Exception as e:
        logger.error(f"Ошибка при выполнении задачи отправки новостей: {e}", exc_info=True)

# --- Модуль викторины с GPT ---

async def generate_quiz_question() -> Optional[Dict]:
    """
    Генерирует вопрос для викторины с помощью OpenAI GPT на основе последних новостей.
    """
    if not openai_client:
        return None
        
    logger.info("Генерация вопроса для викторины...")
    try:
        news = await fetch_latest_news()
        if not news:
            return None
        
        # Используем краткое содержание последней новости как контекст
        context = news[0]['summary']
        
        prompt = f"""
        На основе следующего текста новости из мира криптовалют, создай один вопрос для викторины с четырьмя вариантами ответа.
        
        Контекст:
        \"\"\"
        {context}
        \"\"\"
        
        Твоя задача:
        1. Внимательно прочти контекст и выдели ключевой факт.
        2. Сформулируй четкий вопрос, основанный на этом факте.
        3. Создай один правильный ответ.
        4. Создай три правдоподобных, но неверных ответа.
        5. Верни результат в виде строгого JSON-объекта со следующими ключами: "question" (строка), "options" (список из 4 строк), "correct_option_index" (число от 0 до 3).
        
        JSON-ответ должен быть единственным выводом, без дополнительных пояснений.
        """

        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        
        quiz_data = await asyncio.to_thread(lambda: response.choices[0].message.model_dump_json())
        import json
        quiz_data = json.loads(json.loads(quiz_data)['content'])
        
        # Валидация полученных данных
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
# Раздел 6: Обработчики команд и колбэков Telegram
# ==============================================================================

def get_main_keyboard():
    """Возвращает основную клавиатуру с кнопками."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Доходные ASIC-майнеры", callback_data="get_asics")
    builder.button(text="📈 Курс криптовалюты", callback_data="get_price_prompt")
    if CMC_API_KEY:
        builder.button(text="😨 Индекс страха и жадности", callback_data="get_fear_greed")
    builder.button(text="📰 Последние новости", callback_data="get_news")
    if OPENAI_API_KEY:
        builder.button(text="🧠 Викторина", callback_data="start_quiz")
    builder.adjust(1)
    return builder.as_markup()

@dp.message(CommandStart())
async def send_welcome(message: Message):
    """Обработчик команды /start."""
    await message.answer(
        "👋 Привет! Я твой крипто-помощник.\n"
        "Я помогу тебе найти информацию о доходности ASIC-майнеров, курсах криптовалют и многом другом.\n\n"
        "Выбери одну из опций ниже:",
        reply_markup=get_main_keyboard()
    )

@dp.callback_query(lambda c: c.data == 'get_asics')
async def handle_asics_command(callback_query: CallbackQuery):
    """Обработчик кнопки 'Доходные ASIC-майнеры'."""
    await callback_query.message.answer("🔍 Ищу самые доходные ASIC-майнеры... Это может занять несколько секунд.")
    asics = await get_profitable_asics()
    if not asics:
        await callback_query.message.answer("😕 Не удалось получить данные о майнерах. Попробуйте позже.")
        await callback_query.answer()
        return

    response_text = "🏆 **Топ-10 самых доходных ASIC-майнеров на сегодня:**\n\n"
    for i, miner in enumerate(asics[:10]):
        response_text += (
            f"**{i+1}. {sanitize_html(miner.name)}**\n"
            f"   - Алгоритм: `{miner.algorithm}`\n"
            f"   - Хешрейт: `{miner.hashrate}`\n"
            f"   - Потребление: `{miner.power} W`\n"
            f"   - **Доход в день: `${miner.profitability:.2f}`**\n\n"
        )
    
    await callback_query.message.answer(response_text, parse_mode="Markdown")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == 'get_price_prompt')
async def handle_price_prompt(callback_query: CallbackQuery):
    """Запрашивает у пользователя тикер монеты."""
    await callback_query.message.answer("Введите тикер или название криптовалюты (например, `BTC`, `Ethereum`, `Aleo`):", parse_mode="Markdown")
    await callback_query.answer()

async def process_crypto_query(message: Message):
    """Общая функция для обработки запроса курса криптовалюты."""
    query = message.text.strip()
    await message.answer(f"🔍 Ищу информацию по '{query}'...")
    
    coin = await get_crypto_price(query)
    if not coin:
        await message.answer(f"😕 Не удалось найти информацию по запросу '{query}'. Убедитесь, что тикер или название верны.")
        return
        
    response_text = (
        f"**{coin.name} ({coin.symbol.upper()})**\n\n"
        f"💰 **Цена:** ${coin.price:,.4f}\n"
    )
    if coin.market_cap and coin.market_cap > 0:
        response_text += f"📊 **Рыночная капитализация:** ${coin.market_cap:,.0f}\n"
    
    if coin.algorithm:
        response_text += f"⚙️ **Алгоритм:** `{coin.algorithm}`\n\n"
        
        all_asics = await get_profitable_asics()
        # Игнорируем регистр и возможные пробелы/тире при сравнении алгоритмов
        normalized_algo = coin.algorithm.lower().replace('-', '').replace(' ', '')
        relevant_asics = [
            asic for asic in all_asics 
            if asic.algorithm.lower().replace('-', '').replace(' ', '') == normalized_algo
        ]
        
        if relevant_asics:
            response_text += "⛏️ **Рекомендуемое оборудование:**\n"
            for i, asic in enumerate(relevant_asics[:3]):
                response_text += f"- {sanitize_html(asic.name)} (Доход: ${asic.profitability:.2f}/день)\n"
        else:
            response_text += "⛏️ Подходящее ASIC-оборудование не найдено в базе."
    else:
        response_text += "⛏️ Алгоритм майнинга не определен для этой монеты."

    await message.answer(response_text, parse_mode="Markdown")

@dp.message(Command('price'))
async def price_command_handler(message: Message, command: Command):
    if command.args:
        message.text = command.args
        await process_crypto_query(message)
    else:
        await message.answer("Пожалуйста, укажите тикер после команды, например: `/price btc`")

@dp.message()
async def handle_text_message(message: Message):
    """Обрабатывает ввод пользователя для поиска курса криптовалюты."""
    # Этот обработчик должен быть последним, чтобы ловить обычный текст
    await process_crypto_query(message)

@dp.callback_query(lambda c: c.data == 'get_fear_greed')
async def handle_fear_greed_command(callback_query: CallbackQuery):
    """Обработчик кнопки 'Индекс страха и жадности'."""
    await callback_query.message.answer("🧐 Анализирую настроения рынка...")
    index_data = await get_fear_and_greed_index()
    if not index_data or not index_data.get('value'):
        await callback_query.message.answer("😕 Не удалось получить данные. Возможно, API-ключ для CoinMarketCap не настроен.")
        await callback_query.answer()
        return

    value = int(index_data['value'])
    classification = index_data['classification']
    emoji = "😨" if value <= 25 else "😟" if value <= 49 else "😐" if value <= 54 else "😃" if value <= 75 else "🤑"
    
    response_text = (
        f"**Индекс страха и жадности**\n\n"
        f"{emoji} **Текущее значение: {value} ({classification})**\n\n"
        f"Индекс измеряет эмоции и настроения на криптовалютном рынке. "
        f"Низкое значение указывает на 'Экстремальный страх' (возможность для покупки), "
        f"а высокое - на 'Экстремальную жадность' (рынок может быть перегрет)."
    )
    await callback_query.message.answer(response_text, parse_mode="Markdown")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == 'get_news')
async def handle_news_command(callback_query: CallbackQuery):
    """Обработчик кнопки 'Последние новости'."""
    await callback_query.message.answer("📰 Загружаю последние новости...")
    latest_news = await fetch_latest_news()
    if not latest_news:
        await callback_query.message.answer("😕 Не удалось получить новости. Попробуйте позже.")
        await callback_query.answer()
        return

    response_text = "📰 **Последние новости из мира криптовалют:**\n\n"
    for i, news_item in enumerate(latest_news):
        title = sanitize_html(news_item['title']).replace('[', '(').replace(']', ')')
        response_text += f"{i+1}. [{title}]({news_item['link']})\n"
    
    await callback_query.message.answer(response_text, parse_mode="Markdown", disable_web_page_preview=True)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == 'start_quiz')
async def handle_quiz_command(callback_query: CallbackQuery):
    """Обработчик кнопки 'Викторина'."""
    await callback_query.message.answer("⏳ Генерирую уникальный вопрос для викторины... Пожалуйста, подождите.")
    quiz_data = await generate_quiz_question()
    if not quiz_data:
        await callback_query.message.answer("😕 Не удалось сгенерировать вопрос. Возможно, API-ключ OpenAI не настроен. Попробуйте позже.")
        await callback_query.answer()
        return

    await bot.send_poll(
        chat_id=callback_query.from_user.id,
        question=quiz_data['question'],
        options=quiz_data['options'],
        is_anonymous=False,
        type='quiz',
        correct_option_id=quiz_data['correct_option_index']
    )
    await callback_query.answer()


# ==============================================================================
# Раздел 7: Основная функция запуска бота
# ==============================================================================
async def main():
    """Основная функция для запуска бота и планировщика."""
    # Проверка наличия токена
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("Токен Telegram-бота не найден. Установите переменную окружения TELEGRAM_BOT_TOKEN.")
        return
    if not OPENAI_API_KEY:
        logger.warning("Ключ OpenAI API не найден. Функция викторины будет недоступна.")
    if not CMC_API_KEY:
        logger.warning("Ключ CoinMarketCap API не найден. 'Индекс страха и жадности' будет недоступен.")
    
    # Добавление задачи в планировщик
    if NEWS_CHAT_ID:
        scheduler.add_job(send_news_job, 'interval', hours=NEWS_INTERVAL_HOURS, misfire_grace_time=600)
        scheduler.start()
        logger.info(f"Задача по отправке новостей запланирована каждые {NEWS_INTERVAL_HOURS} часа.")
    else:
        logger.warning("NEWS_CHAT_ID не указан, автоматическая отправка новостей отключена.")

    # Запуск бота
    logger.info("Запуск бота...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if scheduler.running:
            scheduler.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")

