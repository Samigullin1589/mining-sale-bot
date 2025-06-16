import os
import json
import time
import random
import logging
from datetime import datetime, timedelta
import pytz
import feedparser

import telebot
import requests
import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fpdf import FPDF

# --- КОНФИГ ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
GROUP_ID = -1002408729915  # ваш id группы
ADMINS = [7473992492, 5860994210]  # ваши id админов
PARTNERS_LINKS = ['https://app.leadteh.ru/w/dTeKr']

COINDESK_RSS = 'https://www.coindesk.com/arc/outboundfeeds/rss/'
COINTELEGRAPH_RSS = 'https://cointelegraph.com/rss'
CRYPTO_PANIC_URL = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&public=true"
GOOGLE_SHEET_ID = "1WqzsXwqw-aDH_lNWSpX5bjHFqT5BHmXYFSgHupAlWQg"
SHEET_NAME = "Лист1"

os.environ["OPENAI_API_KEY"] = OPENAI_KEY

bot = telebot.TeleBot(TOKEN)
logging.basicConfig(level=logging.INFO)

# --- Google Sheets ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(
    "sage-instrument-338811-a8c8cc7f2500.json", scope)
gsheet = gspread.authorize(creds)
sheet = gsheet.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME)

# --- Локализация ---
LANGS = {'ru': 'Русский', 'en': 'English'}
user_lang = {}  # user_id: 'ru'/'en'

# --- Переменные для автонаграды ---
user_activity = {}  # user_id: {'count': X, 'last': timestamp, 'badge': ...}
BADGES = ["🥇", "🥈", "🥉"]

# --- Антиспам-паттерны ---
spam_patterns = []
warns = {}

# --- Кнопки с ротацией ---
BUTTONS = [
    ("💰 Посмотреть актуальный прайс и приобрести", PARTNERS_LINKS[0]),
    ("⚡ Спецусловия на оборудование тут", PARTNERS_LINKS[0]),
    ("🔥 Лучшие цены — подробнее здесь", PARTNERS_LINKS[0]),
    ("👉 Запросить индивидуальное предложение", PARTNERS_LINKS[0])
]

def get_button():
    return random.choice(BUTTONS)

# --- Логирование ошибок ---
def log_error(text):
    now = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, "ERROR", text])

def log_event(event, user_id, info=""):
    now = datetime.now(pytz.UTC).strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, event, str(user_id), info])

# --- GPT-реферат + перевод ---
def summarize_translate(text, lang="ru"):
    try:
        prompt = f"Сделай краткий, сжатый пересказ новости на русском для телеграм, без англицизмов и воды. Текст:\n{text}"
        r = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "system", "content": prompt}],
            temperature=0.4,
            max_tokens=220
        )
        summary = r.choices[0].message.content.strip()
        return summary
    except Exception as e:
        log_error(f"GPT error: {e}")
        return text[:400] + "..."

# --- Проверка спама ---
def is_spam(text):
    for pattern in spam_patterns:
        if pattern.lower() in text.lower():
            return True
    return False

# --- Статистика пользователя ---
def update_activity(user):
    if user.id not in user_activity:
        user_activity[user.id] = {'count': 0, 'last': time.time(), 'badge': ''}
    user_activity[user.id]['count'] += 1
    user_activity[user.id]['last'] = time.time()
    # Автонаграды
    count = user_activity[user.id]['count']
    if count > 30:
        user_activity[user.id]['badge'] = BADGES[0]
    elif count > 20:
        user_activity[user.id]['badge'] = BADGES[1]
    elif count > 10:
        user_activity[user.id]['badge'] = BADGES[2]

def get_top(n=5):
    ranked = sorted(user_activity.items(), key=lambda x: x[1]['count'], reverse=True)
    return ranked[:n]

# --- Функция отправки новостей ---
def send_news(chat_id, title, link, summary=None):
    button = get_button()
    msg = f"📰 <b>{title}</b>\n\n"
    if summary:
        msg += summary + "\n\n"
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton(button[0], url=button[1]))
    bot.send_message(chat_id, msg, parse_mode='HTML', disable_web_page_preview=True, reply_markup=markup)

# --- Новости с CryptoPanic ---
def get_cryptopanic_news():
    try:
        resp = requests.get(CRYPTO_PANIC_URL)
        items = resp.json().get("results", [])[:2]
        for post in items:
            title = post.get('title', '')
            url = post.get('url', '')
            summary = summarize_translate(title)
            send_news(GROUP_ID, title, url, summary)
        log_event("news", "system", "CryptoPanic")
    except Exception as e:
        log_error(f"CryptoPanic: {e}")

# --- Новости с NewsAPI ---
def get_newsapi_news():
    try:
        url = f"https://newsapi.org/v2/top-headlines?category=business&q=crypto&language=ru&apiKey={NEWSAPI_KEY}"
        resp = requests.get(url)
        items = resp.json().get("articles", [])[:2]
        for a in items:
            title = a.get("title", "")
            link = a.get("url", "")
            summary = summarize_translate(title)
            send_news(GROUP_ID, title, link, summary)
        log_event("news", "system", "NewsAPI")
    except Exception as e:
        log_error(f"NewsAPI: {e}")

