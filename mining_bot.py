import os
import telebot
import requests
import time
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import feedparser
import pytz

# --- Настройки (токены, вебхуки, ключи) ---
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or "ТВОЙ_ТОКЕН_ТУТ"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL") or "https://ТВОЙ-ДОМЕН.onrender.com/"  # без /webhook, будет ниже
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY") or "ТВОЙ_NEWSAPI_KEY"
GOOGLE_JSON = os.environ.get("GOOGLE_JSON", "sage-instrument-338811-a8c8cc7f2500.json")
SHEET_ID = os.environ.get("SHEET_ID") or "ID_ТВОЕЙ_ТАБЛИЦЫ"
SHEET_NAME = os.environ.get("SHEET_NAME", "Лист1")

bot = telebot.TeleBot(BOT_TOKEN)

# --- Flask App ---
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return '', 403

@app.route("/", methods=['GET'])
def index():
    return "Bot is running!", 200

# --- Установить Webhook при запуске ---
def set_webhook():
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + "/webhook")

# --- Google Sheets подключение ---
def get_gsheet():
    creds = Credentials.from_service_account_file(GOOGLE_JSON, scopes=[
        'https://www.googleapis.com/auth/spreadsheets'
    ])
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# --- Пример команды /start ---
@bot.message_handler(commands=['start'])
def start(msg):
    bot.send_message(msg.chat.id, "Привет! Бот работает через Webhook!")

# --- Пример автоновостей (NewsAPI + CryptoPanic RSS) ---
def get_news():
    news = []
    try:
        # NewsAPI
        url = f"https://newsapi.org/v2/everything?q=cryptocurrency&apiKey={NEWSAPI_KEY}&pageSize=1"
        resp = requests.get(url).json()
        for item in resp.get("articles", []):
            news.append(item["title"] + "\n" + item["url"])
    except Exception as e:
        news.append(f"[Ошибка NewsAPI: {e}]")
    # CryptoPanic RSS
    try:
        d = feedparser.parse("https://cryptopanic.com/news/rss")
        if d.entries:
            entry = d.entries[0]
            news.append(entry.title + "\n" + entry.link)
    except Exception as e:
        news.append(f"[Ошибка CryptoPanic: {e}]")
    return "\n\n".join(news)

@bot.message_handler(commands=['news', 'новости'])
def cmd_news(msg):
    text = get_news()
    bot.send_message(msg.chat.id, text)

# --- Логирование ошибок в Google Sheets ---
def log_error_to_sheet(error_msg):
    try:
        sh = get_gsheet()
        sh.append_row([time.strftime("%Y-%m-%d %H:%M:%S"), "error", error_msg])
    except Exception as e:
        print(f"Ошибка логирования: {e}")

# --- Пример спам-фильтра ---
SPAM_PHRASES = ["заработок без вложений", "казино", "ставки", "раздача"]

@bot.message_handler(func=lambda m: any(x in m.text.lower() for x in SPAM_PHRASES))
def spam_filter(msg):
    bot.delete_message(msg.chat.id, msg.message_id)
    bot.send_message(msg.chat.id, "Сообщение удалено как спам.")
    log_error_to_sheet(f"SPAM: {msg.text}")

# --- Пример отчёта по команде ---
@bot.message_handler(commands=['stat'])
def cmd_stat(msg):
    try:
        sh = get_gsheet()
        rows = sh.get_all_values()
        bot.send_message(msg.chat.id, f"Всего записей: {len(rows)}")
    except Exception as e:
        bot.send_message(msg.chat.id, "Ошибка: " + str(e))

# --- Основной запуск Flask + webhook ---
if __name__ == '__main__':
    set_webhook()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
