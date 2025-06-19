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
from typing import List, Optional, Dict

import aiofiles
import aiohttp
import bleach
import feedparser
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, User
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bs4 import BeautifulSoup
from cachetools import TTLCache
from openai import AsyncOpenAI

# ==============================================================================
# Раздел 2: Конфигурация и константы
# ==============================================================================
class Config:
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
    GAME_DATA_FILE = "game_data.json"
    PROFILES_DATA_FILE = "user_profiles.json"
    ASIC_SOURCE_URL = 'https://www.asicminervalue.com/'
    CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"
    COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
    LEVEL_MULTIPLIERS = {1: 1, 2: 1.5, 3: 2.2, 4: 3.5, 5: 5}
    UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])
logger = logging.getLogger(__name__)

bot = Bot(token=Config.TELEGRAM_BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="UTC")
asic_cache = TTLCache(maxsize=1, ttl=3600)

# ==============================================================================
# Раздел 3: Модели данных и состояния
# ==============================================================================
class Form(StatesGroup):
    waiting_for_calculator_cost = State()
    waiting_for_ticker = State()

@dataclass
class AsicMiner:
    name: str; algorithm: str; hashrate: str; power: int; profitability: float

@dataclass
class GameRig:
    name: str; asic_model: str; base_rate: float
    level: int = 1; balance: float = 0.0
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
        logger.error(f"Ошибка чтения {filepath}: {e}"); return {}

async def write_json_file(filepath: str, data: Dict):
    try:
        async with aiofiles.open(filepath, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, indent=4, ensure_ascii=False, default=str))
    except Exception as e:
        logger.error(f"Ошибка записи {filepath}: {e}")

# ==============================================================================
# Раздел 5: Основные модули (API, Калькулятор, Игра, Антиспам)
# ==============================================================================
@asic_cache.cached(key=lambda: 'top_asics')
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
                try:
                    cols = row.find_all('td')
                    if len(cols) > 6:
                        name, hashrate, power, algo, prof = cols[0].text, cols[2].text, cols[3].text, cols[5].text, cols[6].text
                        profitability = float(re.sub(r'[^\d.]', '', prof)) if prof else 0.0
                        if profitability > 0:
                            miners.append(AsicMiner(name.strip(), algo.strip(), hashrate.strip(), int(re.sub(r'\D', '', power) or 0), profitability))
                except (ValueError, IndexError) as e:
                    logger.warning(f"Пропущена строка при парсинге ASIC: {e} | Строка: {[c.text for c in cols]}")
                    continue
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
            return float(data.get('Valute', {}).get('USD', {}).get('Value', 90.0))
    except Exception:
        return 90.0

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

