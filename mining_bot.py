import os
import json
import time
import requests
from flask import Flask, request
from threading import Thread
from datetime import datetime, timedelta

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
CRYPTO_API_KEY = os.environ['CRYPTO_API_KEY']
WEBHOOK_URL = os.environ['WEBHOOK_URL']
CHAT_ID = -1002408729915  # Mining_Sale
ADMINS = [7473992492, 5860994210]  # @mining_sale_admin, @MoLd8

GPT_CACHE = {}
LAST_NEWS_TIME = 0
NEWS_INTERVAL = 10800  # 3 часа
CACHE_TTL = timedelta(days=3)

HEADERS = {
    "Authorization": f"Bearer {OPENAI_API_KEY}"
}

def send_message(chat_id, text, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    requests.post(url, json=payload)

def send_admin_error_log(error_text):
    for admin in ADMINS:
        send_message(admin, f"🚨 Ошибка в боте:\n\n{error_text}")

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data:
        return "ok"
    msg = data["message"]
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = msg.get("text", "")

    if "/stats" in text and user_id in ADMINS:
        stats = f"🔢 Сообщений в кеше: {len(GPT_CACHE)}"
        send_message(chat_id, stats)
        return "ok"

    if "казино" in text.lower():
        send_message(chat_id, "🚫 Реклама казино запрещена.")
        return "ok"

    response_text = handle_gpt_response(text)
    if response_text:
        send_message(chat_id, response_text)

    return "ok"

def handle_gpt_response(text):
    now = datetime.utcnow()
    if text in GPT_CACHE:
        cached, timestamp = GPT_CACHE[text]
        if now - timestamp < CACHE_TTL:
            return cached

    prompt = f"Ты помощник в Telegram-чате по майнингу. Пользователь спросил: {text}. Ответь строго по теме, кратко и понятно."

    try:
        res = requests.post("https://api.openai.com/v1/chat/completions", headers=HEADERS, json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
        })
        if res.status_code != 200:
            send_admin_error_log(f"OpenAI ошибка {res.status_code}:\n{res.text}")
            return "⚠️ Временная ошибка. Попробуйте позже."
        output = res.json()["choices"][0]["message"]["content"]
        GPT_CACHE[text] = (output, now)
        return output
    except Exception as e:
        send_admin_error_log(str(e))
        return "⚠️ GPT недоступен. Обратитесь позже."

def post_news():
    global LAST_NEWS_TIME
    while True:
        now = time.time()
        if now - LAST_NEWS_TIME >= NEWS_INTERVAL:
            try:
                news = fetch_crypto_news()
                ad = "📣 Надёжный поставщик ASIC-оборудования (реклама): https://app.leadteh.ru/w/dTeKr"
                send_message(CHAT_ID, news + "\n\n" + ad)
                LAST_NEWS_TIME = now
            except Exception as e:
                send_admin_error_log(str(e))
        time.sleep(60)

def fetch_crypto_news():
    res = requests.get(f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&public=true")
    if res.status_code != 200:
        raise Exception(f"CryptoPanic ошибка {res.status_code}:\n{res.text}")
    articles = res.json().get("results", [])[:3]
    return "\n\n".join([f"📰 [{a['title']}]({a['url']})" for a in articles])

def set_webhook():
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/setWebhook?url={WEBHOOK_URL}"
    res = requests.get(url)
    print(res.text)

if __name__ == "__main__":
    Thread(target=post_news).start()
    set_webhook()
    app.run(host="0.0.0.0", port=10000)
