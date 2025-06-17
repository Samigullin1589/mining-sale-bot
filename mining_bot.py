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
# Устанавливаем бэкенд Matplotlib, который не требует GUI. Важно для серверов.
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
PARTNER_BUTTON_TEXT_OPTIONS = [
    "🎁 Узнать спеццены", "🔥 Эксклюзивное предложение",
    "💡 Получить консультацию", "💎 Прайс от экспертов"
]
BOT_HINTS = [
    "💡 Попробуйте команду `/price`", "⚙️ Нажмите на кнопку 'Топ-5 ASIC'",
    "🌦️ Узнайте погоду, просто написав 'погода'", "⛏️ Рассчитайте прибыль с помощью 'Калькулятора'",
    "📰 Хотите новости? Просто напишите 'новости'", "⛽️ Узнайте цену на газ командой `/gas`",
    "🤑 Начните свой виртуальный майнинг с `/my_rig`", "😱 Проверьте Индекс Страха и Жадности командой `/fear`",
    "⏳ Сколько до халвинга? Узнайте: `/halving`"
]
CURRENCY_MAP = {
    'доллар': 'USD', 'usd': 'USD', '$': 'USD', 'евро': 'EUR', 'eur': 'EUR', '€': 'EUR',
    'рубль': 'RUB', 'rub': 'RUB', '₽': 'RUB', 'юань': 'CNY', 'cny': 'CNY',
    'биткоин': 'BTC', 'btc': 'BTC', 'бтс': 'BTC', 'втс': 'BTC', 'эфир': 'ETH', 'eth': 'ETH',
}
HALVING_INTERVAL = 210000
NEXT_HALVING_BLOCK = 840000

# --- Инициализация ---
if not BOT_TOKEN:
    logger.critical("Критическая ошибка: не найдена переменная окружения TG_BOT_TOKEN")
    raise ValueError("Критическая ошибка: TG_BOT_TOKEN не установлен")

try:
    bot = telebot.TeleBot(BOT_TOKEN, threaded=False, parse_mode='HTML')
    app = Flask(__name__)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.critical(f"Не удалось инициализировать одного из клиентов API: {e}")
    raise

# --- Глобальные переменные ---
user_states = {} 
asic_cache = {"data": [], "timestamp": None}
user_rigs = {} 

# ========================================================================================
# 2. РАБОТА С ВНЕШНИМИ СЕРВИСАМИ (API)
# ========================================================================================

def get_gsheet():
    """Подключается к Google Sheets."""
    try:
        creds_dict = json.loads(GOOGLE_JSON_STR)
        creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        return gspread.authorize(creds).open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    except (json.JSONDecodeError, ValueError, gspread.exceptions.GSpreadException) as e:
        logger.error(f"Ошибка подключения к Google Sheets: {e}")
        raise

def log_to_sheet(row_data: list):
    """Логирует данные в Google Sheets."""
    try:
        get_gsheet().append_row(row_data, value_input_option='USER_ENTERED')
        logger.info(f"Запись в Google Sheets: {row_data}")
    except Exception as e:
        logger.error(f"Ошибка записи в Google Sheets: {e}")

