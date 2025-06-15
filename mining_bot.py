import os
import time
import json
import requests
import threading
from flask import Flask, request
from datetime import datetime, timedelta
from collections import defaultdict

import telebot

TOKEN = os.getenv('TELEGRAM_TOKEN')
CRYPTOPANIC_API_KEY = os.getenv('CRYPTOPANIC_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# Основные переменные
ADMIN_IDS = [7473992492, 5860994210]  # id админов
CHAT_ID = -1002408729915  # основной чат @Mining_Sale

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN, threaded=False)

# Кэш для статистики и новостей
stats = defaultdict(int)
news_cache = {"time": 0, "text": ""}
last_news_time = 0

def is_admin(user_id):
    return user_id in ADMIN_IDS

# --- ФУНКЦИЯ ПОЛУЧЕНИЯ НОВОСТЕЙ ---

def fetch_crypto_news():
    global news_cache
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API_KEY}&public=true"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            log_text = f"CryptoPanic ошибка {res.status_code}:\n{res.text[:300]}"
            print(log_text)
            return None
        data = res.json()
        if "results" not in data or not data["results"]:
            print("CryptoPanic: пустой ответ!")
            return None
        news_list = []
        for item in data["results"][:3]:
            title = item.get("title", "")
            url = item.get("url", "")
            news_list.append(f"• [{title}]({url})")
        return "\n".join(news_list)
    except Exception as e:
        print(f"CryptoPanic ошибка: {e}")
        return None

# --- ФУНКЦИЯ АВТОМАТИЧЕСКОЙ ОТПРАВКИ НОВОСТЕЙ ---

def send_news_job():
    global last_news_time
    while True:
        now = datetime.utcnow()
        if now.minute == 0 and now.hour % 3 == 0:  # ровно каждые 3 часа
            if (time.time() - last_news_time) > 3600:  # чтобы не дублировало при рестарте
                send_news()
                last_news_time = time.time()
        time.sleep(60)

def send_news():
    news = fetch_crypto_news()
    if news:
        msg = (
            f"{news}\n\n"
            "🔥 Интересует оборудование? Спецусловия тут: https://app.leadteh.ru/w/dTeKr"
        )
    else:
        msg = (
            "Не удалось получить новости.\n\n"
            "🔥 Интересует оборудование? Спецусловия тут: https://app.leadteh.ru/w/dTeKr"
        )
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Ошибка при отправке новости: {e}")

# --- КОМАНДА /stats ---

@bot.message_handler(commands=['stats', 'стата'])
def stats_command(message):
    if not is_admin(message.from_user.id):
        return
    day = datetime.utcnow().strftime('%Y-%m-%d')
    week = datetime.utcnow().isocalendar()[1]
    user_count = len(stats["users"]) if "users" in stats else 0
    reply = (
        f"Статистика чата:\n"
        f"Сообщений сегодня: {stats.get('today', 0)}\n"
        f"Сообщений за неделю: {stats.get('week', 0)}\n"
        f"Уникальных участников: {user_count}\n"
        f"Ответов бота: {stats.get('bot_replies', 0)}"
    )
    bot.reply_to(message, reply)

# --- УМНЫЙ АВТООТВЕТЧИК ---

KEYWORDS = {
    "купить": "Вы можете купить оборудование у проверенного поставщика: https://app.leadteh.ru/w/dTeKr",
    "что выбрать": "Определитесь с бюджетом и требуемой мощностью. Из популярных — Whatsminer, Antminer.",
    "валюта": "Актуальный курс и новости — cryptopanic.com",
    "розетка": "Рекомендуется использовать отдельную линию электропитания и учитывать мощность ASIC.",
    "обзор": "Актуальные обзоры оборудования — cryptopanic.com и t.me/MiningClubStoreOfficialBOT",
    # ...дополните по желанию
}

@bot.message_handler(func=lambda m: True, content_types=['text'])
def text_handler(message):
    user_id = message.from_user.id
    stats["today"] = stats.get("today", 0) + 1
    stats["week"] = stats.get("week", 0) + 1
    stats.setdefault("users", set()).add(user_id)

    text = message.text.lower()
    for k, v in KEYWORDS.items():
        if k in text:
            stats["bot_replies"] = stats.get("bot_replies", 0) + 1
            bot.reply_to(message, v)
            return
    # Если не нашли ключевых слов — не отвечаем (или можете добавить GPT-режим)

# --- МОДЕРАТОР (ПРОСТЕЙШИЙ ФИЛЬТР) ---
# (добавьте по мере необходимости)

# --- FLASK WEBHOOK ---

@app.route("/webhook", methods=["POST"])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return 'Only JSON allowed', 400

@app.route("/", methods=["GET"])
def index():
    return "Mining_Sale_Bot — работает!"

# --- ЗАПУСК ПОТОКА С НОВОСТЯМИ ---

if __name__ == "__main__":
    threading.Thread(target=send_news_job, daemon=True).start()
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)
