# -*- coding: utf-8 -*-

# ========================================================================================
# 1. ИМПОРТЫ И КОНФИГУРАЦИЯ
# ========================================================================================
import os
import telebot
import requests
import time
import threading
import schedule
import json
import atexit
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
from telebot import types
from openai import OpenAI
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import io
import re
import random
import logging

# --- Настройка логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Ключи и Настройки (Загрузка из переменных окружения) ---
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
NEWSAPI_KEY = os.getenv("CRYPTO_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "YourApiKeyToken") # УДАЛЕНО: Больше не используется
NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
GOOGLE_JSON_STR = os.getenv("GOOGLE_JSON")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Лист1")
DATA_FILE = "user_data.json"

# --- Проверка наличия токена ---
if not BOT_TOKEN:
    logger.critical("Критическая ошибка: TG_BOT_TOKEN не установлен.")
    raise ValueError("Критическая ошибка: TG_BOT_TOKEN не установлен")

# --- Константы ---
PARTNER_URL = "https://app.leadteh.ru/w/dTeKr"
PARTNER_BUTTON_TEXT_OPTIONS = ["🎁 Узнать спеццены", "🔥 Эксклюзивное предложение", "💡 Получить консультацию", "💎 Прайс от экспертов"]
BOT_HINTS = [
    "💡 Узнайте курс любой монеты командой `/price`", "⚙️ Посмотрите на самые доходные ASIC",
    "⛏️ Рассчитайте прибыль с помощью 'Калькулятора'", "📰 Хотите свежие крипто-новости?",
    "🤑 Улучшайте свою ферму командой `/upgrade_rig`", "😱 Проверьте Индекс Страха и Жадности",
    "🏆 Сравните себя с лучшими в `/top_miners`", "🎓 Что такое 'HODL'? Узнайте: `/word`",
    "🧠 Проверьте знания и заработайте в `/quiz`", "🛍️ Загляните в магазин улучшений: `/shop`"
]
HALVING_INTERVAL = 210000

# --- Игровые константы ---
CRYPTO_TERMS = ["Блокчейн", "Газ (Gas)", "Халвинг", "ICO", "DeFi", "NFT", "Сатоши", "Кит (Whale)", "HODL", "DEX", "Смарт-контракт"]
MINING_RATES = {1: 0.0001, 2: 0.0002, 3: 0.0004, 4: 0.0008, 5: 0.0016}
UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1}
STREAK_BONUS_MULTIPLIER = 0.05
BOOST_COST = 0.0005
BOOST_DURATION_HOURS = 24
QUIZ_REWARD = 0.0001
QUIZ_MIN_CORRECT_FOR_REWARD = 3
QUIZ_QUESTIONS_COUNT = 5

# --- Класс для обработки исключений Telebot ---
class ExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        logger.error("Произошла ошибка в обработчике pyTelegramBotAPI:", exc_info=exception)
        return True

# --- Инициализация клиентов ---
bot = telebot.TeleBot(BOT_TOKEN, threaded=False, parse_mode='HTML', exception_handler=ExceptionHandler())
app = Flask(__name__)
try:
    openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
    if not openai_client:
        logger.warning("OPENAI_API_KEY не найден. Функциональность GPT будет отключена.")
except Exception as e:
    openai_client = None
    logger.error(f"Не удалось инициализировать клиент OpenAI: {e}", exc_info=True)

# --- Глобальные переменные и кэш ---
asic_cache = {"data": [], "timestamp": None}
currency_cache = {"rate": None, "timestamp": None}
user_quiz_states = {} # Состояния для викторины