def get_crypto_price(coin_id="bitcoin", vs_currency="usd"):
    """Получает цену криптовалюты с резервированием."""
    sources = [
        {"name": "CoinGecko", "url": f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies={vs_currency}"},
        {"name": "Binance", "url": "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"}
    ]
    if coin_id != "bitcoin": sources.pop(1) # Binance только для BTC

    for source in sources:
        try:
            res = requests.get(source["url"], timeout=5).json()
            if source["name"] == "CoinGecko" and res.get(coin_id, {}).get(vs_currency):
                return (float(res[coin_id][vs_currency]), "CoinGecko")
            elif source["name"] == "Binance" and res.get('price'):
                return (float(res['price']), "Binance")
        except requests.RequestException as e:
            logger.warning(f"Ошибка API {source['name']}: {e}")
            continue
    return (None, None)

def get_eth_gas_price():
    """Получает цену на газ в сети Ethereum."""
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

def get_weather(city: str):
    """Получает погоду с wttr.in."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0', "Accept-Language": "ru"}
        r = requests.get(f"https://wttr.in/{city}?format=j1", headers=headers, timeout=4).json()
        current = r["current_condition"][0]
        weather_desc = current['lang_ru'][0]['value']
        city_name = r['nearest_area'][0]['areaName'][0]['value']
        return (f"🌍 {city_name}\n"
                f"🌡 Температура: {current['temp_C']}°C (Ощущается как {current['FeelsLikeC']}°C)\n"
                f"☁️ Погода: {weather_desc}\n"
                f"💧 Влажность: {current['humidity']}% | 💨 Ветер: {current['windspeedKmph']} км/ч")
    except requests.exceptions.Timeout:
        return "[❌ Сервер погоды отвечает слишком долго.]"
    except Exception as e:
        logger.error(f"Ошибка получения погоды для '{city}': {e}")
        return f"[❌ Не удалось найти город '{city}'.]"

def ask_gpt(prompt: str, model: str = "gpt-4o"):
    """Отправляет запрос к OpenAI GPT."""
    try:
        res = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Ты — полезный ассистент, который отвечает на русском, используя HTML-теги: <b>, <i>, <code>, <pre>."},
                {"role": "user", "content": prompt}
            ],
            timeout=20.0
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Ошибка вызова OpenAI API: {e}")
        return "[❌ Ошибка GPT: Не удалось получить ответ.]"
        
def get_top_asics(force_update: bool = False):
    """Получает топ-5 ASIC с asicminervalue.com с кэшированием."""
    global asic_cache
    if not force_update and asic_cache["data"] and (datetime.now() - asic_cache["timestamp"] < timedelta(hours=1)):
        logger.info("Используется кэш ASIC.")
        return asic_cache["data"]
    try:
        r = requests.get("https://www.asicminervalue.com/miners/sha-256", timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        parsed_asics = []
        for row in soup.select("table tbody tr")[:5]:
            cols = row.find_all("td")
            if len(cols) < 4: continue
            name = cols[0].find('a').get_text(strip=True) if cols[0].find('a') else "Unknown ASIC"
            power_watts = float(re.search(r'([\d\.]+)', cols[2].get_text(strip=True)).group(1))
            daily_revenue = float(re.search(r'([\d\.]+)', cols[3].get_text(strip=True)).group(1))
            if power_watts > 0 and daily_revenue > 0:
                parsed_asics.append({
                    'name': name, 'hashrate': cols[1].get_text(strip=True),
                    'power_watts': power_watts, 'daily_revenue': daily_revenue
                })
        if not parsed_asics: raise ValueError("Не удалось распарсить ни одного ASIC")
        asic_cache = {"data": parsed_asics, "timestamp": datetime.now()}
        logger.info(f"Успешно получено {len(parsed_asics)} ASIC.")
        return parsed_asics
    except Exception as e:
        logger.error(f"Не удалось получить данные по ASIC: {e}")
        return []

def get_crypto_news(keywords: list = None):
    """Получает и суммирует новости с CryptoPanic."""
    try:
        params = {"auth_token": NEWSAPI_KEY, "public": "true", "currencies": "BTC,ETH"}
        if keywords: params["currencies"] = ",".join(keywords).upper()
        
        posts = requests.get("https://cryptopanic.com/api/v1/posts/", params=params, timeout=10).json().get("results", [])[:3]
        if not posts: return "[🧐 Новостей по вашему запросу не найдено]"
        
        items = []
        for post in posts:
            summary = ask_gpt(f"Сделай краткое саммари (1 предложение): '{post['title']}'", 'gpt-3.5-turbo')
            if '[❌' in summary: summary = post['title']
            clean_summary = telebot.util.escape(summary)
            items.append(f'🔹 <a href="{post.get("url", "")}">{clean_summary}</a>')
        return "\n\n".join(items)
    except requests.RequestException as e:
        logger.error(f"Ошибка API новостей: {e}")
        return "[❌ Ошибка API новостей]"

# ========================================================================================
# 3. ИНТЕРАКТИВНЫЕ ФУНКЦИИ
# ========================================================================================

def get_fear_and_greed_index():
    """Получает 'Индекс страха и жадности' и генерирует картинку."""
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

        colors = ['#ff0000', '#ff4500', '#ffff00', '#adff2f', '#00ff00']
        for i in range(100):
            ax.barh(1, 0.0314, left=3.14 - (i * 0.0314), height=0.2, 
                    color=colors[min(len(colors) - 1, int(i / 25))])

        angle = 3.14 - (value * 0.0314)
        ax.annotate('', xy=(angle, 1), xytext=(0, 0), arrowprops=dict(facecolor='white', shrink=0.05, width=2, headwidth=8))
        ax.text(0, 0, f"{value}\n{classification}", ha='center', va='center', fontsize=24, color='white', weight='bold')
        fig.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, transparent=True)
        buf.seek(0)
        plt.close(fig)
        
        text = f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>\n" \
               f"Настроение рынка сейчас ближе к <i>{'страху' if value < 50 else 'жадности'}</i>."
        return buf, text
    except Exception as e:
        logger.error(f"Ошибка при создании графика индекса страха: {e}", exc_info=True)
        return None, "[❌ Ошибка при получении индекса]"

def get_halving_info():
    """Получает информацию о времени до следующего халвинга."""
    try:
        current_block = int(requests.get("https://blockchain.info/q/getblockcount", timeout=5).text)
        blocks_left = NEXT_HALVING_BLOCK - current_block
        if blocks_left <= 0: return f"🎉 <b>Халвинг уже произошел!</b>"

        days_left, rem_minutes = divmod(blocks_left * 10, 1440)
        hours_left, _ = divmod(rem_minutes, 60)

        return (f"⏳ <b>До халвинга Bitcoin осталось:</b>\n\n"
                f"🗓 <b>Дней:</b> <code>{days_left}</code> | ⏰ <b>Часов:</b> <code>{hours_left}</code>\n"
                f"🧱 <b>Блоков до халвинга:</b> <code>{blocks_left:,}</code>")
    except requests.RequestException as e:
        logger.error(f"Ошибка получения данных для халвинга: {e}")
        return "[❌ Не удалось получить данные о халвинге]"

# ========================================================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И УТИЛИТЫ
# ========================================================================================

def get_main_keyboard():
    """Создает основную клавиатуру."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = ["💹 Курс BTC", "⛽️ Газ ETH", "⚙️ Топ-5 ASIC", "⛏️ Калькулятор",
               "📰 Новости", "🌦️ Погода", "😱 Индекс Страха", "⏳ Халвинг"]
    markup.add(*[types.KeyboardButton(text) for text in buttons])
    return markup

