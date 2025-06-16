import os
import json
import time
import logging
import threading
import requests
import gspread
import feedparser
from flask import Flask, request
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials
from telebot import TeleBot, types

# --- ENV ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
CRYPTO_API_KEY = os.getenv('CRYPTO_API_KEY', '')
ADMINS = [7473992492, 5860994210]
GROUP_ID = -1002408729915

AD_URLS = [
    {"text": "💰 Посмотреть актуальный прайс и приобрести", "url": "https://app.leadteh.ru/w/dTeKr"},
    {"text": "🔥 Лучшие условия на оборудование здесь", "url": "https://app.leadteh.ru/w/dTeKr"},
    {"text": "📦 Купить ASIC-майнер выгодно", "url": "https://app.leadteh.ru/w/dTeKr"}
]

SHEET_ID = '1WqzsXwqw-aDH_lNWSpX5bjHFqT5BHmXYFSgHupAlWQg'
GSHEET_JSON = 'sage-instrument-338811-a8c8cc7f2500.json'

bot = TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)
stats = {
    "messages": 0, "users": set(), "ad_views": 0, "bot_replies": 0,
    "new_users": set(), "user_msgs": {}, "user_lang": {}, "daily_msgs": {}, "weekly_msgs": {}, "monthly_msgs": {}
}
last_news = ""  # чтобы не повторять новости

# Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GSHEET_JSON, scope)
gs_client = gspread.authorize(creds)
sheet = gs_client.open_by_key(SHEET_ID).sheet1

# ---- Фильтр спама ----
SPAM_FILE = 'spam_patterns.txt'
def load_spam():
    try:
        with open(SPAM_FILE, 'r', encoding='utf8') as f:
            return [line.strip().lower() for line in f if line.strip()]
    except:
        return ["казино", "ставки", "free btc", "быстрый заработок", "free usdt"]
def save_spam(patterns):
    with open(SPAM_FILE, 'w', encoding='utf8') as f:
        for line in patterns:
            f.write(line+'\n')
spam_patterns = load_spam()

def log_admin(msg):
    for admin_id in ADMINS:
        bot.send_message(admin_id, msg)

def gpt_translate(text, lang="ru"):
    try:
        if lang == "ru":
            prompt = f"Переведи на русский, только саму новость, без лишнего."
        elif lang == "en":
            prompt = f"Translate to English, just the news, no comments."
        else:
            prompt = f"Переведи на русский, только саму новость, без лишнего."
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        data = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": text}
            ],
            "max_tokens": 500, "temperature": 0.5
        }
        r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data, timeout=15)
        r.raise_for_status()
        return r.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        log_admin(f"GPT error: {str(e)}")
        return text

def get_user_lang(uid):
    return stats["user_lang"].get(uid, "ru")

def set_user_lang(uid, lang):
    stats["user_lang"][uid] = lang

# --- Новости CryptoPanic или Cointelegraph ---
def get_crypto_news(uid=0):
    # news_text, link
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTO_API_KEY}&public=true&currencies=BTC,ETH"
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            posts = data.get('results', [])
            if posts:
                post = posts[0]
                lang = get_user_lang(uid)
                ru_title = gpt_translate(post['title'], lang=lang)
                return ru_title, post['url']
    except Exception as e:
        log_admin(f"Ошибка CryptoPanic: {str(e)}")
    # Резерв: Cointelegraph RSS
    try:
        d = feedparser.parse("https://cointelegraph.com/rss")
        entry = d.entries[0]
        title = entry.title
        link = entry.link
        lang = get_user_lang(uid)
        ru_title = gpt_translate(title, lang=lang)
        return ru_title, link
    except Exception as e:
        log_admin(f"Ошибка Cointelegraph: {str(e)}")
        return "Новости недоступны", None

