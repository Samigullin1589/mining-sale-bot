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
import matplotlib.pyplot as plt
import io
import re
import random
import logging

# --- Настройка логирования ---
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

# --- Ключи и Настройки (Загрузка из переменных окружения) ---
# РЕКОМЕНДАЦИЯ: Используйте os.getenv() вместо os.environ.get() для лучшей практики.
# getenv не вызовет ошибку, если переменная не найдена, а вернет None.
BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
NEWSAPI_KEY = os.getenv("CRYPTO_API_KEY") # CryptoPanic API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "YourApiKeyToken")

NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID") # Канал для новостей
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID") # ID админа для отчетов

# Ключ теперь читается как текстовая переменная, а не как путь к файлу
GOOGLE_JSON_STR = os.getenv("GOOGLE_JSON")
SHEET_ID = os.getenv("SHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "Лист1")

# --- Настройки Партнерской Ссылки ---
PARTNER_URL = "https://app.leadteh.ru/w/dTeKr"
PARTNER_BUTTON_TEXT_OPTIONS = [
    "🎁 Узнать спеццены", "🔥 Эксклюзивное предложение",
    "💡 Получить консультацию", "💎 Прайс от экспертов"
]

# --- Глобальные переменные и кэш ---
if not BOT_TOKEN:
    raise ValueError("Критическая ошибка: не найдена переменная окружения TG_BOT_TOKEN")

# УЛУЧШЕНО: Добавлена обработка ошибок при инициализации API
try:
    bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
    app = Flask(__name__)
    openai_client = OpenAI(api_key=OPENAI_API_KEY)
except Exception as e:
    logging.critical(f"Не удалось инициализировать одного из клиентов API: {e}")
    raise

# Словари для отслеживания состояния пользователей
pending_weather_requests = {}
pending_calculator_requests = {}
asic_cache = {"data": [], "timestamp": None}

# Словарь для универсального парсера валют
CURRENCY_MAP = {
    'доллар': 'USD', 'usd': 'USD', '$': 'USD',
    'евро': 'EUR', 'eur': 'EUR', '€': 'EUR',
    'рубль': 'RUB', 'rub': 'RUB', '₽': 'RUB',
    'юань': 'CNY', 'cny': 'CNY',
    'биткоин': 'BTC', 'btc': 'BTC', 'бтс': 'BTC', 'втс': 'BTC',
    'эфир': 'ETH', 'eth': 'ETH',
}

# ========================================================================================
# 2. ФУНКЦИИ ДЛЯ РАБОТЫ С ВНЕШНИМИ API И СЕРВИСАМИ
# ========================================================================================

def get_gsheet():
    """Подключается к Google Sheets используя ключи из переменной окружения."""
    if not GOOGLE_JSON_STR:
        logging.error("Переменная окружения GOOGLE_JSON не установлена.")
        raise ValueError("Ключи Google Sheets не найдены.")
    try:
        creds_dict = json.loads(GOOGLE_JSON_STR)
        creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        gc = gspread.authorize(creds)
        return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    except json.JSONDecodeError:
        logging.error("Неверный формат JSON в переменной GOOGLE_JSON.")
        raise
    except Exception as e:
        logging.error(f"Ошибка подключения к Google Sheets: {e}")
        raise

def log_to_sheet(row_data: list):
    """Логирует данные в новую строку Google Sheets."""
    try:
        sheet = get_gsheet()
        sheet.append_row(row_data, value_input_option='USER_ENTERED')
        logging.info(f"Запись в Google Sheets: {row_data}")
    except Exception as e:
        logging.error(f"Ошибка записи в Google Sheets: {e}")

def get_crypto_price(coin_id="bitcoin", vs_currency="usd"):
    """
    ТРОЙНОЕ РЕЗЕРВИРОВАНИЕ: Получает цену с Binance, при ошибке -> KuCoin, при ошибке -> CoinGecko.
    Возвращает кортеж (цена, источник).
    """
    # 1. Binance
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5).json()
        if 'price' in res: return (float(res['price']), "Binance")
    except Exception as e:
        logging.warning(f"Ошибка API Binance: {e}. Пробую KuCoin.")
    # 2. KuCoin
    try:
        res = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=BTC-USDT", timeout=5).json()
        if res.get('data') and res['data'].get('price'): return (float(res['data']['price']), "KuCoin")
    except Exception as e:
        logging.warning(f"Ошибка API KuCoin: {e}. Пробую CoinGecko.")
    # 3. CoinGecko
    try:
        res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies={vs_currency}", timeout=5).json()
        if coin_id in res and vs_currency in res[coin_id]: return (float(res[coin_id][vs_currency]), "CoinGecko")
    except Exception as e:
        logging.error(f"Ошибка API CoinGecko: {e}.")
    return (None, None)