def send_message_with_partner_button(chat_id, text, **kwargs):
    """Отправляет сообщение с партнерской кнопкой и подсказкой."""
    try:
        full_text = f"{text}\n\n---\n<i>{random.choice(BOT_HINTS)}</i>"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
        bot.send_message(chat_id, full_text, reply_markup=markup, disable_web_page_preview=True, **kwargs)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")

def calculate_and_format_profit(electricity_cost_rub: float):
    """Расчитывает и форматирует доходность ASIC."""
    try:
        rate = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=RUB", timeout=5).json()['rates']['RUB']
    except Exception: return "Не удалось получить курс доллара для расчета."

    cost_usd = electricity_cost_rub / rate
    asics = get_top_asics()
    if not asics: return "Не удалось получить данные по ASIC для расчета."

    result = [f"💰 <b>Расчет профита (розетка {electricity_cost_rub:.2f} ₽/кВтч)</b>\n"]
    for asic in asics:
        cost = (asic['power_watts'] / 1000) * 24 * cost_usd
        profit = asic['daily_revenue'] - cost
        result.append(f"<b>{telebot.util.escape(asic['name'])}</b>\n"
                      f"  Доход: ${asic['daily_revenue']:.2f} | Расход: ${cost:.2f}\n"
                      f"  <b>Профит: ${profit:.2f}/день</b>")
    return "\n\n".join(result)

# ========================================================================================
# 5. ОБРАБОТЧИКИ КОМАНД TELEGRAM
# ========================================================================================

@bot.message_handler(commands=['start', 'help'])
def handle_start_help(msg):
    help_text = ("👋 Привет! Я ваш крипто-помощник.\n\n"
                 "<b>Основные команды:</b>\n"
                 "<code>/price</code> - курс BTC, <code>/gas</code> - газ ETH, <code>/news</code> - новости.\n\n"
                 "<b>Утилиты и игра:</b>\n"
                 "<code>/fear</code> - Индекс страха, <code>/halving</code> - таймер до халвинга.\n"
                 "<code>/my_rig</code>, <code>/collect</code> - ваша виртуальная ферма.")
    bot.send_message(msg.chat.id, help_text, reply_markup=get_main_keyboard())

@bot.message_handler(commands=['price'])
def handle_price(msg):
    coin_symbol = msg.text.split()[1].upper() if len(msg.text.split()) > 1 else "BTC"
    coin_id = CURRENCY_MAP.get(coin_symbol.lower(), coin_symbol.lower())
    price, source = get_crypto_price(coin_id, "usd")
    if price:
        send_message_with_partner_button(msg.chat.id, f"💹 Курс {coin_symbol}/USD: <b>${price:,.2f}</b>\n<i>(Данные от {source})</i>")
    else:
        bot.send_message(msg.chat.id, f"❌ Не удалось получить курс для {coin_symbol}.")

