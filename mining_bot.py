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
# НОВАЯ БИБЛИОТЕКА ДЛЯ РАБОТЫ С BINANCE API
from binance.client import Client
from binance.exceptions import BinanceAPIException

# --- Ключи и Настройки (Загрузка из переменных окружения) ---
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
NEWSAPI_KEY = os.environ.get("CRYPTO_API_KEY") # CryptoPanic API Key
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# ДОБАВЛЕНЫ КЛЮЧИ BINANCE
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.environ.get("BINANCE_SECRET_KEY")

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

# Инициализация клиента Binance, если ключи предоставлены
binance_client = None
if BINANCE_API_KEY and BINANCE_SECRET_KEY:
    try:
        binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
    except Exception as e:
        print(f"Не удалось инициализировать клиент Binance: {e}")


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

def get_crypto_price(symbol="BTC-USDT"):
    """
    УЛУЧШЕННАЯ ФУНКЦИЯ: Получает цену с Binance, при ошибке переключается на KuCoin.
    Возвращает кортеж (цена, источник).
    """
    # Попытка 1: Binance
    try:
        binance_symbol = symbol.replace('-', '')
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol.upper()}", timeout=5).json()
        if 'price' in res:
            return (float(res['price']), "Binance")
    except Exception as e:
        print(f"Ошибка API Binance: {e}. Пробую запасной вариант.")

    # Попытка 2: KuCoin (запасной вариант)
    try:
        res = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={symbol.upper()}", timeout=5).json()
        if res.get('data') and res['data'].get('price'):
            return (float(res['data']['price']), "KuCoin")
    except Exception as e:
        print(f"Ошибка API KuCoin: {e}.")
    
    return (None, None)

def get_binance_balance():
    """НОВАЯ ФУНКЦИЯ: Получает баланс аккаунта Binance, используя API ключи."""
    if not binance_client:
        return "Клиент Binance не настроен. Проверьте переменные окружения BINANCE_API_KEY и BINANCE_SECRET_KEY."

    try:
        # Получаем информацию об аккаунте
        account_info = binance_client.get_account()
        balances = account_info.get('balances', [])
        
        # Фильтруем активы, у которых есть баланс
        non_zero_balances = [b for b in balances if float(b['free']) > 0 or float(b['locked']) > 0]
        
        if not non_zero_balances:
            return "На вашем спотовом аккаунте нет активов с ненулевым балансом."

        # Получаем текущие цены для всех пар к USDT
        prices = {p['symbol']: float(p['price']) for p in binance_client.get_all_tickers() if 'USDT' in p['symbol']}
        
        # Рассчитываем стоимость каждого актива в USD
        usd_values = []
        for asset in non_zero_balances:
            total_balance = float(asset['free']) + float(asset['locked'])
            asset_name = asset['asset']
            
            if asset_name == 'USDT':
                usd_value = total_balance
            else:
                price = prices.get(f"{asset_name}USDT", 0)
                usd_value = total_balance * price
            
            if usd_value > 1: # Показываем только активы стоимостью > $1
                usd_values.append({'asset': asset_name, 'total_balance': total_balance, 'usd_value': usd_value})

        # Сортируем по стоимости в USD и берем топ-5
        top_assets = sorted(usd_values, key=lambda x: x['usd_value'], reverse=True)[:5]
        
        total_usd_value = sum(item['usd_value'] for item in usd_values)

        response_lines = [f"💎 **Общий баланс: ~${total_usd_value:,.2f}**\n\nТоп-5 активов:"]
        for asset in top_assets:
            response_lines.append(
                f"• **{asset['asset']}**: {asset['total_balance']:.6f} (~${asset['usd_value']:,.2f})"
            )
        return "\n".join(response_lines)

    except BinanceAPIException as e:
        return f"❌ Ошибка API Binance: {e.message}. Проверьте правильность ключей и их разрешения."
    except Exception as e:
        return f"❌ Произошла непредвиденная ошибка: {e}"

