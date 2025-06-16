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
from bs4 import BeautifulSoup

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
pending_weather_requests = {}

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

def get_gsheet():
    creds = Credentials.from_service_account_file(GOOGLE_JSON, scopes=['https://www.googleapis.com/auth/spreadsheets'])
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

def log_error_to_sheet(error_msg):
    try:
        sh = get_gsheet()
        sh.append_row([time.strftime("%Y-%m-%d %H:%M:%S"), "error", error_msg])
    except:
        pass

TOP_ASICS = []

def update_top_asics():
    try:
        url = "https://www.asicminervalue.com/miners/sha-256"
        r = requests.get(url, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        TOP_ASICS.clear()
        for row in soup.select("table tbody tr")[:5]:
            tds = row.find_all("td")
            model = tds[0].get_text(strip=True)
            hr = tds[1].get_text(strip=True)
            watt = tds[2].get_text(strip=True)
            profit = tds[3].get_text(strip=True)
            TOP_ASICS.append(f"{model} — {hr}, {watt}, доход: {profit}/день")
    except Exception as e:
        TOP_ASICS.clear()
        TOP_ASICS.append(f"[Ошибка обновления ASIC: {e}]")

def schedule_asic_updates():
    schedule.every().day.at("03:00").do(update_top_asics)
    update_top_asics()

def ask_gpt(prompt):
    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        return f"[GPT ошибка: {e}]"

def get_weather(city):
    try:
        url = f"https://wttr.in/{city}?format=j1"
        r = requests.get(url).json()
        current = r["current_condition"][0]
        temp = current["temp_C"]
        desc = current["weatherDesc"][0]["value"]
        humidity = current["humidity"]
        wind = current["windspeedKmph"]
        return (
            f"🌍 Город: {city.title()}\n"
            f"🌡 Температура: {temp}°C\n"
            f"☁️ Погода: {desc}\n"
            f"💧 Влажность: {humidity}%\n"
            f"💨 Ветер: {wind} км/ч"
        )
    except Exception as e:
        return f"[Ошибка погоды: {e}]"

def get_currency_rate(from_symbol, to_symbol):
    try:
        url = f"https://api.exchangerate.host/latest?base={from_symbol.upper()}&symbols={to_symbol.upper()}"
        data = requests.get(url).json()
        rate = data['rates'][to_symbol.upper()]
        return f"💱 {from_symbol.upper()} → {to_symbol.upper()} = {rate:.2f}"
    except Exception as e:
        return f"[Ошибка курса: {e}]"

def get_coin_price(coin_id='bitcoin'):
    try:
        data = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd").json()
        return float(data[coin_id]['usd'])
    except:
        return None

def get_crypto_news():
    try:
        r = requests.get(f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&currencies=BTC,ETH&public=true").json()
        filtered = r.get("results", [])[:3]
        items = []
        for item in filtered:
            title = item.get("title", "Без заголовка")
            url = item.get("url", "")
            translated = ask_gpt(f"Переведи и кратко поясни:\n{title}")
            items.append(f"🔹 {translated}\n{url}")
        return "\n\n".join(items) if items else "[Нет свежих новостей]"
    except Exception as e:
        return f"[Ошибка CryptoPanic: {e}]"

def is_mining_price_message(text):
    return any(x in text.lower() for x in ["th", "asics", "в наличии", "продам", "бу", "новые", "usd", "$"])

def analyze_mining_prices(text):
    prompt = (
        "Это сообщение из Telegram-чата с прайсами на майнинг-оборудование."
        " Проанализируй как трейдер: есть ли выгодные предложения, актуальные цены, есть ли подозрительно дешевые."
        " Ответь кратко, на русском, без формальностей.\n\nТекст:\n" + text
    )
    return ask_gpt(prompt)

@bot.message_handler(func=lambda msg: True)
def handle_all_messages(msg):
    user_id = msg.from_user.id
    text = msg.text.lower()

    if user_id in pending_weather_requests:
        response = get_weather(msg.text)
        del pending_weather_requests[user_id]
        bot.send_message(msg.chat.id, response)
        return

    if "погода" in text:
        pending_weather_requests[user_id] = True
        bot.send_message(msg.chat.id, "🌦 В каком городе вас интересует погода?")
        return

    if "курс btc" in text:
        price = get_coin_price("bitcoin")
        bot.send_message(msg.chat.id, f"💰 Курс BTC: ${price}" if price else "Не удалось получить курс BTC")
        return

    if "доллар к евро" in text:
        bot.send_message(msg.chat.id, get_currency_rate("usd", "eur"))
        return

    if "tiktok.com" in text:
        bot.send_message(msg.chat.id, "⚠️ Бот не может просматривать TikTok. Опишите суть — помогу!")
        return

    if is_mining_price_message(text):
        feedback = analyze_mining_prices(msg.text)
        bot.send_message(msg.chat.id, feedback)
        return

    if any(k in text for k in ["asic", "модель", "розетка", "квт", "выгодно", "доходность"]):
        models = "\n".join(TOP_ASICS)
        prompt = (
            "Ниже представлен актуальный список ASIC SHA‑256 моделей, полученный с сайта asicminervalue.com,"
            " обновлённый сегодня. Используй исключительно эти данные.\n\n"
            f"{models}\n\nТеперь ответь на вопрос пользователя:\n{msg.text}"
        )
    else:
        prompt = msg.text

    try:
        answer = ask_gpt(prompt)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Прайс от партнёра", url="https://app.leadteh.ru/w/dTeKr"))
        bot.send_message(msg.chat.id, answer, reply_markup=markup)
    except Exception as e:
        bot.send_message(msg.chat.id, f"[GPT ошибка: {e}]")

def auto_send_news():
    try:
        news = get_crypto_news()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💬 Получить прайс от партнёра", url="https://app.leadteh.ru/w/dTeKr"))
        bot.send_message(NEWS_CHAT_ID, news, reply_markup=markup)
    except Exception as e:
        print(f"[Авторассылка]: {e}")

def auto_check_status():
    errors = []
    for key, name in [(BOT_TOKEN, "BOT_TOKEN"), (WEBHOOK_URL, "WEBHOOK_URL"),
                      (NEWSAPI_KEY, "NEWSAPI_KEY"), (SHEET_ID, "SHEET_ID"), (OPENAI_API_KEY, "OPENAI_API_KEY")]:
        if not key or "⚠️" in str(key): errors.append(name)
    try: ask_gpt("Проверка GPT")
    except Exception as e: errors.append(f"GPT: {e}")
    try: get_gsheet()
    except Exception as e: errors.append(f"Sheets: {e}")
    status = "✅ Все работает" if not errors else "⚠️ Проблемы:\n" + "\n".join(errors)
    bot.send_message(ADMIN_CHAT_ID, status)

schedule.every(3).hours.do(auto_send_news)
schedule.every(3).hours.do(auto_check_status)
schedule_asic_updates()

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    set_webhook()
    threading.Thread(target=run_scheduler).start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