class Game:
    def __init__(self, file_path: str):
        self.file_path = file_path; self.user_rigs: Dict[str, GameRig] = {}
    async def load(self):
        data = await read_json_file(self.file_path)
        for uid, d in data.items():
            d['last_collected'] = datetime.fromisoformat(d['last_collected']) if d.get('last_collected') else None
            self.user_rigs[uid] = GameRig(**d)
        logger.info(f"Игровые данные загружены: {len(self.user_rigs)} игроков.")
    async def save(self): await write_json_file(self.file_path, {u: r.__dict__ for u, r in self.user_rigs.items()})
    async def create_rig(self, user: User) -> str:
        uid = str(user.id)
        if uid in self.user_rigs: return "У вас уже есть ферма! /my_rig"
        asics = await get_profitable_asics()
        if not asics: return "😕 Не удалось создать ферму, нет данных об оборудовании."
        starter_asic = asics[random.randint(5, min(15, len(asics)-1))]
        async with aiohttp.ClientSession() as s, s.get(f"{Config.COINGECKO_API_URL}/simple/price?ids=bitcoin&vs_currencies=usd") as r:
            btc_price = (await r.json()).get("bitcoin", {}).get("usd", 65000)
        base_rate = starter_asic.profitability / btc_price
        self.user_rigs[uid] = GameRig(name=user.full_name, asic_model=starter_asic.name, base_rate=base_rate)
        return f"🎉 Поздравляем! Ваша ферма с **{starter_asic.name}** создана!"
    def get_rig_info(self, uid: str) -> Optional[str]:
        rig = self.user_rigs.get(uid)
        if not rig: return None
        rate = rig.base_rate * Config.LEVEL_MULTIPLIERS.get(rig.level, 1)
        cost = Config.UPGRADE_COSTS.get(rig.level + 1)
        up_txt = f"Улучшение до {rig.level + 1} ур: `{cost}` BTC." if cost else "Максимальный уровень!"
        return (f"🖥️ **Ферма «{bleach.clean(rig.name)}»** | Ур. {rig.level}\n"
                f"Оборудование: *{rig.asic_model}*\n"
                f"Добыча: `{rate:.8f} BTC/день`\n"
                f"Баланс: `{rig.balance:.8f}` BTC\n\n{up_txt}")
    def collect_reward(self, uid: str) -> str:
        rig = self.user_rigs.get(uid)
        if not rig: return "У вас нет фермы. /my_rig"
        if rig.last_collected and (datetime.now() - rig.last_collected) < timedelta(hours=23, minutes=55):
            h, m = divmod((timedelta(hours=24) - (datetime.now() - rig.last_collected)).seconds, 3600)
            return f"Еще рано! Попробуйте через **{h}ч {m//60}м**."
        mined = rig.base_rate * Config.LEVEL_MULTIPLIERS.get(rig.level, 1)
        rig.balance += mined; rig.last_collected = datetime.now()
        return f"✅ Собрано **{mined:.8f}** BTC! Ваш баланс: `{rig.balance:.8f}` BTC."
    def upgrade_rig(self, uid: str) -> str:
        rig = self.user_rigs.get(uid)
        if not rig: return "У вас нет фермы."
        cost = Config.UPGRADE_COSTS.get(rig.level + 1)
        if not cost: return "🎉 У вас максимальный уровень!"
        if rig.balance < cost: return f"❌ Нужно {cost} BTC."
        rig.balance -= cost; rig.level += 1
        return f"🚀 **Улучшение завершено!** Ваша ферма достигла **{rig.level}** уровня!"
    def get_top_miners(self) -> str:
        if not self.user_rigs: return "Пока нет ни одного майнера."
        s_rigs = sorted(self.user_rigs.values(), key=lambda r: r.balance, reverse=True)
        top = [f"**{i+1}.** {bleach.clean(r.name)} - `{r.balance:.6f}` BTC (Ур. {r.level})" for i, r in enumerate(s_rigs[:5])]
        return "🏆 **Топ-5 Виртуальных Майнеров:**\n" + "\n".join(top)

class AntiSpam:
    def __init__(self, file_path: str):
        self.file_path = file_path; self.user_profiles: Dict[str, UserProfile] = {}
        self.spam_keywords = ['p2p', 'арбитраж', 'обмен', 'сигналы']
    async def load(self):
        data = await read_json_file(self.file_path)
        for uid, pd in data.items():
            pd['first_msg'] = datetime.fromisoformat(pd['first_msg']); pd['last_seen'] = datetime.fromisoformat(pd['last_seen'])
            self.user_profiles[uid] = UserProfile(**pd)
        logger.info(f"Профили загружены: {len(self.user_profiles)} записей.")
    async def save(self): await write_json_file(self.file_path, {u: p.__dict__ for u, p in self.user_profiles.items()})
    def process_message(self, message: Message):
        user, uid = message.from_user, str(message.from_user.id)
        if uid not in self.user_profiles:
            self.user_profiles[uid] = UserProfile(user.id, user.full_name, user.username)
        p = self.user_profiles[uid]; p.msg_count += 1; p.last_seen = datetime.utcnow()
        text = (message.text or message.caption or "").lower()
        if any(k in text for k in self.spam_keywords): p.spam_count += 1; logger.warning(f"Спам от {p.name}: {p.spam_count}")

game = Game(Config.GAME_DATA_FILE); antispam = AntiSpam(Config.PROFILES_DATA_FILE)

