import os
import telebot
import requests
import time
import schedule
import threading
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import feedparser
import pytz

# --- Настройки (токены, вебхуки, ключи) ---
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY")
GOOGLE_JSON = os.environ.get("GOOGLE_JSON")
SHEET_ID = os.environ.get("SHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "Лист1")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Webhook Flask обработчик ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return '', 403

@app.route('/', methods=['GET'])
def index():
    return 'Bot is running!', 200

# --- Webhook установка ---
def set_webhook():
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL.rstrip('/') + "/webhook")

# --- Google Sheets ---
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
    except Exception as e:
        print("Ошибка логирования:", e)

# --- Команды ---
@bot.message_handler(commands=['start'])
def start(msg):
    bot.send_message(msg.chat.id, "Привет! Бот работает через Webhook!")

@bot.message_handler(commands=['stat'])
def stat(msg):
    try:
        sh = get_gsheet()
        rows = sh.get_all_values()
        bot.send_message(msg.chat.id, f"Всего записей: {len(rows)}")
    except Exception as e:
        bot.send_message(msg.chat.id, "Ошибка: " + str(e))

@bot.message_handler(commands=['news', 'новости'])
def cmd_news(msg):
    text = get_news()
    bot.send_message(msg.chat.id, text)
    bot.send_message(msg.chat.id, "🔥 Интересует оборудование? Спецусловия тут: https://app.leadteh.ru/w/dTeKr")

# --- Автоновости ---
def get_news():
    news = []
    try:
        url = f"https://newsapi.org/v2/everything?q=cryptocurrency&apiKey={NEWSAPI_KEY}&pageSize=1"
        resp = requests.get(url).json()
        for item in resp.get("articles", []):
            news.append(item["title"] + "\n" + item["url"])
    except Exception as e:
        news.append("[Ошибка NewsAPI: " + str(e) + "]")
    try:
        d = feedparser.parse("https://cryptopanic.com/news/rss")
        if d.entries:
            entry = d.entries[0]
            news.append(entry.title + "\n" + entry.link)
    except Exception as e:
        news.append("[Ошибка CryptoPanic: " + str(e) + "]")
    return "\n\n".join(news) + "\n\n🔥 Интересует оборудование? Спецусловия тут: https://app.leadteh.ru/w/dTeKr"

def auto_news():
    try:
        text = get_news()
        bot.send_message(chat_id=os.environ.get("NEWS_CHAT_ID"), text=text)
    except Exception as e:
        log_error_to_sheet("AUTO NEWS ERROR: " + str(e))

schedule.every(3).hours.do(auto_news)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(30)

# --- Спам-фильтр ---
SPAM_PHRASES = ["заработок без вложений", "казино", "ставки", "раздача"]
@bot.message_handler(func=lambda m: any(x in m.text.lower() for x in SPAM_PHRASES))
def spam_filter(msg):
    bot.delete_message(msg.chat.id, msg.message_id)
    bot.send_message(msg.chat.id, "Сообщение удалено как спам.")
    log_error_to_sheet("SPAM: " + msg.text)

# --- Ответ на любое сообщение ---
@bot.message_handler(func=lambda m: True)
def echo_all(msg):
    bot.send_message(msg.chat.id, f"Вы написали: {msg.text}")

# --- Запуск ---
if __name__ == '__main__':
    set_webhook()
    threading.Thread(target=run_scheduler).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
