# -*- coding: utf-8 -*-
# ==============================================================================
# Раздел 1: Импорты и начальная настройка
# ==============================================================================
import asyncio
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

import aiofiles
import aiohttp
import bleach
import feedparser
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command, Text
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, User
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from cachetools import TTLCache, cached
from openai import AsyncOpenAI

# ==============================================================================
# Раздел 2: Конфигурация и константы
# ==============================================================================
class Config:
    # --- API и токены ---
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    CMC_API_KEY = os.getenv("CMC_API_KEY")
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

    # --- Файлы данных ---
    GAME_DATA_FILE = "game_data.json"
    PROFILES_DATA_FILE = "user_profiles.json"

    # --- API URL ---
    ASIC_SOURCE_URL = 'https://www.asicminervalue.com/'
    COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
    MINERSTAT_COINS_URL = "https://api.minerstat.com/v2/coins"
    FEAR_AND_GREED_API_URL = "https://pro-api.coinmarketcap.com/v3/fear-and-greed/historical"
    CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"

    # --- Новости ---
    NEWS_RSS_FEEDS = ["https://cointelegraph.com/rss/tag/russia", "https://forklog.com/feed", "https://www.rbc.ru/crypto/feed", "https://bits.media/rss/"]
    NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")
    NEWS_INTERVAL_HOURS = 3

    # --- Игра ---
    LEVEL_MULTIPLIERS = {1: 1, 2: 1.5, 3: 2.2, 4: 3.5, 5: 5}
    UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1}

# --- Настройка журналирования ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

# --- Инициализация основных компонентов ---
bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")
openai_client = AsyncOpenAI(api_key=Config.OPENAI_API_KEY) if Config.OPENAI_API_KEY else None

# ==============================================================================
# Раздел 3: Модели данных и состояния
# ==============================================================================
class Form(StatesGroup):
    waiting_for_ticker = State()
    waiting_for_calculator_cost = State()

@dataclass
class AsicMiner:
    name: str; algorithm: str; hashrate: str; power: int; profitability: float; source: str

@dataclass
class CryptoCoin:
    id: str; symbol: str; name: str; price: float
    algorithm: Optional[str] = None; market_cap: Optional[int] = None

@dataclass
class GameRig:
    name: str
    asic_model: str
    base_rate: float
    level: int = 1
    balance: float = 0.0
    last_collected: Optional[datetime] = None

@dataclass
class UserProfile:
    user_id: int; name: str; username: Optional[str]
    msg_count: int = 0; spam_count: int = 0
    first_msg: datetime = field(default_factory=datetime.utcnow)
    last_seen: datetime = field(default_factory=datetime.utcnow)

# ==============================================================================
# Раздел 4: Вспомогательные функции и файловый I/O
# ==============================================================================
async def read_json_file(filepath: str) -> Dict:
    if not os.path.exists(filepath): return {}
    try:
        async with aiofiles.open(filepath, 'r', encoding='utf-8') as f:
            return json.loads(await f.read())
    except Exception as e:
        logger.error(f"Ошибка чтения JSON файла {filepath}: {e}")
        return {}

async def write_json_file(filepath: str, data: Dict):
    try:
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=4, ensure_ascii=False, default=str))
    except Exception as e:
        logger.error(f"Ошибка записи JSON файла {filepath}: {e}")

# ==============================================================================
# Раздел 5: Основные модули (API, Калькулятор, Игра, Антиспам)
# ==============================================================================

# --- API Handler ---
@cached(TTLCache(maxsize=1, ttl=3600))
async def get_profitable_asics() -> List[AsicMiner]:
    logger.info("Обновление кэша ASIC-майнеров...")
    miners: List[AsicMiner] = []
    try:
        async with aiohttp.ClientSession() as session, session.get(Config.ASIC_SOURCE_URL, timeout=20) as response:
            html = await response.text()
        soup = BeautifulSoup(html, 'lxml')
        table = soup.find('table', {'class': 'table-hover'})
        if table:
            for row in table.find('tbody').find_all('tr'):
                cols = row.find_all('td')
                if len(cols) > 6:
                    name, hashrate, power, algo, prof = cols[0].text, cols[2].text, cols[3].text, cols[5].text, cols[6].text
                    profitability = float(re.sub(r'[^\d.]', '', prof)) if prof else 0.0
                    if profitability > 0:
                        miners.append(AsicMiner(name.strip(), algo.strip(), hashrate.strip(), int(re.sub(r'\D', '', power)), profitability, 'AsicMinerValue'))
    except Exception as e:
        logger.error(f"Ошибка скрапинга AsicMinerValue: {e}", exc_info=True)
    
    sorted_miners = sorted(miners, key=lambda m: m.profitability, reverse=True)
    logger.info(f"Кэш ASIC обновлен. Найдено {len(sorted_miners)} устройств.")
    return sorted_miners