def get_eth_gas_price():
    """Получает актуальную цену газа в сети Ethereum."""
    try:
        res = requests.get(f"https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey={ETHERSCAN_API_KEY}", timeout=5).json()
        if res.get("status") == "1" and res.get("result"):
            gas_info = res["result"]
            return (f"⛽️ **Актуальная цена газа в Ethereum (Gwei):**\n\n"
                    f"🐢 **Медленно:** `{gas_info['SafeGasPrice']}` Gwei\n"
                    f"🚶‍♂️ **Средне:** `{gas_info['ProposeGasPrice']}` Gwei\n"
                    f"🚀 **Быстро:** `{gas_info['FastGasPrice']}` Gwei")
        else:
            return "[❌ Не удалось получить данные о газе с Etherscan]"
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка сети при запросе цены на газ: {e}")
        return f"[❌ Сетевая ошибка при запросе цены на газ]"
    except Exception as e:
        logging.error(f"Неизвестная ошибка при запросе цены на газ: {e}")
        return f"[❌ Ошибка при запросе цены на газ]"

def get_weather(city: str):
    """Получает погоду с сервиса wttr.in."""
    try:
        # УЛУЧШЕНО: Добавлены заголовки для имитации запроса от браузера
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(f"https://wttr.in/{city}?format=j1", headers=headers, timeout=7).json()
        current = r["current_condition"][0]
        return (f"🌍 {city.title()}\n"
                f"🌡 Температура: {current['temp_C']}°C (Ощущается как {current['FeelsLikeC']}°C)\n"
                f"☁️ Погода: {current['lang_ru'][0]['value']}\n"
                f"💧 Влажность: {current['humidity']}%\n"
                f"💨 Ветер: {current['windspeedKmph']} км/ч")
    except Exception as e:
        logging.error(f"Ошибка получения погоды для '{city}': {e}")
        return f"[❌ Не удалось найти город '{city}' или произошла ошибка.]"

def get_currency_rate(base="USD", to="RUB"):
    """Получает курс валют с exchangerate.host."""
    try:
        res = requests.get(f"https://api.exchangerate.host/latest?base={base.upper()}&symbols={to.upper()}", timeout=5).json()
        if res.get('rates') and res['rates'].get(to.upper()):
            rate = res['rates'][to.upper()]
            return f"💹 {base.upper()} → {to.upper()} = **{rate:.2f}**"
        return f"[❌ Не удалось получить курс для {base.upper()} к {to.upper()}]"
    except Exception as e:
        logging.error(f"Ошибка получения курса валют: {e}")
        return f"[❌ Ошибка API курсов валют]"

def ask_gpt(prompt: str, model: str = "gpt-4o"):
    """Отправляет запрос к OpenAI GPT."""
    try:
        # УЛУЧШЕНО: Использование системного сообщения для более точного указания роли
        res = openai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Ты — полезный ассистент, который всегда отвечает на русском языке."},
                {"role": "user", "content": prompt}
            ],
            timeout=20.0 # Установлен таймаут для долгих запросов
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Ошибка вызова OpenAI API: {e}")
        return f"[❌ Ошибка GPT: Не удалось получить ответ. Попробуйте позже.]"

