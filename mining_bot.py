import os
import json
import time
import random
import logging
import threading
import requests
from flask import Flask, request
from datetime import datetime, timedelta
from pytz import timezone
import gspread
from google.oauth2.service_account import Credentials
from fpdf import FPDF
import telebot
import xml.etree.ElementTree as ET

# === CONFIG ===
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN") or "ВАШ_ТОКЕН"
GPT_API_KEY = os.environ.get("OPENAI_API_KEY") or "ВАШ_КЛЮЧ"
CRYPTO_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY") or "ВАШ_КЛЮЧ"
NEWSAPI_KEY = "1b8deaa7f4c54f35b19f4edda97edfe6"

ADMIN_CHAT_IDS = [-1002408729915]  # ID вашей группы
ADMINS = [7473992492, 5860994210]  # ID админов

GOOGLE_CRED_FILE = "sage-instrument-338811-a8c8cc7f2500.json"
GOOGLE_SHEET_ID = "1WqzsXwqw-aDH_lNWSpX5bjHFqT5BHmXYFSgHupAlWQg"
STATS_TAB = "Стата с барахолки майнинг"
LOGS_TAB = "Ошибки"

PROMO_LINKS = [
    ("💰 Посмотреть актуальный прайс и приобрести", "https://app.leadteh.ru/w/dTeKr"),
    ("🔥 Получить условия на оборудование", "https://app.leadteh.ru/w/dTeKr"),
    ("📦 Узнать наличие на складе", "https://app.leadteh.ru/w/dTeKr"),
    ("👉 Заказать консультацию", "https://app.leadteh.ru/w/dTeKr"),
    ("💸 Получить спецпредложение", "https://app.leadteh.ru/w/dTeKr"),
]

app = Flask(__name__)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# === Google Sheets Setup ===
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file(GOOGLE_CRED_FILE, scopes=scope)
gs = gspread.authorize(creds)
ws = gs.open_by_key(GOOGLE_SHEET_ID).worksheet(STATS_TAB)
try:
    ws_logs = gs.open_by_key(GOOGLE_SHEET_ID).worksheet(LOGS_TAB)
except:
    ws_logs = gs.open_by_key(GOOGLE_SHEET_ID).add_worksheet(LOGS_TAB, rows=100, cols=10)

stats = {"messages": 0, "users": {}, "top": {}, "ads": 0, "warnings": 0}
spam_patterns = set()

def log_to_sheet(event_type, msg, details=""):
    try:
        ws_logs.append_row([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), event_type, str(msg), details])
    except Exception as e:
        print(f"Sheet logging error: {e}")

def get_random_promo():
    return random.choice(PROMO_LINKS)

def translate(text, target="ru"):
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": f"Переведи и сожми суть (summary) на {target}: {text}"}]
    }
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {GPT_API_KEY}"},
        json=payload,
        timeout=30
    )
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        log_to_sheet("ERROR", "GPT translate", f"{response.status_code} {response.text}")
        return text

def fetch_news(source):
    try:
        if source == "cryptopanic":
            url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&currencies=BTC,ETH&public=true"
            resp = requests.get(url, timeout=15)
            data = resp.json()
            items = data.get("results", [])
            if not items: return None
            article = items[0]
            return article["title"]
        elif source == "newsapi":
            url = f"https://newsapi.org/v2/top-headlines?category=business&q=crypto&apiKey={NEWSAPI_KEY}"
            resp = requests.get(url, timeout=15)
            articles = resp.json().get("articles", [])
            if not articles: return None
            return articles[0]["title"]
        elif source == "cointelegraph":
            # RSS парсер Cointelegraph
            url = "https://cointelegraph.com/rss"
            resp = requests.get(url, timeout=15)
            tree = ET.fromstring(resp.content)
            first_item = tree.find('./channel/item/title')
            return first_item.text if first_item is not None else None
    except Exception as e:
        log_to_sheet("ERROR", f"News API {source}", str(e))
        return None

def push_stats():
    try:
        row = [datetime.now().strftime("%Y-%m-%d %H:%M"), stats["messages"], len(stats["users"]), stats["ads"], stats["warnings"]]
        ws.append_row(row)
    except Exception as e:
        log_to_sheet("ERROR", "PushStats", str(e))

def export_pdf_stats():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"Статистика Mining Sale Bot ({datetime.now().strftime('%Y-%m-%d %H:%M')})", ln=1)
    pdf.cell(0, 10, f"Всего сообщений: {stats['messages']}", ln=1)
    pdf.cell(0, 10, f"Уникальных пользователей: {len(stats['users'])}", ln=1)
    pdf.cell(0, 10, f"Рекламных сообщений: {stats['ads']}", ln=1)
    pdf.cell(0, 10, f"Предупреждений: {stats['warnings']}", ln=1)
    top_users = sorted(stats["users"].items(), key=lambda x: x[1], reverse=True)[:5]
    pdf.cell(0, 10, f"Топ-5 пользователей:", ln=1)
    for i, (uid, cnt) in enumerate(top_users, 1):
        pdf.cell(0, 10, f"{i}. ID: {uid} — {cnt} сообщений", ln=1)
    pdf_file = f"stats_{int(time.time())}.pdf"
    pdf.output(pdf_file)
    return pdf_file

