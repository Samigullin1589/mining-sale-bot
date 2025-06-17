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
import json # ИСПРАВЛЕНО: Добавлен импорт json
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
ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "YourApiKeyToken")

NEWS_CHAT_ID = os.environ.get("NEWS_CHAT_ID") # Канал для новостей
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID") # ID админа для отчетов

# ИСПРАВЛЕНО: Теперь ключ читается как текстовая переменная, а не как путь к файлу
GOOGLE_JSON_STR = os.environ.get("GOOGLE_JSON")
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
    """ИСПРАВЛЕНО: Подключается к Google Sheets используя ключи из переменной окружения."""
    if not GOOGLE_JSON_STR:
        print("Ошибка: переменная окружения GOOGLE_JSON не установлена.")
        raise ValueError("Ключи Google Sheets не найдены.")
    try:
        creds_dict = json.loads(GOOGLE_JSON_STR)
        creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])
        gc = gspread.authorize(creds)
        return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    except json.JSONDecodeError:
        print("Ошибка: неверный формат JSON в переменной GOOGLE_JSON.")
        raise
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

def get_crypto_price(coin_id="bitcoin", vs_currency="usd"):
    """
    ТРОЙНОЕ РЕЗЕРВИРОВАНИЕ: Получает цену с Binance, при ошибке -> KuCoin, при ошибке -> CoinGecko.
    Возвращает кортеж (цена, источник).
    """
    try:
        res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5).json()
        if 'price' in res: return (float(res['price']), "Binance")
    except Exception as e: print(f"Ошибка API Binance: {e}. Пробую KuCoin.")
    try:
        res = requests.get(f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol=BTC-USDT", timeout=5).json()
        if res.get('data') and res['data'].get('price'): return (float(res['data']['price']), "KuCoin")
    except Exception as e: print(f"Ошибка API KuCoin: {e}. Пробую CoinGecko.")
    try:
        res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies={vs_currency}", timeout=5).json()
        if coin_id in res and vs_currency in res[coin_id]: return (float(res[coin_id][vs_currency]), "CoinGecko")
    except Exception as e: print(f"Ошибка API CoinGecko: {e}.")
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
        else: return "[❌ Не удалось получить данные о газе с Etherscan]"
    except Exception as e: return f"[❌ Ошибка при запросе цены на газ: {e}]"

def get_weather(city: str):
    try:
        r = requests.get(f"https://wttr.in/{city}?format=j1").json()
        current = r["current_condition"][0]
        return (f"🌍 {city.title()}\n🌡 Температура: {current['temp_C']}°C\n☁️ Погода: {current['weatherDesc'][0]['value']}\n💧 Влажность: {current['humidity']}%\n💨 Ветер: {current['windspeedKmph']} км/ч")
    except Exception as e: return f"[❌ Ошибка получения погоды: {e}]"

def get_currency_rate(base="USD", to="EUR"):
    try:
        res = requests.get(f"https://api.exchangerate.host/latest?base={base.upper()}&symbols={to.upper()}").json()
        if res.get('rates') and res['rates'].get(to.upper()):
            return f"� {base.upper()} → {to.upper()} = {res['rates'][to.upper()]:.2f}"
        return f"[❌ Не удалось получить курс для {base.upper()} к {to.upper()}]"
    except Exception as e: return f"[❌ Ошибка получения курса: {e}]"

def ask_gpt(prompt: str, model: str = "gpt-4o"):
    try:
        res = openai_client.chat.completions.create(model=model, messages=[{"role": "user", "content": f"Отвечай всегда на русском языке. {prompt}"}])
        return res.choices[0].message.content.strip()
    except Exception as e: return f"[❌ Ошибка GPT: {e}]"

def get_top_asics():
    global asic_cache
    if asic_cache["data"] and asic_cache["timestamp"] and (datetime.now() - asic_cache["timestamp"] < timedelta(hours=1)):
        return asic_cache["data"]
    try:
        r = requests.get("https://www.asicminervalue.com/miners/sha-256", timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        updated_asics = [f"• {tds[0].get_text(strip=True)}: {tds[1].get_text(strip=True)}, {tds[2].get_text(strip=True)}, доход ~{tds[3].get_text(strip=True)}/день" for tds in (row.find_all("td") for row in soup.select("table tbody tr")[:5])]
        asic_cache = {"data": updated_asics, "timestamp": datetime.now()}
        return updated_asics
    except Exception as e: return [f"[❌ Ошибка обновления ASIC: {e}]"]

def get_crypto_news(keywords: list = None):
    try:
        params = {"auth_token": NEWSAPI_KEY, "public": "true", "currencies": ",".join(keywords).upper() if keywords else "BTC,ETH"}
        r = requests.get("https://cryptopanic.com/api/v1/posts/", params=params).json()
        posts = r.get("results", [])[:3]
        if not posts: return "[🧐 Новостей по вашему запросу не найдено]"
        items = [f"🔹 {ask_gpt(f'Переведи и сократи до 1-2 предложений главную мысль этой новости: {post['title']}', 'gpt-3.5-turbo')}\n[Источник]({post.get('url', '')})" for post in posts]
        return "\n\n".join(items) if items else "[🤷‍♂️ Свежих новостей нет]"
    except Exception as e: return f"[❌ Ошибка получения новостей: {e}]"

# ========================================================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И УТИЛИТЫ
# ========================================================================================

def get_main_keyboard():
    """Создает основную клавиатуру с кнопками."""
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(types.KeyboardButton("💹 Курс BTC"), types.KeyboardButton("⛽️ Газ ETH"),
               types.KeyboardButton("⚙️ Топ-5 ASIC"), types.KeyboardButton("⛏️ Калькулятор"),
               types.KeyboardButton("📰 Новости"), types.KeyboardButton("🌦️ Погода"))
    return markup

def get_random_partner_button():
    """Создает инлайн-кнопку со случайным текстом."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))
    return markup
    
def send_message_with_partner_button(chat_id, text, **kwargs):
    """Обертка для отправки сообщения с прикрепленной партнерской кнопкой."""
    kwargs.setdefault('parse_mode', 'Markdown')
    kwargs.setdefault('reply_markup', get_random_partner_button())
    bot.send_message(chat_id, text, **kwargs)

def calculate_and_format_profit(electricity_cost_rub: float):
    """ИСПРАВЛЕНО: Расчет и форматирование доходности ASIC с конвертацией из рублей."""
    # Получаем курс USD к RUB
    try:
        rate_info = requests.get(f"https://api.exchangerate.host/latest?base=USD&symbols=RUB").json()
        usd_to_rub_rate = rate_info['rates']['RUB']
    except Exception as e:
        print(f"Ошибка получения курса USD/RUB для калькулятора: {e}")
        return "Не удалось получить курс доллара для расчета. Попробуйте позже."

    electricity_cost_usd = electricity_cost_rub / usd_to_rub_rate
    
    asics_data = get_top_asics()
    if not asics_data or "Ошибка" in asics_data[0]:
        return "Не удалось получить данные по ASIC для расчета. Попробуйте позже."

    result = [f"💰 **Расчет чистой прибыли при цене розетки {electricity_cost_rub:.2f} ₽/кВтч (~${electricity_cost_usd:.3f}/кВтч)**\n"]
    for asic_string in asics_data:
        try:
            name_match = re.search(r"•\s(.*?):", asic_string)
            power_match = re.search(r"(\d+W)", asic_string)
            revenue_match = re.search(r"\$([\d\.]+)", asic_string)
            
            if not all([name_match, power_match, revenue_match]): continue
                
            name = name_match.group(1).strip()
            power_watts = float(power_match.group(1).replace('W', ''))
            daily_revenue = float(revenue_match.group(1))

            daily_power_kwh = (power_watts / 1000) * 24
            daily_electricity_cost = daily_power_kwh * electricity_cost_usd
            net_profit = daily_revenue - daily_electricity_cost

            result.append(
                f"**{name}**\n"
                f"  - Доход: `${daily_revenue:.2f}`\n"
                f"  - Расход: `${daily_electricity_cost:.2f}`\n"
                f"  - **Чистая прибыль: `${net_profit:.2f}`/день**"
            )
        except Exception as e:
            print(f"Ошибка парсинга ASIC для калькулятора: {e}")
            continue
    
    return "\n".join(result)

# ========================================================================================
# 4. ЗАДАЧИ, ВЫПОЛНЯЕМЫЕ ПО РАСПИСАНИЮ (SCHEDULE)
# ========================================================================================

def keep_alive():
    """Отправляет запрос самому себе, чтобы приложение не "засыпало" на хостинге."""
    if WEBHOOK_URL:
        try:
            requests.get(WEBHOOK_URL.rsplit('/', 1)[0])
            print(f"[{datetime.now()}] Keep-alive пинг отправлен.")
        except Exception as e: print(f"Ошибка keep-alive пинга: {e}")

def auto_send_news():
    if not NEWS_CHAT_ID: return
    try:
        news = get_crypto_news()
        send_message_with_partner_button(NEWS_CHAT_ID, news, disable_web_page_preview=True)
        print(f"[{datetime.now()}] Новости успешно отправлены в чат {NEWS_CHAT_ID}")
    except Exception as e:
        print(f"[{datetime.now()}] Ошибка при авторассылке новостей: {e}")
        if ADMIN_CHAT_ID: bot.send_message(ADMIN_CHAT_ID, f"⚠️ Не удалось выполнить авторассылку новостей:\n{e}")

def auto_check_status():
    if not ADMIN_CHAT_ID: return
    errors = []
    if "ошибка" in ask_gpt("Тест", "gpt-3.5-turbo").lower(): errors.append("API OpenAI (GPT) вернул ошибку.")
    try: get_gsheet()
    except Exception: errors.append("Не удалось подключиться к Google Sheets.")
    if "ошибка" in get_crypto_news().lower(): errors.append("API новостей (CryptoPanic) вернул ошибку.")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_msg = f"✅ **Плановая проверка ({ts})**\n\nВсе системы работают." if not errors else f"⚠️ **Проблемы ({ts}):**\n" + "\n".join([f"🚨 {e}" for e in errors])
    try: bot.send_message(ADMIN_CHAT_ID, status_msg, parse_mode="Markdown")
    except Exception as e: print(f"-> Не удалось отправить отчет админу: {e}")

# ========================================================================================
# 5. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ TELEGRAM
# ========================================================================================

@bot.message_handler(commands=['start', 'help'])
def handle_start_help(msg):
    help_text = ("👋 Привет! Я ваш помощник в мире криптовалют и майнинга.\n\n"
                 "Используйте кнопки ниже или отправьте мне команду.\n\n"
                 "**Основные команды:**\n"
                 "`/price [ПАРА]` - узнать курс (по умолчанию - BTC).\n"
                 "`/chart` - построить график доходности из Google Sheets.")
    bot.send_message(msg.chat.id, help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['price'])
def handle_price(msg):
    try: pair_text = msg.text.split()[1].upper()
    except IndexError: pair_text = "BTC-USDT"
    price, source = get_crypto_price(pair_text.split('-')[0].lower(), "usd")
    if price: send_message_with_partner_button(msg.chat.id, f"💹 Курс {pair_text.replace('-', '/')}: ${price:,.2f} (данные от {source})")
    else: bot.send_message(msg.chat.id, f"❌ Не удалось получить курс для {pair_text} ни с одного источника.")

@bot.message_handler(commands=['chart'])
def handle_chart(msg):
    bot.send_message(msg.chat.id, "⏳ Строю график...")
    try:
        sheet = get_gsheet()
        records = sheet.get_all_values()[1:]
        dates, profits = [], []
        error_lines = []
        for i, r in enumerate(records):
            try:
                if not r or not r[0] or not r[2]: continue
                date_obj = datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S")
                profit_str = re.search(r'\$(\d+\.?\d*)', r[2])
                if profit_str:
                    profits.append(float(profit_str.group(1)))
                    dates.append(date_obj)
            except (ValueError, IndexError):
                error_lines.append(str(i + 2))
                continue
        if not dates or len(dates) < 2:
            bot.send_message(msg.chat.id, "Недостаточно данных для графика. Нужно минимум 2 корректные записи.")
            return

        if error_lines:
            bot.send_message(msg.chat.id, f"⚠️ **Предупреждение:** Не удалось обработать строки: {', '.join(error_lines)}. Убедитесь, что дата в формате `ГГГГ-ММ-ДД ЧЧ:ММ:СС` и в тексте есть цена в `$`. График построен по остальным данным.")

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(dates, profits, marker='o', linestyle='-', color='#00aaff'); ax.set_title('Динамика доходности', fontsize=16, color='white'); ax.tick_params(axis='x', colors='white', rotation=30); ax.tick_params(axis='y', colors='white'); fig.tight_layout()
        buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=150, transparent=True); buf.seek(0)
        bot.send_photo(msg.chat.id, buf, caption="📈 График доходности на основе ваших данных.")
        plt.close(fig)
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ Не удалось построить график: {e}")

@bot.message_handler(content_types=['text'])
def handle_all_text_messages(msg):
    user_id = msg.from_user.id
    text_lower = msg.text.lower()

    # --- Обработка состояний (ожидание ввода) ---
    if pending_weather_requests.get(user_id):
        del pending_weather_requests[user_id]
        send_message_with_partner_button(msg.chat.id, get_weather(msg.text), reply_markup=get_main_keyboard())
        return

    if pending_calculator_requests.get(user_id):
        try:
            electricity_cost = float(text_lower.replace(',', '.'))
            del pending_calculator_requests[user_id]
            calculation_result = calculate_and_format_profit(electricity_cost)
            send_message_with_partner_button(msg.chat.id, calculation_result, reply_markup=get_main_keyboard())
        except ValueError:
            bot.send_message(msg.chat.id, "❌ Неверный формат. Пожалуйста, введите число, например: `7.5`")
        return

    # --- Обработка кнопок и ключевых фраз ---
    if 'курс btc' in text_lower or 'курс' in text_lower and ('биткоин' in text_lower or 'бтс' in text_lower or 'втс' in text_lower):
        price, source = get_crypto_price("bitcoin", "usd")
        if price:
            comment = ask_gpt(f"Курс BTC ${price:,.2f}. Дай краткий, дерзкий комментарий (1 предложение) о рынке.", "gpt-3.5-turbo")
            send_message_with_partner_button(msg.chat.id, f"💰 **Курс BTC: ${price:,.2f}** (данные от {source})\n\n*{comment}*")
        else: bot.send_message(msg.chat.id, "❌ Не удалось получить курс BTC ни с одного источника.")
        return
        
    if 'газ eth' in text_lower:
        send_message_with_partner_button(msg.chat.id, get_eth_gas_price())
        return
        
    if 'калькулятор' in text_lower:
        pending_calculator_requests[user_id] = True
        bot.send_message(msg.chat.id, "💡 Введите стоимость вашей электроэнергии в **рублях** за кВт/ч (например: `7.5`)", reply_markup=types.ReplyKeyboardRemove())
        return

    if 'топ-5 asic' in text_lower:
        send_message_with_partner_button(msg.chat.id, f"**Топ-5 самых доходных ASIC на сегодня:**\n" + "\n".join(get_top_asics()))
        return
        
    if 'новости' in text_lower:
        keywords = [word.upper() for word in text_lower.split() if word.upper() in ['BTC', 'ETH', 'SOL', 'MINING']]
        send_message_with_partner_button(msg.chat.id, get_crypto_news(keywords or None), disable_web_page_preview=True)
        return

    if 'погода' in text_lower:
        pending_weather_requests[user_id] = True
        bot.send_message(msg.chat.id, "🌦 В каком городе показать погоду?", reply_markup=types.ReplyKeyboardRemove())
        return

    # ИСПРАВЛЕНО: Более надежный триггер для конвертера валют
    match = re.search(r'(\w+)\s+к\s+(\w+)', text_lower)
    if match and ('курс' in text_lower or len(match.groups())==2):
        base_word = match.group(1)
        quote_word = match.group(2)
        base_currency = CURRENCY_MAP.get(base_word)
        quote_currency = CURRENCY_MAP.get(quote_word)
        if base_currency and quote_currency:
            send_message_with_partner_button(msg.chat.id, get_currency_rate(base_currency, quote_currency))
            return

    sale_words = ["продам", "продать", "куплю", "купить", "в наличии", "предзаказ"]
    item_words = ["asic", "асик", "$", "whatsminer", "antminer"]
    if any(word in text_lower for word in sale_words) and any(word in text_lower for word in item_words):
        log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or msg.from_user.first_name, msg.text])
        analysis = ask_gpt(f"Это прайс на майнинг-оборудование. Проанализируй как трейдер... Ответь кратко, без формальностей.\n\nТекст:\n{msg.text}")
        send_message_with_partner_button(msg.chat.id, analysis)
        return
    
    # --- Если ничего не подошло, отправляем в GPT ---
    send_message_with_partner_button(msg.chat.id, ask_gpt(msg.text))

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
    schedule.every(25).minutes.do(keep_alive)
    schedule.every(3).hours.do(auto_send_news)
    schedule.every(3).hours.do(auto_check_status)
    schedule.every(1).hours.do(get_top_asics)
    get_top_asics(); auto_check_status(); keep_alive()
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    if WEBHOOK_URL:
        bot.remove_webhook(); time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + "/webhook")
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)
