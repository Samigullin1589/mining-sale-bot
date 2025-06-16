import os
import json
import time
import pytz
import logging
import requests
import feedparser
from datetime import datetime
import telebot
from telebot import types
import openai
import gspread
from google.oauth2.service_account import Credentials
from fpdf import FPDF

# --- Переменные окружения ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY")
CRYPTO_PANIC_KEY = os.environ.get("CRYPTO_PANIC_KEY")
GOOGLE_SHEET = os.environ.get("GOOGLE_SHEET") # ID таблицы
ADMIN_IDS = [7473992492, 5860994210]  # Админы группы
GROUP_ID = -1002408729915

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "sage-instrument-338811-a8c8cc7f2500.json"

# --- Бот ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- Google Sheets ---
def get_sheet():
    creds = Credentials.from_service_account_file(
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"],
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(GOOGLE_SHEET).worksheet("Стата с барахолки майнинг")
    return sheet

# --- Кнопки для URL ---
BUTTON_TEXTS = [
    "💰 Посмотреть актуальный прайс и приобрести",
    "🔥 Интересуют спецусловия на оборудование?",
    "⚡️ Получить свежий прайс прямо сейчас",
    "🎯 Перейти к выгодным предложениям",
    "🚀 Узнать цены и купить оборудование",
]
def get_rotated_button():
    return BUTTON_TEXTS[int(time.time()) % len(BUTTON_TEXTS)]

# --- Локализация ---
def tr(text, lang="ru"):
    translations = {
        "ru": {
            "news": "Новости",
            "reward": "Вы получили награду!",
            "stats": "Статистика за сутки",
        },
        "en": {
            "news": "News",
            "reward": "You received a reward!",
            "stats": "Stats for the day",
        }
    }
    return translations.get(lang, {}).get(text, text)

# --- Логирование ошибок в Google Sheets ---
def log_error(exc_text, comment=""):
    try:
        sheet = get_sheet()
        now = datetime.now(pytz.timezone("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([now, "ERROR", exc_text, comment])
    except Exception as e:
        print("Failed to log error:", e)

# --- Авто-спам фильтр (self-learning, простая реализация) ---
SPAM_PATTERNS_FILE = "spam_patterns.txt"
def load_spam_patterns():
    if not os.path.exists(SPAM_PATTERNS_FILE):
        with open(SPAM_PATTERNS_FILE, "w", encoding="utf-8") as f:
            f.write("казино\nfast payout\nfree money\n")
    with open(SPAM_PATTERNS_FILE, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def save_spam_pattern(pattern):
    with open(SPAM_PATTERNS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{pattern}\n")

def is_spam(msg):
    text = msg.text.lower()
    for pat in load_spam_patterns():
        if pat in text:
            return True
    return False

# --- Рейтинг пользователей ---
USER_STATS_FILE = "user_stats.json"
def update_user_stat(uid):
    if not os.path.exists(USER_STATS_FILE):
        stats = {}
    else:
        with open(USER_STATS_FILE, encoding="utf-8") as f:
            stats = json.load(f)
    stats[str(uid)] = stats.get(str(uid), 0) + 1
    with open(USER_STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f)

def get_top_users(n=3):
    if not os.path.exists(USER_STATS_FILE):
        return []
    with open(USER_STATS_FILE, encoding="utf-8") as f:
        stats = json.load(f)
    sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
    return sorted_stats[:n]

def reward_top_users():
    top = get_top_users(3)
    rewards = ["🥇", "🥈", "🥉"]
    for i, (uid, count) in enumerate(top):
        try:
            bot.send_message(int(uid), f"{rewards[i]} {tr('reward')}")
        except Exception as e:
            log_error(str(e), f"Reward to {uid}")

# --- Авто-сжатие и перевод новостей ---
def summarize_translate(news, lang="ru"):
    openai.api_key = OPENAI_API_KEY
    prompt = f"Сделай краткое резюме и переведи на {lang.upper()}: {news}"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content.strip()

# --- Получение новостей ---
def get_news_cryptopanic():
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_PANIC_KEY}&currencies=BTC,ETH"
    data = requests.get(url).json()
    items = data["results"]
    return [item["title"] for item in items[:3]]

def get_news_newsapi():
    url = f"https://newsapi.org/v2/top-headlines?category=business&q=crypto&apiKey={NEWSAPI_KEY}&language=en"
    data = requests.get(url).json()
    if data["status"] != "ok":
        return []
    return [art["title"] for art in data["articles"][:3]]

def get_news_coindesk():
    feed = feedparser.parse("https://www.coindesk.com/arc/outboundfeeds/rss/")
    return [entry["title"] for entry in feed.entries[:3]]

# --- Генерация PDF статистики (по команде) ---
def export_stats_pdf():
    sheet = get_sheet()
    data = sheet.get_all_values()
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for row in data[-50:]:
        pdf.cell(200, 10, txt=" | ".join(row), ln=1)
    pdf.output("stats.pdf")
    return "stats.pdf"

# --- Команды Telegram ---
@bot.message_handler(commands=["start"])
def cmd_start(m):
    bot.send_message(m.chat.id, "Привет! Я бот Mining Sale, использую /news, /стата, /top, /addspam, /stats_pdf.")

@bot.message_handler(commands=["news", "новости"])
def cmd_news(m):
    try:
        news = get_news_cryptopanic() + get_news_newsapi() + get_news_coindesk()
        txt = ""
        for n in news:
            txt += f"📰 {summarize_translate(n, 'ru')}\n"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(get_rotated_button(), url="https://app.leadteh.ru/w/dTeKr"))
        bot.send_message(m.chat.id, txt, reply_markup=markup)
        update_user_stat(m.from_user.id)
    except Exception as e:
        log_error(str(e), "news cmd")
        bot.send_message(m.chat.id, "Ошибка получения новостей!")

@bot.message_handler(commands=["top"])
def cmd_top(m):
    top = get_top_users(5)
    msg = "🏆 Топ-5 активных участников:\n"
    for i, (uid, count) in enumerate(top):
        msg += f"{i+1}) {uid}: {count} сообщений\n"
    bot.send_message(m.chat.id, msg)

@bot.message_handler(commands=["стата"])
def cmd_stata(m):
    try:
        sheet = get_sheet()
        data = sheet.get_all_values()[-10:]
        msg = "\n".join(" | ".join(r) for r in data)
        bot.send_message(m.chat.id, f"Последние записи:\n{msg}")
    except Exception as e:
        log_error(str(e), "стата cmd")
        bot.send_message(m.chat.id, "Ошибка выгрузки статы.")

@bot.message_handler(commands=["stats_pdf"])
def cmd_stats_pdf(m):
    try:
        f = export_stats_pdf()
        with open(f, "rb") as doc:
            bot.send_document(m.chat.id, doc)
    except Exception as e:
        log_error(str(e), "stats_pdf cmd")
        bot.send_message(m.chat.id, "Ошибка при формировании PDF.")

@bot.message_handler(commands=["addspam"])
def cmd_addspam(m):
    # usage: /addspam слово/фраза
    pat = m.text.split(maxsplit=1)[-1]
    save_spam_pattern(pat)
    bot.send_message(m.chat.id, f"Паттерн '{pat}' добавлен в фильтр!")

# --- Фильтр спама, обработка сообщений ---
@bot.message_handler(func=lambda m: True, content_types=["text"])
def all_msgs(m):
    if is_spam(m):
        bot.delete_message(m.chat.id, m.message_id)
        bot.send_message(m.from_user.id, "Ваше сообщение было определено как спам и удалено.")
        log_error("Spam deleted", m.text)
        return
    update_user_stat(m.from_user.id)

# --- Автонаграждение (раз в сутки) ---
def daily_tasks():
    while True:
        now = datetime.now(pytz.timezone("Europe/Moscow"))
        if now.hour == 23:
            reward_top_users()
        time.sleep(3600)

import threading
threading.Thread(target=daily_tasks, daemon=True).start()

if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True)