@bot.message_handler(commands=['fear', 'fng'])
def handle_fear_and_greed(msg):
    bot.send_message(msg.chat.id, "⏳ Генерирую актуальный Индекс страха...")
    photo, text = get_fear_and_greed_index()
    if photo:
        try: bot.send_photo(msg.chat.id, photo, caption=text, reply_markup=get_random_partner_button())
        except Exception as e:
            logger.error(f"Не удалось отправить фото индекса: {e}. Отправляю текстом.")
            send_message_with_partner_button(msg.chat.id, text)
    else:
        send_message_with_partner_button(msg.chat.id, text)

@bot.message_handler(commands=['my_rig', 'collect'])
def handle_rig_commands(msg):
    user_id = msg.from_user.id
    command = msg.text.split()[0]

    if command == '/my_rig':
        if user_id not in user_rigs:
            user_rigs[user_id] = {'last_collected': None, 'balance': 0.0}
            response = "🎉 Поздравляю! Вы запустили ферму! Собирайте награду: <code>/collect</code>"
        else:
            response = f"🖥️ Баланс вашей фермы: <code>{user_rigs[user_id]['balance']:.6f}</code> BTC"
        send_message_with_partner_button(msg.chat.id, response)
        return

    if command == '/collect':
        if user_id not in user_rigs:
            send_message_with_partner_button(msg.chat.id, "🤔 У вас нет фермы. Создайте: <code>/my_rig</code>")
            return
        
        rig = user_rigs[user_id]
        if rig['last_collected'] and (datetime.now() - rig['last_collected']) < timedelta(hours=24):
            time_left = timedelta(hours=24) - (datetime.now() - rig['last_collected'])
            h, m = divmod(time_left.seconds, 3600)[0], divmod(time_left.seconds % 3600, 60)[0]
            response = f"Попробуйте снова через <b>{h}ч {m}м</b>."
        else:
            mined = random.uniform(0.00005, 0.00025)
            rig['balance'] += mined
            rig['last_collected'] = datetime.now()
            response = f"✅ Собрано <b>{mined:.6f}</b> BTC! Ваш баланс: <code>{rig['balance']:.6f}</code> BTC."
        send_message_with_partner_button(msg.chat.id, response)

# ========================================================================================
# 6. ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ
# ========================================================================================

@bot.message_handler(content_types=['text'])
def handle_text_messages(msg):
    user_id = msg.from_user.id
    text_lower = msg.text.lower().strip()
    
    # --- Обработка состояний (ожидание ввода) ---
    if user_states.get(user_id) == 'weather_request':
        user_states.pop(user_id, None)
        bot.send_message(msg.chat.id, f"⏳ Ищу погоду для <b>{telebot.util.escape(msg.text)}</b>...", reply_markup=get_main_keyboard())
        send_message_with_partner_button(msg.chat.id, get_weather(msg.text))
        return

    if user_states.get(user_id) == 'calculator_request':
        try:
            cost = float(text_lower.replace(',', '.'))
            user_states.pop(user_id, None)
            bot.send_message(msg.chat.id, "⏳ Считаю прибыль...", reply_markup=get_main_keyboard())
            send_message_with_partner_button(msg.chat.id, calculate_and_format_profit(cost))
        except ValueError:
            bot.send_message(msg.chat.id, "❌ Неверный формат. Введите число (например: <code>7.5</code>)")
        return

    # --- Карта команд с клавиатуры ---
    command_map = {
        "💹 курс btc": lambda: handle_price(telebot.util.quick_markup({}, row_width=1)), # Фиктивный объект
        "⛽️ газ eth": lambda: send_message_with_partner_button(msg.chat.id, get_eth_gas_price()),
        "😱 индекс страха": lambda: handle_fear_and_greed(msg),
        "⏳ халвинг": lambda: send_message_with_partner_button(msg.chat.id, get_halving_info()),
        "⚙️ топ-5 asic": lambda: handle_asics_text(msg),
        "📰 новости": lambda: send_message_with_partner_button(msg.chat.id, get_crypto_news()),
        "⛏️ калькулятор": lambda: set_user_state(user_id, 'calculator_request', "💡 Введите стоимость электроэнергии в <b>рублях</b> за кВт/ч:"),
        "🌦️ погода": lambda: set_user_state(user_id, 'weather_request', "🌦 В каком городе показать погоду?"),
    }
    if text_lower in command_map:
        command_map[text_lower]()
        # Имитируем отправку сообщения для handle_price
        if text_lower == "💹 курс btc": handle_price(type('obj', (object,), {'text': '/price BTC'}))
        return

    # --- Анализ объявлений ---
    sale_words = ["продам", "продать", "куплю", "купить", "в наличии"]
    item_words = ["asic", "асик", "whatsminer", "antminer", "карта", "ферма"]
    if any(word in text_lower for word in sale_words) and any(word in text_lower for word in item_words):
        log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or "N/A", msg.text])
        prompt = f"Пользователь прислал объявление в майнинг-чат. Кратко и неформально прокомментируй его, поддержи диалог. НЕ предлагай другие площадки. Текст: '{msg.text}'"
        send_message_with_partner_button(msg.chat.id, ask_gpt(prompt))
        return
        
    # --- Ответ GPT на всё остальное ---
    bot.send_chat_action(msg.chat.id, 'typing')
    send_message_with_partner_button(msg.chat.id, ask_gpt(msg.text))