def send_news_with_button(chat_id, uid=0, news=None):
    ad = AD_URLS[int(time.time()) % len(AD_URLS)]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(ad["text"], url=ad["url"]))
    if not news:
        news = get_crypto_news(uid)
    news_text, link = news
    text = f"📰 {news_text}"
    if link:
        text += f"\n\n{link}"
    bot.send_message(chat_id, text, reply_markup=markup)
    stats["ad_views"] += 1

def schedule_news():
    last_sent = ""
    while True:
        now = datetime.utcnow()
        if now.hour % 3 == 0 and now.minute < 3:
            news_text, link = get_crypto_news()
            if news_text != last_sent:
                send_news_with_button(GROUP_ID, news=(news_text, link))
                last_sent = news_text
            time.sleep(180)
        else:
            time.sleep(60)

def dump_stats():
    # Статистика: выгрузка и автонаграды за день
    while True:
        now = datetime.utcnow()
        if now.hour == 21 and now.minute < 10:
            day_row = [
                str(datetime.now()),
                stats["messages"],
                len(stats["users"]),
                len(stats["new_users"]),
                stats["ad_views"],
                stats["bot_replies"]
            ]
            sheet.append_row(day_row)
            # Топ-1 актив
            top = sorted(stats["user_msgs"].items(), key=lambda x: x[1], reverse=True)
            if top:
                best_id = top[0][0]
                bot.send_message(GROUP_ID, f"👏 Поздравляем самого активного участника дня: [{best_id}](tg://user?id={best_id})!", parse_mode="Markdown")
            # Админам отчет
            msg = (
                f"Стата за сутки:\n"
                f"Сообщений: {stats['messages']}\n"
                f"Уникальных: {len(stats['users'])}\n"
                f"Новых: {len(stats['new_users'])}\n"
                f"Реклама: {stats['ad_views']}\n"
                f"Бот ответов: {stats['bot_replies']}"
            )
            log_admin(msg)
            stats["messages"] = 0
            stats["ad_views"] = 0
            stats["bot_replies"] = 0
            stats["new_users"].clear()
            stats["user_msgs"].clear()
        time.sleep(60*10)

@bot.message_handler(commands=['start', 'help'])
def help_msg(message):
    lang = get_user_lang(message.from_user.id)
    msg = {
        "ru": "Я Mining Sale Bot! Пиши вопросы — получай свежие новости и аналитику по майнингу.\nДоступные команды: /news, /stats, /top, /lang, /spam_add, /spam_list, /spam_del",
        "en": "I'm Mining Sale Bot! Ask questions — get fresh mining news and analytics.\nCommands: /news, /stats, /top, /lang, /spam_add, /spam_list, /spam_del"
    }
    bot.send_message(message.chat.id, msg[lang])

@bot.message_handler(commands=['lang'])
def setlang(message):
    parts = message.text.split()
    if len(parts) > 1 and parts[1].lower() in ["ru", "en"]:
        set_user_lang(message.from_user.id, parts[1].lower())
        bot.reply_to(message, f"Язык установлен: {parts[1].upper()}")
    else:
        bot.reply_to(message, "Укажите ru или en (Choose ru or en). Пример: /lang ru")

@bot.message_handler(commands=['news', 'новости'])
def cmd_news(message):
    send_news_with_button(message.chat.id, message.from_user.id)

@bot.message_handler(commands=['stats'])
def stats_cmd(message):
    if message.from_user.id in ADMINS:
        msg = (
            f"Сегодня:\n"
            f"Сообщений: {stats['messages']}\n"
            f"Уникальных: {len(stats['users'])}\n"
            f"Новых: {len(stats['new_users'])}\n"
            f"Реклама: {stats['ad_views']}\n"
            f"Бот ответов: {stats['bot_replies']}"
        )
        bot.reply_to(message, msg)
@bot.message_handler(commands=['stats_week'])
def stats_week(message):
    if message.from_user.id in ADMINS:
        # Здесь просто пример — можно подключить подсчет по датам
        bot.reply_to(message, "Стата за неделю: (реализуйте подсчет, если надо — помогу).")

