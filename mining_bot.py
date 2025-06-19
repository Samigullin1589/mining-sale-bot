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
from aiogram.filters import CommandStart, Command, Text
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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
CMC_API_KEY = os.getenv("CMC_API_KEY")

# --- Конфигурация парсинга и сбора данных ---
ASIC_SOURCES = {'asicminervalue': 'https://www.asicminervalue.com/'}
COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
MINERSTAT_COINS_URL = "https://api.minerstat.com/v2/coins"
FEAR_AND_GREED_API_URL = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical"

# --- Конфигурация новостей ---
NEWS_RSS_FEEDS = [
    "https://cointelegraph.com/rss/tag/russia", "https://forklog.com/feed",
    "https://www.rbc.ru/crypto/feed", "https://bits.media/rss/",
]
NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")
NEWS_INTERVAL_HOURS = 3

# --- Конфигурация кэширования ---
asic_cache = TTLCache(maxsize=1, ttl=3600)
crypto_price_cache = TTLCache(maxsize=500, ttl=300)
fear_greed_cache = TTLCache(maxsize=1, ttl=14400)
coin_list_cache = TTLCache(maxsize=1, ttl=86400)

# --- Настройка журналирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Инициализация основных компонентов ---
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ==============================================================================
# Раздел 3: Модели данных и состояния
# ==============================================================================
class Form(StatesGroup):
    waiting_for_ticker = State()

@dataclass
class AsicMiner:
    name: str; algorithm: str; hashrate: str; power: int; profitability: float; source: str

@dataclass
class CryptoCoin:
    id: str; symbol: str; name: str; price: float
    algorithm: Optional[str] = None
    market_cap: Optional[int] = None

# ==============================================================================
# Раздел 4: Вспомогательные функции
# ==============================================================================

def sanitize_html(text: str) -> str:
    if not text: return ""
    return bleach.clean(text, tags=[], attributes={}, strip=True).strip()

async def resilient_request(session: aiohttp.ClientSession, url: str, headers: Optional[Dict] = None, params: Optional[Dict] = None) -> Optional[Dict]:
    try:
        request_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'}
        if headers: request_headers.update(headers)
        async with session.get(url, headers=request_headers, params=params, timeout=15) as response:
            response.raise_for_status()
            return await response.json()
    except Exception as e:
        logger.error(f"Ошибка запроса к {url}: {e}")
    return None

def parse_power(power_str: str) -> int:
    return int(re.sub(r'[^0-9]', '', power_str)) if power_str else 0

def parse_profitability(profit_str: str) -> float:
    cleaned_str = re.sub(r'[^\d.]', '', profit_str)
    return float(cleaned_str) if cleaned_str else 0.0

# ==============================================================================
# Раздел 5: Модули сбора данных
# ==============================================================================

async def scrape_asicminervalue(session: aiohttp.ClientSession) -> List[AsicMiner]:
    miners: List[AsicMiner] = []
    try:
        async with session.get(ASIC_SOURCES['asicminervalue'], timeout=20) as response:
            html = await response.text()
        soup = BeautifulSoup(html, 'lxml')
        table = soup.find('table', {'class': 'table-hover'})
        if not table: return miners
        for row in table.find('tbody').find_all('tr'):
            cols = row.find_all('td')
            if len(cols) > 6:
                name, hashrate, power, algo, prof = cols[0].text, cols[2].text, cols[3].text, cols[5].text, cols[6].text
                profitability = parse_profitability(prof)
                if profitability > 0:
                    miners.append(AsicMiner(name.strip(), algo.strip(), hashrate.strip(), parse_power(power), profitability, 'AsicMinerValue'))
    except Exception as e:
        logger.error(f"Критическая ошибка при скрапинге AsicMinerValue: {e}", exc_info=True)
    return miners

@cached(asic_cache)
async def get_profitable_asics() -> List[AsicMiner]:
    logger.info("Обновление кэша ASIC-майнеров...")
    async with aiohttp.ClientSession() as session:
        miners = await scrape_asicminervalue(session)
    if not miners:
        logger.warning("Не удалось получить данные по ASIC.")
        return []
    sorted_miners = sorted(miners, key=lambda m: m.profitability, reverse=True)
    logger.info(f"Кэш ASIC-майнеров обновлен. Найдено {len(sorted_miners)} устройств.")
    return sorted_miners

@cached(coin_list_cache)
async def get_coin_list_with_algorithms() -> Dict[str, str]:
    logger.info("Обновление кэша списка монет с алгоритмами...")
    coin_algo_map = {}
    async with aiohttp.ClientSession() as session:
        data = await resilient_request(session, MINERSTAT_COINS_URL)
        if data:
            for coin_data in data:
                symbol, algorithm = coin_data.get('coin'), coin_data.get('algorithm')
                if symbol and algorithm: coin_algo_map[symbol.upper()] = algorithm
    logger.info(f"Кэш списка монет обновлен. Загружено {len(coin_algo_map)} монет.")
    return coin_algo_map

