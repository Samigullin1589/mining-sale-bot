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
from typing import List, Dict, Optional, Any

# Основные библиотеки для асинхронности и Telegram
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ForceReply, ReplyKeyboardRemove
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.client.default import DefaultBotProperties

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
    BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
    NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    WEBHOOK_PATH = "/webhook"
    WEB_SERVER_HOST = "0.0.0.0"
    WEB_SERVER_PORT = int(os.getenv("PORT", 8080))
    
    GAME_DATA_FILE = "game_data.json"
    PROFILES_DATA_FILE = "user_profiles.json"
    ASIC_CACHE_FILE = "asic_data_cache.json"
    DYNAMIC_KEYWORDS_FILE = "dynamic_keywords.json"

    LEVEL_MULTIPLIERS = {1: 1, 2: 1.5, 3: 2.2, 4: 3.5, 5: 5}
    UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1}
    STREAK_BONUS_MULTIPLIER = 0.05
    QUIZ_REWARD = 0.0001
    QUIZ_MIN_CORRECT_FOR_REWARD = 3
    QUIZ_QUESTIONS_COUNT = 5
    SHOP_ITEMS = {
        'boost': {'name': '⚡️ Буст х2 (24ч)', 'cost': 0.0005},
        'overclock': {'name': '⚙️ Оверклокинг-чип (+5% навсегда)', 'cost': 0.002, 'effect': 0.05}
    }
    RANDOM_EVENT_CHANCE = 0.1
    HALVING_INTERVAL = 210000
    CRYPTO_TERMS = ["Блокчейн", "Газ (Gas)", "Халвинг", "ICO", "DeFi", "NFT", "Сатоши", "Кит (Whale)", "HODL", "DEX", "Смарт-контракт"]
    BOT_HINTS = [
        "💡 Узнайте курс любой монеты, просто написав ее тикер!", "⚙️ Посмотрите на самые доходные ASIC",
        "⛏️ Рассчитайте прибыль с помощью 'Калькулятора'", "📰 Хотите свежие крипто-новости?",
        "🤑 Попробуйте наш симулятор майнинга!", "😱 Проверьте Индекс Страха и Жадности",
        "🏆 Сравните себя с лучшими в таблице лидеров", "🎓 Что такое 'HODL'? Узнайте: /word",
        "🧠 Проверьте знания и заработайте в /quiz", "🛍️ Загляните в магазин улучшений"
    ]
    PARTNER_URL = os.getenv("PARTNER_URL", "https://cutt.ly/5rWGcgYL")
    PARTNER_BUTTON_TEXT_OPTIONS = ["🎁 Узнать спеццены", "🔥 Эксклюзивное предложение", "💡 Получить консультацию", "💎 Прайс от экспертов"]
    PARTNER_AD_TEXT_OPTIONS = [
        "Хотите превратить виртуальные BTC в реальные? Для этого нужно настоящее оборудование! Наши партнеры предлагают лучшие условия для старта.",
        "Виртуальный майнинг - это только начало. Готовы к реальной добыче? Ознакомьтесь с предложениями от проверенных поставщиков.",
    ]
    WARN_LIMIT = 3
    MUTE_DURATION_HOURS = 24
    SPAM_KEYWORDS = ['p2p', 'арбитраж', 'обмен', 'сигналы', 'обучение', 'заработок', 'инвестиции', 'вложения', 'схема', 'связка']
    TICKER_ALIASES = {'бтк': 'BTC', 'биткоин': 'BTC', 'биток': 'BTC', 'eth': 'ETH', 'эфир': 'ETH', 'эфириум': 'ETH', 'sol': 'SOL', 'солана': 'SOL'}
    POPULAR_TICKERS = ['BTC', 'ETH', 'SOL', 'TON', 'KAS']
    NEWS_RSS_FEEDS = ["https://forklog.com/feed", "https://bits.media/rss/", "https://www.rbc.ru/crypto/feed", "https://beincrypto.ru/feed/", "https://cointelegraph.com/rss/tag/russia"]
    FALLBACK_ASICS = [
        {'name': 'Antminer S21 200T', 'hashrate': '200 TH/s', 'power_watts': 3550, 'daily_revenue': 11.50, 'algorithm': 'SHA-256'},
    ]

