import os
import telebot
import requests
import time
import threading
import schedule
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

# --- Ключи и Настройки (Загрузка из переменных окружения) ---
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
NEWSAPI_KEY = os.environ.get("CRYPTO_API_KEY") # CryptoPanic API Key
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

NEWS_CHAT_ID = os.environ.get("NEWS_CHAT_ID") # Канал для новостей
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID") # ID админа для отчетов

GOOGLE_JSON_PATH = os.environ.get("GOOGLE_JSON", "sage-instrument.json")
SHEET_ID = os.environ.get("SHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "Лист1")

# --- Настройки Партнерской Ссылки ---
PARTNER_URL = "https://app.leadteh.ru/w/dTeKr"
PARTNER_BUTTON_TEXT_OPTIONS = [
    "🎁 Узнать спеццены", "🔥 Эксклюзивное предложение",
    "💡 Получить консультацию", "💎 Прайс от экспертов"
]

# --- Глобальные переменные и кэш ---
if not BOT_TOKEN:
    raise ValueError("Критическая ошибка: не найдена переменная окружения TG_BOT_TOKEN")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
pending_weather_requests = {}
asic_cache = {"data": [], "timestamp": None}

# Словарь для универсального парсера валют
CURRENCY_MAP = {
    'доллар': 'USD', 'usd': 'USD', '$': 'USD',
    'евро': 'EUR', 'eur': 'EUR', '€': 'EUR',
    'рубль': 'RUB', 'rub': 'RUB', '₽': 'RUB',
    'юань': 'CNY', 'cny': 'CNY',
    'биткоин': 'BTC', 'btc': 'BTC',
    'эфир': 'ETH', 'eth': 'ETH',
}

# ========================================================================================
# 2. ФУНКЦИИ ДЛЯ РАБОТЫ С ВНЕШНИМИ API И СЕРВИСАМИ
# ========================================================================================

def get_gsheet():
    """Подключается к Google Sheets и возвращает объект листа."""
    try:
        creds = Credentials.from_service_account_file(GOOGLE_JSON_PATH, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        gc = gspread.authorize(creds)
        return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    except Exception as e:
        print(f"Ошибка подключения к Google Sheets: {e}")
        raise

def log_to_sheet(row_data: list):
    """Логирует данные в новую строку Google Sheets."""
    try:
        sheet = get_gsheet()
        sheet.append_row(row_data, value_input_option='USER_ENTERED')
    except Exception as e:
        print(f"Ошибка записи в Google Sheets: {e}")

def get_binance_price(symbol="BTCUSDT"):
    """Получает цену указанной пары с Binance."""
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.upper()}").json()
        return float(res['price']) if 'price' in res else None
    except Exception:
        return None

def get_weather(city: str):
    """Получает погоду с wttr.in."""
    try:
        r = requests.get(f"https://wttr.in/{city}?format=j1").json()
        current = r["current_condition"][0]
        return (
            f"🌍 {city.title()}\n"
            f"🌡 Температура: {current['temp_C']}°C\n"
            f"☁️ Погода: {current['weatherDesc'][0]['value']}\n"

            f"💧 Влажность: {current['humidity']}%\n"
            f"💨 Ветер: {current['windspeedKmph']} км/ч"
        )
    except Exception as e:
        return f"[❌ Ошибка получения погоды: {e}]"

def get_currency_rate(base="USD", to="EUR"):
    """Получает курс валют с exchangerate.host."""
    try:
        res = requests.get(f"https://api.exchangerate.host/latest?base={base.upper()}&symbols={to.upper()}").json()
        rate = res['rates'][to.upper()]
        return f"💱 {base.upper()} → {to.upper()} = {rate:.2f}"
    except Exception as e:
        return f"[❌ Ошибка получения курса: {e}]"

def ask_gpt(prompt: str, model: str = "gpt-4o"):
    """Отправляет запрос к OpenAI GPT."""
    try:
        res = openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"[❌ Ошибка GPT: {e}]"

def get_top_asics():
    """Получает топ-5 ASIC'ов с asicminervalue.com, использует кэш (1 час)."""
    global asic_cache
    now = datetime.now()
    if asic_cache["data"] and asic_cache["timestamp"] and (now - asic_cache["timestamp"] < timedelta(hours=1)):
        return asic_cache["data"]

    try:
        r = requests.get("https://www.asicminervalue.com/miners/sha-256", timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        updated_asics = [
            f"• {tds[0].get_text(strip=True)}: {tds[1].get_text(strip=True)}, {tds[2].get_text(strip=True)}, доход ~{tds[3].get_text(strip=True)}/день"
            for tds in (row.find_all("td") for row in soup.select("table tbody tr")[:5])
        ]
        
        asic_cache = {"data": updated_asics, "timestamp": now}
        return updated_asics
    except Exception as e:
        return [f"[❌ Ошибка обновления ASIC: {e}]"]

def get_crypto_news(keywords: list = None):
    """Получает 3 новости с CryptoPanic, с возможностью фильтрации."""
    try:
        params = {"auth_token": NEWSAPI_KEY, "public": "true"}
        params["currencies"] = ",".join(keywords).upper() if keywords else "BTC,ETH"

        r = requests.get("https://cryptopanic.com/api/v1/posts/", params=params).json()
        posts = r.get("results", [])[:3]

        if not posts: return "[🧐 Новостей по вашему запросу не найдено]"
            
        items = [
            f"🔹 {ask_gpt(f'Переведи и сократи до 1-2 предложений главную мысль этой новости: {post['title']}', 'gpt-3.5-turbo')}\n[Источник]({post.get('url', '')})"
            for post in posts
        ]
        return "\n\n".join(items) if items else "[🤷‍♂️ Свежих новостей нет]"
    except Exception as e:
        return f"[❌ Ошибка получения новостей: {e}]"

# ========================================================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И УТИЛИТЫ
# ========================================================================================

def parse_currency_pair(text: str):
    """Извлекает пару валют из текста вроде 'курс доллара к рублю'."""
    match = re.search(r'(\w+|\$|€|₽)\s+к\s+(\w+|\$|€|₽)', text.lower())
    if not match: return None
    
    base = CURRENCY_MAP.get(match.group(1))
    quote = CURRENCY_MAP.get(match.group(2))
    return (base, quote) if base and quote else None

def get_random_partner_button():
    """Создает инлайн-кнопку со случайным текстом."""
    markup = types.InlineKeyboardMarkup()
    button_text = random.choice(PARTNER_BUTTON_TEXT_OPTIONS)
    markup.add(types.InlineKeyboardButton(button_text, url=PARTNER_URL))
    return markup

# ========================================================================================
# 4. ЗАДАЧИ, ВЫПОЛНЯЕМЫЕ ПО РАСПИСАНИЮ (SCHEDULE)
# ========================================================================================

def auto_send_news():
    """Задача для отправки новостей в канал."""
    print(f"[{datetime.now()}] Запуск авторассылки новостей...")
    if not NEWS_CHAT_ID: return

    try:
        news = get_crypto_news()
        bot.send_message(NEWS_CHAT_ID, news, reply_markup=get_random_partner_button(), parse_mode="Markdown", disable_web_page_preview=True)
        print("-> Новости успешно отправлены.")
    except Exception as e:
        print(f"-> Ошибка при авторассылке новостей: {e}")
        if ADMIN_CHAT_ID:
            bot.send_message(ADMIN_CHAT_ID, f"⚠️ Не удалось выполнить авторассылку новостей:\n{e}")

def auto_check_status():
    """Задача для проверки работоспособности систем и отправки отчета админу."""
    print(f"[{datetime.now()}] Запуск проверки состояния систем...")
    if not ADMIN_CHAT_ID: return

    errors = []
    # Проверка ключевых API
    try:
        if "ошибка" in ask_gpt("Тест", "gpt-3.5-turbo").lower(): errors.append("API OpenAI (GPT) вернул ошибку.")
    except Exception: errors.append("Не удалось подключиться к OpenAI.")
    
    try: get_gsheet()
    except Exception: errors.append("Не удалось подключиться к Google Sheets.")
        
    try:
        if "ошибка" in get_crypto_news().lower(): errors.append("API новостей (CryptoPanic) вернул ошибку.")
    except Exception: errors.append("Не удалось подключиться к CryptoPanic.")
    
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not errors:
        status_msg = f"✅ **Плановая проверка ({ts})**\n\nВсе системы работают в штатном режиме."
    else:
        status_msg = f"⚠️ **Плановая проверка ({ts})**\n\nОбнаружены проблемы:\n" + "\n".join([f"🚨 {e}" for e in errors])
        
    try:
        bot.send_message(ADMIN_CHAT_ID, status_msg, parse_mode="Markdown")
        print("-> Отчет о состоянии отправлен админу.")
    except Exception as e:
        print(f"-> Не удалось отправить отчет админу: {e}")

# ========================================================================================
# 5. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ TELEGRAM
# ========================================================================================

@bot.message_handler(commands=['start'])
def handle_start(msg):
    bot.send_message(msg.chat.id, "👋 Привет! Я ваш помощник в мире криптовалют и майнинга. Задайте вопрос или используйте команду.")

@bot.message_handler(commands=['price'])
def handle_price(msg):
    """Обрабатывает запрос курса /price [ПАРА], например /price ETH-USDT"""
    try:
        pair = msg.text.split()[1].replace('-', '').upper()
    except IndexError:
        pair = "BTCUSDT" # По умолчанию
    
    price = get_binance_price(pair)
    if price:
        bot.send_message(msg.chat.id, f"💹 Курс {pair} по Binance: ${price:,.2f}")
    else:
        bot.send_message(msg.chat.id, f"Не удалось найти пару {pair}. Попробуйте формат `BTCUSDT` или `ETHUSDT`.")

@bot.message_handler(commands=['chart'])
def handle_chart(msg):
    """Рисует график доходности из Google Sheets."""
    bot.send_message(msg.chat.id, "⏳ Строю график... Это может занять некоторое время.")
    try:
        sheet = get_gsheet()
        records = sheet.get_all_values()[1:]
        
        dates, profits = [], []
        for r in records:
            try:
                # Ожидаем дату в столбце 1 (A), текст с ценой в столбце 3 (C)
                date_obj = datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
                profit_str = re.search(r'\$(\d+\.?\d*)', r[2])
                if profit_str:
                    profits.append(float(profit_str.group(1)))
                    dates.append(date_obj)
            except (ValueError, IndexError, TypeError):
                continue

        if not dates or len(dates) < 2:
            bot.send_message(msg.chat.id, "Недостаточно данных для графика. Нужно минимум 2 записи с датой и суммой в '$'.")
            return

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(dates, profits, marker='o', linestyle='-', color='#00aaff')
        ax.set_title('Динамика доходности', fontsize=16, color='white')
        ax.set_xlabel('Дата', fontsize=12, color='white')
        ax.set_ylabel('Доход, USD', fontsize=12, color='white')
        ax.grid(True, which='both', linestyle='--', linewidth=0.5)
        ax.tick_params(axis='x', colors='white', rotation=30)
        ax.tick_params(axis='y', colors='white')
        fig.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, transparent=True)
        buf.seek(0)
        bot.send_photo(msg.chat.id, buf, caption="📈 График доходности на основе ваших данных.")
        plt.close(fig)

    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ Не удалось построить график: {e}")
        if ADMIN_CHAT_ID:
            bot.send_message(ADMIN_CHAT_ID, f"⚠️ Ошибка при построении графика для пользователя {msg.from_user.id}:\n{e}")

@bot.message_handler(func=lambda msg: True)
def handle_all_messages(msg):
    user_id = msg.from_user.id
    text_lower = msg.text.lower()

    if pending_weather_requests.get(user_id):
        del pending_weather_requests[user_id]
        bot.send_message(msg.chat.id, get_weather(msg.text))
        return

    if "погода" in text_lower:
        pending_weather_requests[user_id] = True
        bot.send_message(msg.chat.id, "🌦 В каком городе показать погоду?")
        return

    if any(k in text_lower for k in ["курс btc", "курс биткоина"]):
        price = get_binance_price("BTCUSDT")
        if price:
            comment = ask_gpt(f"Курс BTC ${price:,.2f}. Дай краткий, дерзкий комментарий (1 предложение) о рынке.", "gpt-3.5-turbo")
            bot.send_message(msg.chat.id, f"💰 **Курс BTC: ${price:,.2f}**\n\n*{comment}*")
        else:
            bot.send_message(msg.chat.id, "❌ Не удалось получить курс BTC.")
        return

    currency_pair = parse_currency_pair(text_lower)
    if currency_pair:
        bot.send_message(msg.chat.id, get_currency_rate(*currency_pair))
        return

    if "новости" in text_lower:
        keywords = [word.upper() for word in text_lower.split() if word.upper() in ['BTC', 'ETH', 'SOL', 'MINING']]
        news = get_crypto_news(keywords or None)
        bot.send_message(msg.chat.id, news, parse_mode="Markdown", disable_web_page_preview=True)
        return

    if any(x in text_lower for x in ["продам", "в наличии", "предзаказ", "$"]):
        log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or msg.from_user.first_name, msg.text])
        analysis_prompt = f"Это прайс на майнинг-оборудование. Проанализируй как трейдер: выгодные предложения, актуальность цен, подозрительно дешевые позиции. Ответь кратко, без формальностей.\n\nТекст:\n{msg.text}"
        bot.send_message(msg.chat.id, ask_gpt(analysis_prompt))
        return

    if any(k in text_lower for k in ["asic", "асик", "модель", "розетка", "доходность"]):
        models_info = "\n".join(get_top_asics())
        prompt = f"Ты — консультант по майнингу. Вот свежие данные о топ-5 ASIC:\n{models_info}\n\nИспользуй только эти данные. Ответь на вопрос кратко и по делу.\nВопрос: {msg.text}"
    else:
        prompt = msg.text

    try:
        answer = ask_gpt(prompt)
        bot.send_message(msg.chat.id, answer, reply_markup=get_random_partner_button(), parse_mode="Markdown")
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ Произошла ошибка при обработке запроса: {e}")

