import os
import telebot
import requests
from flask import Flask, request
from datetime import datetime, timedelta

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
ADMIN_ID = os.getenv("ADMIN_ID")  # str

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# Кэш по ключевым словам (на 15 мин)
gpt_cache = {}
CACHE_TTL = timedelta(minutes=15)

# ========== GPT ==========

def ask_gpt(prompt):
    now = datetime.now()
    cached = gpt_cache.get(prompt)
    if cached and now - cached["time"] < CACHE_TTL:
        return cached["response"]

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    json_data = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "Ты — ассистент по майнингу."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
    }

    try:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=json_data, timeout=10)
        res.raise_for_status()
        data = res.json()
        gpt_reply = data["choices"][0]["message"]["content"]
        gpt_cache[prompt] = {"response": gpt_reply, "time": now}
        return gpt_reply

    except requests.exceptions.RequestException as e:
        err_msg = f"❗ GPT ошибка:\n{str(e)}"
        try:
            err_msg += f"\n{res.status_code} {res.text}"
        except:
            pass
        bot.send_message(ADMIN_ID, err_msg)
        return "⚠️ GPT временно недоступен. Попробуйте позже."

# ========== CryptoPanic ==========

def get_crypto_news():
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&public=true"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        articles = data["results"][:5]
        message = "📰 Новости CryptoPanic:\n\n"
        for a in articles:
            message += f"• <a href='{a['url']}'>{a['title']}</a>\n"
        return message
    except requests.exceptions.RequestException as e:
        err = f"CryptoPanic ошибка: {str(e)}"
        try:
            err += f"\n{response.status_code} {response.text}"
        except:
            pass
        bot.send_message(ADMIN_ID, f"🚨 Ошибка в боте:\n\n{err}")
        return "⚠️ Новости временно недоступны."

# ========== Telegram ==========

@bot.message_handler(commands=["start"])
def start_message(msg):
    bot.send_message(msg.chat.id, "Привет! Напиши вопрос по майнингу.")

@bot.message_handler(func=lambda message: True)
def reply_handler(message):
    text = message.text.strip().lower()
    if "новости" in text:
        bot.send_message(message.chat.id, get_crypto_news(), parse_mode="HTML")
    else:
        reply = ask_gpt(message.text)
        bot.send_message(message.chat.id, reply)

# ========== Webhook ==========

@app.route('/webhook', methods=["POST"])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return '', 200
    return 'Unsupported Media Type', 415

# ========== Запуск Flask ==========

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
