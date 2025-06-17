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
import html
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
# Настраиваем формат логирования для удобного отслеживания работы бота
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S'
)
logger = logging.getLogger(__name__)

# --- Ключи и Настройки (Загрузка из переменных окружения) ---
# Безопасно получаем ключи API и другие настройки из переменных окружения
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
NEWSAPI_KEY = os.getenv("CRYPTO_API_KEY") # Ключ для CryptoPanic
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "YourApiKeyToken")
NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
GOOGLE_JSON_STR = os.getenv("GOOGLE_JSON")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Лист1")
DATA_FILE = "user_data.json" # Файл для хранения данных пользователей

# --- Проверка наличия токена ---
if not BOT_TOKEN:
    logger.critical("Критическая ошибка: TG_BOT_TOKEN не установлен. Бот не может быть запущен.")
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
# Старый список вопросов удален, так как теперь они загружаются из сети
MINING_RATES = {1: 0.0001, 2: 0.0002, 3: 0.0004, 4: 0.0008, 5: 0.0016}
UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1}
STREAK_BONUS_MULTIPLIER = 0.05
BOOST_COST = 0.0005
BOOST_DURATION_HOURS = 24
QUIZ_REWARD = 0.0001
QUIZ_MIN_CORRECT_FOR_REWARD = 3
QUIZ_QUESTIONS_COUNT = 5 # Количество вопросов в одной викторине

# --- Класс для обработки исключений Telebot ---
class ExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        logger.error("Произошла ошибка в обработчике pyTelegramBotAPI:", exc_info=exception)
        return True

# --- Инициализация ---
try:
    bot = telebot.TeleBot(BOT_TOKEN, threaded=False, parse_mode='HTML', exception_handler=ExceptionHandler())
    app = Flask(__name__)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.critical(f"Не удалось инициализировать клиентов API: {e}")
    raise

# --- Глобальные переменные ---
user_states = {} # Временные состояния пользователей (для запросов типа "введите тикер")
asic_cache = {"data": [], "timestamp": None}
user_rigs = {} # Данные об игровых фермах пользователей
currency_cache = {"rate": None, "timestamp": None}

# ========================================================================================
# 2. СОХРАНЕНИЕ И ЗАГРУЗКА ДАННЫХ
# ========================================================================================
def save_user_data():
    """Сохраняет данные пользователей (фермы) в JSON файл."""
    try:
        # Конвертируем datetime объекты в строки для JSON-сериализации
        data_to_save = {}
        for user_id, rig_data in user_rigs.items():
            # создаем копию, чтобы не изменять оригинальный словарь
            copied_data = rig_data.copy()
            for key, value in copied_data.items():
                if isinstance(value, datetime):
                    copied_data[key] = value.isoformat()
            data_to_save[user_id] = copied_data

        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
        logger.info("Данные пользователей успешно сохранены.")
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных пользователей: {e}")

def load_user_data():
    """Загружает данные пользователей из JSON файла при старте."""
    global user_rigs
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                # Конвертируем строки обратно в datetime объекты
                for user_id, rig_data in loaded_data.items():
                    for key, value in rig_data.items():
                        if isinstance(value, str) and re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', value):
                            rig_data[key] = datetime.fromisoformat(value)
                    user_rigs[int(user_id)] = rig_data
            logger.info(f"Данные {len(user_rigs)} пользователей успешно загружены.")
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Файл данных не найден или поврежден. Будет создан новый. Ошибка: {e}")
        user_rigs = {}
    except Exception as e:
        logger.error(f"Не удалось загрузить данные пользователей: {e}")


# ========================================================================================
# 3. РАБОТА С ВНЕШНИМИ СЕРВИСАМИ (API)
# ========================================================================================
def get_gsheet():
    """Подключается к Google Sheets и возвращает объект рабочего листа."""
    try:
        creds_dict = json.loads(GOOGLE_JSON_STR)
        creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        return gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    except Exception as e:
        logger.error(f"Ошибка подключения к Google Sheets: {e}")
        return None

def log_to_sheet(row_data: list):
    """Записывает строку данных в Google Sheets."""
    try:
        sheet = get_gsheet()
        if sheet:
            sheet.append_row(row_data, value_input_option='USER_ENTERED')
        else:
            logger.error("Не удалось получить объект листа для записи.")
    except Exception as e:
        logger.error(f"Ошибка записи в Google Sheets: {e}")