# --- Настройка журналирования ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s', datefmt='%d/%b/%Y %H:%M:%S')
logger = logging.getLogger(__name__)

# --- Проверка конфигурации ---
if not Config.BOT_TOKEN:
    logger.critical("Критическая ошибка: TG_BOT_TOKEN не установлен.")
    raise ValueError("Критическая ошибка: TG_BOT_TOKEN не установлен")

# --- Инициализация ---
bot = Bot(token=Config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")
openai_client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY) if Config.OPENAI_API_KEY else None
user_quiz_states = {}
temp_user_choices = {}

# ========================================================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ========================================================================================
# ... (вспомогательные функции, как sanitize_html, resilient_request, get_main_keyboard)
def sanitize_html(text: str) -> str:
    if not text: return ""
    return bleach.clean(text, tags=[], attributes={}, strip=True).strip()

async def resilient_request(session: aiohttp.ClientSession, method: str, url: str, **kwargs) -> Optional[Dict[str, Any]]:
    try:
        async with session.request(method, url, timeout=15, **kwargs) as response:
            if response.status == 429:
                logger.warning(f"Слишком много запросов к {url}. Статус 429.")
                return None
            response.raise_for_status()
            if "application/json" in response.content_type:
                return await response.json()
            else:
                return {"text_content": await response.text()}
    except Exception as e:
        logger.error(f"Ошибка запроса к {url}: {e}")
        return None