def get_top_asics(force_update: bool = False):
    """Получает топ-5 ASIC с asicminervalue.com, использует кэш."""
    global asic_cache
    cache_is_valid = asic_cache["data"] and asic_cache["timestamp"] and (datetime.now() - asic_cache["timestamp"] < timedelta(hours=1))
    if cache_is_valid and not force_update:
        logging.info("Используется кэш ASIC.")
        return asic_cache["data"]
    try:
        logging.info("Обновление данных по ASIC с сайта...")
        r = requests.get("https://www.asicminervalue.com/miners/sha-256", timeout=15)
        r.raise_for_status() # Проверка на HTTP ошибки
        soup = BeautifulSoup(r.text, "html.parser")
        table_rows = soup.select("table tbody tr")
        if not table_rows:
            return ["[❌ Не удалось найти таблицу с асиками на странице.]"]

        updated_asics = []
        for row in table_rows[:5]:
            cols = row.find_all("td")
            if len(cols) > 3:
                 # УЛУЧШЕНО: Более надежный парсинг с проверками
                name = cols[0].get_text(strip=True)
                th = cols[1].get_text(strip=True)
                power = cols[2].get_text(strip=True)
                profit = cols[3].get_text(strip=True)
                updated_asics.append(f"• {name}: {th}, {power}, доход ~{profit}/день")

        if not updated_asics:
             return ["[❌ Структура таблицы на сайте изменилась, не удалось извлечь данные.]"]

        asic_cache = {"data": updated_asics, "timestamp": datetime.now()}
        logging.info("Данные по ASIC успешно обновлены.")
        return updated_asics
    except Exception as e:
        logging.error(f"Ошибка обновления данных по ASIC: {e}")
        return [f"[❌ Ошибка при обновлении списка ASIC: {e}]"]

def get_crypto_news(keywords: list = None):
    """Получает 3 последние новости с CryptoPanic."""
    try:
        params = {"auth_token": NEWSAPI_KEY, "public": "true"}
        if keywords:
            params["currencies"] = ",".join(keywords).upper()
        else:
             params["currencies"] = "BTC,ETH" # Новости по умолчанию

        r = requests.get("https://cryptopanic.com/api/v1/posts/", params=params, timeout=10).json()
        posts = r.get("results", [])[:3]

        if not posts:
            return "[🧐 Новостей по вашему запросу не найдено]"

        # УЛУЧШЕНО: Использование GPT для саммаризации
        prompt_for_gpt = (
            "Ниже приведены заголовки новостей. Для каждого заголовка сделай краткое саммари на русском (1 предложение). "
            "Отформатируй ответ так: 'САММАРИ 1\nСАММАРИ 2\nСАММАРИ 3'.\n\n" +
            "\n".join([f"{i+1}. {p['title']}" for i, p in enumerate(posts)])
        )
        summaries_text = ask_gpt(prompt_for_gpt, 'gpt-3.5-turbo')
        summaries = summaries_text.split('\n') if summaries_text and "Ошибка" not in summaries_text else [p['title'] for p in posts]

        items = [f"🔹 {summaries[i].strip()}\n[Источник]({post.get('url', '')})" for i, post in enumerate(posts) if i < len(summaries)]
        return "\n\n".join(items) if items else "[🤷‍♂️ Свежих новостей нет]"

    except Exception as e:
        logging.error(f"Ошибка получения новостей: {e}")
        return f"[❌ Ошибка API новостей]"

# ========================================================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И УТИЛИТЫ
# ========================================================================================

def get_main_keyboard():
    """Создает основную клавиатуру с кнопками."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=False)
    buttons = [
        types.KeyboardButton("💹 Курс BTC"), types.KeyboardButton("⛽️ Газ ETH"),
        types.KeyboardButton("⚙️ Топ-5 ASIC"), types.KeyboardButton("⛏️ Калькулятор"),
        types.KeyboardButton("📰 Новости"), types.KeyboardButton("🌦️ Погода")
    ]
    markup.add(*buttons)
    return markup

def get_random_partner_button():
    """Создает инлайн-кнопку со случайным текстом."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
    return markup