def ask_gpt(prompt: str, model: str = "gpt-4o"):
    """Отправляет запрос к OpenAI API и возвращает ответ."""
    try:
        res = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Ты — полезный ассистент, который отвечает на русском, используя HTML-теги: <b>, <i>, <code>, <pre>."},
                {"role": "user", "content": prompt}
            ],
            timeout=20.0)
        return res.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Ошибка вызова OpenAI API: {e}")
        return "[❌ Ошибка GPT: Не удалось получить ответ.]"

def get_crypto_price(ticker="BTC"):
    """Получает цену криптовалюты с нескольких бирж для надежности."""
    ticker = ticker.upper()
    sources = [
        f"https://api.binance.com/api/v3/ticker/price?symbol={ticker}USDT",
        f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={ticker}-USDT",
    ]
    for i, url in enumerate(sources):
        try:
            res = requests.get(url, timeout=4).json()
            if i == 0 and 'price' in res: return (float(res['price']), "Binance")
            if i == 1 and res.get('data', {}).get('price'): return (float(res['data']['price']), "KuCoin")
        except Exception:
            logger.warning(f"Не удалось получить цену для {ticker} с URL: {url}")
            continue
    logger.error(f"Не удалось получить цену для {ticker} со всех источников.")
    return (None, None)

def get_top_asics(force_update: bool = False):
    """Парсит сайт asicminervalue.com для получения топ-5 доходных ASIC."""
    global asic_cache
    if not force_update and asic_cache.get("data") and (datetime.now() - asic_cache.get("timestamp", datetime.min) < timedelta(hours=1)):
        return asic_cache.get("data")
    try:
        r = requests.get("https://www.asicminervalue.com", timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        parsed_asics = []
        sha256_header = soup.find('h2', id='sha-256')
        if not sha256_header: raise ValueError("Не найден заголовок 'sha-256' на странице.")
        sha256_table = sha256_header.find_next('table')
        if not sha256_table: raise ValueError("Не найдена таблица после заголовка 'sha-256'.")

        for row in sha256_table.select("tbody tr"):
            cols = row.find_all("td")
            if len(cols) < 5: continue
            name_tag = cols[1].find('a')
            if not name_tag: continue
            name = name_tag.get_text(strip=True)
            hashrate_str = cols[2].get_text(strip=True)
            power_str = cols[3].get_text(strip=True)
            revenue_str = cols[4].get_text(strip=True)
            power_watts_match = re.search(r'([\d,]+)', power_str)
            daily_revenue_match = re.search(r'([\d\.]+)', revenue_str.replace('$', ''))

            if power_watts_match and daily_revenue_match:
                power_watts = float(power_watts_match.group(1).replace(',', ''))
                daily_revenue = float(daily_revenue_match.group(1))
                if power_watts > 0:
                    parsed_asics.append({'name': name, 'hashrate': hashrate_str, 'power_watts': power_watts, 'daily_revenue': daily_revenue})

        if not parsed_asics: raise ValueError("Не удалось распарсить ни одного ASIC из таблицы.")

        parsed_asics.sort(key=lambda x: x['daily_revenue'], reverse=True)
        asic_cache = {"data": parsed_asics[:5], "timestamp": datetime.now()}
        logger.info(f"Успешно получено {len(asic_cache['data'])} ASIC.")
        return asic_cache["data"]
    except Exception as e:
        logger.error(f"Не удалось получить данные по ASIC: {e}", exc_info=True)
        return []

def get_fear_and_greed_index():
    """Получает 'Индекс страха и жадности' и создает изображение."""
    try:
        data = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()['data'][0]
        value, classification = int(data['value']), data['value_classification']
        
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(8, 4.5), subplot_kw={'projection': 'polar'})
        ax.set_yticklabels([]); ax.set_xticklabels([]); ax.grid(False)
        ax.spines['polar'].set_visible(False); ax.set_ylim(0, 1)
        
        colors = ['#d94b4b', '#e88452', '#ece36a', '#b7d968', '#73c269'] # От красного к зеленому
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
        
        prompt = f"Кратко объясни для майнера, как 'Индекс страха и жадности' со значением '{value} ({classification})' влияет на рынок и его возможные действия. (2-3 предложения)"
        explanation = ask_gpt(prompt)
        text = f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>\n\n{explanation}"
        return buf, text
    except Exception as e:
        logger.error(f"Ошибка при создании графика индекса страха: {e}", exc_info=True)
        return None, "[❌ Ошибка при получении индекса]"