@bot.message_handler(commands=['stats_month'])
def stats_month(message):
    if message.from_user.id in ADMINS:
        bot.reply_to(message, "Стата за месяц: (реализуйте подсчет, если надо — помогу).")

@bot.message_handler(commands=['top'])
def top_users(message):
    # Топ-10
    top = sorted(stats["user_msgs"].items(), key=lambda x: x[1], reverse=True)[:10]
    out = ["🏆 ТОП-10 активных участников:"]
    for i, (uid, count) in enumerate(top, 1):
        out.append(f"{i}. [{uid}](tg://user?id={uid}) — {count} сообщений")
    bot.send_message(message.chat.id, "\n".join(out), parse_mode="Markdown")

# === Автообучаемый фильтр спама ===
@bot.message_handler(commands=['spam_add'])
def add_spam(message):
    if message.from_user.id in ADMINS:
        parts = message.text.split(maxsplit=1)
        if len(parts) > 1:
            spam_patterns.append(parts[1].strip().lower())
            save_spam(spam_patterns)
            bot.reply_to(message, f"Шаблон добавлен: {parts[1]}")
        else:
            bot.reply_to(message, "Пример: /spam_add плохой_текст")

@bot.message_handler(commands=['spam_list'])
def spam_list(message):
    if message.from_user.id in ADMINS:
        text = "\n".join([f"{i+1}. {p}" for i,p in enumerate(spam_patterns)])
        bot.reply_to(message, f"Текущие шаблоны спама:\n{text}")

@bot.message_handler(commands=['spam_del'])
def spam_del(message):
    if message.from_user.id in ADMINS:
        parts = message.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < len(spam_patterns):
                rem = spam_patterns.pop(idx)
                save_spam(spam_patterns)
                bot.reply_to(message, f"Удалено: {rem}")
            else:
                bot.reply_to(message, "Нет такого номера.")
        else:
            bot.reply_to(message, "Пример: /spam_del 2")

@bot.message_handler(func=lambda m: True)
def main_handler(message):
    stats["messages"] += 1
    stats["users"].add(message.from_user.id)
    stats["user_msgs"][message.from_user.id] = stats["user_msgs"].get(message.from_user.id, 0) + 1
    if message.from_user.id not in stats["new_users"]:
        stats["new_users"].add(message.from_user.id)
    # Спам
    lower = message.text.lower()
    for pattern in spam_patterns:
        if pattern in lower:
            bot.delete_message(message.chat.id, message.message_id)
            bot.send_message(message.chat.id, "⛔️ Спам/мошенничество. Пользователь заблокирован.")
            try:
                bot.kick_chat_member(message.chat.id, message.from_user.id)
            except:
                pass
            return
    # Автоответы
    keywords = ["майнинг", "asic", "купить", "валюта", "розетка", "выгодно", "что выбрать", "обзор"]
    if any(k in lower for k in keywords):
        lang = get_user_lang(message.from_user.id)
        if lang == "en":
            prompt = f"Answer concisely in English, only about mining: {message.text}"
        else:
            prompt = f"Ответь кратко на русском и только по теме майнинга: {message.text}"
        answer = gpt_translate(prompt, lang=lang)
        bot.reply_to(message, answer)
        stats["bot_replies"] += 1
    elif "новости" in lower or "news" in lower:
        cmd_news(message)

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_str = request.get_data().decode('utf-8')
        update = types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return 'ok', 200
    else:
        return 'invalid content-type', 403

def run_bot():
    bot.remove_webhook()
    bot.set_webhook(url=os.getenv('WEBHOOK_URL'))
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000)), debug=False)

if __name__ == '__main__':
    threading.Thread(target=schedule_news, daemon=True).start()
    threading.Thread(target=dump_stats, daemon=True).start()
    run_bot()