def send_message_with_partner_button(chat_id, text, **kwargs):
    """Обертка для отправки сообщения с прикрепленной партнерской кнопкой."""
    try:
        kwargs.setdefault('parse_mode', 'Markdown')
        kwargs.setdefault('reply_markup', get_random_partner_button())
        bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")

def calculate_and_format_profit(electricity_cost_rub: float):
    """Расчет и форматирование доходности ASIC с конвертацией из рублей."""
    try:
        rate_info = requests.get(f"https://api.exchangerate.host/latest?base=USD&symbols=RUB", timeout=5).json()
        usd_to_rub_rate = rate_info['rates']['RUB']
    except Exception as e:
        logging.error(f"Ошибка получения курса USD/RUB для калькулятора: {e}")
        return "Не удалось получить курс доллара для расчета. Попробуйте позже."

    electricity_cost_usd = electricity_cost_rub / usd_to_rub_rate
    asics_data = get_top_asics()
    if not asics_data or "Ошибка" in asics_data[0]:
        return "Не удалось получить данные по ASIC для расчета. Попробуйте позже."

    result = [f"💰 **Расчет чистой прибыли при цене розетки {electricity_cost_rub:.2f} ₽/кВтч (~${electricity_cost_usd:.3f}/кВтч)**\n"]
    for asic_string in asics_data:
        try:
            # УЛУЧШЕНО: Более устойчивый к ошибкам парсинг с помощью regex
            match = re.search(r"•\s*(.*?):\s*.*?(\d+W).*?\$([\d\.]+)", asic_string)
            if not match:
                continue

            name, power_str, revenue_str = match.groups()
            power_watts = float(power_str.replace('W', ''))
            daily_revenue = float(revenue_str)

            daily_power_kwh = (power_watts / 1000) * 24
            daily_electricity_cost = daily_power_kwh * electricity_cost_usd
            net_profit = daily_revenue - daily_electricity_cost

            result.append(
                f"**{name.strip()}**\n"
                f"  - Доход: `${daily_revenue:.2f}`\n"
                f"  - Расход: `${daily_electricity_cost:.2f}`\n"
                f"  - **Чистая прибыль: `${net_profit:.2f}`/день**"
            )
        except (ValueError, TypeError, IndexError) as e:
            logging.warning(f"Ошибка парсинга ASIC для калькулятора '{asic_string}': {e}")
            continue

    return "\n".join(result) if len(result) > 1 else "Не удалось рассчитать прибыль ни для одного ASIC."

# ========================================================================================
# 4. ЗАДАЧИ, ВЫПОЛНЯЕМЫЕ ПО РАСПИСАНИЮ (SCHEDULE)
# ========================================================================================

def keep_alive():
    """Отправляет запрос самому себе, чтобы приложение не 'засыпало' на хостинге."""
    if WEBHOOK_URL:
        try:
            # УЛУЧШЕНО: Пингуется базовый URL, а не эндпоинт вебхука
            base_url = WEBHOOK_URL.rsplit('/', 1)[0]
            requests.get(base_url, timeout=10)
            logging.info(f"Keep-alive пинг на {base_url} отправлен.")
        except Exception as e:
            logging.warning(f"Ошибка keep-alive пинга: {e}")

def auto_send_news():
    """Автоматическая отправка новостей в указанный канал."""
    if not NEWS_CHAT_ID: return
    try:
        logging.info("Запуск авторассылки новостей...")
        news = get_crypto_news()
        send_message_with_partner_button(NEWS_CHAT_ID, news, disable_web_page_preview=True)
        logging.info(f"Новости успешно отправлены в чат {NEWS_CHAT_ID}")
    except Exception as e:
        logging.error(f"Ошибка при авторассылке новостей: {e}")
        if ADMIN_CHAT_ID:
            bot.send_message(ADMIN_CHAT_ID, f"⚠️ Не удалось выполнить авторассылку новостей:\n{e}")

