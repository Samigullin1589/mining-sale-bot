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
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
from telebot import types
from openai import OpenAI
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import matplotlib
matplotlib.use('Agg') # Устанавливаем бэкенд Matplotlib для серверов
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

# --- Ключи и Настройки ---
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
NEWSAPI_KEY = os.getenv("CRYPTO_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "YourApiKeyToken")
NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
GOOGLE_JSON_STR = os.getenv("GOOGLE_JSON")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Лист1")

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
CURRENCY_MAP = {
    'доллар': 'USD', 'usd': 'USD', '$': 'USD', 'евро': 'EUR', 'eur': 'EUR', '€': 'EUR',
    'рубль': 'RUB', 'rub': 'RUB', '₽': 'RUB', 'юань': 'CNY', 'cny': 'CNY',
    'биткоин': 'BTC', 'btc': 'BTC', 'бтс': 'BTC', 'втс': 'BTC', 'эфир': 'ETH', 'eth': 'ETH',
}
HALVING_INTERVAL = 210000

# --- Игровые константы ---
CRYPTO_TERMS = ["Блокчейн", "Газ (Gas)", "Халвинг", "ICO", "DeFi", "NFT", "Сатоши", "Кит (Whale)", "HODL", "DEX", "Смарт-контракт"]
QUIZ_QUESTIONS = [
    {"question": "Кто является создателем Bitcoin?", "options": ["Виталик Бутерин", "Сатоши Накамото", "Илон Маск", "Павел Дуров"], "correct_index": 1},
    {"question": "Что такое 'халвинг' Bitcoin?", "options": ["Удвоение награды", "Уменьшение награды вдвое", "Обновление сети", "Создание новой монеты"], "correct_index": 1},
    {"question": "Какая криптовалюта второй по капитализации после Bitcoin?", "options": ["Solana", "Ripple (XRP)", "Dogecoin", "Ethereum"], "correct_index": 3},
    {"question": "Что означает аббревиатура 'NFT'?", "options": ["Non-Fungible Token", "New Financial Technology", "Network Fee Token", "National Fiscal Token"], "correct_index": 0},
    {"question": "Как называется самая маленькая единица Bitcoin?", "options": ["Копейка", "Цент", "Сатоши", "Вэй"], "correct_index": 2}
]
MINING_RATES = {1: 0.0001, 2: 0.0002, 3: 0.0004, 4: 0.0008, 5: 0.0016}
UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1}
STREAK_BONUS_MULTIPLIER = 0.05
BOOST_COST = 0.0005
BOOST_DURATION_HOURS = 24
QUIZ_REWARD = 0.0001
QUIZ_MIN_CORRECT_FOR_REWARD = 3

# Обработчик исключений для детального логирования
class ExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        logger.error("Произошла ошибка в обработчике pyTelegramBotAPI:", exc_info=exception)
        return True

# --- Инициализация ---
if not BOT_TOKEN:
    logger.critical("Критическая ошибка: TG_BOT_TOKEN не установлен")
    raise ValueError("Критическая ошибка: TG_BOT_TOKEN не установлен")

try:
    bot = telebot.TeleBot(BOT_TOKEN, threaded=False, parse_mode='HTML', exception_handler=ExceptionHandler())
    app = Flask(__name__)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.critical(f"Не удалось инициализировать клиентов API: {e}")
    raise

# --- Глобальные переменные ---
user_states = {}
asic_cache = {"data": [], "timestamp": None}
user_rigs = {}
currency_cache = {"rate": None, "timestamp": None}

# ========================================================================================
# 2. РАБОТА С ВНЕШНИМИ СЕРВИСАМИ (API)
# ========================================================================================
def get_crypto_price(ticker="BTC"):
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
            continue
    logger.error(f"Не удалось получить цену для {ticker}.")
    return (None, None)