# ========================================================================================
# 2. КЛАСС ИГРОВОЙ ЛОГИКИ
# ========================================================================================
class GameLogic:
    """Инкапсулирует всю логику, связанную с игрой 'симулятор майнинга'."""
    def __init__(self, data_file):
        self.data_file = data_file
        self.user_rigs = self.load_data()
        atexit.register(self.save_data) # Сохраняем данные при выходе

    def load_data(self):
        """Загружает данные пользователей из JSON файла при старте."""
        try:
            if os.path.exists(self.data_file):
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    rigs = {}
                    for user_id, rig_data in loaded_data.items():
                        for key, value in rig_data.items():
                            if 'until' in key or 'collected' in key and value:
                                rig_data[key] = datetime.fromisoformat(value)
                        rigs[int(user_id)] = rig_data
                logger.info(f"Данные {len(rigs)} пользователей успешно загружены.")
                return rigs
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"Файл данных не найден или поврежден. Будет создан новый. Ошибка: {e}")
        except Exception as e:
            logger.error(f"Не удалось загрузить данные пользователей: {e}", exc_info=True)
        return {}

    def save_data(self):
        """Сохраняет данные пользователей (фермы) в JSON файл."""
        try:
            data_to_save = {}
            for user_id, rig_data in self.user_rigs.items():
                copied_data = rig_data.copy()
                for key, value in copied_data.items():
                    if isinstance(value, datetime):
                        copied_data[key] = value.isoformat()
                data_to_save[user_id] = copied_data

            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data_to_save, f, indent=4, ensure_ascii=False)
            logger.info("Данные пользователей успешно сохранены.")
        except Exception as e:
            logger.error(f"Ошибка при сохранении данных пользователей: {e}", exc_info=True)

    def get_rig_info(self, user_id, user_name):
        """Возвращает информацию о ферме пользователя, создавая ее при необходимости."""
        if user_id not in self.user_rigs:
            self.user_rigs[user_id] = {'last_collected': None, 'balance': 0.0, 'level': 1, 'streak': 0, 'name': user_name, 'boost_active_until': None}
            initial_message = "🎉 Поздравляю! Вы запустили свою первую виртуальную ферму!\n\n"
        else:
            initial_message = ""
        
        rig = self.user_rigs[user_id]
        next_level = rig['level'] + 1
        upgrade_cost_text = f"Стоимость улучшения до {next_level} уровня: <code>{UPGRADE_COSTS.get(next_level, 'N/A')}</code> BTC." if next_level in UPGRADE_COSTS else "Вы достигли максимального уровня!"
        
        boost_status = ""
        if rig.get('boost_active_until') and datetime.now() < rig['boost_active_until']:
            time_left = rig['boost_active_until'] - datetime.now()
            h, rem = divmod(time_left.seconds, 3600)
            m, _ = divmod(rem, 60)
            boost_status = f"⚡️ <b>Буст x2 активен еще: {h}ч {m}м</b>\n"

        response = (f"{initial_message}🖥️ <b>Ферма {telebot.util.escape(rig['name'])}</b>\n\n"
                    f"<b>Уровень:</b> {rig['level']}\n"
                    f"<b>Баланс:</b> <code>{rig['balance']:.8f}</code> BTC\n"
                    f"<b>Дневная серия:</b> {rig['streak']} 🔥 (бонус <b>+{rig['streak'] * STREAK_BONUS_MULTIPLIER:.0%}</b>)\n"
                    f"{boost_status}\n"
                    f"{upgrade_cost_text}\n\n"
                    "<code>/collect</code>, <code>/upgrade_rig</code>, <code>/shop</code>")
        return response

    def collect_reward(self, user_id):
        if user_id not in self.user_rigs: return "🤔 У вас нет фермы. Начните с <code>/my_rig</code>."
        
        rig = self.user_rigs[user_id]
        now = datetime.now()
        if rig.get('last_collected') and (now - rig['last_collected']) < timedelta(hours=24):
            time_left = timedelta(hours=24) - (now - rig['last_collected'])
            h, m = divmod(time_left.seconds, 3600)[0], divmod(time_left.seconds % 3600, 60)[0]
            return f"Вы уже собирали награду. Попробуйте снова через <b>{h}ч {m}м</b>."
        
        rig['streak'] = rig['streak'] + 1 if rig.get('last_collected') and (now - rig['last_collected']) < timedelta(hours=48) else 1
        
        base_mined = MINING_RATES.get(rig['level'], 0.0001)
        streak_bonus = base_mined * rig['streak'] * STREAK_BONUS_MULTIPLIER
        boost_multiplier = 2 if rig.get('boost_active_until') and now < rig['boost_active_until'] else 1
        total_mined = (base_mined + streak_bonus) * boost_multiplier
        
        rig['balance'] += total_mined
        rig['last_collected'] = now
        
        boost_text = " (x2 Буст!)" if boost_multiplier > 1 else ""
        return (f"✅ Собрано <b>{total_mined:.8f}</b> BTC{boost_text}!\n"
                f"  (База: {base_mined:.8f} + Бонус за серию: {streak_bonus:.8f})\n"
                f"🔥 Ваша серия: <b>{rig['streak']} дней!</b>\n"
                f"💰 Ваш новый баланс: <code>{rig['balance']:.8f}</code> BTC.")

    def upgrade_rig(self, user_id):
        if user_id not in self.user_rigs: return "🤔 У вас нет фермы. Начните с <code>/my_rig</code>."
        
        rig = self.user_rigs[user_id]
        next_level, cost = rig['level'] + 1, UPGRADE_COSTS.get(rig['level'] + 1)
        if not cost: return "🎉 Поздравляем, у вас максимальный уровень фермы!"
        
        if rig['balance'] >= cost:
            rig['balance'] -= cost
            rig['level'] = next_level
            return f"🚀 <b>Улучшение завершено!</b>\n\nВаша ферма достигла <b>{next_level}</b> уровня!"
        else:
            return f"❌ <b>Недостаточно средств.</b>\n\nДля улучшения до {next_level} уровня требуется <code>{cost}</code> BTC."

    def get_top_miners(self):
        if not self.user_rigs: return "Пока нет ни одного майнера для составления топа."
        
        sorted_rigs = sorted(self.user_rigs.values(), key=lambda r: r.get('balance', 0), reverse=True)
        response = ["🏆 <b>Топ-5 Виртуальных Майнеров:</b>\n"]
        for i, rig in enumerate(sorted_rigs[:5]):
            response.append(f"<b>{i+1}.</b> {telebot.util.escape(rig.get('name','N/A'))} - <code>{rig.get('balance',0):.6f}</code> BTC (Ур. {rig.get('level',1)})")
        return "\n".join(response)
        
    def buy_boost(self, user_id):
        if user_id not in self.user_rigs: return "🤔 У вас нет фермы. Начните с <code>/my_rig</code>."
        rig = self.user_rigs[user_id]
        if rig.get('boost_active_until') and datetime.now() < rig['boost_active_until']:
            return "У вас уже активен буст!"
            
        if rig['balance'] >= BOOST_COST:
            rig['balance'] -= BOOST_COST
            rig['boost_active_until'] = datetime.now() + timedelta(hours=BOOST_DURATION_HOURS)
            return "⚡️ <b>Энергетический буст куплен!</b>\n\nВаша добыча будет удвоена в течение следующих 24 часов."
        else:
            return "❌ <b>Недостаточно средств.</b>"

    def apply_quiz_reward(self, user_id):
        if user_id in self.user_rigs:
            self.user_rigs[user_id]['balance'] += QUIZ_REWARD
            return f"\n\n🎁 За отличный результат вам начислено <b>{QUIZ_REWARD:.4f} BTC!</b>"
        else:
            return f"\n\n🎁 Вы бы получили <b>{QUIZ_REWARD:.4f} BTC</b>, если бы у вас была ферма! Начните с <code>/my_rig</code>."