# --- Новости с CoinDesk RSS ---
def get_coindesk_news():
    try:
        feed = feedparser.parse(COINDESK_RSS)
        for entry in feed.entries[:2]:
            title = entry.title
            link = entry.link
            summary = summarize_translate(title)
            send_news(GROUP_ID, title, link, summary)
        log_event("news", "system", "CoinDesk")
    except Exception as e:
        log_error(f"CoinDesk: {e}")

# --- Новости с Cointelegraph RSS ---
def get_cointelegraph_news():
    try:
        feed = feedparser.parse(COINTELEGRAPH_RSS)
        for entry in feed.entries[:2]:
            title = entry.title
            link = entry.link
            summary = summarize_translate(title)
            send_news(GROUP_ID, title, link, summary)
        log_event("news", "system", "Cointelegraph")
    except Exception as e:
        log_error(f"Cointelegraph: {e}")

# --- Автоновости по расписанию ---
def scheduled_news():
    h = datetime.now().hour
    if h % 6 == 0: get_cryptopanic_news()
    if h % 6 == 2: get_newsapi_news()
    if h % 6 == 4: get_coindesk_news()
    if h % 6 == 5: get_cointelegraph_news()
    # log_event("cron_news", "system", f"hour {h}")

# --- PDF-экспорт статистики ---
def export_stats_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, "Статистика активности чата", ln=1)
    top = get_top(10)
    for idx, (uid, data) in enumerate(top, 1):
        pdf.cell(0, 10, f"{idx}. {uid} ({data['count']}): {data['badge']}", ln=1)
    fname = "/tmp/stats.pdf"
    pdf.output(fname)
    return fname

# --- Telegram-команды ---
@bot.message_handler(commands=["start"])
def start(m):
    bot.reply_to(m, "👋 Привет! Я Mining_Sale_Bot. Авто-новости, умный фильтр и статистика. Напишите /help.")

@bot.message_handler(commands=["help"])
def help_cmd(m):
    txt = """
<b>🤖 Возможности:</b>
• Авто-новости по крипте и майнингу
• Ротация нативных кнопок
• Умный фильтр спама
• Рейтинг активности (/top)
• Экспорт статистики (/stats)
• PDF-отчёты для админов
• EN/RU локализация — /lang en или /lang ru
"""
    bot.reply_to(m, txt, parse_mode="HTML")

@bot.message_handler(commands=["lang"])
def lang_cmd(m):
    arg = m.text.split()[-1].lower()
    if arg in LANGS:
        user_lang[m.from_user.id] = arg
        bot.reply_to(m, f"Язык интерфейса: {LANGS[arg]}")
    else:
        bot.reply_to(m, "EN/RU only. Пример: /lang ru")

@bot.message_handler(commands=["news", "новости"])
def news_cmd(m):
    get_cryptopanic_news()
    get_newsapi_news()
    get_coindesk_news()
    get_cointelegraph_news()
    bot.reply_to(m, "Новости опубликованы!")

@bot.message_handler(commands=["stats", "стата"])
def stats_cmd(m):
    top = get_top(10)
    rows = [f"{idx+1}. <b>{bot.get_chat_member(GROUP_ID, uid).user.first_name}</b> — {d['count']} {d['badge']}" for idx, (uid, d) in enumerate(top)]
    txt = "<b>ТОП по активности:</b>\n" + "\n".join(rows)
    if m.from_user.id in ADMINS:
        bot.send_message(m.from_user.id, txt, parse_mode="HTML")
    else:
        bot.reply_to(m, "Только для админов!")

@bot.message_handler(commands=["pdf"])
def pdf_cmd(m):
    if m.from_user.id in ADMINS:
        fname = export_stats_pdf()
        with open(fname, "rb") as f:
            bot.send_document(m.from_user.id, f)
        bot.send_message(m.from_user.id, "PDF-отчёт отправлен.")
    else:
        bot.reply_to(m, "Только для админов!")

@bot.message_handler(commands=["top"])
def top_cmd(m):
    stats_cmd(m)

# --- Сообщения: сбор активности, антиспам ---
@bot.message_handler(func=lambda m: True)
def all_msgs(m):
    update_activity(m.from_user)
    if is_spam(m.text):
        warns.setdefault(m.from_user.id, 0)
        warns[m.from_user.id] += 1
        if warns[m.from_user.id] >= 3:
            bot.ban_chat_member(GROUP_ID, m.from_user.id)
            bot.reply_to(m, "Вы забанены за спам.")
            log_event("ban", m.from_user.id, m.text)
        else:
            bot.reply_to(m, f"⚠️ Предупреждение за спам ({warns[m.from_user.id]}/3)")
        return
    # Можно вставить ответчик на ключевые слова и помощь по майнингу

# --- Flask для Webhook и Cron (если на Render) ---
from flask import Flask, request

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))])
    return 'ok'

@app.route('/cron', methods=['GET'])
def cron():
    scheduled_news()
    return 'Cron executed!'

if __name__ == "__main__":
    app.run(port=5000)
