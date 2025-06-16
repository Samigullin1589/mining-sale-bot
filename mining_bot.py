import os
import json
import logging
import time
import random
import requests
import openai
import gspread
import pytz
from datetime import datetime, timedelta
from fpdf import FPDF
from feedparser import parse as feedparse
from oauth2client.service_account import ServiceAccountCredentials
from pyTelegramBotAPI import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- Константы ---
TG_TOKEN = os.getenv("TELEGRAM_TOKEN", "ВАШ_ТГ_ТОКЕН")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "ВАШ_OPENAI_API_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "ВАШ_NEWSAPI_KEY")
ADMIN_IDS = [7473992492, 5860994210]   # Ваши id админов
GROUP_ID = -1002408729915              # id группы
GOOGLE_CREDS_PATH = '/etc/secrets/sage-instrument-338811-a8c8cc7f2500.json'
SHEET_ID = '1WqzsXwqw-aDH_lNWSpX5bjHFqT5BHmXYFSgHupAlWQg'
SHEET_TAB = 'Лист1'
REKLAMA_LINK = "https://app.leadteh.ru/w/dTeKr"
BUTTON_CTA = [
    "💰 Посмотреть актуальный прайс и приобрести",
    "🔥 Получить спецусловия прямо сейчас!",
    "🤑 Запросить оптовый прайс и консультацию",
    "📦 Выбрать оборудование для майнинга с гарантией"
]
TIMEZONE = pytz.timezone('Europe/Moscow')

# --- Логирование в Google Sheets ---
def log_event(event_type, user_id, msg, extra=None):
    try:
        creds_dict = json.load(open(GOOGLE_CREDS_PATH, "r"))
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict, [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ])
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_TAB)
        now = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
        ws.append_row([now, event_type, str(user_id), str(msg), json.dumps(extra or {})])
    except Exception as e:
        print(f"[LOG ERR]: {e}")

# --- Инициализация бота и OpenAI ---
bot = telebot.TeleBot(TG_TOKEN)
openai.api_key = OPENAI_KEY

# --- Перевод и сжатие текста через GPT ---
def gpt_translate_summary(text, lang="ru"):
    prompt = (
        f"Кратко перескажи главное (3-5 предложений) и переведи на {lang}:\n\n"
        f"Текст: \"{text}\""
    )
    resp = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400, temperature=0.6
    )
    return resp.choices[0].message.content.strip()

# --- КНОПКА CTA (ротация текста) ---
def cta_keyboard():
    btn_text = random.choice(BUTTON_CTA)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(btn_text, url=REKLAMA_LINK))
    return kb

# --- Получение новостей ---
def fetch_cryptopanic():
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token=ВАШ_CRYPTOPANIC_TOKEN&public=true"
    resp = requests.get(url, timeout=10).json()
    news = []
    for post in resp.get("results", [])[:3]:
        news.append(post["title"] + "\n" + post["url"])
    return news

def fetch_newsapi():
    url = f"https://newsapi.org/v2/top-headlines?category=business&q=crypto&language=en&apiKey={NEWSAPI_KEY}"
    resp = requests.get(url, timeout=10).json()
    return [a["title"] for a in resp.get("articles", [])[:3]]

def fetch_rss(source="https://cointelegraph.com/rss"):
    d = feedparse(source)
    return [entry.title for entry in d.entries[:3]]

# --- Основная рассылка новостей ---
def send_news(chat_id, lang="ru"):
    try:
        all_news = []
        for get_news in [fetch_cryptopanic, fetch_newsapi, lambda: fetch_rss("https://www.coindesk.com/arc/outboundfeeds/rss/")]:

            for n in get_news():
                translated = gpt_translate_summary(n, lang)
                bot.send_message(chat_id, translated, reply_markup=cta_keyboard())
                all_news.append(translated)
        log_event("news_sent", chat_id, "ok", {"count": len(all_news)})
    except Exception as e:
        bot.send_message(chat_id, f"❗️ Ошибка отправки новостей: {e}")
        log_event("news_error", chat_id, str(e))

# --- Команды Telegram ---
@bot.message_handler(commands=['news', 'новости'])
def cmd_news(msg):
    send_news(msg.chat.id)
    log_event("cmd_news", msg.from_user.id, msg.text)

@bot.message_handler(commands=['pdf'])
def cmd_pdf(msg):
    try:
        # Формируем PDF по последним 10 строкам статистики
        creds_dict = json.load(open(GOOGLE_CREDS_PATH, "r"))
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict, [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ])
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_TAB)
        data = ws.get_all_values()[-10:]
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for row in data:
            pdf.cell(200, 10, txt=" | ".join(row), ln=True)
        fname = "stats.pdf"
        pdf.output(fname)
        with open(fname, "rb") as f:
            bot.send_document(msg.chat.id, f)
        log_event("pdf_sent", msg.from_user.id, "ok")
    except Exception as e:
        bot.send_message(msg.chat.id, f"Ошибка PDF: {e}")
        log_event("pdf_err", msg.from_user.id, str(e))

# --- Фильтр спама (простая версия, можно расширять) ---
SPAM_PATTERNS = ["scam", "casino", "казино", "даром", "free money"]

@bot.message_handler(func=lambda m: any(x in m.text.lower() for x in SPAM_PATTERNS))
def filter_spam(msg):
    bot.delete_message(msg.chat.id, msg.message_id)
    log_event("spam_blocked", msg.from_user.id, msg.text)

# --- Рейтинг активности (очень базово, можно доработать под ваши нужды) ---
@bot.message_handler(commands=['top'])
def cmd_top(msg):
    try:
        creds_dict = json.load(open(GOOGLE_CREDS_PATH, "r"))
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            creds_dict, [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ])
        gc = gspread.authorize(creds)
        ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_TAB)
        data = ws.get_all_values()
        user_stats = {}
        for row in data:
            uid = row[2]
            user_stats[uid] = user_stats.get(uid, 0) + 1
        top = sorted(user_stats.items(), key=lambda x: -x[1])[:3]
        res = "\n".join([f"{i+1}. {uid} — {cnt} сообщений" for i, (uid, cnt) in enumerate(top)])
        bot.send_message(msg.chat.id, f"🏆 Топ-3 самых активных:\n{res}")
        log_event("cmd_top", msg.from_user.id, "ok", {"result": res})
    except Exception as e:
        bot.send_message(msg.chat.id, f"Ошибка рейтинга: {e}")
        log_event("top_err", msg.from_user.id, str(e))

# --- Базовая обработка всех остальных сообщений для лога ---
@bot.message_handler(func=lambda m: True)
def all_handler(msg):
    log_event("msg", msg.from_user.id, msg.text)

# --- Запуск бота ---
if __name__ == "__main__":
    bot.polling(none_stop=True)