# Инициализируем класс с игровой логикой
game = GameLogic(DATA_FILE)

# ========================================================================================
# 3. РАБОТА С ВНЕШНИМИ СЕРВИСАМИ (API)
# ========================================================================================
def get_gsheet():
    """Подключается к Google Sheets и возвращает объект рабочего листа."""
    try:
        if not GOOGLE_JSON_STR or not SHEET_ID:
            logger.warning("Переменные для Google Sheets не установлены. Работа с таблицами будет пропущена.")
            return None
        creds_dict = json.loads(GOOGLE_JSON_STR)
        creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        return gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    except Exception as e:
        logger.error(f"Ошибка подключения к Google Sheets: {e}")
        return None

# Остальные API-функции без изменений...
def log_to_sheet(row_data: list):
    try:
        sheet = get_gsheet()
        if sheet: sheet.append_row(row_data, value_input_option='USER_ENTERED')
    except Exception as e: logger.error(f"Ошибка записи в Google Sheets: {e}")

def ask_gpt(prompt: str, model: str = "gpt-4o"):
    if not openai_client: return "[❌ Ошибка: Клиент OpenAI не инициализирован. Проверьте ключ API.]"
    try:
        res = openai_client.chat.completions.create(model=model, messages=[{"role": "system", "content": "Ты — полезный ассистент, отвечающий на русском с HTML-тегами."}, {"role": "user", "content": prompt}], timeout=20.0)
        return res.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Ошибка вызова OpenAI API: {e}"); return "[❌ Ошибка GPT: Не удалось получить ответ.]"