# ==============================================================================
# Раздел 6: Обработчики команд
# ==============================================================================
@dp.message(CommandStart())
async def send_welcome(message: Message):
    builder = ReplyKeyboardBuilder()
    keys = ["💰 Топ ASIC", "📈 Курс", "⛏️ Калькулятор", "📰 Новости", "⏳ Халвинг", "🕹️ Моя ферма"]
    for k in keys: builder.add(types.KeyboardButton(text=k))
    builder.adjust(2)
    await message.answer("👋 Привет! Я твой крипто-помощник.", reply_markup=builder.as_markup(resize_keyboard=True))

async def show_news(message: Message): await message.answer("📰 Функция новостей временно отключена.")
async def show_halving(message: Message): await message.answer(await get_halving_info(), parse_mode="Markdown")

# --- Обработчики калькулятора ---
@dp.message(F.text.lower().contains("калькулятор"))
async def calculator_start(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_calculator_cost)
    await message.answer("💡 Введите стоимость электроэнергии в **рублях** за кВт/ч (например: `4.5`):", parse_mode="Markdown")

@dp.message(Form.waiting_for_calculator_cost)
async def calculator_process(message: Message, state: FSMContext):
    try:
        cost = float(message.text.replace(',', '.')); await state.clear()
        await message.answer(await Calculator.calculate(cost), parse_mode="Markdown")
    except ValueError: await message.answer("❌ Неверный формат. Введите число (например: `4.5`).")

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
        creation_msg = await game.create_rig(message.from_user)
        await message.answer(creation_msg, parse_mode="Markdown")
        if "Поздравляем" in creation_msg: await my_rig_handler(message)

@dp.callback_query(F.data.startswith("game_"))
async def game_callbacks(cb: CallbackQuery):
    action, uid = cb.data.split("_")[1], str(cb.from_user.id)
    text = ""
    if action == "collect": text = game.collect_reward(uid)
    elif action == "upgrade": text = game.upgrade_rig(uid)
    elif action == "top": text = game.get_top_miners()
    await cb.answer(text, show_alert=action != "top")
    if action == "top": await cb.message.answer(text, parse_mode="Markdown")
    
    info = game.get_rig_info(uid)
    if info:
        try: await cb.message.edit_text(info, parse_mode="Markdown", reply_markup=cb.message.reply_markup)
        except: pass # Сообщение не изменилось

# --- Обработчики курса ---
@dp.message(F.text.lower().contains("курс"))
async def price_start(message: Message, state: FSMContext):
    await state.set_state(Form.waiting_for_ticker)
    await message.answer("Введите тикер криптовалюты:")

@dp.message(Form.waiting_for_ticker)
async def process_ticker(message: Message, state: FSMContext):
    await state.clear()
    coin = await get_crypto_price(message.text)
    if not coin: return await message.answer(f"😕 Не удалось найти информацию по запросу '{message.text}'.")
    await message.answer(f"**{coin.name} ({coin.symbol})**: `${coin.price:,.4f}`", parse_mode="Markdown")

# --- Маршрутизатор остальных текстовых команд ---
@dp.message(F.text)
async def text_command_router(message: Message, state: FSMContext):
    text = message.text.lower()
    if "топ asic" in text: await show_asics(message)
    elif "новости" in text: await show_news(message)
    elif "халвинг" in text: await show_halving(message)
    else: # Если ничего не подошло, считаем спамом
        antispam.process_message(message)

# ==============================================================================
# Раздел 7: Основная функция запуска бота
# ==============================================================================
async def main():
    if not Config.TELEGRAM_BOT_TOKEN:
        return logger.critical("Токен Telegram-бота не найден!")
    
    await game.load(); await antispam.load()
    scheduler.add_job(game.save, 'interval', minutes=5)
    scheduler.add_job(antispam.save, 'interval', minutes=5)
    scheduler.start()
    logger.info("Планировщик сохранения данных запущен.")
    
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Запуск бота...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try: asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): logger.info("Бот остановлен.")