def auto_check_status():
    """Плановая проверка работоспособности систем и отправка отчета админу."""
    if not ADMIN_CHAT_ID: return
    logging.info("Запуск плановой проверки систем...")
    errors = []
    # 1. Проверка OpenAI
    if "ошибка" in ask_gpt("Тест", "gpt-3.5-turbo").lower():
        errors.append("API OpenAI (GPT) вернул ошибку.")
    # 2. Проверка Google Sheets
    try:
        get_gsheet()
    except Exception:
        errors.append("Не удалось подключиться к Google Sheets.")
    # 3. Проверка новостного API
    if "ошибка" in get_crypto_news().lower():
        errors.append("API новостей (CryptoPanic) вернул ошибку.")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not errors:
        status_msg = f"✅ **Плановая проверка ({ts})**\n\nВсе системы работают."
    else:
        error_list = "\n".join([f"� {e}" for e in errors])
        status_msg = f"⚠️ **Проблемы в работе бота ({ts}):**\n{error_list}"
    try:
        bot.send_message(ADMIN_CHAT_ID, status_msg, parse_mode="Markdown")
        logging.info("Отчет о состоянии отправлен админу.")
    except Exception as e:
        logging.error(f"Не удалось отправить отчет админу: {e}")

# ========================================================================================
# 5. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ TELEGRAM
# ========================================================================================

@bot.message_handler(commands=['start', 'help'])
def handle_start_help(msg):
    """Обработчик команд /start и /help."""
    help_text = (
        "👋 Привет! Я ваш помощник в мире криптовалют и майнинга.\n\n"
        "Используйте кнопки ниже или отправьте мне команду.\n\n"
        "**Основные команды:**\n"
        "`/price` - узнать курс BTC (или `/price ETH-USDT`).\n"
        "`/chart` - построить график доходности из Google Sheets.\n"
        "`/news` - получить свежие крипто-новости.\n"
        "`/gas` - узнать цену на газ в сети Ethereum.\n\n"
        "Просто напишите мне что-нибудь, и я постараюсь помочь!"
    )
    bot.send_message(msg.chat.id, help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['price'])
def handle_price(msg):
    """Обработчик команды /price."""
    try:
        # УЛУЧШЕНО: Более гибкий парсинг пары
        parts = msg.text.split()
        pair_text = parts[1].upper() if len(parts) > 1 else "BTC-USDT"
        coin, currency = (pair_text.split('-') + ['USD'])[:2]
        # Для CoinGecko нужен ID, а не тикер
        coin_id_map = {'BTC': 'bitcoin', 'ETH': 'ethereum'}
        coin_id = coin_id_map.get(coin, coin.lower())
    except IndexError:
        pair_text = "BTC-USDT"
        coin_id, currency = "bitcoin", "usd"

    price, source = get_crypto_price(coin_id, currency.lower())
    if price:
        send_message_with_partner_button(msg.chat.id, f"💹 Курс {pair_text.replace('-', '/')}: **${price:,.2f}**\n_(Данные от {source})_")
    else:
        bot.send_message(msg.chat.id, f"❌ Не удалось получить курс для {pair_text} ни с одного источника.")