def set_user_state(user_id, state, text):
    """Устанавливает состояние пользователя и отправляет сообщение."""
    user_states[user_id] = state
    bot.send_message(user_id, text, reply_markup=types.ReplyKeyboardRemove())
    
def handle_asics_text(msg):
    """Обработчик для вывода списка ASIC."""
    bot.send_message(msg.chat.id, "⏳ Загружаю актуальный список...")
    asics = get_top_asics()
    if not asics:
        send_message_with_partner_button(msg.chat.id, "Не удалось получить данные об ASIC.")
        return

    # Форматируем в виде таблицы
    header = "Модель              | H/s      | P, W | Доход/день"
    divider = "--------------------|----------|------|-----------"
    rows = [f"{a['name']:<20.19}| {a['hashrate'].split()[0]:<9}| {a['power_watts']!s:<5}| ${a['daily_revenue']:<9.2f}" for a in asics]
    response_text = f"<pre>{header}\n{divider}\n" + "\n".join(rows) + "</pre>"
    
    gpt_prompt = ("Вот список доходных ASIC. Напиши короткий (1-2 предложения) мотивирующий комментарий для майнинг-чата. "
                  "Подтолкни к мысли об обновлении, намекая на консультацию по кнопке ниже. Будь убедительным, но не навязчивым.")
    response_text += f"\n\n{ask_gpt(gpt_prompt, 'gpt-4o')}"
    send_message_with_partner_button(msg.chat.id, response_text)

# ========================================================================================
# 7. ЗАПУСК БОТА И ПЛАНИРОВЩИКА
# ========================================================================================

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
        return '', 200
    return 'Forbidden', 403

@app.route("/")
def index():
    return "Bot is running!", 200

def run_scheduler():
    """Запускает фоновые задачи."""
    schedule.every(25).minutes.do(lambda: requests.get(WEBHOOK_URL.rsplit('/', 1)[0]) if WEBHOOK_URL else None)
    schedule.every(4).hours.do(auto_send_news)
    schedule.every(6).hours.do(auto_check_status)
    schedule.every(1).hours.do(get_top_asics, force_update=True)
    
    logger.info("Планировщик запущен, первоначальный запуск задач...")
    get_top_asics(force_update=True)
    auto_check_status()
    
    while True:
        schedule.run_pending()
        time.sleep(1)

def auto_send_news():
    if NEWS_CHAT_ID: send_message_with_partner_button(NEWS_CHAT_ID, get_crypto_news())

def auto_check_status():
    if not ADMIN_CHAT_ID: return
    errors = []
    if get_crypto_price()[0] is None: errors.append("API цены")
    if "[❌" in ask_gpt("Тест"): errors.append("API OpenAI")
    try: get_gsheet()
    except Exception: errors.append("Google Sheets")
    
    ts = datetime.now().strftime("%H:%M")
    status = "✅ Все системы в норме." if not errors else f"⚠️ Сбой в: {', '.join(errors)}"
    bot.send_message(ADMIN_CHAT_ID, f"<b>Отчет о состоянии ({ts})</b>\n{status}")

if __name__ == '__main__':
    logger.info("Запуск бота...")
    threading.Thread(target=run_scheduler, daemon=True).start()
    if WEBHOOK_URL:
        logger.info("Режим вебхука. Установка...")
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=f"{WEBHOOK_URL.rstrip('/')}/webhook")
        app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
    else:
        logger.info("Запуск в режиме long-polling...")
        bot.remove_webhook()
        bot.polling(none_stop=True)