def get_usd_rub_rate():
    """Получает курс USD/RUB с кешированием."""
    global currency_cache
    if currency_cache.get("rate") and (datetime.now() - currency_cache.get("timestamp", datetime.min) < timedelta(minutes=30)):
        return currency_cache["rate"]
    sources = ["https://api.exchangerate.host/latest?base=USD&symbols=RUB", "https://api.exchangerate-api.com/v4/latest/USD"]
    for url in sources:
        try:
            response = requests.get(url, timeout=4); response.raise_for_status()
            rate = response.json().get('rates', {}).get('RUB')
            if rate:
                currency_cache = {"rate": rate, "timestamp": datetime.now()}
                return rate
        except Exception: continue
    logger.error("Не удалось получить курс USD/RUB.")
    return None

def get_halving_info():
    """Рассчитывает время до следующего халвинга Bitcoin."""
    try:
        current_block = int(requests.get("https://blockchain.info/q/getblockcount", timeout=5).text)
        current_epoch = current_block // HALVING_INTERVAL
        next_halving_block = (current_epoch + 1) * HALVING_INTERVAL
        blocks_left = next_halving_block - current_block
        if blocks_left <= 0: return f"🎉 <b>Халвинг на блоке {next_halving_block - HALVING_INTERVAL} уже произошел!</b>"
        
        # Среднее время блока ~10 минут
        minutes_left = blocks_left * 10
        days_left = minutes_left // (24 * 60)
        hours_left = (minutes_left % (24*60)) // 60
        
        return f"⏳ <b>До халвинга Bitcoin осталось:</b>\n\n🗓 <b>Дней:</b> <code>{days_left}</code> | ⏰ <b>Часов:</b> <code>{hours_left}</code>\n🧱 <b>Блоков до халвинга:</b> <code>{blocks_left:,}</code>"
    except Exception as e:
        logger.error(f"Ошибка получения данных для халвинга: {e}")
        return "[❌ Не удалось получить данные о халвинге]"

def get_crypto_news():
    """Получает последние новости с CryptoPanic и делает краткое саммари с помощью GPT."""
    try:
        params = {"auth_token": NEWSAPI_KEY, "public": "true", "currencies": "BTC,ETH"}
        posts = requests.get("https://cryptopanic.com/api/v1/posts/", params=params, timeout=10).json().get("results", [])[:3]
        if not posts: return "[🧐 Новостей по вашему запросу не найдено]"
        
        items = []
        for post in posts:
            summary = ask_gpt(f"Сделай краткое саммари на русском (1 предложение): '{post['title']}'", 'gpt-3.5-turbo')
            if '[❌' in summary: summary = telebot.util.escape(post['title'])
            items.append(f'🔹 <a href="{post.get("url", "")}">{summary}</a>')
            
        return "📰 <b>Последние крипто-новости:</b>\n\n" + "\n\n".join(items)
    except requests.RequestException as e:
        logger.error(f"Ошибка API новостей: {e}")
        return "[❌ Ошибка API новостей]"

def get_eth_gas_price():
    """Получает актуальную цену на газ в сети Ethereum."""
    try:
        res = requests.get(f"https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey={ETHERSCAN_API_KEY}", timeout=5).json()
        if res.get("status") == "1" and res.get("result"):
            gas = res["result"]
            return (f"⛽️ <b>Актуальная цена газа (Gwei):</b>\n\n"
                    f"🐢 <b>Медленно:</b> <code>{gas['SafeGasPrice']}</code>\n"
                    f"🚶‍♂️ <b>Средне:</b> <code>{gas['ProposeGasPrice']}</code>\n"
                    f"🚀 <b>Быстро:</b> <code>{gas['FastGasPrice']}</code>")
        return "[❌ Не удалось получить данные о газе]"
    except requests.RequestException as e:
        logger.error(f"Ошибка сети при запросе цены на газ: {e}")
        return "[❌ Сетевая ошибка при запросе цены на газ]"

def get_new_quiz_questions():
    """Получает новые вопросы для викторины из Open Trivia Database."""
    try:
        url = f"https://opentdb.com/api.php?amount={QUIZ_QUESTIONS_COUNT}&type=multiple&category=18" # Категория: Компьютеры
        response = requests.get(url, timeout=7).json()
        if response.get("response_code") != 0:
            logger.error(f"API викторин вернуло ошибку: {response}")
            return None
        
        formatted_questions = []
        for item in response.get("results", []):
            question_text = html.unescape(item['question'])
            correct_answer = html.unescape(item['correct_answer'])
            options = [html.unescape(o) for o in item['incorrect_answers']]
            options.append(correct_answer)
            random.shuffle(options)
            correct_index = options.index(correct_answer)
            
            formatted_questions.append({
                "question": question_text,
                "options": options,
                "correct_index": correct_index
            })
        return formatted_questions
    except Exception as e:
        logger.error(f"Не удалось загрузить вопросы для викторины: {e}")
        return None

