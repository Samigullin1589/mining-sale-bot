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
from datetime import datetime

# --- Настройки ---
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY")
CRYPTO_API_KEY = os.environ.get("CRYPTO_API_KEY")
GOOGLE_JSON = os.environ.get("GOOGLE_JSON", "sage-instrument.json")
SHEET_ID = os.environ.get("SHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "Лист1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
NEWS_CHAT_ID = os.environ.get("NEWS_CHAT_ID")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
app = Flask(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)

# --- Webhook ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
        bot.process_new_updates([update])
        return '', 200
    return '', 403

@app.route("/")
def index():
    return "Bot is running!", 200

def set_webhook():
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + "/webhook")

# --- GPT ---
def ask_gpt(prompt):
    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"[Ошибка GPT: {e}]"

# --- Sheets ---
def get_gsheet():
    creds = Credentials.from_service_account_file(GOOGLE_JSON, scopes=[
        'https://www.googleapis.com/auth/spreadsheets']
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

def log_error_to_sheet(error_msg):
    try:
        sh = get_gsheet()
        sh.append_row([time.strftime("%Y-%m-%d %H:%M:%S"), "error", error_msg])
    except Exception:
        pass

# --- Новости ---
def get_coin_price(coin_id='bitcoin'):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        data = requests.get(url, timeout=5).json()
        return float(data[coin_id]['usd'])
    except:
        return None

def get_crypto_news():
    news = []
    # NewsAPI
    try:
        r = requests.get(f"https://newsapi.org/v2/everything?q=cryptocurrency&apiKey={NEWSAPI_KEY}&pageSize=1").json()
        for item in r.get("articles", []):
            translated = ask_gpt("Переведи на русский и кратко перескажи:\n" + item["title"])
            news.append(f"{translated}\n{item['url']}")
    except Exception as e:
        news.append(f"[Ошибка NewsAPI: {e}]")

    # CryptoPanic
    try:
        if CRYPTO_API_KEY:
            r = requests.get(
                f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&currencies=BTC,ETH&public=true"
            ).json()
            filtered = [
                p for p in r.get("results", [])
                if any(tag["label"].lower() in ["bullish", "news", "signal"] for tag in p.get("tags", []))
            ][:3]
            if filtered:
                for item in filtered:
                    title = item.get("title", "Без заголовка")
                    url = item.get("url", "")
                    time_raw = item.get("published_at", "")
                    time_str = datetime.fromisoformat(time_raw.replace("Z", "+00:00")).strftime("%H:%M %d.%m")
                    translated = ask_gpt("Переведи на русский и кратко перескажи:\n" + title)
                    news.append(f"🕒 {time_str}\n🔹 {translated}\n{url}")
            else:
                news.append("[Нет подходящих новостей в CryptoPanic]")
        else:
            news.append("[CRYPTO_API_KEY не задан]")
    except Exception as e:
        news.append(f"[Ошибка CryptoPanic: {e}]")

    return "\n\n".join(news)

# --- Калькулятор ---
def calculate_profit(ths, watt, kwh_cost, coin_price, coin_per_th_day):
    coin_day = ths * coin_per_th_day
    income = coin_day * coin_price
    cost = (watt * 24 / 1000) * kwh_cost
    profit = income - cost
    return round(profit, 2), round(income, 2), round(cost, 2)

@bot.message_handler(commands=['calc'])
def handle_calc(msg):
    try:
        parts = msg.text.split()
        if len(parts) != 4:
            raise ValueError
        ths = float(parts[1])
        watt = float(parts[2])
        kwh = float(parts[3])
        btc = get_coin_price("bitcoin")
        if not btc:
            raise Exception("Не удалось получить цену BTC")
        profit, income, cost = calculate_profit(ths, watt, kwh, btc, 0.000027)
        bot.send_message(msg.chat.id,
            f"📟 Доходность (BTC):\n💰 Доход: ${income}\n🔌 Расход: ${cost}\n📈 Профит: ${profit}\n(по курсу ${btc})")
    except:
        bot.send_message(msg.chat.id, "❗ Используйте формат: /calc 120 3300 0.07")

# --- Команды ---
@bot.message_handler(func=lambda msg: msg.text.lower() in ['start', 'старт'])
def handle_start(msg):
    bot.send_message(msg.chat.id, "Привет! Бот запущен и готов к работе.")

@bot.message_handler(func=lambda msg: msg.text.lower() in ['news', 'новости'])
def handle_news(msg):
    text = get_crypto_news()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 Получить прайс от нашего партнёра", url="https://app.leadteh.ru/w/dTeKr"))
    bot.send_message(msg.chat.id, text, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text.lower() in ['stat', 'стат'])
def handle_stat(msg):
    try:
        rows = get_gsheet().get_all_values()
        bot.send_message(msg.chat.id, f"Всего записей: {len(rows)}")
    except Exception as e:
        bot.send_message(msg.chat.id, "Ошибка: " + str(e))

# --- Обработка текста через GPT ---
@bot.message_handler(func=lambda msg: True)
def handle_gpt(msg):
    try:
        answer = ask_gpt(msg.text)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Прайс на оборудование от партнёра", url="https://app.leadteh.ru/w/dTeKr"))
        bot.send_message(msg.chat.id, answer, reply_markup=markup)
    except Exception as e:
        bot.send_message(msg.chat.id, f"[GPT ошибка: {e}]")

# --- Спам-фильтр ---
SPAM_PHRASES = ["заработок без вложений", "казино", "ставки", "раздача"]
@bot.message_handler(func=lambda m: any(x in m.text.lower() for x in SPAM_PHRASES))
def spam_filter(msg):
    bot.delete_message(msg.chat.id, msg.message_id)
    bot.send_message(msg.chat.id, "Сообщение удалено как спам.")
    log_error_to_sheet(f"SPAM: {msg.text}")

# --- Автофункции ---
def auto_send_news():
    try:
        news = get_crypto_news()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Получить прайс от партнёра", url="https://app.leadteh.ru/w/dTeKr"))
        bot.send_message(NEWS_CHAT_ID, news, reply_markup=markup)
    except Exception as e:
        print(f"Ошибка автоотправки: {e}")

def auto_check_status():
    errors = []
    for key, name in [(BOT_TOKEN, "BOT_TOKEN"), (WEBHOOK_URL, "WEBHOOK_URL"),
                      (NEWSAPI_KEY, "NEWSAPI_KEY"), (SHEET_ID, "SHEET_ID"), (OPENAI_API_KEY, "OPENAI_API_KEY")]:
        if not key or "⚠️" in str(key): errors.append(name)
    try: get_crypto_news()
    except Exception as e: errors.append(f"News: {e}")
    try: ask_gpt("Проверка")
    except Exception as e: errors.append(f"GPT: {e}")
    try: get_gsheet()
    except Exception as e: errors.append(f"Sheets: {e}")
    status = "✅ Все работает" if not errors else "⚠️ Проблемы:\n" + "\n".join(errors)
    bot.send_message(ADMIN_CHAT_ID, status)

schedule.every(3).hours.do(auto_send_news)
schedule.every(3).hours.do(auto_check_status)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# --- Запуск ---
if __name__ == '__main__':
    set_webhook()
    threading.Thread(target=run_scheduler).start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
