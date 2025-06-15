import os
import time
import json
import requests
from flask import Flask, request
import threading
from collections import defaultdict

# --- ENV ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CRYPTO_API_KEY = os.getenv('CRYPTO_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID', '-1002408729915')
ADMIN_CHAT_IDS = os.getenv('ADMIN_CHAT_IDS', '7473992492,5860994210').split(',')

BOT_NAME = "Mining_Sale_bot"
NEWS_INTERVAL = 3 * 60 * 60  # 3 часа

# --- GPT CACHE ---
gpt_cache = {}

# --- Ссылки для перехода (без слова "партнер") ---
def load_links():
    try:
        with open("partners.txt", "r", encoding="utf-8") as f:
            links = [line.strip() for line in f if line.strip()]
        return links
    except Exception:
        return ["https://app.leadteh.ru/w/dTeKr"]

# --- Модерация: шаблоны и статистика ---
moderation_patterns = set()
warned_users = defaultdict(int)
stats = {
    "messages_today": 0,
    "messages_week": 0,
    "unique_users": set(),
    "new_users": set(),
    "ad_shown": 0,
    "bot_answers": 0,
    "most_active": defaultdict(int)
}

app = Flask(__name__)

# --- Автопостинг новостей каждые 3 часа ---
def auto_post_news():
    while True:
        post_news_to_chat()
        time.sleep(NEWS_INTERVAL)

def post_news_to_chat():
    news, err = fetch_cryptopanic_news()
    if err:
        send_admin(f"CryptoPanic ошибка {err['code']}:\n{err['body']}")
        return
    link = pick_link()
    text = format_news(news) + "\n\n" + f"🔥 Интересует оборудование? Спецусловия тут: {link}"
    send_message(GROUP_CHAT_ID, text)
    stats["ad_shown"] += 1

def fetch_cryptopanic_news():
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&currencies=BTC,ETH&filter=hot"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json(), None
        else:
            return None, {"code": r.status_code, "body": r.text}
    except Exception as e:
        return None, {"code": "ERR", "body": str(e)}

def format_news(news_json):
    try:
        items = news_json["results"][:5]
        out = ["📰 Последние новости:"]
        for i, item in enumerate(items, 1):
            out.append(f"{i}. {item['title']} ({item['url']})")
        return "\n".join(out)
    except Exception:
        return "Не удалось получить новости."

def pick_link():
    links = load_links()
    import random
    return random.choice(links) if links else "https://app.leadteh.ru/w/dTeKr"

def gpt_query(prompt):
    if prompt in gpt_cache:
        return gpt_cache[prompt]
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    data = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "Отвечай кратко, профессионально, без воды. Только по делу про майнинг, оборудование, крипту. Не выдумывай новости!"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 500
    }
    try:
        r = requests.post(url, headers=headers, json=data, timeout=15)
        if r.status_code == 200:
            result = r.json()["choices"][0]["message"]["content"]
            gpt_cache[prompt] = result
            return result
        else:
            log_error(f"OpenAI error {r.status_code}: {r.text}")
            return f"⚠️ GPT временно недоступен. Попробуйте позже. [{r.status_code}]"
    except Exception as e:
        log_error(f"OpenAI error: {str(e)}")
        return f"⚠️ GPT временно недоступен. Попробуйте позже."

def moderate_message(user_id, user_name, text):
    spam_words = ["casino", "казино", "дешевые бабки", "лотерея", "poker", "ставки", "быстрые деньги"]
    if any(sw in text.lower() for sw in spam_words):
        return "spam"
    for pattern in moderation_patterns:
        if pattern in text.lower():
            warned_users[user_id] += 1
            if warned_users[user_id] == 1:
                return "warn1"
            elif warned_users[user_id] == 2:
                return "warn2"
            else:
                return "ban"
    return None

def send_admin(text):
    for admin_id in ADMIN_CHAT_IDS:
        send_message(admin_id.strip(), f"Ошибка в боте:\n{text}")