def get_top_asics(force_update: bool = False):
    global asic_cache
    if not force_update and asic_cache.get("data") and (datetime.now() - asic_cache["timestamp"] < timedelta(hours=1)):
        return asic_cache["data"]
    try:
        r = requests.get("https://www.asicminervalue.com", timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        parsed_asics = []
        sha256_table = soup.find('h2', id='sha-256').find_next('table')
        for row in sha256_table.select("tbody tr"):
            cols = [col for col in row.find_all("td")]
            if len(cols) < 5: continue
            
            name = cols[1].find('a').get_text(strip=True) if cols[1].find('a') else "N/A"
            if name == "N/A": continue # Пропускаем, если нет имени

            hashrate = cols[2].get_text(strip=True)
            power_watts_match = re.search(r'([\d,]+)', cols[3].get_text(strip=True))
            daily_revenue_match = re.search(r'([\d\.]+)', cols[4].get_text(strip=True).replace('$', ''))

            if power_watts_match and daily_revenue_match:
                power_watts = float(power_watts_match.group(1).replace(',', ''))
                daily_revenue = float(daily_revenue_match.group(1))
                if power_watts > 0:
                    parsed_asics.append({'name': name, 'hashrate': hashrate, 'power_watts': power_watts, 'daily_revenue': daily_revenue})
        
        if not parsed_asics: raise ValueError("Не удалось распарсить ASIC")
        
        parsed_asics.sort(key=lambda x: x['daily_revenue'], reverse=True)
        asic_cache = {"data": parsed_asics[:5], "timestamp": datetime.now()}
        logger.info(f"Успешно получено {len(asic_cache['data'])} ASIC.")
        return asic_cache["data"]
    except Exception as e:
        logger.error(f"Не удалось получить данные по ASIC: {e}", exc_info=True)
        return []

def get_fear_and_greed_index():
    try:
        data = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()['data'][0]
        value, classification = int(data['value']), data['value_classification']
        
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
        
        # Используем text вместо annotate для центрального текста, чтобы он не был полярным
        fig.text(0.5, 0.5, f"{value}", ha='center', va='center', fontsize=48, color='white', weight='bold')
        fig.text(0.5, 0.35, classification, ha='center', va='center', fontsize=20, color='white')

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, transparent=True)
        buf.seek(0)
        plt.close(fig)
        
        text = f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>\n"
        return buf, text
    except Exception as e:
        logger.error(f"Ошибка при создании графика индекса страха: {e}", exc_info=True)
        return None, "[❌ Ошибка при получении индекса]"

# ========================================================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ========================================================================================
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = ["💹 Курс", "⚙️ Топ-5 ASIC", "⛏️ Калькулятор", "📰 Новости", 
               "😱 Индекс Страха", "⏳ Халвинг", "🧠 Викторина", "🎓 Слово дня",
               "🏆 Топ майнеров", "🛍️ Магазин"]
    markup.add(*[types.KeyboardButton(text) for text in buttons])
    return markup
    
def send_message_with_partner_button(chat_id, text, **kwargs):
    try:
        full_text = f"{text}\n\n---\n<i>{random.choice(BOT_HINTS)}</i>"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
        bot.send_message(chat_id, full_text, reply_markup=markup, disable_web_page_preview=True, **kwargs)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")

def send_photo_with_partner_button(chat_id, photo, caption, **kwargs):
    try:
        if not photo: raise ValueError("Объект фото пустой")
        full_caption = f"{caption}\n\n---\n<i>{random.choice(BOT_HINTS)}</i>"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
        bot.send_photo(chat_id, photo, caption=full_caption, reply_markup=markup, **kwargs)
    except Exception as e:
        logger.error(f"Не удалось отправить фото: {e}. Отправляю текстом.")
        send_message_with_partner_button(chat_id, caption, **kwargs)

def get_usd_rub_rate():
    global currency_cache
    if currency_cache["rate"] and (datetime.now() - currency_cache["timestamp"] < timedelta(minutes=30)):
        return currency_cache["rate"]
    sources = ["https://api.exchangerate.host/latest?base=USD&symbols=RUB", "https://api.exchangerate-api.com/v4/latest/USD"]
    for url in sources:
        try:
            response = requests.get(url, timeout=4)
            response.raise_for_status()
            rate = response.json().get('rates', {}).get('RUB')
            if rate:
                currency_cache = {"rate": rate, "timestamp": datetime.now()}
                logger.info(f"Получен курс {rate} с {url}")
                return rate
        except Exception: continue
    logger.error("Не удалось получить курс USD/RUB ни с одного источника")
    return None