@bot.message_handler(commands=['chart'])
def handle_chart(msg):
    """Строит и отправляет график на основе данных из Google Sheets."""
    bot.send_message(msg.chat.id, "⏳ Строю график, это может занять немного времени...")
    try:
        sheet = get_gsheet()
        # УЛУЧШЕНО: Получаем только нужные столбцы
        records = sheet.get_all_values()[1:] # Пропускаем заголовок
        dates, profits = [], []
        error_lines = []

        for i, row in enumerate(records):
            try:
                if not row or len(row) < 3 or not row[0] or not row[2]: continue
                date_obj = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                # УЛУЧШЕНО: Более надежный поиск цены
                profit_match = re.search(r'\$([\d\.]+)', row[2])
                if profit_match:
                    profits.append(float(profit_match.group(1)))
                    dates.append(date_obj)
            except (ValueError, IndexError):
                error_lines.append(str(i + 2)) # +2 т.к. начинаем с 1 и есть заголовок
                continue

        if len(dates) < 2:
            bot.send_message(msg.chat.id, "Недостаточно данных для построения графика. Нужно минимум 2 корректные записи в таблице.")
            return

        if error_lines:
            bot.send_message(msg.chat.id, f"⚠️ **Предупреждение:** Не удалось обработать строки: {', '.join(error_lines)}. Убедитесь, что дата в формате `ГГГГ-ММ-ДД ЧЧ:ММ:СС` и в тексте есть цена в `$`. График построен по остальным данным.")

        # Построение графика
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(dates, profits, marker='o', linestyle='-', color='#00aaff', label='Чистая прибыль ($)')
        ax.set_title('Динамика доходности майнинга', fontsize=16, color='white')
        ax.set_ylabel('Прибыль, $', color='white')
        ax.tick_params(axis='x', colors='white', rotation=30)
        ax.tick_params(axis='y', colors='white')
        ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='#555555')
        ax.legend()
        fig.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, transparent=True)
        buf.seek(0)
        bot.send_photo(msg.chat.id, buf, caption="📈 График динамики доходности на основе ваших данных из Google Sheets.")
        plt.close(fig)

    except Exception as e:
        logging.error(f"Ошибка построения графика: {e}")
        bot.send_message(msg.chat.id, f"❌ Не удалось построить график: {e}")

@bot.message_handler(content_types=['text'])
def handle_all_text_messages(msg):
    """Основной обработчик текстовых сообщений."""
    user_id = msg.from_user.id
    text_lower = msg.text.lower().strip()

    # --- 1. Обработка состояний (ожидание ввода от пользователя) ---
    if pending_weather_requests.get(user_id):
        del pending_weather_requests[user_id]
        bot.send_message(msg.chat.id, "⏳ Ищу погоду...", reply_markup=get_main_keyboard())
        send_message_with_partner_button(msg.chat.id, get_weather(msg.text))
        return

    if pending_calculator_requests.get(user_id):
        try:
            electricity_cost = float(text_lower.replace(',', '.'))
            del pending_calculator_requests[user_id]
            bot.send_message(msg.chat.id, "⏳ Считаю прибыль...", reply_markup=get_main_keyboard())
            calculation_result = calculate_and_format_profit(electricity_cost)
            send_message_with_partner_button(msg.chat.id, calculation_result)
        except ValueError:
            bot.send_message(msg.chat.id, "❌ Неверный формат. Пожалуйста, введите число, например: `7.5` или `3`")
        return

    # --- 2. Обработка кнопок и ключевых фраз ---
    if text_lower in ["💹 курс btc", "/btc"]:
        price, source = get_crypto_price("bitcoin", "usd")
        if price:
            comment = ask_gpt(f"Курс BTC ${price:,.2f}. Дай краткий, дерзкий комментарий (1 предложение) о рынке.", "gpt-3.5-turbo")
            send_message_with_partner_button(msg.chat.id, f"💰 **Курс BTC: ${price:,.2f}** (данные от {source})\n\n*{comment}*")
        else:
            bot.send_message(msg.chat.id, "❌ Не удалось получить курс BTC ни с одного источника.")
        return

    if text_lower in ["⛽️ газ eth", "/gas"]:
        send_message_with_partner_button(msg.chat.id, get_eth_gas_price())
        return

    if text_lower in ["⛏️ калькулятор", "/calc"]:
        pending_calculator_requests[user_id] = True
        # УЛУЧШЕНО: Убираем клавиатуру только на время ввода
        bot.send_message(msg.chat.id, "💡 Введите стоимость вашей электроэнергии в **рублях** за кВт/ч (например: `7.5`)", reply_markup=types.ReplyKeyboardRemove())
        return

    if text_lower in ["⚙️ топ-5 asic", "/asics"]:
        bot.send_message(msg.chat.id, "⏳ Загружаю актуальный список...")
        send_message_with_partner_button(msg.chat.id, f"**Топ-5 самых доходных ASIC на сегодня:**\n" + "\n".join(get_top_asics()))
        return

    if text_lower in ["📰 новости", "/news"]:
        bot.send_message(msg.chat.id, "⏳ Ищу свежие новости...")
        keywords = [word.upper() for word in text_lower.split() if word.upper() in ['BTC', 'ETH', 'SOL', 'MINING']]
        send_message_with_partner_button(msg.chat.id, get_crypto_news(keywords or None), disable_web_page_preview=True)
        return

    if text_lower in ["🌦️ погода", "/weather"]:
        pending_weather_requests[user_id] = True
        bot.send_message(msg.chat.id, "🌦 В каком городе показать погоду?", reply_markup=types.ReplyKeyboardRemove())
        return

    # --- 3. Универсальный конвертер валют ---
    match = re.search(r'(\S+)\s+(?:в|to|к)\s+(\S+)', text_lower)
    if match and ('курс' in text_lower or 'конверт' in text_lower):
        base_word, quote_word = match.groups()
        base_currency = CURRENCY_MAP.get(base_word)
        quote_currency = CURRENCY_MAP.get(quote_word)
        if base_currency and quote_currency:
            send_message_with_partner_button(msg.chat.id, get_currency_rate(base_currency, quote_currency))
            return

    # --- 4. Анализ объявлений ---
    sale_words = ["продам", "продать", "куплю", "купить", "в наличии", "предзаказ"]
    item_words = ["asic", "асик", "whatsminer", "antminer", "карта", "ферма"]
    if any(word in text_lower for word in sale_words) and any(word in text_lower for word in item_words):
        log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or msg.from_user.first_name, msg.text])
        analysis = ask_gpt(f"Это объявление или прайс на майнинг-оборудование. Проанализируй его как опытный трейдер или поставщик. Укажи на сильные и слабые стороны, дай краткий совет. Ответь неформально.\n\nТекст:\n{msg.text}")
        send_message_with_partner_button(msg.chat.id, analysis)
        return

    # --- 5. Если ничего не подошло, отправляем в GPT как общий вопрос ---
    bot.send_chat_action(msg.chat.id, 'typing')
    send_message_with_partner_button(msg.chat.id, ask_gpt(msg.text))