# ========================================================================================
# 6. ЗАПУСК БОТА, ВЕБХУКА И ПЛАНИРОВЩИКА
# ========================================================================================

@app.route('/webhook', methods=['POST'])
def webhook():
    """Принимает обновления от Telegram."""
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
        return '', 200
    return 'Forbidden', 403

@app.route("/")
def index():
    """Простая страница, чтобы видеть, что бот запущен."""
    return "Bot is running!", 200

def run_scheduler():
    """Бесконечный цикл для выполнения задач по расписанию."""
    # Запуск задач сразу после старта, чтобы не ждать 3 часа
    get_top_asics()
    auto_check_status()

    # Настройка расписания
    schedule.every(3).hours.do(auto_send_news)
    schedule.every(3).hours.do(auto_check_status)
    schedule.every(1).hours.do(get_top_asics) # Обновление кэша асиков

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    # Установка вебхука
    if WEBHOOK_URL:
        print(f"Установка вебхука на: {WEBHOOK_URL}")
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + "/webhook")
        print("Вебхук успешно установлен.")
    else:
        print("Переменная WEBHOOK_URL не установлена. Бот не будет работать через вебхук.")
    
    # Запуск планировщика в отдельном потоке
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    # Запуск Flask-приложения
    port = int(os.environ.get('PORT', 10000))
    print(f"Запуск Flask приложения на порту {port}")
    app.run(host="0.0.0.0", port=port)
