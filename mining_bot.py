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
    "⛏️ Рассчитайте прибыль с помощью 'Калькулятора'", "📰 Хотите новости? Просто напишите 'новости'",
    "🤑 Улучшайте свою ферму командой `/upgrade_rig`", "😱 Проверьте Индекс Страха и Жадности командой `/fear`",
    "🏆 Посмотрите на лучших майнеров: `/top_miners`", "🎓 Узнайте крипто-термин дня: `/word`",
    "🧠 Проверьте свои знания в викторине: `/quiz`"
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
# 🚀 НОВОЕ: Настройки для улучшений фермы
MINING_RATES = {1: 0.0001, 2: 0.0002, 3: 0.0004, 4: 0.0008, 5: 0.0016} # Базовая добыча за сбор
UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1} # Стоимость перехода на следующий уровень
STREAK_BONUS_MULTIPLIER = 0.05 # 5% бонус за каждый день серии

# Обработчик исключений для детального логирования
class ExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception):
        logger.error("Произошла ошибка в обработчике pyTelegramBotAPI:", exc_info=exception)
        return True # Продолжаем работу

# --- Инициализация ---
if not BOT_TOKEN:
    logger.critical("Критическая ошибка: не найдена переменная окружения TG_BOT_TOKEN")
    raise ValueError("Критическая ошибка: TG_BOT_TOKEN не установлен")

try:
    bot = telebot.TeleBot(BOT_TOKEN, threaded=False, parse_mode='HTML', exception_handler=ExceptionHandler())
    app = Flask(__name__)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logger.critical(f"Не удалось инициализировать одного из клиентов API: {e}")
    raise

# --- Глобальные переменные (в реальном приложении лучше использовать БД) ---
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
        {"name": "Binance", "url": f"https://api.binance.com/api/v3/ticker/price?symbol={coin_id.upper()}USDT"}
    ]
    
    # Binance поддерживает только определенные тикеры, так что проверяем
    if coin_id.upper() != "BTC":
        sources.pop(1)
    
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
        for row in soup.select("table tbody tr"):
            cols = [col for col in row.find_all("td")]
            if len(cols) < 5: continue 
            name = cols[1].find('a').get_text(strip=True) if cols[1].find('a') else "Unknown ASIC"
            hashrate = cols[2].get_text(strip=True)
            power = cols[3].get_text(strip=True)
            revenue = cols[4].get_text(strip=True)
            power_watts_match = re.search(r'([\d,]+)', power)
            daily_revenue_match = re.search(r'([\d\.]+)', revenue)
            if power_watts_match and daily_revenue_match:
                power_watts = float(power_watts_match.group(1).replace(',', ''))
                daily_revenue = float(daily_revenue_match.group(1))
                if power_watts > 0 and daily_revenue > 0:
                    parsed_asics.append({
                        'name': name, 'hashrate': hashrate,
                        'power_watts': power_watts, 'daily_revenue': daily_revenue
                    })
        if not parsed_asics: raise ValueError("Не удалось распарсить ни одного ASIC")
        parsed_asics.sort(key=lambda x: x['daily_revenue'], reverse=True)
        top_5_asics = parsed_asics[:5]
        asic_cache = {"data": top_5_asics, "timestamp": datetime.now()}
        logger.info(f"Успешно получено {len(top_5_asics)} ASIC.")
        return top_5_asics
    except Exception as e:
        logger.error(f"Не удалось получить данные по ASIC: {e}", exc_info=True)
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
            if '[❌' in summary: 
                summary = telebot.util.escape(post['title']) 
            items.append(f'🔹 <a href="{post.get("url", "")}">{summary}</a>')
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
        current_epoch = current_block // HALVING_INTERVAL
        next_halving_block = (current_epoch + 1) * HALVING_INTERVAL
        blocks_left = next_halving_block - current_block
        if blocks_left <= 0: return f"🎉 <b>Халвинг на блоке {next_halving_block - HALVING_INTERVAL} уже произошел!</b>\nСледующий ожидается на блоке {next_halving_block}."
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
    buttons = ["💹 Курс BTC", "⚙️ Топ-5 ASIC", "⛏️ Калькулятор", "📰 Новости", 
               "😱 Индекс Страха", "⏳ Халвинг", "🧠 Викторина", "🎓 Слово дня",
               "🏆 Топ майнеров"]
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