@cached(TTLCache(maxsize=1, ttl=300))
async def get_usd_rub_rate() -> float:
    try:
        async with aiohttp.ClientSession() as session, session.get(Config.CBR_API_URL) as response:
            data = await response.json()
            rate = data.get('Valute', {}).get('USD', {}).get('Value', 90.0)
            return float(rate)
    except Exception:
        return 90.0

# --- Calculator Logic ---
class Calculator:
    @staticmethod
    async def calculate(electricity_cost_rub: float) -> str:
        asics = await get_profitable_asics()
        if not asics: return "😕 Не удалось получить данные о майнерах для расчета."
        
        rate = await get_usd_rub_rate()
        cost_usd = electricity_cost_rub / rate
        
        result = [f"💰 **Расчет профита (розетка {electricity_cost_rub:.2f} ₽/кВтч)**\n"]
        for asic in asics[:12]:
            daily_cost = (asic.power / 1000) * 24 * cost_usd
            profit = asic.profitability - daily_cost
            result.append(f"**{bleach.clean(asic.name)}**\n   Профит: **${profit:.2f}/день**")
        return "\n\n".join(result)

# --- Game Logic ---
class Game:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.user_rigs: Dict[str, GameRig] = {}

    async def load(self):
        data = await read_json_file(self.file_path)
        for uid, rig_data in data.items():
            last_collected = datetime.fromisoformat(rig_data['last_collected']) if rig_data.get('last_collected') else None
            self.user_rigs[uid] = GameRig(**{**rig_data, 'last_collected': last_collected})
        logger.info(f"Игровые данные загружены. {len(self.user_rigs)} игроков.")

    async def save(self):
        await write_json_file(self.file_path, {uid: rig.__dict__ for uid, rig in self.user_rigs.items()})

    async def create_rig(self, user: User) -> str:
        uid = str(user.id)
        if uid in self.user_rigs: return "У вас уже есть ферма! Посмотрите информацию: /my_rig"
        
        top_asics = await get_profitable_asics()
        if not top_asics: return "😕 Не удалось создать ферму, нет данных об оборудовании."
        
        starter_asic = top_asics[random.randint(5, 15)] # Берем не самый топовый для старта
        btc_price_data = await get_crypto_price("BTC")
        btc_price = btc_price_data.price if btc_price_data else 65000
        
        base_rate = starter_asic.profitability / btc_price
        
        self.user_rigs[uid] = GameRig(name=user.full_name, asic_model=starter_asic.name, base_rate=base_rate)
        return f"🎉 Поздравляем! Ваша ферма с **{starter_asic.name}** создана! Начните собирать награду."

    def get_rig_info(self, uid: str) -> Optional[str]:
        rig = self.user_rigs.get(uid)
        if not rig: return None
        
        current_rate = rig.base_rate * Config.LEVEL_MULTIPLIERS.get(rig.level, 1)
        next_level = rig.level + 1
        upgrade_cost = Config.UPGRADE_COSTS.get(next_level)
        upgrade_text = f"Стоимость улучшения до {next_level} ур: `{upgrade_cost}` BTC." if upgrade_cost else "Вы достигли максимального уровня!"
        
        return (f"🖥️ **Ферма «{bleach.clean(rig.name)}»**\n"
                f"Оборудование: *{rig.asic_model}*\n\n"
                f"**Уровень:** {rig.level}\n"
                f"**Добыча:** `{current_rate:.8f} BTC/день`\n"
                f"**Баланс:** `{rig.balance:.8f}` BTC\n\n"
                f"{upgrade_text}")

    def collect_reward(self, uid: str) -> str:
        rig = self.user_rigs.get(uid)
        if not rig: return "У вас нет фермы. Создайте ее командой /my_rig"
        
        now = datetime.now()
        if rig.last_collected and (now - rig.last_collected) < timedelta(hours=23, minutes=55):
            time_left = timedelta(hours=24) - (now - rig.last_collected)
            h, m = divmod(time_left.seconds, 3600); m //= 60
            return f"Вы уже собирали награду. Попробуйте снова через **{h}ч {m}м**."
        
        base_mined = rig.base_rate * Config.LEVEL_MULTIPLIERS.get(rig.level, 1)
        rig.balance += base_mined
        rig.last_collected = now
        
        return (f"✅ Собрано **{base_mined:.8f}** BTC!\n"
                f"💰 Ваш новый баланс: `{rig.balance:.8f}` BTC.")

    def upgrade_rig(self, uid: str) -> str:
        rig = self.user_rigs.get(uid)
        if not rig: return "У вас нет фермы."
        next_level = rig.level + 1
        cost = Config.UPGRADE_COSTS.get(next_level)
        if not cost: return "🎉 Поздравляем, у вас максимальный уровень фермы!"
        if rig.balance < cost: return f"❌ **Недостаточно средств.** Нужно {cost} BTC."
        
        rig.balance -= cost
        rig.level = next_level
        return f"🚀 **Улучшение завершено!** Ваша ферма достигла **{next_level}** уровня!"

    def get_top_miners(self) -> str:
        if not self.user_rigs: return "Пока нет ни одного майнера для составления топа."
        sorted_rigs = sorted(self.user_rigs.values(), key=lambda r: r.balance, reverse=True)
        top_list = [f"**{i+1}.** {bleach.clean(rig.name)} - `{rig.balance:.6f}` BTC (Ур. {rig.level})" for i, rig in enumerate(sorted_rigs[:5])]
        return "🏆 **Топ-5 Виртуальных Майнеров:**\n" + "\n".join(top_list)