def get_main_keyboard():
    buttons = [
        [KeyboardButton(text="💹 Курс"), KeyboardButton(text="⚙️ Топ ASIC")],
        [KeyboardButton(text="⛏️ Калькулятор"), KeyboardButton(text="📰 Новости")],
        [KeyboardButton(text="😱 Индекс Страха"), KeyboardButton(text="⏳ Халвинг")],
        [KeyboardButton(text="📡 Статус BTC"), KeyboardButton(text="🧠 Викторина")],
        [KeyboardButton(text="🕹️ Виртуальный Майнинг")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=False)

async def send_message_with_partner_button(chat_id: int, text: str, reply_markup: Optional[types.InlineKeyboardMarkup] = None):
    try:
        builder = InlineKeyboardBuilder()
        if reply_markup:
            # This is a simplification. A full conversion from old markup is complex.
            # Assuming the old markup had button rows.
            for row in reply_markup.keyboard:
                row_buttons = []
                for button in row:
                    row_buttons.append(InlineKeyboardButton(text=button.text, url=button.url, callback_data=button.callback_data))
                builder.row(*row_buttons)

        builder.row(InlineKeyboardButton(text=random.choice(Config.PARTNER_BUTTON_TEXT_OPTIONS), url=Config.PARTNER_URL))
        
        full_text = f"{text}\n\n---\n<i>{random.choice(Config.BOT_HINTS)}</i>"
        
        await bot.send_message(chat_id, full_text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "can't parse entities" in str(e):
            cleaned_text = sanitize_html(text)
            full_text = f"{cleaned_text}\n\n---\n<i>{random.choice(Config.BOT_HINTS)}</i>"
            await bot.send_message(chat_id, full_text, reply_markup=builder.as_markup(), disable_web_page_preview=True)
        else:
            logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")

async def send_photo_with_partner_button(chat_id: int, photo: io.BytesIO, caption: str):
    try:
        photo.seek(0)
        builder = InlineKeyboardBuilder()
        builder.button(text=random.choice(Config.PARTNER_BUTTON_TEXT_OPTIONS), url=Config.PARTNER_URL)
        markup = builder.as_markup()
        
        hint = f"\n\n---\n<i>{random.choice(Config.BOT_HINTS)}</i>"
        if len(caption) + len(hint) > 1024:
            caption = caption[:1024 - len(hint) - 3] + "..."
        final_caption = f"{caption}{hint}"
        
        await bot.send_photo(chat_id, types.BufferedInputFile(photo.read(), filename="image.png"), caption=final_caption, reply_markup=markup)
    except Exception as e:
        logger.error(f"Не удалось отправить фото: {e}. Отправляю текстом.")
        await send_message_with_partner_button(chat_id, caption)

# ========================================================================================
# 4. КЛАССЫ ЛОГИКИ (ApiHandler, GameLogic, SpamAnalyzer)
# ========================================================================================

class ApiHandler:
    def __init__(self):
        self.coingecko_cache = {} # Простой кэш для ID монет
        self.asic_cache = {"data": [], "timestamp": None}
        self.currency_cache = {"rate": None, "timestamp": None}

    def _load_json_file(self, file_path, default_value=None):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return default_value if default_value is not None else {}

    def _save_json_file(self, file_path, data):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Ошибка сохранения файла {file_path}: {e}")
    
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

    async def get_crypto_price(self, ticker="BTC"):
        ticker_input = ticker.strip().lower()
        ticker_upper = Config.TICKER_ALIASES.get(ticker_input, ticker_input.upper())
        coin_id = self.coingecko_cache.get(ticker_upper.lower())
        
        async with aiohttp.ClientSession() as session:
            if not coin_id:
                search_data = await resilient_request(session, 'get', f"https://api.coingecko.com/api/v3/search?query={ticker_input}")
                if search_data and search_data.get('coins'):
                    top_coin = search_data['coins'][0]
                    coin_id = top_coin.get('id')
                    ticker_upper = top_coin.get('symbol', ticker_upper).upper()
                    self.coingecko_cache[ticker_upper.lower()] = coin_id
                else:
                    return None
            
            price_response = await resilient_request(session, 'get', f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd")
            if not price_response or not price_response.get(coin_id, {}).get('usd'):
                return None
            
            price_data = {'price': float(price_response[coin_id]['usd']), 'source': 'CoinGecko', 'ticker': ticker_upper}
            return price_data

    # Остальные методы ApiHandler, такие как get_top_asics, get_fear_and_greed_index и т.д.
    # Должны быть здесь в полной версии. Для примера - заглушки.
    async def get_top_asics(self, force_update: bool = False):
        return Config.FALLBACK_ASICS

    async def get_fear_and_greed_index(self):
        async with aiohttp.ClientSession() as session:
            data = await resilient_request(session, 'get', "https://api.alternative.me/fng/?limit=1")
            if not data or 'data' not in data or not data['data']:
                return None, "[❌ Ошибка при получении индекса]"
        
        value_data = data['data'][0]
        value, classification = int(value_data['value']), value_data['value_classification']
        
        # Генерация изображения...
        plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(8, 4.5), subplot_kw={'projection': 'polar'})
        ax.set_yticklabels([]); ax.set_xticklabels([]); ax.grid(False); ax.spines['polar'].set_visible(False); ax.set_ylim(0, 1)
        colors = ['#d94b4b', '#e88452', '#ece36a', '#b7d968', '#73c269']
        for i in range(100): ax.barh(1, 0.0314, left=3.14 - (i * 0.0314), height=0.3, color=colors[min(len(colors) - 1, int(i / 25))])
        angle = 3.14 - (value * 0.0314)
        ax.annotate('', xy=(angle, 1), xytext=(0, 0), arrowprops=dict(facecolor='white', shrink=0.05, width=4, headwidth=10))
        fig.text(0.5, 0.5, f"{value}", ha='center', va='center', fontsize=48, color='white', weight='bold')
        fig.text(0.5, 0.35, classification, ha='center', va='center', fontsize=20, color='white')
        buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=150, transparent=True); plt.close(fig)
        
        explanation = await self.ask_gpt(f"Кратко объясни для майнера, как 'Индекс страха и жадности' со значением '{value} ({classification})' влияет на рынок. Не более 2-3 предложений.")
        return buf, f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>\n\n{explanation}"

    async def get_halving_info(self):
         async with aiohttp.ClientSession() as session:
            response = await resilient_request(session, 'get', "https://mempool.space/api/blocks/tip/height")
            if not response or not response.get('text_content', '').isdigit():
                return "[❌ Не удалось получить данные о халвинге]"
            current_block = int(response['text_content'])
            blocks_left = ((current_block // Config.HALVING_INTERVAL) + 1) * Config.HALVING_INTERVAL - current_block
            days, rem_min = divmod(blocks_left * 10, 1440)
            hours, _ = divmod(rem_min, 60)
            return f"⏳ <b>До халвинга Bitcoin осталось:</b>\n\n🗓 <b>Дней:</b> <code>{days}</code> | ⏰ <b>Часов:</b> <code>{hours}</code>\n🧱 <b>Блоков до халвинга:</b> <code>{blocks_left:,}</code>"
    
    async def get_crypto_news(self):
        all_news = []
        async with aiohttp.ClientSession(headers={'User-Agent': 'Mozilla/5.0'}) as session:
            for url in Config.NEWS_RSS_FEEDS:
                try:
                    data = await resilient_request(session, 'get', url)
                    if data and data.get("text_content"):
                        feed = feedparser.parse(data["text_content"])
                        for entry in feed.entries:
                             all_news.append({'title': entry.title, 'link': entry.link, 'published': date_parser.parse(entry.published).replace(tzinfo=None)})
                except Exception as e:
                    logger.warning(f"Не удалось получить новости из {url}: {e}")
        
        if not all_news:
            return None
        all_news.sort(key=lambda x: x['published'], reverse=True)
        seen_titles = set()
        unique_news = [item for item in all_news if item['title'].strip().lower() not in seen_titles and not seen_titles.add(item['title'].strip().lower())]
        
        return unique_news[:5]

class GameLogic:
    def __init__(self, data_file):
        self.data_file = data_file
        self.user_rigs = api._load_json_file(self.data_file, default_value={})

    # ... (все методы GameLogic из вашего оригинального кода)
    # Важно: методы, вызывающие await, должны быть async def
    async def create_rig(self, user_id, user_name, asic_data):
        if str(user_id) in self.user_rigs: return "У вас уже есть ферма!"
        price_data = await api.get_crypto_price("BTC")
        btc_price = price_data['price'] if price_data else 65000
        self.user_rigs[str(user_id)] = {'last_collected': None, 'balance': 0.0, 'level': 1, 'streak': 0, 'name': user_name, 'boost_active_until': None, 'asic_model': asic_data['name'], 'base_rate': asic_data['daily_revenue'] / btc_price, 'overclock_bonus': 0.0, 'penalty_multiplier': 1.0}
        return f"🎉 Поздравляем! Ваша ферма с <b>{asic_data['name']}</b> успешно создана!"
    
    # ... и так далее для всех методов

class SpamAnalyzer:
    def __init__(self, profiles_file, keywords_file):
        self.user_profiles = api._load_json_file(profiles_file, default_value={})
        self.dynamic_keywords = api._load_json_file(keywords_file, default_value=[])

    # ... (все методы SpamAnalyzer из вашего оригинального кода)
    # Важно: методы, вызывающие await (bot.send_message и др.), должны быть async def
    async def process_message(self, msg: types.Message):
        user = msg.from_user
        text = msg.text or msg.caption or ""
        profile = self.user_profiles.setdefault(str(user.id), {'first_msg': datetime.utcnow().isoformat(), 'msg_count': 0, 'spam_count': 0})
        profile.update({'user_id': user.id, 'name': user.full_name, 'username': user.username, 'msg_count': profile.get('msg_count', 0) + 1, 'last_seen': datetime.utcnow().isoformat()})
        if any(keyword in text.lower() for keyword in Config.SPAM_KEYWORDS + self.dynamic_keywords):
            await self.handle_spam_detection(msg)

    async def handle_spam_detection(self, msg: types.Message, initiated_by_admin=False):
        # ... логика с bot.delete_message, bot.send_message и т.д.
        pass

# ========================================================================================
# 6. ИНИЦИАЛИЗАЦИЯ ГЛОБАЛЬНЫХ ОБЪЕКТОВ
# ========================================================================================
api = ApiHandler()
game = GameLogic(Config.GAME_DATA_FILE) 
spam_analyzer = SpamAnalyzer(Config.PROFILES_DATA_FILE, Config.DYNAMIC_KEYWORDS_FILE) 

# ========================================================================================
# 7. ОБРАБОТЧИКИ КОМАНД И КОЛБЭКОВ
# ========================================================================================
@dp.message(CommandStart())
async def handle_start(message: Message):
    await message.answer("👋 Привет! Я ваш крипто-помощник.", reply_markup=get_main_keyboard())

# --- Обработчики кнопок ---
@dp.message(F.text == "💹 Курс")
async def handle_price_button(message: Message):
    builder = InlineKeyboardBuilder()
    for ticker in Config.POPULAR_TICKERS:
        builder.button(text=ticker, callback_data=f"price_{ticker}")
    builder.button(text="➡️ Другая монета", callback_data="price_other")
    builder.adjust(3, 2)
    await message.answer("Курс какой криптовалюты вас интересует?", reply_markup=builder.as_markup())
    
# ... (остальные обработчики для кнопок)

@dp.message(F.text == "😱 Индекс Страха")
async def handle_fear_greed_button(message: Message):
    await bot.send_chat_action(message.chat.id, 'typing')
    image, text = await api.get_fear_and_greed_index()
    if image:
        await send_photo_with_partner_button(message.chat.id, image, text)
    else:
        await send_message_with_partner_button(message.chat.id, text)

# --- Обработчики колбэков ---
@dp.callback_query(F.data.startswith("price_"))
async def handle_price_callback(callback: CallbackQuery):
    # ...
    pass

# --- Обработчик любого текста ---
@dp.message(F.text)
async def handle_any_text(message: Message):
    # Пропускаем, если текст совпадает с кнопкой
    button_texts = ["💹 Курс", "⚙️ Топ ASIC", "⛏️ Калькулятор", "📰 Новости", "😱 Индекс Страха", "⏳ Халвинг", "📡 Статус BTC", "🧠 Викторина", "🕹️ Виртуальный Майнинг"]
    if message.text in button_texts:
        return
        
    await spam_analyzer.process_message(message)
    await bot.send_chat_action(message.chat.id, 'typing')
    
    price_data = await api.get_crypto_price(message.text)
    if price_data:
        text = f"💹 Курс {price_data['ticker'].upper()}/USD: <b>${price_data['price']:,.4f}</b>\n<i>(Данные от {price_data['source']})</i>"
        await send_message_with_partner_button(message.chat.id, text)
    else:
        response = await api.ask_gpt(message.text)
        await send_message_with_partner_button(message.chat.id, response)

# ========================================================================================
# 8. ЗАПУСК БОТА И ВЕБ-СЕРВЕРА
# ========================================================================================
async def on_startup(bot: Bot):
    if Config.WEBHOOK_URL:
        webhook_url = f"{Config.WEBHOOK_URL.rstrip('/')}{Config.WEBHOOK_PATH}"
        await bot.set_webhook(webhook_url, drop_pending_updates=True)
        logger.info(f"Вебхук установлен на URL: {webhook_url}")
    scheduler.start()
    logger.info("Планировщик запущен.")

async def on_shutdown(bot: Bot):
    logger.warning("Остановка бота...")
    scheduler.shutdown()
    await bot.delete_webhook()
    logger.info("Вебхук удален.")

async def auto_send_news_job():
    if not Config.NEWS_CHAT_ID: return
    logger.info("ПЛАНИРОВЩИК: Отправка новостей...")
    try:
        news = await api.get_crypto_news()
        if news:
            summary = await api.ask_gpt(f"Сделай очень краткое саммари новости в одно предложение: {news[0]['title']}")
            text = f"📰 <a href=\"{news[0]['link']}\">{summary}</a>"
            await send_message_with_partner_button(int(Config.NEWS_CHAT_ID), text)
    except Exception as e:
        logger.error(f"Ошибка в задаче auto_send_news_job: {e}", exc_info=True)

def main():
    scheduler.add_job(auto_send_news_job, 'interval', hours=3, id='auto_news_sender')
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=Config.WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    
    logger.info(f"Запуск веб-сервера на {Config.WEB_SERVER_HOST}:{Config.WEB_SERVER_PORT}")
    web.run_app(app, host=Config.WEB_SERVER_HOST, port=Config.WEB_SERVER_PORT)

if __name__ == '__main__':
    main()