def send_photo_with_partner_button(chat_id, photo, caption, **kwargs):
    """Отправляет фото с партнерской кнопкой и подсказкой."""
    try:
        if not photo: raise ValueError("Объект фото пустой")
        full_caption = f"{caption}\n\n---\n<i>{random.choice(BOT_HINTS)}</i>"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
        bot.send_photo(chat_id, photo, caption=full_caption, reply_markup=markup, **kwargs)
    except Exception as e:
        logger.error(f"Не удалось отправить фото в чат {chat_id}: {e}")
        send_message_with_partner_button(chat_id, caption, **kwargs)

def calculate_and_format_profit(electricity_cost_rub: float):
    """Расчитывает и форматирует доходность ASIC."""
    try:
        response = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=RUB", timeout=5)
        response.raise_for_status()
        rate = response.json().get('rates', {}).get('RUB')
        if not rate: raise ValueError("Курс RUB не найден в ответе API")
    except Exception as e:
        logger.error(f"Ошибка получения курса для калькулятора: {e}")
        return "Не удалось получить курс доллара для расчета. Попробуйте позже."
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
                 "<code>/my_rig</code> - инфо о ферме, <code>/collect</code> - сбор награды.\n"
                 "<code>/upgrade_rig</code> - улучшение фермы.\n"
                 "<code>/top_miners</code> - таблица лидеров.\n"
                 "<code>/quiz</code> - викторина, <code>/word</code> - слово дня.")
    bot.send_message(msg.chat.id, help_text, reply_markup=get_main_keyboard())

def get_price_and_send(chat_id, coin_symbol="BTC"):
    """Получает цену и отправляет сообщение."""
    coin_id = CURRENCY_MAP.get(coin_symbol.lower(), coin_symbol.lower())
    price, source = get_crypto_price(coin_id, "usd")
    if price:
        text = f"💹 Курс {coin_symbol}/USD: <b>${price:,.2f}</b>\n<i>(Данные от {source})</i>"
        send_message_with_partner_button(chat_id, text)
    else:
        text = f"❌ Не удалось получить курс для {coin_symbol}."
        bot.send_message(chat_id, text)

@bot.message_handler(commands=['price'])
def handle_price(msg):
    coin_symbol = msg.text.split()[1].upper() if len(msg.text.split()) > 1 else "BTC"
    get_price_and_send(msg.chat.id, coin_symbol)

@bot.message_handler(commands=['fear', 'fng'])
def handle_fear_and_greed(msg):
    bot.send_message(msg.chat.id, "⏳ Генерирую актуальный Индекс страха...")
    photo, text = get_fear_and_greed_index()
    send_photo_with_partner_button(msg.chat.id, photo=photo, caption=text)

# --- Игровые команды ---
@bot.message_handler(commands=['my_rig'])
def handle_my_rig(msg):
    """Показывает информацию о ферме пользователя."""
    user_id = msg.from_user.id
    if user_id not in user_rigs:
        user_rigs[user_id] = {'last_collected': None, 'balance': 0.0, 'level': 1, 'streak': 0, 'name': msg.from_user.first_name}
        response = "🎉 Поздравляю! Вы запустили свою первую виртуальную ферму!\n\n"
    else:
        response = ""
    rig = user_rigs[user_id]
    next_level = rig['level'] + 1
    upgrade_cost_text = f"Стоимость улучшения до {next_level} уровня: <code>{UPGRADE_COSTS.get(next_level, 'N/A')}</code> BTC." if next_level in UPGRADE_COSTS else "Вы достигли максимального уровня!"
    response += (f"🖥️ <b>Ферма {telebot.util.escape(rig['name'])}</b>\n\n"
                 f"<b>Уровень:</b> {rig['level']}\n"
                 f"<b>Баланс:</b> <code>{rig['balance']:.6f}</code> BTC\n"
                 f"<b>Дневная серия:</b> {rig['streak']} 🔥 (дает бонус <b>{rig['streak'] * STREAK_BONUS_MULTIPLIER:.0%}</b>)\n\n"
                 f"{upgrade_cost_text}\n\n"
                 "Используйте <code>/collect</code> для сбора и <code>/upgrade_rig</code> для улучшения.")
    send_message_with_partner_button(msg.chat.id, response)