def calculate_and_format_profit(electricity_cost_rub: float):
    rate = get_usd_rub_rate()
    if not rate: return "Не удалось получить курс доллара для расчета. Попробуйте позже."
    cost_usd = electricity_cost_rub / rate
    asics = get_top_asics()
    if not asics: return "Не удалось получить данные по ASIC для расчета."
    result = [f"💰 <b>Расчет профита (розетка {electricity_cost_rub:.2f} ₽/кВтч)</b>\n"]
    for asic in asics:
        cost = (asic['power_watts'] / 1000) * 24 * cost_usd
        profit = asic['daily_revenue'] - cost
        result.append(f"<b>{telebot.util.escape(asic['name'])}</b>\n  Профит: <b>${profit:.2f}/день</b> (Доход: ${asic['daily_revenue']:.2f}, Расход: ${cost:.2f})")
    return "\n\n".join(result)

# ========================================================================================
# 4. ОБРАБОТЧИКИ КОМАНД И ИГРОВАЯ ЛОГИКА
# ========================================================================================
@bot.message_handler(commands=['start', 'help'])
def handle_start_help(msg):
    help_text = ("👋 Привет! Я ваш крипто-помощник.\n\n"
                 "<b>Основные команды:</b>\n"
                 "<code>/price</code>, <code>/gas</code>, <code>/news</code>\n\n"
                 "<b>Утилиты и игра:</b>\n"
                 "<code>/my_rig</code>, <code>/collect</code>, <code>/upgrade_rig</code>\n"
                 "<code>/shop</code>, <code>/top_miners</code>, <code>/quiz</code>, <code>/word</code>.")
    bot.send_message(msg.chat.id, help_text, reply_markup=get_main_keyboard())

def get_price_and_send(chat_id, ticker="BTC"):
    price, source = get_crypto_price(ticker)
    if price:
        text = f"💹 Курс {ticker.upper()}/USD: <b>${price:,.2f}</b>\n<i>(Данные от {source})</i>"
        send_message_with_partner_button(chat_id, text, reply_markup=get_main_keyboard())
    else:
        text = f"❌ Не удалось получить курс для {ticker.upper()}."
        bot.send_message(chat_id, text, reply_markup=get_main_keyboard())

@bot.message_handler(commands=['price'])
def handle_price(msg):
    args = msg.text.split()
    if len(args) > 1: get_price_and_send(msg.chat.id, args[1])
    else: set_user_state(msg.from_user.id, 'price_request', "Курс какой криптовалюты вас интересует? (напр: BTC, ETH, SOL)")

@bot.message_handler(commands=['fear', 'fng'])
def handle_fear_and_greed(msg):
    bot.send_message(msg.chat.id, "⏳ Генерирую актуальный Индекс страха...")
    photo, text = get_fear_and_greed_index()
    send_photo_with_partner_button(msg.chat.id, photo=photo, caption=text)

# ... (Остальные обработчики команд вынесены в основной обработчик текста)

