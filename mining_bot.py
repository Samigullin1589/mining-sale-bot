import os
import time
import threading
import logging
from flask import Flask, request
import requests
import telebot
from telebot import types
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Переменные окружения ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CRYPTO_API_KEY = os.getenv('CRYPTO_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

# --- Константы ---
ADMIN_IDS = [7473992492, 5860994210] # ваши id админов
CHAT_ID = -1002408729915             # id группы

REKLAMA_LINK = "https://app.leadteh.ru/w/dTeKr"
NEWS_INTERVAL_HOURS = 3

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# --- Хранилище статистики ---
stats = {
    "messages": [],
    "unique_users": set(),
    "news_posts": [],
    "bot_replies": 0,
    "ads_shown": 0
}

# --- Получение новостей CryptoPanic ---
def fetch_cryptopanic_news():
    url = f'https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&public=true&currencies=BTC,ETH,USDT,USDC'
    try:
        response = requests.get(url, timeout=7)
        if response.status_code == 200:
            data = response.json()
            if 'results' in data and len(data['results']) > 0:
                news = data['results'][0]
                title = news.get('title', 'Нет заголовка')
                url = news.get('url', '')
                return f'📰 {title}\n{url}'
            else:
                return '❌ Нет свежих новостей.'
        else:
            logger.error(f"CryptoPanic error {response.status_code}: {response.text}")
            return f"❗️Ошибка CryptoPanic {response.status_code}"
    except Exception as e:
        logger.error(f"CryptoPanic Exception: {e}")
        return f"❗️Ошибка при получении новостей: {e}"

# --- Отправка новостей с рекламой ---
def send_news_with_ad():
    news_text = fetch_cryptopanic_news()
    ad_text = f"\n\n🔥 Интересует оборудование? Спецусловия тут:\n{REKLAMA_LINK}"
    try:
        bot.send_message(CHAT_ID, f"{news_text}{ad_text}", disable_web_page_preview=True)
        stats['news_posts'].append(datetime.now())
        stats['ads_shown'] += 1
    except Exception as e:
        logger.error(f"Ошибка отправки новости: {e}")

# --- Автоматический постинг новостей каждые 3 часа ---
def schedule_news():
    def job():
        while True:
            now = datetime.now()
            if now.minute == 0 and now.hour % NEWS_INTERVAL_HOURS == 0:
                send_news_with_ad()
            time.sleep(60)
    t = threading.Thread(target=job, daemon=True)
    t.start()

# --- Статистика по чату ---
def get_stats():
    today = datetime.now().date()
    week_ago = today - timedelta(days=6)
    today_msgs = [m for m in stats['messages'] if m[1].date() == today]
    week_msgs = [m for m in stats['messages'] if week_ago <= m[1].date() <= today]
    unique_today = len(set(m[0] for m in today_msgs))
    unique_week = len(set(m[0] for m in week_msgs))
    text = (f"📊 Статистика:\n"
            f"Сегодня сообщений: {len(today_msgs)}\n"
            f"За неделю сообщений: {len(week_msgs)}\n"
            f"Уникальных сегодня: {unique_today}\n"
            f"Уникальных за неделю: {unique_week}\n"
            f"Показов рекламы: {stats['ads_shown']}\n"
            f"Бот ответил: {stats['bot_replies']}\n"
            f"Постов новостей: {len(stats['news_posts'])}")
    return text

# --- Обработка команд /news и /новости ---
@bot.message_handler(commands=['news', 'новости'])
def news_command(message):
    news_text = fetch_cryptopanic_news()
    ad_text = f"\n\n🔥 Интересует оборудование? Спецусловия тут:\n{REKLAMA_LINK}"
    bot.send_message(message.chat.id, f"{news_text}{ad_text}", disable_web_page_preview=True)
    stats['bot_replies'] += 1

# --- Обработка команды /stats (только для админов) ---
@bot.message_handler(commands=['stats', 'стата'])
def stats_command(message):
    if message.from_user.id in ADMIN_IDS:
        bot.send_message(message.chat.id, get_stats())
    else:
        bot.reply_to(message, "⛔️ Только для админов.")

# --- Логика автоответов, модерации, сбора статистики ---
@bot.message_handler(func=lambda m: True, content_types=['text'])
def handle_text(message):
    # Запись статистики
    stats['messages'].append((message.from_user.id, datetime.now()))
    stats['unique_users'].add(message.from_user.id)

    # Ключевые слова — пример
    if any(word in message.text.lower() for word in ['майнинг', 'обзор', 'валюта', 'где купить']):
        bot.reply_to(message, "Задайте уточняющий вопрос: например, какой майнер или что интересует?")
        stats['bot_replies'] += 1

    # Модерация спама и рекламы (пример)
    if "казино" in message.text.lower() or "777" in message.text:
        try:
            bot.delete_message(message.chat.id, message.message_id)
            bot.send_message(message.chat.id, "⛔️ Реклама казино запрещена!")
        except Exception as e:
            logger.warning(f"Ошибка при удалении сообщения: {e}")

# --- Webhook endpoint для Telegram ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    else:
        return 'Invalid request', 403

# --- Старт ---
if __name__ == "__main__":
    # Установить webhook (если не установлен)
    if WEBHOOK_URL:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
    schedule_news()
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)))
