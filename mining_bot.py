import os
import telebot
import requests
import time
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
import feedparser
import pytz
import schedule
import threading
from telebot import types
import openai

# --- Настройки ---
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY")
GOOGLE_JSON = os.environ.get("GOOGLE_JSON", "sage-instrument-338811-a8c8cc7f2500.json")
SHEET_ID = os.environ.get("SHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "Лист1")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# --- Webhook ---
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

def set_webhook():
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + "/webhook")

# --- Подключение к Google Sheets ---
def get_gsheet():
    creds = Credentials.from_service_account_file(GOOGLE_JSON, scopes=[
        'https://www.googleapis.com/auth/spreadsheets'
    ])
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# --- Новости ---
def get_news():
    news = []
    try:
        url = f"https://newsapi.org/v2/everything?q=cryptocurrency&apiKey={NEWSAPI_KEY}&pageSize=1"
        resp = requests.get(url).json()
        for item in resp.get("articles", []):
            news.append(item["title"] + "\n" + item["url"])
    except Exception as e:
        news.append(f"[Ошибка NewsAPI: {e}]")
    try:
        d = feedparser.parse("https://cryptopanic.com/news/rss")
        if d.entries:
            entry = d.entries[0]
            news.append(entry.title + "\n" + entry.link)
    except Exception as e:
        news.append(f"[Ошибка CryptoPanic: {e}]")
    return "\n\n".join(news)

# --- Команды без слешей ---
@bot.message_handler(func=lambda msg: msg.text.lower() in ['start', 'старт'])
def handle_start(msg):
    bot.send_message(msg.chat.id, "Привет! Бот работает через Webhook!")

@bot.message_handler(func=lambda msg: msg.text.lower() in ['news', 'новости'])
def handle_news(msg):
    text = get_news()
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔥 Интересует оборудование?", url="https://app.leadteh.ru/w/dTeKr"))
    bot.send_message(msg.chat.id, text, reply_markup=markup)

@bot.message_handler(func=lambda msg: msg.text.lower() in ['stat', 'стат', 'записи', 'таблица'])
def handle_stat(msg):
    try:
        sh = get_gsheet()
        rows = sh.get_all_values()
        bot.send_message(msg.chat.id, f"Всего записей: {len(rows)}")
    except Exception as e:
        bot.send_message(msg.chat.id, "Ошибка: " + str(e))

# --- GPT-ответ ---
openai.api_key = OPENAI_API_KEY

def ask_gpt(prompt):
    res = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    return res.choices[0].message.content.strip()

@bot.message_handler(func=lambda msg: True)
def handle_gpt(msg):
    if msg.text:
        try:
            reply = ask_gpt(msg.text)
            bot.send_message(msg.chat.id, reply)
        except Exception as e:
            bot.send_message(msg.chat.id, f"Ошибка GPT: {e}")

# --- Логирование спама ---
SPAM_PHRASES = ["заработок без вложений", "казино", "ставки", "раздача"]

@bot.message_handler(func=lambda m: any(x in m.text.lower() for x in SPAM_PHRASES))
def spam_filter(msg):
    bot.delete_message(msg.chat.id, msg.message_id)
    bot.send_message(msg.chat.id, "Сообщение удалено как спам.")
    log_error_to_sheet(f"SPAM: {msg.text}")

def log_error_to_sheet(error_msg):
    try:
        sh = get_gsheet()
        sh.append_row([time.strftime("%Y-%m-%d %H:%M:%S"), "error", error_msg])
    except Exception as e:
        print(f"Ошибка логирования: {e}")

# --- Автоотправка новостей ---
def auto_send_news():
    try:
        text = get_news()
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔥 Интересует оборудование? Спецусловия тут:", url="https://app.leadteh.ru/w/dTeKr"))
        bot.send_message(os.environ.get("NEWS_CHAT_ID"), text, reply_markup=markup)
    except Exception as e:
        print(f"Ошибка авторассылки новостей: {e}")

schedule.every(3).hours.do(auto_send_news)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# --- Запуск ---
if __name__ == '__main__':
    set_webhook()
    threading.Thread(target=run_scheduler).start()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