# --- AntiSpam Logic ---
class AntiSpam:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.user_profiles: Dict[str, UserProfile] = {}
        self.spam_keywords = ['p2p', 'арбитраж', 'обмен', 'сигналы', 'обучение', 'заработок']

    async def load(self):
        data = await read_json_file(self.file_path)
        for uid, profile_data in data.items():
            self.user_profiles[uid] = UserProfile(**profile_data)
        logger.info(f"Профили пользователей загружены. {len(self.user_profiles)} записей.")

    async def save(self):
        await write_json_file(self.file_path, {uid: profile.__dict__ for uid, profile in self.user_profiles.items()})

    def process_message(self, message: Message):
        user = message.from_user
        uid = str(user.id)
        if uid not in self.user_profiles:
            self.user_profiles[uid] = UserProfile(user_id=user.id, name=user.full_name, username=user.username)
        
        profile = self.user_profiles[uid]
        profile.msg_count += 1
        profile.last_seen = datetime.utcnow()

        text = (message.text or message.caption or "").lower()
        if any(keyword in text for keyword in self.spam_keywords):
            profile.spam_count += 1
            # Здесь можно добавить логику для удаления сообщения и выдачи предупреждения
            # asyncio.create_task(bot.delete_message(...))
            # asyncio.create_task(bot.send_message(...))
            logger.warning(f"Обнаружен спам от {user.full_name} ({uid}). Счетчик: {profile.spam_count}")

# Инициализация модулей
game = Game(Config.GAME_DATA_FILE)
antispam = AntiSpam(Config.PROFILES_DATA_FILE)

# ==============================================================================
# Раздел 6: Функции отображения и обработчики
# ==============================================================================

# --- Функции отображения (вызываются из обработчиков) ---
async def show_main_menu(message: Message, text: str = "👋 Привет! Я твой крипто-помощник."):
    builder = ReplyKeyboardBuilder()
    builder.row(types.KeyboardButton(text="💰 Топ ASIC"), types.KeyboardButton(text="📈 Курс"))
    builder.row(types.KeyboardButton(text="⛏️ Калькулятор"), types.KeyboardButton(text="📰 Новости"))
    builder.row(types.KeyboardButton(text="⏳ Халвинг"), types.KeyboardButton(text="🕹️ Моя ферма"))
    await message.answer(text, reply_markup=builder.as_markup(resize_keyboard=True))

async def show_asics(message: Message):
    await message.answer("🔍 Ищу самые доходные ASIC-майнеры...")
    asics = await get_profitable_asics()
    if not asics: return await message.answer("😕 Не удалось получить данные о майнерах.")
    response_text = "🏆 **Топ-10 самых доходных ASIC-майнеров на сегодня:**\n\n"
    for i, miner in enumerate(asics[:10]):
        response_text += (f"**{i+1}. {bleach.clean(miner.name)}**\n"
                          f"   - Алгоритм: `{miner.algorithm}`\n"
                          f"   - Доход в день: `${miner.profitability:.2f}`\n")
    await message.answer(response_text, parse_mode="Markdown")

async def show_news(message: Message):
    # Логика получения и отображения новостей (упрощена)
    await message.answer("📰 Функция новостей в разработке.")

async def show_halving_info(message: Message):
    await message.answer("⏳ Рассчитываю время до халвинга...")
    text = await get_halving_info()
    await message.answer(text, parse_mode="Markdown")