# ========================================================================================
# 6. ЗАПУСК БОТА, ВЕБХУКА И ПЛАНИРОВЩИКА
# ========================================================================================

@app.route('/' + BOT_TOKEN, methods=['POST'])
def webhook():
    """Обработчик вебхука от Telegram."""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Forbidden', 403

@app.route("/")
def index():
    """Страница для проверки, что бот запущен."""
    return "Bot is running!", 200

def run_scheduler():
    """Запускает фоновые задачи по расписанию."""
    # Задачи
    schedule.every(25).minutes.do(keep_alive)
    schedule.every(4).hours.do(auto_send_news)
    schedule.every(6).hours.do(auto_check_status)
    schedule.every(1).hours.do(get_top_asics)

    # Первый запуск сразу после старта
    logging.info("Первоначальный запуск фоновых задач...")
    get_top_asics(force_update=True)
    auto_check_status()
    keep_alive()

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    logging.info("Запуск бота...")
    if WEBHOOK_URL:
        # Установка вебхука
        logging.info("Режим вебхука. Установка...")
        bot.remove_webhook()
        time.sleep(0.5)
        bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + "/" + BOT_TOKEN)
        logging.info(f"Вебхук установлен на: {WEBHOOK_URL}")

        # Запуск планировщика в отдельном потоке
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        logging.info("Планировщик запущен.")

        # Запуск Flask-приложения
        port = int(os.environ.get('PORT', 10000))
        app.run(host="0.0.0.0", port=port)
    else:
        # Режим long-polling для локального тестирования
        logging.info("Вебхук не найден. Запуск в режиме long-polling для отладки...")
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        bot.remove_webhook()
        bot.polling(none_stop=True)