def is_admin(user_id):
    return str(user_id) in [a.strip() for a in ADMIN_CHAT_IDS]

def log_error(text):
    print(f"ERROR: {text}")
    send_admin(text)

def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=data, timeout=5)
    except Exception as e:
        print(f"SendMessage error: {e}")

def delete_message(chat_id, message_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/deleteMessage"
    requests.post(url, data={"chat_id": chat_id, "message_id": message_id})

def ban_user(chat_id, user_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/banChatMember"
    requests.post(url, data={"chat_id": chat_id, "user_id": user_id})

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = request.get_json()
        handle_update(update)
        return "ok", 200
    return "Unsupported Media Type", 415

def handle_update(update):
    try:
        msg = update.get("message") or update.get("edited_message")
        if not msg: return

        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        user_name = msg["from"].get("username", "")
        text = msg.get("text", "")

        stats["messages_today"] += 1
        stats["messages_week"] += 1
        stats["unique_users"].add(user_id)
        stats["most_active"][user_name] += 1

        mod = moderate_message(user_id, user_name, text)
        if mod == "spam":
            delete_message(chat_id, msg["message_id"])
            send_message(chat_id, "⚠️ Сообщение удалено (спам/реклама запрещена)")
            return
        elif mod == "warn1":
            send_message(chat_id, f"⚠️ @{user_name}, пожалуйста, не публикуйте подозрительные сообщения.")
            return
        elif mod == "warn2":
            send_message(chat_id, f"‼️ @{user_name}, последнее предупреждение за подозрительные сообщения.")
            return
        elif mod == "ban":
            ban_user(chat_id, user_id)
            send_message(chat_id, f"⛔️ Пользователь @{user_name} забанен за подозрительную активность.")
            return

        if text.lower().startswith("/подозрительно"):
            pattern = text.partition(" ")[2].strip().lower()
            if pattern:
                moderation_patterns.add(pattern)
                send_message(chat_id, f"Добавлен новый шаблон подозрительных сообщений: {pattern}")
            return

        if text.lower().startswith("/стата"):
            if is_admin(user_id):
                report = generate_stats_report()
                send_message(chat_id, report)
            else:
                send_message(chat_id, "Команда доступна только администраторам.")
            return

        keywords = ["майнинг", "asic", "whatsminer", "antminer", "крипта", "обзор", "где купить", "розетка", "валюта", "сравнить", "выбор"]
        if any(kw in text.lower() for kw in keywords):
            reply = gpt_query(text)
            send_message(chat_id, reply)
            stats["bot_answers"] += 1
            return

        if text.lower() in ["новости", "/news"]:
            news, err = fetch_cryptopanic_news()
            if err:
                send_message(chat_id, f"CryptoPanic ошибка {err['code']}:\n{err['body']}")
                return
            link = pick_link()
            news_text = format_news(news) + "\n\n" + f"🔥 Интересует оборудование? Спецусловия тут: {link}"
            send_message(chat_id, news_text)
            stats["ad_shown"] += 1
            return

    except Exception as e:
        log_error(f"handle_update error: {str(e)}")

def generate_stats_report():
    try:
        report = [
            "📊 Статистика Mining_Sale_Bot:",
            f"- Сообщений сегодня: {stats['messages_today']}",
            f"- Сообщений за неделю: {stats['messages_week']}",
            f"- Уникальных участников: {len(stats['unique_users'])}",
            f"- Новых пользователей: {len(stats['new_users'])}",
            f"- Кол-во переходов по ссылкам: {stats['ad_shown']}",
            f"- Ответов бота: {stats['bot_answers']}",
            "- Топ-5 самых активных участников:"
        ]
        top = sorted(stats["most_active"].items(), key=lambda x: x[1], reverse=True)[:5]
        for u, cnt in top:
            report.append(f"  @{u}: {cnt} сообщений")
        return "\n".join(report)
    except Exception as e:
        return f"Ошибка генерации отчёта: {str(e)}"

if __name__ == "__main__":
    if GROUP_CHAT_ID:
        threading.Thread(target=auto_post_news, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