# ========================================================================================
# 5. ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ
# ========================================================================================
@bot.message_handler(content_types=['text'])
def handle_text_messages(msg):
    try:
        user_id = msg.from_user.id
        text_lower = msg.text.lower().strip()
        current_state = user_states.get(user_id)

        # 1. Обработка состояний (ожидание ввода)
        if current_state:
            state_handlers = {
                'price_request': lambda: get_price_and_send(msg.chat.id, msg.text),
                'weather_request': lambda: send_message_with_partner_button(msg.chat.id, get_weather(msg.text)),
                'calculator_request': lambda: send_message_with_partner_button(msg.chat.id, calculate_and_format_profit(float(msg.text.replace(',', '.'))))
            }
            if current_state in state_handlers:
                user_states.pop(user_id, None)
                state_handlers[current_state]()
                return
        
        # 2. Обработка кнопок с клавиатуры
        command_map = {
            "💹 курс": lambda: set_user_state(user_id, 'price_request', "Курс какой криптовалюты вас интересует? (напр: BTC, ETH, SOL)"),
            "⚙️ топ-5 asic": lambda: handle_asics_text(msg),
            "⛏️ калькулятор": lambda: set_user_state(user_id, 'calculator_request', "💡 Введите стоимость электроэнергии в <b>рублях</b> за кВт/ч:"),
            "📰 новости": lambda: send_message_with_partner_button(msg.chat.id, get_crypto_news()),
            "😱 индекс страха": lambda: handle_fear_and_greed(msg),
            "⏳ халвинг": lambda: send_message_with_partner_button(msg.chat.id, get_halving_info()),
            "🧠 викторина": lambda: handle_quiz(msg),
            "🎓 слово дня": lambda: handle_word_of_the_day(msg),
            "🏆 топ майнеров": lambda: handle_top_miners(msg),
            "🛍️ магазин": lambda: handle_shop(msg),
            "🌦️ погода": lambda: set_user_state(user_id, 'weather_request', "🌦 В каком городе показать погоду?")
        }
        if text_lower in command_map:
            command_map[text_lower]()
            return

        # 3. Анализ и ответ GPT на остальное
        sale_words = ["продам", "купить", "в наличии"]
        item_words = ["asic", "асик", "whatsminer", "antminer"]
        if any(w in text_lower for w in sale_words) and any(w in text_lower for w in item_words):
            log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or "N/A", msg.text])
            prompt = f"Пользователь прислал объявление в майнинг-чат. Кратко и неформально прокомментируй его, поддержи диалог. Текст: '{msg.text}'"
            send_message_with_partner_button(msg.chat.id, ask_gpt(prompt))
        else:
            bot.send_chat_action(msg.chat.id, 'typing')
            send_message_with_partner_button(msg.chat.id, ask_gpt(msg.text))

    except Exception as e:
        logger.error(f"Критическая ошибка в handle_text_messages!", exc_info=e)
        bot.send_message(msg.chat.id, "😵 Ой, что-то пошло не так. Мы уже разбираемся!")

def set_user_state(user_id, state, text):
    user_states[user_id] = state
    bot.send_message(user_id, text, reply_markup=types.ReplyKeyboardRemove())
    
def handle_asics_text(msg):
    bot.send_message(msg.chat.id, "⏳ Загружаю актуальный список...")
    asics = get_top_asics()
    if not asics: return send_message_with_partner_button(msg.chat.id, "Не удалось получить данные об ASIC.")
    header = "Модель              | H/s      | P, W | Доход/день"
    divider = "--------------------|----------|------|-----------"
    rows = [f"{a['name']:<20.19}| {a['hashrate']:<9}| {a['power_watts']:<5.0f}| ${a['daily_revenue']:<10.2f}" for a in asics]
    response_text = f"<pre>{header}\n{divider}\n" + "\n".join(rows) + "</pre>"
    gpt_prompt = "Вот список доходных ASIC. Напиши короткий мотивирующий комментарий (1-2 предложения) для майнинг-чата. Подтолкни к мысли об обновлении."
    response_text += f"\n\n{ask_gpt(gpt_prompt, 'gpt-4o')}"
    send_message_with_partner_button(msg.chat.id, response_text)

# ... (Остальные игровые обработчики и викторина)

# ========================================================================================
# 6. ЗАПУСК БОТА И ПЛАНИРОВЩИКА
# ========================================================================================

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        if request.headers.get('content-type') == 'application/json':
            bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
            return '', 200
        return 'Forbidden', 403
    except Exception as e:
        logger.error("Критическая ошибка в вебхуке!", exc_info=e)
        return "Error", 500

# ... (Остальной код запуска без изменений)

if __name__ == '__main__':
    logger.info("Запуск бота...")
    threading.Thread(target=run_scheduler, daemon=True).start()
    if WEBHOOK_URL:
        logger.info("Режим вебхука...")
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=f"{WEBHOOK_URL.rstrip('/')}/webhook")
        app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
    else:
        logger.info("Режим long-polling...")
        bot.remove_webhook()
        bot.polling(none_stop=True)