def get_crypto_price(ticker="BTC"):
    ticker = ticker.upper()
    sources = [f"https://api.binance.com/api/v3/ticker/price?symbol={ticker}USDT", f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={ticker}-USDT"]
    for i, url in enumerate(sources):
        try:
            res = requests.get(url, timeout=4).json()
            if i == 0 and 'price' in res: return (float(res['price']), "Binance")
            if i == 1 and res.get('data', {}).get('price'): return (float(res['data']['price']), "KuCoin")
        except Exception: continue
    logger.error(f"Не удалось получить цену для {ticker}."); return (None, None)

def get_top_asics(force_update: bool = False):
    global asic_cache
    if not force_update and asic_cache.get("data") and (datetime.now() - asic_cache.get("timestamp", datetime.min) < timedelta(hours=1)): return asic_cache.get("data")
    try:
        r = requests.get("https://www.asicminervalue.com", timeout=15); r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml"); parsed_asics = []
        table = soup.find('h2', id='sha-256').find_next('table')
        for row in table.select("tbody tr"):
            cols = row.find_all("td"); name_tag = cols[1].find('a')
            if len(cols) < 5 or not name_tag: continue
            name = name_tag.get_text(strip=True); hashrate = cols[2].get_text(strip=True)
            power = re.search(r'([\d,]+)', cols[3].get_text(strip=True))
            revenue = re.search(r'([\d\.]+)', cols[4].get_text(strip=True).replace('$', ''))
            if power and revenue: parsed_asics.append({'name': name, 'hashrate': hashrate, 'power_watts': float(power.group(1).replace(',', '')), 'daily_revenue': float(revenue.group(1))})
        if not parsed_asics: raise ValueError("Не удалось распарсить ASIC.")
        parsed_asics.sort(key=lambda x: x['daily_revenue'], reverse=True)
        asic_cache = {"data": parsed_asics[:5], "timestamp": datetime.now()}
        logger.info(f"Успешно получено {len(asic_cache['data'])} ASIC.")
        return asic_cache["data"]
    except Exception as e: logger.error(f"Не удалось получить данные по ASIC: {e}", exc_info=True); return []

def get_fear_and_greed_index():
    try:
        data = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()['data'][0]
        value, classification = int(data['value']), data['value_classification']
        plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(8, 4.5), subplot_kw={'projection': 'polar'})
        ax.set_yticklabels([]); ax.set_xticklabels([]); ax.grid(False); ax.spines['polar'].set_visible(False); ax.set_ylim(0, 1)
        colors = ['#d94b4b', '#e88452', '#ece36a', '#b7d968', '#73c269']
        for i in range(100): ax.barh(1, 0.0314, left=3.14 - (i * 0.0314), height=0.3, color=colors[min(len(colors) - 1, int(i / 25))])
        angle = 3.14 - (value * 0.0314)
        ax.annotate('', xy=(angle, 1), xytext=(0, 0), arrowprops=dict(facecolor='white', shrink=0.05, width=4, headwidth=10))
        fig.text(0.5, 0.5, f"{value}", ha='center', va='center', fontsize=48, color='white', weight='bold')
        fig.text(0.5, 0.35, classification, ha='center', va='center', fontsize=20, color='white')
        buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=150, transparent=True); buf.seek(0); plt.close(fig)
        prompt = f"Кратко объясни для майнера, как 'Индекс страха и жадности' со значением '{value} ({classification})' влияет на рынок и его возможные действия. (2-3 предложения)"
        explanation = ask_gpt(prompt)
        text = f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>\n\n{explanation}"
        return buf, text
    except Exception as e:
        logger.error(f"Ошибка при создании графика индекса страха: {e}", exc_info=True)
        return None, "[❌ Ошибка при получении индекса]"

def get_usd_rub_rate():
    global currency_cache
    if currency_cache.get("rate") and (datetime.now() - currency_cache.get("timestamp", datetime.min) < timedelta(minutes=30)): return currency_cache["rate"]
    sources = ["https://api.exchangerate.host/latest?base=USD&symbols=RUB", "https://api.exchangerate-api.com/v4/latest/USD"]
    for url in sources:
        try:
            response = requests.get(url, timeout=4); response.raise_for_status()
            rate = response.json().get('rates', {}).get('RUB')
            if rate: currency_cache = {"rate": rate, "timestamp": datetime.now()}; return rate
        except Exception: continue
    return None