@bot.message_handler(commands=['collect'])
def handle_collect(msg):
    """Собирает награду с фермы."""
    user_id = msg.from_user.id
    if user_id not in user_rigs:
        return send_message_with_partner_button(msg.chat.id, "🤔 У вас нет фермы. Начните с команды <code>/my_rig</code>.")
    rig = user_rigs[user_id]
    now = datetime.now()
    if rig['last_collected'] and (now - rig['last_collected']) < timedelta(hours=24):
        time_left = timedelta(hours=24) - (now - rig['last_collected'])
        h, m = divmod(time_left.seconds, 3600)[0], divmod(time_left.seconds % 3600, 60)[0]
        return send_message_with_partner_button(msg.chat.id, f"Вы уже собирали награду. Попробуйте снова через <b>{h}ч {m}м</b>.")
    if rig['last_collected'] and (now - rig['last_collected']) < timedelta(hours=48):
        rig['streak'] += 1
    else:
        rig['streak'] = 1
    base_mined = MINING_RATES.get(rig['level'], 0.0001)
    streak_bonus = base_mined * rig['streak'] * STREAK_BONUS_MULTIPLIER
    total_mined = base_mined + streak_bonus
    rig['balance'] += total_mined
    rig['last_collected'] = now
    response = (f"✅ Собрано <b>{total_mined:.6f}</b> BTC!\n"
                f"  (Базовая добыча: {base_mined:.6f} + Бонус за серию: {streak_bonus:.6f})\n"
                f"🔥 Ваша серия: <b>{rig['streak']} дней!</b>\n"
                f"💰 Ваш новый баланс: <code>{rig['balance']:.6f}</code> BTC.")
    send_message_with_partner_button(msg.chat.id, response)

@bot.message_handler(commands=['upgrade_rig'])
def handle_upgrade_rig(msg):
    """Улучшает ферму пользователя."""
    user_id = msg.from_user.id
    if user_id not in user_rigs:
        return send_message_with_partner_button(msg.chat.id, "🤔 У вас нет фермы. Начните с команды <code>/my_rig</code>.")
    rig = user_rigs[user_id]
    next_level = rig['level'] + 1
    cost = UPGRADE_COSTS.get(next_level)
    if not cost:
        return send_message_with_partner_button(msg.chat.id, "🎉 Поздравляем, у вас уже максимальный уровень фермы!")
    if rig['balance'] >= cost:
        rig['balance'] -= cost
        rig['level'] = next_level
        response = f"🚀 <b>Улучшение завершено!</b>\n\nВаша ферма достигла <b>{next_level}</b> уровня! " \
                   f"Теперь вы будете добывать больше.\n" \
                   f"💰 Ваш баланс: <code>{rig['balance']:.6f}</code> BTC."
    else:
        needed = cost - rig['balance']
        response = f"❌ <b>Недостаточно средств.</b>\n\n" \
                   f"Для улучшения до {next_level} уровня требуется <code>{cost}</code> BTC.\n" \
                   f"Вам не хватает <code>{needed:.6f}</code> BTC. Копите дальше!"
    send_message_with_partner_button(msg.chat.id, response)

@bot.message_handler(commands=['top_miners'])
def handle_top_miners(msg):
    """Показывает таблицу лидеров."""
    if not user_rigs:
        return send_message_with_partner_button(msg.chat.id, "Пока нет ни одного майнера для составления топа.")
    sorted_rigs = sorted(user_rigs.values(), key=lambda r: r['balance'], reverse=True)
    response = ["🏆 <b>Топ-5 Виртуальных Майнеров:</b>\n"]
    for i, rig in enumerate(sorted_rigs[:5]):
        response.append(f"<b>{i+1}.</b> {telebot.util.escape(rig['name'])} - <code>{rig['balance']:.6f}</code> BTC (Ур. {rig['level']})")
    send_message_with_partner_button(msg.chat.id, "\n".join(response))

# --- Обработчики викторины и слова дня ---
@bot.message_handler(commands=['word'])
def handle_word_of_the_day(msg):
    term = random.choice(CRYPTO_TERMS)
    prompt = f"Объясни термин '{term}' простыми словами для новичка в криптовалютах (2-3 предложения). Ответ дай на русском языке, используя HTML-теги для выделения."
    explanation = ask_gpt(prompt, "gpt-3.5-turbo")
    text = f"🎓 <b>Слово дня: {term}</b>\n\n{explanation}"
    send_message_with_partner_button(msg.chat.id, text)
    
@bot.message_handler(commands=['quiz'])
def handle_quiz(msg):
    user_id = msg.from_user.id
    user_states[user_id] = {'quiz_active': True, 'score': 0, 'question_index': 0}
    bot.send_message(msg.chat.id, "🔥 <b>Начинаем крипто-викторину!</b>\nОтветьте на 5 вопросов.", reply_markup=types.ReplyKeyboardRemove())
    send_quiz_question(msg.chat.id, user_id)