async def process_crypto_query(message: Message, state: FSMContext):
    await state.clear()
    query = message.text.strip()
    await message.answer(f"🔍 Ищу информацию по '{query}'...")
    coin = await get_crypto_price(query)
    if not coin: return await message.answer(f"😕 Не удалось найти информацию по запросу '{query}'.")
    response_text = f"**{coin.name} ({coin.symbol.upper()})**\n\n💰 **Цена:** ${coin.price:,.4f}\n"
    if coin.algorithm: response_text += f"⚙️ **Алгоритм:** `{coin.algorithm}`\n"
    await message.answer(response_text, parse_mode="Markdown")

# --- Основные обработчики команд ---
@dp.message(CommandStart())
async def send_welcome(message: Message):
    await show_main_menu(message)

@dp.message(F.text.lower().contains("топ asic"))
async def text_asics_handler(message: Message): await show_asics(message)
@dp.message(F.text.lower().contains("новости"))
async def text_news_handler(message: Message): await show_news(message)
@dp.message(F.text.lower().contains("халвинг"))
async def text_halving_handler(message: Message): await show_halving_info(message)

# --- Обработчики калькулятора (с состояниями) ---
@dp.message(F.text.lower().contains("калькулятор"))
async def calculator_start(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_calculator_cost)
    await message.answer("💡 Введите стоимость электроэнергии в **рублях** за кВт/ч (например: `4.5`):", parse_mode="Markdown")

@dp.message(Form.waiting_for_calculator_cost)
async def calculator_process(message: Message, state: FSMContext):
    try:
        cost = float(message.text.replace(',', '.'))
        await state.clear()
        calculation_result = await Calculator.calculate(cost)
        await message.answer(calculation_result, parse_mode="Markdown")
    except ValueError:
        await message.answer("❌ Неверный формат. Введите число (например: `4.5`).")

# --- Обработчики игры ---
@dp.message(F.text.lower().contains("моя ферма"))
async def my_rig_handler(message: Message):
    uid = str(message.from_user.id)
    info = game.get_rig_info(uid)
    if info:
        builder = InlineKeyboardBuilder()
        builder.button(text="💰 Собрать", callback_data="game_collect")
        builder.button(text="🚀 Улучшить", callback_data="game_upgrade")
        builder.button(text="🏆 Топ-5", callback_data="game_top")
        builder.adjust(2)
        await message.answer(info, parse_mode="Markdown", reply_markup=builder.as_markup())
    else:
        await game.create_rig(message.from_user)
        # Повторно вызываем, чтобы показать созданную ферму
        await my_rig_handler(message)

@dp.callback_query(Text(startswith="game_"))
async def game_callbacks(cb: CallbackQuery):
    action = cb.data.split("_")[1]
    uid = str(cb.from_user.id)
    response_text = ""
    if action == "collect": response_text = game.collect_reward(uid)
    elif action == "upgrade": response_text = game.upgrade_rig(uid)
    elif action == "top": response_text = game.get_top_miners()
    
    await cb.answer(response_text, show_alert=True)
    
    # Обновляем сообщение с информацией о ферме
    info = game.get_rig_info(uid)
    if info: await cb.message.edit_text(info, parse_mode="Markdown", reply_markup=cb.message.reply_markup)


# --- Обработчики курса (с состояниями) ---
@dp.message(F.text.lower().contains("курс"))
async def price_start(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_ticker)
    await message.answer("Введите тикер или название криптовалюты:")

@dp.message(Form.waiting_for_ticker)
async def process_ticker(message: Message, state: FSMContext):
    await process_crypto_query(message, state)

# --- Общий обработчик текста для антиспама (должен быть последним) ---
@dp.message()
async def any_text_handler(message: Message):
    antispam.process_message(message)
    # Можно добавить ответ-заглушку, если бот не понял команду
    # await message.answer("Не совсем понял вас. Воспользуйтесь кнопками меню.")

# ==============================================================================
# Раздел 8: Основная функция запуска бота
# ==============================================================================
async def main():
    if not Config.TELEGRAM_BOT_TOKEN:
        return logger.critical("Токен Telegram-бота не найден!")
    
    # Загрузка данных при старте
    await game.load()
    await antispam.load()

    # Настройка и запуск планировщика
    scheduler.add_job(game.save, 'interval', minutes=5, id='save_game')
    scheduler.add_job(antispam.save, 'interval', minutes=5, id='save_profiles')
    scheduler.start()
    logger.info("Планировщик для сохранения данных запущен.")

    logger.info("Удаление старого вебхука...")
    await bot.delete_webhook(drop_pending_updates=True)

    logger.info("Запуск бота в режиме long-polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        if scheduler.running: scheduler.shutdown()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")