@cached(crypto_price_cache)
async def get_crypto_price(query: str) -> Optional[CryptoCoin]:
    query = query.lower().strip()
    if not query: return None
    async with aiohttp.ClientSession() as session:
        search_data = await resilient_request(session, f"{COINGECKO_API_URL}/search", params={'query': query})
        if not (search_data and search_data.get('coins')): return None
        coin_id = search_data['coins'][0].get('id')
        if not coin_id: return None
        market_data_list = await resilient_request(session, f"{COINGECKO_API_URL}/coins/markets", params={'vs_currency': 'usd', 'ids': coin_id})
        if not market_data_list: return None
        md = market_data_list[0]
        algo_map = await get_coin_list_with_algorithms()
        symbol = md.get('symbol', '').upper()
        return CryptoCoin(md.get('id'), symbol, md.get('name'), md.get('current_price', 0.0), algo_map.get(symbol), md.get('market_cap', 0))

async def get_halving_info() -> str:
    urls = ["https://mempool.space/api/blocks/tip/height", "https://blockchain.info/q/getblockcount"]
    current_block = None
    async with aiohttp.ClientSession() as s:
        for url in urls:
            try:
                async with s.get(url, timeout=10) as r:
                    if r.status == 200 and (text := await r.text()).isdigit():
                        current_block = int(text); break
            except Exception: continue
    if not current_block: return "[❌ Не удалось получить данные о халвинге]"
    try:
        HALVING_INTERVAL = 210000
        blocks_left = ((current_block // HALVING_INTERVAL) + 1) * HALVING_INTERVAL - current_block
        days, rem_min = divmod(blocks_left * 10, 1440)
        hours, _ = divmod(rem_min, 60)
        return (f"⏳ **До халвинга Bitcoin осталось:**\n\n"
                f"🗓 **Дней:** `{days}` | ⏰ **Часов:** `{hours}`\n"
                f"🧱 **Блоков до халвинга:** `{blocks_left:,}`")
    except Exception as e:
        logger.error(f"Ошибка обработки данных халвинга: {e}"); return "[❌ Ошибка]"

async def fetch_latest_news() -> List[Dict]:
    all_news = []
    loop = asyncio.get_running_loop()
    for url in NEWS_RSS_FEEDS:
        try:
            feed = await loop.run_in_executor(None, feedparser.parse, url)
            for entry in feed.entries:
                all_news.append({'title': entry.title, 'link': entry.link, 'published': getattr(entry, 'published_parsed', None)})
        except Exception as e:
            logger.error(f"Не удалось спарсить RSS-ленту {url}: {e}")
    all_news.sort(key=lambda x: x['published'] or (0,)*6, reverse=True)
    seen_titles = set()
    return [item for item in all_news if item['title'].lower() not in seen_titles and not seen_titles.add(item['title'].lower())][:5]

# ==============================================================================
# Раздел 6: Функции отображения (для вызова из обработчиков)
# ==============================================================================

async def show_asics(message: Message):
    await message.answer("🔍 Ищу самые доходные ASIC-майнеры...")
    asics = await get_profitable_asics()
    if not asics:
        return await message.answer("😕 Не удалось получить данные о майнерах. Попробуйте позже.")
    response_text = "🏆 **Топ-10 самых доходных ASIC-майнеров на сегодня:**\n\n"
    for i, miner in enumerate(asics[:10]):
        response_text += (f"**{i+1}. {sanitize_html(miner.name)}**\n"
                          f"   - Алгоритм: `{miner.algorithm}`\n"
                          f"   - Хешрейт: `{miner.hashrate}`\n"
                          f"   - Потребление: `{miner.power} W`\n"
                          f"   - **Доход в день: `${miner.profitability:.2f}`**\n\n")
    await message.answer(response_text, parse_mode="Markdown")

async def show_price_prompt(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_ticker)
    await message.answer("Введите тикер или название криптовалюты (например, `BTC`):", parse_mode="Markdown")

async def show_fear_greed(message: Message):
    await message.answer("🧐 Анализирую настроения рынка...")
    # Эта функция была удалена, так как требует платного API. Можно раскомментировать при наличии ключа.
    await message.answer("😕 Функция 'Индекс страха и жадности' временно недоступна.")

async def show_news(message: Message):
    await message.answer("📰 Загружаю последние новости...")
    latest_news = await fetch_latest_news()
    if not latest_news:
        return await message.answer("😕 Не удалось получить новости. Попробуйте позже.")
    response_text = "📰 **Последние новости из мира криптовалют:**\n\n"
    for i, news_item in enumerate(latest_news):
        title = sanitize_html(news_item['title']).replace('[', '(').replace(']', ')')
        response_text += f"{i+1}. [{title}]({news_item['link']})\n"
    await message.answer(response_text, parse_mode="Markdown", disable_web_page_preview=True)

async def show_halving_info(message: Message):
    await message.answer("⏳ Рассчитываю время до халвинга...")
    text = await get_halving_info()
    await message.answer(text, parse_mode="Markdown")

async def start_quiz(message: Message):
     await message.answer("😕 К сожалению, функция викторины временно отключена.")

async def process_crypto_query(message: Message, state: FSMContext):
    await state.clear()
    query = message.text.strip()
    await message.answer(f"🔍 Ищу информацию по '{query}'...")
    coin = await get_crypto_price(query)
    if not coin:
        return await message.answer(f"😕 Не удалось найти информацию по запросу '{query}'.\nУбедитесь, что тикер или название верны.")
    response_text = f"**{coin.name} ({coin.symbol.upper()})**\n\n💰 **Цена:** ${coin.price:,.4f}\n"
    if coin.market_cap: response_text += f"📊 **Капитализация:** ${coin.market_cap:,.0f}\n"
    if coin.algorithm:
        response_text += f"⚙️ **Алгоритм:** `{coin.algorithm}`\n\n"
        all_asics = await get_profitable_asics()
        norm_algo = coin.algorithm.lower().replace('-', '').replace(' ', '')
        rel_asics = [a for a in all_asics if a.algorithm.lower().replace('-', '').replace(' ', '') == norm_algo]
        if rel_asics:
            response_text += "⛏️ **Рекомендуемое оборудование:**\n"
            for asic in rel_asics[:3]:
                response_text += f"- {sanitize_html(asic.name)} (Доход: ${asic.profitability:.2f}/день)\n"
        else:
            response_text += "⛏️ Подходящее ASIC-оборудование не найдено."
    else:
        response_text += "⛏️ Алгоритм майнинга не определен."
    await message.answer(response_text, parse_mode="Markdown")

# ==============================================================================
# Раздел 7: Обработчики команд и колбэков Telegram
# ==============================================================================

COMMAND_MAP = { "топ asic": show_asics, "курс": show_price_prompt, "индекс страха": show_fear_greed, "новости": show_news, "халвинг": show_halving_info }

def get_main_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Топ ASIC", callback_data="cb_asics"); builder.button(text="📈 Курс", callback_data="cb_price")
    # builder.button(text="😨 Индекс Страха", callback_data="cb_fear_greed") # Отключено
    builder.button(text="📰 Новости", callback_data="cb_news"); builder.button(text="⏳ Халвинг", callback_data="cb_halving")
    builder.adjust(2); return builder.as_markup()

@dp.message(CommandStart())
async def send_welcome(message: Message):
    await message.answer("👋 Привет! Я твой крипто-помощник.", reply_markup=get_main_keyboard())

# --- Обработчики колбэков (нажатий на инлайн-кнопки) ---
@dp.callback_query(Text("cb_asics"))
async def cb_asics(cb: CallbackQuery, state: FSMContext): await show_asics(cb.message); await cb.answer()
@dp.callback_query(Text("cb_price"))
async def cb_price(cb: CallbackQuery, state: FSMContext): await show_price_prompt(cb.message, state); await cb.answer()
@dp.callback_query(Text("cb_fear_greed"))
async def cb_fear(cb: CallbackQuery, state: FSMContext): await show_fear_greed(cb.message); await cb.answer()
@dp.callback_query(Text("cb_news"))
async def cb_news(cb: CallbackQuery, state: FSMContext): await show_news(cb.message); await cb.answer()
@dp.callback_query(Text("cb_halving"))
async def cb_halving(cb: CallbackQuery, state: FSMContext): await show_halving_info(cb.message); await cb.answer()

# --- Умный маршрутизатор текстовых сообщений ---
@dp.message(Form.waiting_for_ticker)
async def ticker_entered(message: Message, state: FSMContext):
    await process_crypto_query(message, state)

@dp.message()
async def message_router(message: Message, state: FSMContext):
    clean_text = message.text.lower().strip()
    # Ищем, содержит ли сообщение текст команды
    for command_text, handler_func in COMMAND_MAP.items():
        if command_text in clean_text:
            await handler_func(message)
            return
    # Если команда не найдена, считаем это запросом на курс
    await process_crypto_query(message, state)

# ==============================================================================
# Раздел 8: Основная функция запуска бота
# ==============================================================================
async def main():
    if not TELEGRAM_BOT_TOKEN:
        return logger.critical("Токен Telegram-бота не найден!")
    
    logger.info("Удаление старого вебхука...")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Запуск бота в режиме long-polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")