def send_quiz_question(chat_id, user_id):
    state = user_states.get(user_id)
    if not state or not state.get('quiz_active'): return
    q_index = state['question_index']
    if q_index >= len(QUIZ_QUESTIONS):
        score = state['score']
        bot.send_message(chat_id, f"🎉 <b>Викторина завершена!</b>\nВаш результат: <b>{score} из {len(QUIZ_QUESTIONS)}</b>. Отличная работа!", reply_markup=get_main_keyboard())
        user_states.pop(user_id, None)
        return
    question_data = QUIZ_QUESTIONS[q_index]
    markup = types.InlineKeyboardMarkup()
    for i, option in enumerate(question_data['options']):
        markup.add(types.InlineKeyboardButton(option, callback_data=f"quiz_{q_index}_{i}"))
    bot.send_message(chat_id, f"<b>Вопрос {q_index + 1}:</b>\n{question_data['question']}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('quiz_'))
def handle_quiz_answer(call):
    user_id = call.from_user.id
    state = user_states.get(user_id)
    if not state or not state.get('quiz_active'):
        return bot.answer_callback_query(call.id, "Викторина уже не активна. Начните заново: /quiz")
    _, q_index, answer_index = call.data.split('_')
    q_index, answer_index = int(q_index), int(answer_index)
    if q_index != state.get('question_index'):
        return bot.answer_callback_query(call.id, "Вы уже ответили на этот вопрос.")
    question_data = QUIZ_QUESTIONS[q_index]
    correct_index = question_data['correct_index']
    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None)
    if answer_index == correct_index:
        state['score'] += 1
        bot.send_message(call.message.chat.id, "✅ Правильно!")
    else:
        correct_answer_text = question_data['options'][correct_index]
        bot.send_message(call.message.chat.id, f"❌ Неверно. Правильный ответ: <b>{correct_answer_text}</b>")
    state['question_index'] += 1
    time.sleep(1)
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

        command_map = {
            "💹 курс btc": lambda: get_price_and_send(msg.chat.id, "BTC"),
            "⚙️ топ-5 asic": lambda: handle_asics_text(msg),
            "⛏️ калькулятор": lambda: set_user_state(user_id, 'calculator_request', "💡 Введите стоимость электроэнергии в <b>рублях</b> за кВт/ч:"),
            "📰 новости": lambda: send_message_with_partner_button(msg.chat.id, get_crypto_news()),
            "😱 индекс страха": lambda: handle_fear_and_greed(msg),
            "⏳ халвинг": lambda: send_message_with_partner_button(msg.chat.id, get_halving_info()),
            "🧠 викторина": lambda: handle_quiz(msg),
            "🎓 слово дня": lambda: handle_word_of_the_day(msg),
            "🏆 топ майнеров": lambda: handle_top_miners(msg),
            "🌦️ погода": lambda: set_user_state(user_id, 'weather_request', "🌦 В каком городе показать погоду?")
        }
        if text_lower in command_map:
            command_map[text_lower]()
            return

        sale_words = ["продам", "продать", "куплю", "купить", "в наличии"]
        item_words = ["asic", "асик", "whatsminer", "antminer", "карта", "ферма"]
        if any(word in text_lower for word in sale_words) and any(word in text_lower for word in item_words):
            log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or "N/A", msg.text])
            prompt = f"Пользователь прислал объявление в майнинг-чат. Кратко и неформально прокомментируй его, поддержи диалог. НЕ предлагай другие площадки. Текст: '{msg.text}'"
            send_message_with_partner_button(msg.chat.id, ask_gpt(prompt))
            return
            
        bot.send_chat_action(msg.chat.id, 'typing')
        send_message_with_partner_button(msg.chat.id, ask_gpt(msg.text))

    except Exception as e:
        logger.error(f"Критическая ошибка в handle_text_messages!", exc_info=e)
        try:
            bot.send_message(msg.chat.id, "😵 Ой, что-то пошло не так. Команда разработчиков уже уведомлена.")
        except Exception as e2:
            logger.error(f"Не удалось даже отправить сообщение об ошибке: {e2}")

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
    header = "Модель              | H/s      | P, W | Доход/день"
    divider = "--------------------|----------|------|-----------"
    rows = [f"{a['name']:<20.19}| {a['hashrate']:<9}| {a['power_watts']:<5.0f}| ${a['daily_revenue']:<10.2f}" for a in asics]
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
    if get_crypto_price("bitcoin")[0] is None: errors.append("API цены")
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
        bot.polling(none_stop=Tr
