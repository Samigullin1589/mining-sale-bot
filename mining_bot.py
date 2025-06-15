import os
import time
import openai
import telebot
import requests
import threading
from datetime import datetime

# === НАСТРОЙКИ ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
CRYPTO_NEWS_URL = "https://cryptopanic.com/api/v1/posts/?auth_token=demo&public=true&currencies=BTC"
LEAD_LINK = "https://app.leadteh.ru/w/dTeKr"
POST_INTERVAL = 10800  # 3 часа в секундах

# === ИНИЦИАЛИЗАЦИЯ ===
bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai.api_key = OPENAI_API_KEY

# === СПИСОК КЛЮЧЕВЫХ СЛОВ ===
KEYWORDS = ["где купить", "сколько стоит", "доставка", "гарантия", "цены"]

# === ФУНКЦИЯ: ЗАПРОС К OPENAI ===
def ask_gpt(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return "Извините, произошла ошибка при получении ответа."

# === ФУНКЦИЯ: ПОЛУЧИТЬ НОВОСТИ С CRYPTOPANIC ===
def fetch_news():
    try:
        response = requests.get(CRYPTO_NEWS_URL)
        data = response.json()
        headlines = [post['title'] for post in data.get('results', [])[:5]]
        return "\n".join(f"• {h}" for h in headlines)
    except:
        return "Не удалось получить новости."

# === ФУНКЦИЯ: ПУБЛИКАЦИЯ НОВОСТЕЙ ===
def post_news():
    while True:
        news = fetch_news()
        now = datetime.now().strftime("%H:%M")
        message = f"📰 *Актуальные новости по майнингу* ({now}):\n\n{news}\n\n🔗 [Узнать больше]({LEAD_LINK})"
        try:
            bot.send_message(chat_id="@ВАШ_ЧАТ", text=message, parse_mode="Markdown")
        except Exception as e:
            print("Ошибка отправки новости:", e)
        time.sleep(POST_INTERVAL)

# === ФУНКЦИЯ: ОБРАБОТКА СООБЩЕНИЙ ===
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.lower()
    if any(keyword in text for keyword in KEYWORDS):
        bot.reply_to(message, f"🛠 По вопросам покупки и доставки — наш партнёр: [Связаться]({LEAD_LINK})", parse_mode="Markdown")
    else:
        reply = ask_gpt(message.text)
        bot.reply_to(message, reply)

# === ЗАПУСК ===
threading.Thread(target=post_news).start()
bot.infinity_polling()