@bot.message_handler(commands=['start', 'help'])
def handle_start(msg):
    bot.reply_to(msg, "👋 Привет! Я Mining Sale Bot. Задай любой вопрос по майнингу или напиши /новости для последних новостей.")

@bot.message_handler(commands=['новости', 'news'])
def handle_news(msg):
    now = datetime.now(timezone('Europe/Moscow'))
    if 6 <= now.hour < 13:
        src = "cryptopanic"
    elif 13 <= now.hour < 19:
        src = "newsapi"
    else:
        src = "cointelegraph"
    user_lang = "ru" if msg.from_user.language_code == "ru" else "en"
    news = fetch_news(src)
    if not news:
        bot.send_message(msg.chat.id, "❗️ Не удалось получить новости.", parse_mode="HTML")
        log_to_sheet("ERROR", "No news", f"src={src}")
        return
    summary = translate(news, target=user_lang)
    text, url = get_random_promo()
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton(text, url=url))
    bot.send_message(msg.chat.id, summary, reply_markup=markup)

@bot.message_handler(commands=['стата', 'stats'])
def handle_stats(msg):
    if msg.from_user.id in ADMINS:
        push_stats()
        bot.send_message(msg.chat.id, f"📝 Сообщений: {stats['messages']}\nУникальных: {len(stats['users'])}\nРеклама: {stats['ads']}\nВарнов: {stats['warnings']}")

@bot.message_handler(commands=['pdfstats'])
def handle_pdfstats(msg):
    if msg.from_user.id in ADMINS:
        pdf_file = export_pdf_stats()
        with open(pdf_file, "rb") as f:
            bot.send_document(msg.chat.id, f)
        os.remove(pdf_file)

@bot.message_handler(commands=['top'])
def handle_top(msg):
    top_users = sorted(stats["users"].items(), key=lambda x: x[1], reverse=True)[:3]
    text = "🏆 Топ-3 активных за сутки:\n"
    emoji = ["🥇", "🥈", "🥉"]
    for i, (uid, count) in enumerate(top_users, 1):
        text += f"{emoji[i-1]} <a href='tg://user?id={uid}'>user</a>: {count} сообщений\n"
    bot.send_message(msg.chat.id, text, parse_mode="HTML")

@bot.message_handler(content_types=['text'])
def handle_all(msg):
    try:
        stats["messages"] += 1
        uid = msg.from_user.id
        stats["users"].setdefault(uid, 0)
        stats["users"][uid] += 1
        text = msg.text.lower()
        # Модерация: фильтр спама
        for pattern in spam_patterns:
            if pattern in text:
                stats["warnings"] += 1
                bot.delete_message(msg.chat.id, msg.message_id)
                bot.send_message(msg.chat.id, "⛔️ Спам запрещён!")
                log_to_sheet("SPAM", msg.text, f"user_id={uid}")
                return
        # Автоответ на вопросы по майнингу
        keywords = ["обзор", "что выбрать", "асик", "валюта", "купить", "розетка", "окупаемость"]
        if any(k in text for k in keywords):
            reply = translate(f"Дай краткий, но полезный совет по теме: {msg.text}", target="ru")
            bot.reply_to(msg, reply)
            return
        # Триггер рекламы
        if any(x in text for x in ["майнер", "асик", "оборудование", "купить", "продать"]):
            stats["ads"] += 1
            promo, url = get_random_promo()
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton(promo, url=url))
            bot.send_message(msg.chat.id, promo, reply_markup=markup)
            return
    except Exception as e:
        log_to_sheet("ERROR", "HandleText", str(e))

@bot.message_handler(commands=['подозрительно'])
def add_spam_pattern(msg):
    if msg.reply_to_message:
        pattern = msg.reply_to_message.text.lower()
        spam_patterns.add(pattern)
        bot.reply_to(msg, f"Шаблон '{pattern}' добавлен в фильтр.")
        log_to_sheet("SPAM_ADD", pattern)

def auto_news():
    while True:
        now = datetime.now(timezone('Europe/Moscow'))
        # Каждый источник 1 раз в сутки — 8:00, 15:00, 21:00
        for hour, src in [(8, "cryptopanic"), (15, "newsapi"), (21, "cointelegraph")]:
            if now.hour == hour and now.minute == 0:
                for chat_id in ADMIN_CHAT_IDS:
                    msg = type('Msg', (), {
                        'chat': type('Chat', (), {'id': chat_id}),
                        'from_user': type('User', (), {'language_code': 'ru'})
                    })()
                    handle_news(msg)
                push_stats()
        time.sleep(60)

def run_flask():
    app.run(host='0.0.0.0', port=10000)

@app.route('/webhook', methods=['POST'])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return "ok", 200

if __name__ == "__main__":
    threading.Thread(target=auto_news, daemon=True).start()
    run_flask()