def get_weather(city: str):
    """Получает погоду с wttr.in."""
    try:
        r = requests.get(f"https://wttr.in/{city}?format=j1").json()
        current = r["current_condition"][0]
        return (f"🌍 {city.title()}\n🌡 Температура: {current['temp_C']}°C\n☁️ Погода: {current['weatherDesc'][0]['value']}\n💧 Влажность: {current['humidity']}%\n💨 Ветер: {current['windspeedKmph']} км/ч")
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
        full_prompt = f"Отвечай всегда на русском языке. {prompt}"
        res = openai_client.chat.completions.create(model=model, messages=[{"role": "user", "content": full_prompt}])
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
        updated_asics = [f"• {tds[0].get_text(strip=True)}: {tds[1].get_text(strip=True)}, {tds[2].get_text(strip=True)}, доход ~{tds[3].get_text(strip=True)}/день" for tds in (row.find_all("td") for row in soup.select("table tbody tr")[:5])]
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
        items = [f"🔹 {ask_gpt(f'Переведи и сократи до 1-2 предложений главную мысль этой новости: {post['title']}', 'gpt-3.5-turbo')}\n[Источник]({post.get('url', '')})" for post in posts]
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
    if not NEWS_CHAT_ID: return
    try:
        news = get_crypto_news()
        bot.send_message(NEWS_CHAT_ID, news, reply_markup=get_random_partner_button(), parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        if ADMIN_CHAT_ID: bot.send_message(ADMIN_CHAT_ID, f"⚠️ Не удалось выполнить авторассылку новостей:\n{e}")

def auto_check_status():
    """Задача для проверки работоспособности систем и отправки отчета админу."""
    if not ADMIN_CHAT_ID: return
    errors = []
    if "ошибка" in ask_gpt("Тест", "gpt-3.5-turbo").lower(): errors.append("API OpenAI (GPT) вернул ошибку.")
    try: get_gsheet()
    except Exception: errors.append("Не удалось подключиться к Google Sheets.")
    if "ошибка" in get_crypto_news().lower(): errors.append("API новостей (CryptoPanic) вернул ошибку.")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not errors: status_msg = f"✅ **Плановая проверка ({ts})**\n\nВсе системы работают в штатном режиме."
    else: status_msg = f"⚠️ **Плановая проверка ({ts})**\n\nОбнаружены проблемы:\n" + "\n".join([f"🚨 {e}" for e in errors])
    try: bot.send_message(ADMIN_CHAT_ID, status_msg, parse_mode="Markdown")
    except Exception as e: print(f"-> Не удалось отправить отчет админу: {e}")

# ========================================================================================
# 5. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ TELEGRAM
# ========================================================================================

@bot.message_handler(commands=['start'])
def handle_start(msg):
    bot.send_message(msg.chat.id, "👋 Привет! Я ваш помощник в мире криптовалют и майнинга. Задайте вопрос или используйте команду `/help`.")

@bot.message_handler(commands=['help'])
def handle_help(msg):
    help_text = (
        "**Доступные команды:**\n"
        "`/price [ПАРА]` - узнать курс криптовалюты (например, `/price ETH-USDT`). По умолчанию - BTC.\n"
        "`/balance` - проверить баланс (только в приватном чате со мной).\n"
        "`/chart` - построить график доходности из Google Sheets.\n"
        "\n**Просто напишите мне:**\n"
        "- `курс btc` - узнать курс биткоина с комментарием.\n"
        "- `курс доллара к рублю` - конвертер валют.\n"
        "- `новости` или `новости BTC` - получить свежие крипто-новости.\n"
        "- `погода` - узнать погоду."
    )
    bot.send_message(msg.chat.id, help_text, parse_mode="Markdown")

@bot.message_handler(commands=['price'])
def handle_price(msg):
    try:
        pair_text = msg.text.split()[1].upper()
    except IndexError:
        pair_text = "BTC-USDT"
    price, source = get_crypto_price(pair_text)
    if price:
        bot.send_message(msg.chat.id, f"💹 Курс {pair_text.replace('-', '/')}: ${price:,.2f} (данные от {source})")
    else:
        bot.send_message(msg.chat.id, f"❌ Не удалось получить курс для {pair_text} ни с одного источника.")

@bot.message_handler(commands=['balance'])
def handle_balance(msg):
    """
    ИСПРАВЛЕННЫЙ ОБРАБОТЧИК: для получения баланса с проверкой на приватность.
    """
    if msg.chat.type != 'private':
        bot.reply_to(msg, "🔒 В целях безопасности, команда `/balance` работает только в личном чате со мной. Пожалуйста, напишите мне напрямую.")
        return

    bot.send_message(msg.chat.id, "⏳ Получаю данные о балансе... Это может занять несколько секунд.")
    balance_report = get_binance_balance()
    bot.send_message(msg.chat.id, balance_report, parse_mode="Markdown")

@bot.message_handler(commands=['chart'])
def handle_chart(msg):
    bot.send_message(msg.chat.id, "⏳ Строю график...")
    try:
        sheet = get_gsheet()
        records = sheet.get_all_values()[1:]
        dates, profits = [], []
        for r in records:
            try:
                date_obj = datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
                profit_str = re.search(r'\$(\d+\.?\d*)', r[2])
                if profit_str:
                    profits.append(float(profit_str.group(1)))
                    dates.append(date_obj)
            except (ValueError, IndexError, TypeError): continue
        if not dates or len(dates) < 2:
            bot.send_message(msg.chat.id, "Недостаточно данных для графика. Нужно минимум 2 записи с датой и суммой в '$'.")
            return
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(dates, profits, marker='o', linestyle='-', color='#00aaff')
        ax.set_title('Динамика доходности', fontsize=16, color='white')
        ax.tick_params(axis='x', colors='white', rotation=30); ax.tick_params(axis='y', colors='white')
        fig.tight_layout()
        buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=150, transparent=True); buf.seek(0)
        bot.send_photo(msg.chat.id, buf, caption="📈 График доходности на основе ваших данных.")
        plt.close(fig)
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ Не удалось построить график: {e}")