def get_halving_info():
    try:
        current_block = int(requests.get("https://blockchain.info/q/getblockcount", timeout=5).text)
        blocks_left = ((current_block // HALVING_INTERVAL) + 1) * HALVING_INTERVAL - current_block
        if blocks_left <= 0: return f"🎉 <b>Халвинг уже произошел!</b>"
        days, rem_min = divmod(blocks_left * 10, 1440); hours, _ = divmod(rem_min, 60)
        return f"⏳ <b>До халвинга Bitcoin осталось:</b>\n\n🗓 <b>Дней:</b> <code>{days}</code> | ⏰ <b>Часов:</b> <code>{hours}</code>\n🧱 <b>Блоков до халвинга:</b> <code>{blocks_left:,}</code>"
    except Exception as e: logger.error(f"Ошибка получения данных для халвинга: {e}"); return "[❌ Не удалось получить данные о халвинге]"

def get_crypto_news():
    if not NEWSAPI_KEY: return "[❌ Функция новостей отключена. Администратор не указал ключ API.]"
    try:
        params = {"auth_token": NEWSAPI_KEY, "public": "true", "currencies": "BTC,ETH"}
        posts = requests.get("https://cryptopanic.com/api/v1/posts/", params=params, timeout=10).json().get("results", [])[:3]
        if not posts: return "[🧐 Новостей по вашему запросу не найдено]"
        
        items = []
        for p in posts:
            title = p['title']
            # Исправлено: Убрана вложенная f-строка
            prompt = f"Сделай краткое саммари (1 предложение): '{title}'"
            summary = ask_gpt(prompt, "gpt-4o-mini")
            
            if '[❌' in summary:
                summary = telebot.util.escape(title)
            
            link = p.get("url", "")
            items.append(f'🔹 <a href="{link}">{summary}</a>')
            
        return "📰 <b>Последние крипто-новости:</b>\n\n" + "\n\n".join(items)
    except requests.RequestException as e: logger.error(f"Ошибка API новостей: {e}"); return "[❌ Ошибка API новостей]"

# ИЗМЕНЕНО: Функция для получения цены на газ без API ключа
def get_eth_gas_price():
    """Получает цену на газ из открытого источника ethgas.watch."""
    try:
        res = requests.get("https://ethgas.watch/api/gas", timeout=5).json()
        # Новая структура ответа: {"slow": {"gwei": ...}, "normal": ..., "fast": ...}
        slow_price = res.get('slow', {}).get('gwei', 'N/A')
        normal_price = res.get('normal', {}).get('gwei', 'N/A')
        fast_price = res.get('fast', {}).get('gwei', 'N/A')
        
        return (f"⛽️ <b>Актуальная цена газа (Gwei):</b>\n\n"
                f"🐢 <b>Медленно:</b> <code>{slow_price}</code>\n"
                f"🚶‍♂️ <b>Средне:</b> <code>{normal_price}</code>\n"
                f"🚀 <b>Быстро:</b> <code>{fast_price}</code>\n\n"
                f"<i>Данные от ethgas.watch</i>")
    except Exception as e:
        logger.error(f"Ошибка сети при запросе цены на газ: {e}")
        return "[❌ Не удалось получить данные о газе]"

def get_new_quiz_questions():
    try:
        url = f"https://opentdb.com/api.php?amount={QUIZ_QUESTIONS_COUNT}&type=multiple"
        response = requests.get(url, timeout=7).json()
        if response.get("response_code") != 0: logger.error(f"API викторин вернуло ошибку: {response}"); return None
        formatted_questions = []
        for item in response.get("results", []):
            options = [BeautifulSoup(o, "html.parser").text for o in item['incorrect_answers']]
            correct_answer = BeautifulSoup(item['correct_answer'], "html.parser").text
            options.append(correct_answer); random.shuffle(options)
            formatted_questions.append({"question": BeautifulSoup(item['question'], "html.parser").text, "options": options, "correct_index": options.index(correct_answer)})
        return formatted_questions
    except Exception as e: logger.error(f"Не удалось загрузить вопросы для викторины: {e}"); return None

# ========================================================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ БОТА
# ========================================================================================
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = ["💹 Курс", "⚙️ Топ-5 ASIC", "⛏️ Калькулятор", "📰 Новости", "😱 Индекс Страха", "⏳ Халвинг", "🧠 Викторина", "🎓 Слово дня", "🏆 Топ майнеров", "🛍️ Магазин"]
    markup.add(*[types.KeyboardButton(text) for text in buttons])
    return markup

def send_message_with_partner_button(chat_id, text, **kwargs):
    try:
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
        bot.send_message(chat_id, f"{text}\n\n---\n<i>{random.choice(BOT_HINTS)}</i>", reply_markup=markup, disable_web_page_preview=True, **kwargs)
    except Exception as e: logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")

def send_photo_with_partner_button(chat_id, photo, caption, **kwargs):
    try:
        if not photo: raise ValueError("Объект фото пустой")
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
        bot.send_photo(chat_id, photo, caption=f"{caption}\n\n---\n<i>{random.choice(BOT_HINTS)}</i>", reply_markup=markup, **kwargs)
    except Exception as e: logger.error(f"Не удалось отправить фото: {e}. Отправляю текстом."); send_message_with_partner_button(chat_id, caption)

def calculate_and_format_profit(electricity_cost_rub: float):
    rate = get_usd_rub_rate(); asics = get_top_asics()
    if not rate: return "Не удалось получить курс доллара. Попробуйте позже."
    if not asics: return "Не удалось получить данные по ASIC для расчета."
    cost_usd = electricity_cost_rub / rate
    result = [f"💰 <b>Расчет профита (розетка {electricity_cost_rub:.2f} ₽/кВтч)</b>\n"]
    for asic in asics:
        cost = (asic['power_watts'] / 1000) * 24 * cost_usd; profit = asic['daily_revenue'] - cost
        result.append(f"<b>{telebot.util.escape(asic['name'])}</b>\n  Профит: <b>${profit:.2f}/день</b> (Доход: ${asic['daily_revenue']:.2f}, Расход: ${cost:.2f})")
    return "\n".join(result)

# ========================================================================================
# 5. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ
# ========================================================================================
# --- Основные команды ---
@bot.message_handler(commands=['start', 'help'])
def handle_start_help(msg):
    help_text = ("👋 Привет! Я ваш крипто-помощник.\n\n"
                 "<b>Основные команды:</b>\n"
                 "<code>/price</code>, <code>/gas</code>, <code>/news</code>\n\n"
                 "<b>Утилиты и игра:</b>\n"
                 "<code>/my_rig</code>, <code>/collect</code>, <code>/upgrade_rig</code>\n"
                 "<code>/shop</code>, <code>/top_miners</code>, <code>/quiz</code>, <code>/word</code>.")
    bot.send_message(msg.chat.id, help_text, reply_markup=get_main_keyboard())

# --- Обработчики кнопок и команд (информация) ---
@bot.message_handler(commands=['price'])
@bot.message_handler(func=lambda message: message.text.lower() == '💹 курс')
def handle_price_request(msg):
    sent = bot.send_message(msg.chat.id, "Курс какой криптовалюты вас интересует? (напр: BTC, ETH, SOL)", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(sent, process_price_step)

def process_price_step(msg):
    price, source = get_crypto_price(msg.text)
    if price:
        text = f"💹 Курс {msg.text.upper()}/USD: <b>${price:,.2f}</b>\n<i>(Данные от {source})</i>"
        send_message_with_partner_button(msg.chat.id, text, reply_markup=get_main_keyboard())
    else:
        bot.send_message(msg.chat.id, f"❌ Не удалось получить курс для {msg.text.upper()}.", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['asics'])
@bot.message_handler(func=lambda message: message.text.lower() == '⚙️ топ-5 asic')
def handle_asics_text(msg):
    bot.send_message(msg.chat.id, "⏳ Загружаю актуальный список...")
    asics = get_top_asics()
    if not asics: return send_message_with_partner_button(msg.chat.id, "Не удалось получить данные об ASIC.")
    rows = [f"{a['name']:<22.21}| {a['hashrate']:<9}| {a['power_watts']:<5.0f}| ${a['daily_revenue']:<10.2f}" for a in asics]
    response = f"<pre>Модель                | H/s      | P, W | Доход/день\n" \
               f"----------------------|----------|------|-----------\n" + "\n".join(rows) + "</pre>"
    response += f"\n\n{ask_gpt('Напиши короткий мотивирующий комментарий (1-2 предложения) для майнинг-чата по списку доходных ASIC. Подтолкни к мысли об обновлении.', 'gpt-4o')}"
    send_message_with_partner_button(msg.chat.id, response)

@bot.message_handler(commands=['calculator'])
@bot.message_handler(func=lambda message: message.text.lower() == '⛏️ калькулятор')
def handle_calculator_request(msg):
    sent = bot.send_message(msg.chat.id, "💡 Введите стоимость электроэнергии в <b>рублях</b> за кВт/ч:", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(sent, process_calculator_step)

def process_calculator_step(msg):
    try:
        cost = float(msg.text.replace(',', '.'))
        send_message_with_partner_button(msg.chat.id, calculate_and_format_profit(cost), reply_markup=get_main_keyboard())
    except ValueError:
        bot.send_message(msg.chat.id, "❌ Неверный формат. Пожалуйста, введите число (например: 4.5 или 5).", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['news'])
@bot.message_handler(func=lambda message: message.text.lower() == '📰 новости')
def handle_news(msg): bot.send_chat_action(msg.chat.id, 'typing'); send_message_with_partner_button(msg.chat.id, get_crypto_news())

@bot.message_handler(commands=['fear', 'fng'])
@bot.message_handler(func=lambda message: message.text.lower() == '😱 индекс страха')
def handle_fear_and_greed(msg): bot.send_message(msg.chat.id, "⏳ Генерирую график индекса..."); image, text = get_fear_and_greed_index(); send_photo_with_partner_button(msg.chat.id, image, text) if image else send_message_with_partner_button(msg.chat.id, text)

@bot.message_handler(commands=['halving'])
@bot.message_handler(func=lambda message: message.text.lower() == '⏳ халвинг')
def handle_halving(msg): send_message_with_partner_button(msg.chat.id, get_halving_info())

@bot.message_handler(commands=['gas'])
def handle_gas(msg): send_message_with_partner_button(msg.chat.id, get_eth_gas_price())


# --- Обработчики кнопок и команд (игра) ---
@bot.message_handler(commands=['my_rig'])
def handle_my_rig(msg): send_message_with_partner_button(msg.chat.id, game.get_rig_info(msg.from_user.id, msg.from_user.first_name))

@bot.message_handler(commands=['collect'])
def handle_collect(msg): send_message_with_partner_button(msg.chat.id, game.collect_reward(msg.from_user.id))

@bot.message_handler(commands=['upgrade_rig'])
def handle_upgrade_rig(msg): send_message_with_partner_button(msg.chat.id, game.upgrade_rig(msg.from_user.id))

@bot.message_handler(commands=['top_miners'])
@bot.message_handler(func=lambda message: message.text.lower() == '🏆 топ майнеров')
def handle_top_miners(msg): send_message_with_partner_button(msg.chat.id, game.get_top_miners())

@bot.message_handler(commands=['shop'])
@bot.message_handler(func=lambda message: message.text.lower() == '🛍️ магазин')
def handle_shop(msg): send_message_with_partner_button(msg.chat.id, "🛍️ <b>Магазин улучшений</b>\n\n<b>1. Энергетический буст (x2)</b>\n<i>Удваивает добычу на 24 часа.</i>\n<b>Стоимость:</b> <code>{BOOST_COST}</code> BTC\n\nДля покупки: <code>/buy_boost</code>")

@bot.message_handler(commands=['buy_boost'])
def handle_buy_boost(msg): send_message_with_partner_button(msg.chat.id, game.buy_boost(msg.from_user.id))

# --- Обработчики кнопок и команд (викторина и развлечения) ---
@bot.message_handler(commands=['word'])
@bot.message_handler(func=lambda message: message.text.lower() == '🎓 слово дня')
def handle_word_of_the_day(msg):
    term = random.choice(CRYPTO_TERMS)
    explanation = ask_gpt(f"Объясни термин '{term}' простыми словами для новичка в криптовалютах (2-3 предложения).", "gpt-4o-mini")
    send_message_with_partner_button(msg.chat.id, f"🎓 <b>Слово дня: {term}</b>\n\n{explanation}")

@bot.message_handler(commands=['quiz'])
@bot.message_handler(func=lambda message: message.text.lower() == '🧠 викторина')
def handle_quiz(msg):
    bot.send_message(msg.chat.id, "⏳ Ищу интересные вопросы для викторины...")
    questions = get_new_quiz_questions()
    if not questions: return bot.send_message(msg.chat.id, "Не удалось загрузить вопросы. Попробуйте позже.", reply_markup=get_main_keyboard())
    
    user_quiz_states[msg.from_user.id] = {'score': 0, 'question_index': 0, 'questions': questions}
    bot.send_message(msg.chat.id, f"🔥 <b>Начинаем крипто-викторину!</b>\nОтветьте на {len(questions)} вопросов.", reply_markup=types.ReplyKeyboardRemove())
    send_quiz_question(msg.chat.id, msg.from_user.id)

def send_quiz_question(chat_id, user_id):
    state = user_quiz_states.get(user_id)
    if not state: return
    q_index = state['question_index']
    
    if q_index >= len(state['questions']):
        score = state['score']
        reward_text = game.apply_quiz_reward(user_id) if score >= QUIZ_MIN_CORRECT_FOR_REWARD else ""
        bot.send_message(chat_id, f"🎉 <b>Викторина завершена!</b>\nВаш результат: <b>{score} из {len(state['questions'])}</b>.{reward_text}", reply_markup=get_main_keyboard())
        user_quiz_states.pop(user_id, None)
        return
        
    q_data = state['questions'][q_index]
    markup = types.InlineKeyboardMarkup(row_width=2).add(*[types.InlineKeyboardButton(opt, callback_data=f"quiz_{q_index}_{i}") for i, opt in enumerate(q_data['options'])])
    bot.send_message(chat_id, f"<b>Вопрос {q_index + 1}:</b>\n{q_data['question']}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('quiz_'))
def handle_quiz_answer(call):
    user_id = call.from_user.id
    state = user_quiz_states.get(user_id)
    if not state: return bot.answer_callback_query(call.id, "Викторина уже не активна.")
    
    try: _, q_index_str, answer_index_str = call.data.split('_'); q_index, answer_index = int(q_index_str), int(answer_index_str)
    except (ValueError, IndexError): return bot.answer_callback_query(call.id, "Ошибка в данных викторины.")

    if q_index != state.get('question_index'): return bot.answer_callback_query(call.id, "Вы уже ответили.")
    
    q_data = state['questions'][q_index]
    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
    
    if answer_index == q_data['correct_index']:
        state['score'] += 1; bot.send_message(call.message.chat.id, "✅ Правильно!")
    else:
        bot.send_message(call.message.chat.id, f"❌ Неверно. Правильный ответ: <b>{q_data['options'][q_data['correct_index']]}</b>")
    
    state['question_index'] += 1
    time.sleep(1.5)
    send_quiz_question(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)

# --- Обработчик для всех остальных текстовых сообщений ---
@bot.message_handler(content_types=['text'])
def handle_other_text(msg):
    try:
        # Анализ текста на ключевые слова (покупка/продажа)
        text_lower = msg.text.lower()
        sale_words = ["продам", "купить", "в наличии"]
        item_words = ["asic", "асик", "whatsminer", "antminer"]
        if any(w in text_lower for w in sale_words) and any(w in text_lower for w in item_words):
            log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or "N/A", msg.text])
            prompt = f"Пользователь прислал объявление в майнинг-чат. Кратко и неформально прокомментируй его, поддержи диалог. Текст: '{msg.text}'"
            response = ask_gpt(prompt)
        else:
            # Если ничего не подошло - отправляем запрос в GPT
            bot.send_chat_action(msg.chat.id, 'typing')
            response = ask_gpt(msg.text)
        
        send_message_with_partner_button(msg.chat.id, response)

    except Exception as e:
        logger.error("Критическая ошибка в handle_other_text!", exc_info=e)
        bot.send_message(msg.chat.id, "😵 Ой, что-то пошло не так. Мы уже разбираемся!")

# ========================================================================================
# 6. ЗАПУСК БОТА И ПЛАНИРОВЩИКА
# ========================================================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
        return '', 200
    return 'Forbidden', 403

@app.route("/")
def index(): return "Bot is running!"

def run_scheduler():
    if WEBHOOK_URL: schedule.every(25).minutes.do(lambda: requests.get(WEBHOOK_URL.rsplit('/', 1)[0]))
    schedule.every(4).hours.do(auto_send_news)
    schedule.every(6).hours.do(auto_check_status)
    schedule.every(1).hours.do(get_top_asics, force_update=True)
    schedule.every(5).minutes.do(game.save_data) # Используем метод класса
    
    logger.info("Планировщик запущен.")
    
    while True:
        try: schedule.run_pending(); time.sleep(1)
        except Exception as e: logger.error(f"Ошибка в планировщике: {e}", exc_info=True)

def auto_send_news():
    if NEWS_CHAT_ID: logger.info("Отправка новостей по расписанию..."); send_message_with_partner_button(NEWS_CHAT_ID, get_crypto_news())

def auto_check_status():
    if not ADMIN_CHAT_ID: return
    logger.info("Проверка состояния систем...")
    errors = []
    if get_crypto_price("BTC")[0] is None: errors.append("API цены")
    if openai_client and "[❌" in ask_gpt("Тест"): errors.append("API OpenAI")
    if GOOGLE_JSON_STR and not get_gsheet(): errors.append("Google Sheets")
    status = "✅ Все системы в норме." if not errors else f"⚠️ Сбой в: {', '.join(errors)}"
    try: bot.send_message(ADMIN_CHAT_ID, f"<b>Отчет о состоянии ({datetime.now().strftime('%H:%M')})</b>\n{status}")
    except Exception as e: logger.error(f"Не удалось отправить отчет о состоянии администратору: {e}")

if __name__ == '__main__':
    logger.info("Запуск бота...")
    threading.Thread(target=run_scheduler, daemon=True).start()
    
    if WEBHOOK_URL:
        logger.info("Режим: вебхук.")
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=f"{WEBHOOK_URL.rstrip('/')}/webhook")
        app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
    else:
        logger.info("Режим: long-polling.")
        bot.remove_webhook()
        bot.polling(none_stop=Tr