# ========================================================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ БОТА
# ========================================================================================
def get_main_keyboard():
    """Создает и возвращает основную клавиатуру с кнопками."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = ["💹 Курс", "⚙️ Топ-5 ASIC", "⛏️ Калькулятор", "📰 Новости",
               "😱 Индекс Страха", "⏳ Халвинг", "🧠 Викторина", "🎓 Слово дня",
               "🏆 Топ майнеров", "🛍️ Магазин"]
    markup.add(*[types.KeyboardButton(text) for text in buttons])
    return markup

def send_message_with_partner_button(chat_id, text, **kwargs):
    """Отправляет текстовое сообщение с кнопкой партнера и случайной подсказкой."""
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
        bot.send_message(chat_id, f"{text}\n\n---\n<i>{random.choice(BOT_HINTS)}</i>", reply_markup=markup, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")

def send_photo_with_partner_button(chat_id, photo, caption, **kwargs):
    """Отправляет фото с подписью, кнопкой партнера и подсказкой."""
    try:
        if not photo: raise ValueError("Объект фото пустой")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
        bot.send_photo(chat_id, photo, caption=f"{caption}\n\n---\n<i>{random.choice(BOT_HINTS)}</i>", reply_markup=markup)
    except Exception as e:
        logger.error(f"Не удалось отправить фото: {e}. Отправляю текстом.")
        send_message_with_partner_button(chat_id, caption)

def calculate_and_format_profit(electricity_cost_rub: float):
    """Рассчитывает и форматирует профит для топ-5 ASIC."""
    rate = get_usd_rub_rate()
    if not rate: return "Не удалось получить курс доллара. Попробуйте позже."
    
    cost_usd = electricity_cost_rub / rate
    asics = get_top_asics()
    if not asics: return "Не удалось получить данные по ASIC для расчета."
    
    result = [f"💰 <b>Расчет профита (розетка {electricity_cost_rub:.2f} ₽/кВтч)</b>\n"]
    for asic in asics:
        cost = (asic['power_watts'] / 1000) * 24 * cost_usd
        profit = asic['daily_revenue'] - cost
        result.append(f"<b>{telebot.util.escape(asic['name'])}</b>\n  Профит: <b>${profit:.2f}/день</b> (Доход: ${asic['daily_revenue']:.2f}, Расход: ${cost:.2f})")
    return "\n\n".join(result)

def set_user_state(user_id, state, text):
    """Устанавливает временное состояние для пользователя и отправляет ему сообщение."""
    user_states[user_id] = state
    bot.send_message(user_id, text, reply_markup=types.ReplyKeyboardRemove())

# ========================================================================================
# 5. ОБРАБОТЧИКИ КОМАНД И ИГРОВАЯ ЛОГИКА
# ========================================================================================
# Эти функции теперь определены до их использования в словарях
def handle_start_help(msg):
    help_text = ("👋 Привет! Я ваш крипто-помощник.\n\n"
                 "<b>Основные команды:</b>\n"
                 "<code>/price</code>, <code>/gas</code>, <code>/news</code>\n\n"
                 "<b>Утилиты и игра:</b>\n"
                 "<code>/my_rig</code>, <code>/collect</code>, <code>/upgrade_rig</code>\n"
                 "<code>/shop</code>, <code>/top_miners</code>, <code>/quiz</code>, <code>/word</code>.")
    bot.send_message(msg.chat.id, help_text, reply_markup=get_main_keyboard())

def handle_price(msg):
    """Запрашивает у пользователя тикер криптовалюты."""
    set_user_state(msg.chat.id, 'price_request', "Курс какой криптовалюты вас интересует? (напр: BTC, ETH, SOL)")

def get_price_and_send(chat_id, ticker="BTC"):
    """Получает и отправляет цену криптовалюты."""
    price, source = get_crypto_price(ticker)
    if price:
        text = f"💹 Курс {ticker.upper()}/USD: <b>${price:,.2f}</b>\n<i>(Данные от {source})</i>"
        send_message_with_partner_button(chat_id, text)
    else:
        text = f"❌ Не удалось получить курс для {ticker.upper()}."
        bot.send_message(chat_id, text, reply_markup=get_main_keyboard())

def handle_asics_text(msg):
    bot.send_message(msg.chat.id, "⏳ Загружаю актуальный список...")
    asics = get_top_asics()
    if not asics:
        send_message_with_partner_button(msg.chat.id, "Не удалось получить данные об ASIC. Попробуйте позже.")
        return
    
    header = "Модель                | H/s      | P, W | Доход/день"
    divider = "----------------------|----------|------|-----------"
    rows = [f"{a['name']:<22.21}| {a['hashrate']:<9}| {a['power_watts']:<5.0f}| ${a['daily_revenue']:<10.2f}" for a in asics]
    response_text = f"<pre>{header}\n{divider}\n" + "\n".join(rows) + "</pre>"
    
    gpt_prompt = "Вот список доходных ASIC. Напиши короткий мотивирующий комментарий (1-2 предложения) для майнинг-чата. Подтолкни к мысли об обновлении."
    response_text += f"\n\n{ask_gpt(gpt_prompt, 'gpt-4o')}"
    send_message_with_partner_button(msg.chat.id, response_text)

def handle_calculator(msg):
    set_user_state(msg.chat.id, 'calculator_request', "💡 Введите стоимость электроэнергии в <b>рублях</b> за кВт/ч:")

def handle_news(msg):
    bot.send_chat_action(msg.chat.id, 'typing')
    send_message_with_partner_button(msg.chat.id, get_crypto_news())

def handle_fear_and_greed(msg):
    bot.send_message(msg.chat.id, "⏳ Генерирую график индекса...")
    image, text = get_fear_and_greed_index()
    if image:
        send_photo_with_partner_button(msg.chat.id, image, text)
    else:
        send_message_with_partner_button(msg.chat.id, text)

def handle_halving(msg):
    send_message_with_partner_button(msg.chat.id, get_halving_info())

def handle_my_rig(msg):
    user_id = msg.from_user.id
    response = ""
    if user_id not in user_rigs:
        user_rigs[user_id] = {'last_collected': None, 'balance': 0.0, 'level': 1, 'streak': 0, 'name': msg.from_user.first_name, 'boost_active_until': None}
        response = "🎉 Поздравляю! Вы запустили свою первую виртуальную ферму!\n\n"
    
    rig = user_rigs[user_id]
    next_level = rig['level'] + 1
    upgrade_cost_text = f"Стоимость улучшения до {next_level} уровня: <code>{UPGRADE_COSTS.get(next_level, 'N/A')}</code> BTC." if next_level in UPGRADE_COSTS else "Вы достигли максимального уровня!"
    
    boost_status = ""
    if rig.get('boost_active_until') and datetime.now() < rig['boost_active_until']:
        time_left = rig['boost_active_until'] - datetime.now()
        h, rem = divmod(time_left.seconds, 3600)
        m, _ = divmod(rem, 60)
        boost_status = f"⚡️ <b>Буст x2 активен еще: {h}ч {m}м</b>\n"

    response += (f"🖥️ <b>Ферма {telebot.util.escape(rig['name'])}</b>\n\n"
                 f"<b>Уровень:</b> {rig['level']}\n"
                 f"<b>Баланс:</b> <code>{rig['balance']:.8f}</code> BTC\n"
                 f"<b>Дневная серия:</b> {rig['streak']} 🔥 (бонус <b>+{rig['streak'] * STREAK_BONUS_MULTIPLIER:.0%}</b>)\n"
                 f"{boost_status}\n"
                 f"{upgrade_cost_text}\n\n"
                 "<code>/collect</code>, <code>/upgrade_rig</code>, <code>/shop</code>")
    send_message_with_partner_button(msg.chat.id, response)
    save_user_data()

def handle_collect(msg):
    user_id = msg.from_user.id
    if user_id not in user_rigs: return send_message_with_partner_button(msg.chat.id, "🤔 У вас нет фермы. Начните с <code>/my_rig</code>.")
    
    rig = user_rigs[user_id]
    now = datetime.now()
    if rig.get('last_collected') and (now - rig['last_collected']) < timedelta(hours=24):
        time_left = timedelta(hours=24) - (now - rig['last_collected'])
        h, m = divmod(time_left.seconds, 3600)[0], divmod(time_left.seconds % 3600, 60)[0]
        return send_message_with_partner_button(msg.chat.id, f"Вы уже собирали награду. Попробуйте снова через <b>{h}ч {m}м</b>.")
    
    if rig.get('last_collected') and (now - rig['last_collected']) < timedelta(hours=48):
        rig['streak'] += 1
    else: rig['streak'] = 1
    
    base_mined = MINING_RATES.get(rig['level'], 0.0001)
    streak_bonus = base_mined * rig['streak'] * STREAK_BONUS_MULTIPLIER
    boost_multiplier = 2 if rig.get('boost_active_until') and now < rig['boost_active_until'] else 1
    total_mined = (base_mined + streak_bonus) * boost_multiplier
    
    rig['balance'] += total_mined
    rig['last_collected'] = now
    
    boost_text = " (x2 Буст!)" if boost_multiplier > 1 else ""
    response = (f"✅ Собрано <b>{total_mined:.8f}</b> BTC{boost_text}!\n"
                f"  (База: {base_mined:.8f} + Бонус за серию: {streak_bonus:.8f})\n"
                f"🔥 Ваша серия: <b>{rig['streak']} дней!</b>\n"
                f"💰 Ваш новый баланс: <code>{rig['balance']:.8f}</code> BTC.")
    send_message_with_partner_button(msg.chat.id, response)
    save_user_data()

def handle_upgrade_rig(msg):
    user_id = msg.from_user.id
    if user_id not in user_rigs: return send_message_with_partner_button(msg.chat.id, "🤔 У вас нет фермы. Начните с <code>/my_rig</code>.")
    
    rig = user_rigs[user_id]
    next_level, cost = rig['level'] + 1, UPGRADE_COSTS.get(rig['level'] + 1)
    
    if not cost: return send_message_with_partner_button(msg.chat.id, "🎉 Поздравляем, у вас максимальный уровень фермы!")
    
    if rig['balance'] >= cost:
        rig['balance'] -= cost
        rig['level'] = next_level
        response = f"🚀 <b>Улучшение завершено!</b>\n\nВаша ферма достигла <b>{next_level}</b> уровня!"
        save_user_data()
    else:
        response = f"❌ <b>Недостаточно средств.</b>\n\nДля улучшения до {next_level} уровня требуется <code>{cost}</code> BTC."
    send_message_with_partner_button(msg.chat.id, response)

def handle_top_miners(msg):
    if not user_rigs: return send_message_with_partner_button(msg.chat.id, "Пока нет ни одного майнера для составления топа.")
    
    sorted_rigs = sorted(user_rigs.values(), key=lambda r: r['balance'], reverse=True)
    response = ["🏆 <b>Топ-5 Виртуальных Майнеров:</b>\n"]
    for i, rig in enumerate(sorted_rigs[:5]):
        response.append(f"<b>{i+1}.</b> {telebot.util.escape(rig['name'])} - <code>{rig['balance']:.6f}</code> BTC (Ур. {rig['level']})")
    send_message_with_partner_button(msg.chat.id, "\n".join(response))

def handle_shop(msg):
    text = (f"🛍️ <b>Магазин улучшений</b>\n\n"
            f"<b>1. Энергетический буст (x2)</b>\n"
            f"<i>Удваивает всю вашу добычу на 24 часа.</i>\n"
            f"<b>Стоимость:</b> <code>{BOOST_COST}</code> BTC\n\n"
            f"Для покупки используйте команду <code>/buy_boost</code>")
    send_message_with_partner_button(msg.chat.id, text)

def handle_buy_boost(msg):
    user_id = msg.from_user.id
    if user_id not in user_rigs: return send_message_with_partner_button(msg.chat.id, "� У вас нет фермы. Начните с <code>/my_rig</code>.")
    
    rig = user_rigs[user_id]
    if rig.get('boost_active_until') and datetime.now() < rig['boost_active_until']:
        return send_message_with_partner_button(msg.chat.id, "У вас уже активен буст!")
        
    if rig['balance'] >= BOOST_COST:
        rig['balance'] -= BOOST_COST
        rig['boost_active_until'] = datetime.now() + timedelta(hours=BOOST_DURATION_HOURS)
        response = f"⚡️ <b>Энергетический буст куплен!</b>\n\nВаша добыча будет удвоена в течение следующих 24 часов."
        save_user_data()
    else: response = f"❌ <b>Недостаточно средств.</b>"
    send_message_with_partner_button(msg.chat.id, response)

def handle_word_of_the_day(msg):
    term = random.choice(CRYPTO_TERMS)
    prompt = f"Объясни термин '{term}' простыми словами для новичка в криптовалютах (2-3 предложения)."
    explanation = ask_gpt(prompt, "gpt-3.5-turbo")
    text = f"🎓 <b>Слово дня: {term}</b>\n\n{explanation}"
    send_message_with_partner_button(msg.chat.id, text)

def handle_quiz(msg):
    user_id = msg.from_user.id
    bot.send_message(msg.chat.id, "⏳ Ищу интересные вопросы для викторины...")
    questions = get_new_quiz_questions()
    
    if not questions:
        bot.send_message(msg.chat.id, "Не удалось загрузить вопросы для викторины. Попробуйте позже.", reply_markup=get_main_keyboard())
        return

    user_states[user_id] = {'quiz_active': True, 'score': 0, 'question_index': 0, 'questions': questions}
    bot.send_message(msg.chat.id, f"🔥 <b>Начинаем крипто-викторину!</b>\nОтветьте на {len(questions)} вопросов.", reply_markup=types.ReplyKeyboardRemove())
    send_quiz_question(msg.chat.id, user_id)

def send_quiz_question(chat_id, user_id):
    state = user_states.get(user_id)
    if not state or not state.get('quiz_active'): return
    
    q_index, questions = state['question_index'], state['questions']
    
    if q_index >= len(questions):
        score = state['score']
        reward_text = ""
        if score >= QUIZ_MIN_CORRECT_FOR_REWARD:
            if user_id in user_rigs:
                user_rigs[user_id]['balance'] += QUIZ_REWARD
                reward_text = f"\n\n🎁 За отличный результат вам начислено <b>{QUIZ_REWARD:.4f} BTC!</b>"
                save_user_data()
            else:
                reward_text = f"\n\n🎁 Вы бы получили <b>{QUIZ_REWARD:.4f} BTC</b>, если бы у вас была ферма! Начните с <code>/my_rig</code>."
        
        bot.send_message(chat_id, f"🎉 <b>Викторина завершена!</b>\nВаш результат: <b>{score} из {len(questions)}</b>.{reward_text}", reply_markup=get_main_keyboard())
        user_states.pop(user_id, None)
        return
        
    question_data = questions[q_index]
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(option, callback_data=f"quiz_{q_index}_{i}") for i, option in enumerate(question_data['options'])]
    markup.add(*buttons)
    bot.send_message(chat_id, f"<b>Вопрос {q_index + 1}:</b>\n{question_data['question']}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('quiz_'))
def handle_quiz_answer(call):
    user_id = call.from_user.id
    state = user_states.get(user_id)
    if not state or not state.get('quiz_active'):
        bot.answer_callback_query(call.id, "Викторина уже не активна.")
        bot.edit_message_text("Викторина завершена.", call.message.chat.id, call.message.message_id)
        return

    try:
        _, q_index_str, answer_index_str = call.data.split('_')
        q_index, answer_index = int(q_index_str), int(answer_index_str)
    except ValueError:
        logger.error(f"Некорректные данные в callback викторины: {call.data}")
        return bot.answer_callback_query(call.id, "Ошибка в данных викторины.")

    if q_index != state.get('question_index'):
        return bot.answer_callback_query(call.id, "Вы уже ответили на этот вопрос.")
    
    question_data = state['questions'][q_index]
    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
    
    if answer_index == question_data['correct_index']:
        state['score'] += 1
        bot.send_message(call.message.chat.id, "✅ Правильно!")
    else:
        correct_answer_text = question_data['options'][question_data['correct_index']]
        bot.send_message(call.message.chat.id, f"❌ Неверно. Правильный ответ: <b>{correct_answer_text}</b>")
    
    state['question_index'] += 1
    time.sleep(1.5) # Даем пользователю время прочитать результат
    send_quiz_question(call.message.chat.id, user_id)
    bot.answer_callback_query(call.id)


# ========================================================================================
# 6. ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ
# ========================================================================================
@bot.message_handler(content_types=['text'])
def handle_text_messages(msg):
    try:
        user_id = msg.from_user.id
        text_lower = msg.text.lower().strip()
        current_state = user_states.get(user_id)

        # 1. Обработка состояний (когда бот ждет ввод от пользователя)
        if current_state:
            state_action = None
            if current_state == 'price_request':
                state_action = lambda: get_price_and_send(user_id, msg.text)
            elif current_state == 'calculator_request':
                try:
                    cost = float(msg.text.replace(',', '.'))
                    state_action = lambda: send_message_with_partner_button(user_id, calculate_and_format_profit(cost))
                except ValueError:
                    bot.send_message(user_id, "❌ Неверный формат. Пожалуйста, введите число (например: 4.5 или 5).", reply_markup=get_main_keyboard())
            
            if state_action:
                user_states.pop(user_id, None) # Сбрасываем состояние
                state_action()
                return

        # 2. Обработка команд (/start, /help, etc.)
        command_map = {
            "/start": handle_start_help, "/help": handle_start_help, "/price": handle_price,
            "/fear": handle_fear_and_greed, "/fng": handle_fear_and_greed,
            "/gas": lambda m: send_message_with_partner_button(m.chat.id, get_eth_gas_price()),
            "/my_rig": handle_my_rig, "/collect": handle_collect, "/upgrade_rig": handle_upgrade_rig,
            "/top_miners": handle_top_miners, "/shop": handle_shop, "/buy_boost": handle_buy_boost,
            "/word": handle_word_of_the_day, "/quiz": handle_quiz
        }
        text_command = msg.text.split()[0].lower()
        if text_command in command_map:
            command_map[text_command](msg)
            return

        # 3. Обработка кнопок с клавиатуры
        button_map = {
            "💹 курс": handle_price,
            "⚙️ топ-5 asic": handle_asics_text,
            "⛏️ калькулятор": handle_calculator,
            "📰 новости": handle_news,
            "😱 индекс страха": handle_fear_and_greed,
            "⏳ халвинг": handle_halving,
            "🧠 викторина": handle_quiz,
            "🎓 слово дня": handle_word_of_the_day,
            "🏆 топ майнеров": handle_top_miners,
            "🛍️ магазин": handle_shop,
        }
        if text_lower in button_map:
            button_map[text_lower](msg)
            return

        # 4. Анализ текста на ключевые слова (покупка/продажа)
        sale_words = ["продам", "купить", "в наличии"]
        item_words = ["asic", "асик", "whatsminer", "antminer"]
        if any(w in text_lower for w in sale_words) and any(w in text_lower for w in item_words):
            log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or "N/A", msg.text])
            prompt = f"Пользователь прислал объявление в майнинг-чат. Кратко и неформально прокомментируй его, поддержи диалог. Текст: '{msg.text}'"
            response = ask_gpt(prompt)
        else:
            # 5. Если ничего не подошло - отправляем запрос в GPT
            bot.send_chat_action(user_id, 'typing')
            response = ask_gpt(msg.text)
        
        send_message_with_partner_button(user_id, response)

    except Exception as e:
        logger.error("Критическая ошибка в handle_text_messages!", exc_info=e)
        bot.send_message(msg.chat.id, "😵 Ой, что-то пошло не так. Мы уже разбираемся!")


# ========================================================================================
# 7. ЗАПУСК БОТА И ПЛАНИРОВЩИКА
# ========================================================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    """Обрабатывает входящие обновления от Telegram."""
    try:
        if request.headers.get('content-type') == 'application/json':
            bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
            return '', 200
        return 'Forbidden', 403
    except Exception as e:
        logger.error("Критическая ошибка в вебхуке!", exc_info=e)
        return "Error", 500

@app.route("/")
def index():
    """Простая страница, чтобы показать, что бот запущен."""
    return "Bot is running!"

def run_scheduler():
    """Запускает фоновые задачи по расписанию."""
    if WEBHOOK_URL:
        # Пингуем вебхук, чтобы он не "засыпал" на бесплатных хостингах
        schedule.every(25).minutes.do(lambda: requests.get(WEBHOOK_URL.rsplit('/', 1)[0]))
    
    schedule.every(4).hours.do(auto_send_news)
    schedule.every(6).hours.do(auto_check_status)
    schedule.every(1).hours.do(get_top_asics, force_update=True)
    schedule.every(5).minutes.do(save_user_data) # Периодическое сохранение данных
    
    logger.info("Планировщик запущен, первоначальный запуск задач...")
    get_top_asics(force_update=True)
    auto_check_status()
    
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}", exc_info=True)
        time.sleep(1)

def auto_send_news():
    """Автоматическая отправка новостей в указанный чат."""
    if NEWS_CHAT_ID:
        logger.info("Отправка новостей по расписанию...")
        send_message_with_partner_button(NEWS_CHAT_ID, get_crypto_news())

def auto_check_status():
    """Проверка состояния систем и отправка отчета администратору."""
    if not ADMIN_CHAT_ID: return
    
    logger.info("Проверка состояния систем...")
    errors = []
    if get_crypto_price("BTC")[0] is None: errors.append("API цены")
    if "[❌" in ask_gpt("Тест"): errors.append("API OpenAI")
    if not get_gsheet(): errors.append("Google Sheets")
        
    ts = datetime.now().strftime("%H:%M")
    status = "✅ Все системы в норме." if not errors else f"⚠️ Сбой в: {', '.join(errors)}"
    try:
        bot.send_message(ADMIN_CHAT_ID, f"<b>Отчет о состоянии ({ts})</b>\n{status}")
    except Exception as e:
        logger.error(f"Не удалось отправить отчет о состоянии администратору: {e}")

if __name__ == '__main__':
    logger.info("Запуск бота...")
    load_user_data() # Загружаем данные пользователей при старте
    
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
        bot.polling(none_stop=True)