@bot.message_handler(func=lambda msg: True)
def handle_all_messages(msg):
    user_id = msg.from_user.id
    text_lower = msg.text.lower()

    if pending_weather_requests.get(user_id):
        del pending_weather_requests[user_id]; bot.send_message(msg.chat.id, get_weather(msg.text)); return
    if "погода" in text_lower:
        pending_weather_requests[user_id] = True; bot.send_message(msg.chat.id, "🌦 В каком городе показать погоду?"); return

    if 'курс' in text_lower and ('btc' in text_lower or 'биткоин' in text_lower or 'втс' in text_lower):
        price, source = get_crypto_price("BTC-USDT")
        if price:
            comment = ask_gpt(f"Курс BTC ${price:,.2f}. Дай краткий, дерзкий комментарий (1 предложение) о рынке.", "gpt-3.5-turbo")
            bot.send_message(msg.chat.id, f"💰 **Курс BTC: ${price:,.2f}** (данные от {source})\n\n*{comment}*", parse_mode="Markdown")
        else:
            bot.send_message(msg.chat.id, "❌ Не удалось получить курс BTC ни с одного источника.")
        return

    currency_pair = parse_currency_pair(text_lower)
    if currency_pair:
        bot.send_message(msg.chat.id, get_currency_rate(*currency_pair)); return

    if "новости" in text_lower:
        keywords = [word.upper() for word in text_lower.split() if word.upper() in ['BTC', 'ETH', 'SOL', 'MINING']]
        news = get_crypto_news(keywords or None)
        bot.send_message(msg.chat.id, news, parse_mode="Markdown", disable_web_page_preview=True); return

    if any(x in text_lower for x in ["продам", "в наличии", "предзаказ", "$"]):
        log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or msg.from_user.first_name, msg.text])
        analysis = ask_gpt(f"Это прайс на майнинг-оборудование. Проанализируй как трейдер: выгодные предложения, актуальность цен, подозрительно дешевые позиции. Ответь кратко, без формальностей.\n\nТекст:\n{msg.text}")
        bot.send_message(msg.chat.id, analysis); return

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
    if request.headers.get('content-type') == 'application/json':
        bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
        return '', 200
    return 'Forbidden', 403

@app.route("/")
def index():
    return "Bot is running!", 200

def run_scheduler():
    get_top_asics()
    auto_check_status()
    schedule.every(3).hours.do(auto_send_news)
    schedule.every(3).hours.do(auto_check_status)
    schedule.every(1).hours.do(get_top_asics)
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    if WEBHOOK_URL:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + "/webhook")
    
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)
