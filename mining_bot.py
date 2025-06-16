import os
import time
import requests
import feedparser
import telebot
from flask import Flask, request
import gspread
from google.oauth2.service_account import Credentials
from threading import Thread
import schedule
import openai

# --- Переменные окружения ---
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # без /webhook в конце
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY")
OPENAI_KEY = os.environ.get("OPENAI_API_KEY")
GOOGLE_JSON = os.environ.get("GOOGLE_JSON", "creds.json")
SHEET_ID = os.environ.get("SHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "Лист1")
NEWS_CHAT_ID = os.environ.get("NEWS_CHAT_ID")

bot = telebot.TeleBot(BOT_TOKEN)
openai.api_key = OPENAI_KEY
app = Flask(__name__)

# --- Webhook ---
@app.route("/webhook", methods=['POST'])
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

# --- Google Sheets подключение ---
def get_gsheet():
    creds = Credentials.from_service_account_file(GOOGLE_JSON, scopes=['https://www.googleapis.com/auth/spreadsheets'])
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

# --- Команды ---
@bot.message_handler(commands=['start'])
def start(msg):
    bot.send_message(msg.chat.id, "Привет! Я бот для новостей и помощи по майнингу.")

@bot.message_handler(commands=['news', 'новости'])
def manual_news(msg):
    send_news(chat_id=msg.chat.id)

@bot.message_handler(commands=['stat'])
def stat_handler(msg):
    try:
        sheet = get_gsheet()
        rows = sheet.get_all_values()
        bot.send_message(msg.chat.id, f"Всего записей: {len(rows)}")
    except Exception as e:
        bot.send_message(msg.chat.id, f"Ошибка: {e}")

@bot.message_handler(commands=['ask'])
def ask_handler(msg):
    try:
        prompt = msg.text.split(' ', 1)[1] if ' ' in msg.text else ""
        if not prompt:
            return bot.send_message(msg.chat.id, "Напишите вопрос после команды /ask")
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}]
        )
        answer = resp.choices[0].message.content
        bot.send_message(msg.chat.id, answer)
    except Exception as e:
        bot.send_message(msg.chat.id, f"Ошибка: {e}")

# --- Спам-фильтр ---
SPAM_PHRASES = ["заработок без вложений", "казино", "ставки", "раздача"]

@bot.message_handler(func=lambda m: any(x in m.text.lower() for x in SPAM_PHRASES))
def spam_filter(msg):
    try:
        bot.delete_message(msg.chat.id, msg.message_id)
        bot.send_message(msg.chat.id, "Сообщение удалено как спам.")
        log_error_to_sheet(f"SPAM: {msg.text}")
    except:
        pass

# --- Лог ошибок в Sheets ---
def log_error_to_sheet(error_msg):
    try:
        sheet = get_gsheet()
        sheet.append_row([time.strftime("%Y-%m-%d %H:%M:%S"), "error", error_msg])
    except:
        pass

# --- Авто-новости каждые 3ч ---
def get_news():
    news = []
    try:
        url = f"https://newsapi.org/v2/everything?q=cryptocurrency&apiKey={NEWSAPI_KEY}&pageSize=1"
        resp = requests.get(url).json()
        for item in resp.get("articles", []):
            news.append(f"{item['title']}\n{item['url']}")
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

def send_news(chat_id=None):
    text = get_news()
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("💬 Получить прайс", url="https://app.leadteh.ru/w/dTeKr"))
    try:
        bot.send_message(chat_id or NEWS_CHAT_ID, text, reply_markup=markup)
    except Exception as e:
        log_error_to_sheet(f"Ошибка отправки новостей: {e}")

# --- Планировщик задач ---
def run_scheduler():
    schedule.every(3).hours.do(send_news)
    while True:
        schedule.run_pending()
        time.sleep(60)

# --- Webhook установка ---
def set_webhook():
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=WEBHOOK_URL.rstrip("/") + "/webhook")

# --- Запуск ---
if __name__ == '__main__':
    set_webhook()
    Thread(target=run_scheduler).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
