import os
import openai
import telebot
import requests
import json
import time
from datetime import datetime
from threading import Thread

# API tokens (должны быть заданы в Render в Environment Variables)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY")

# Telegram чат и админы
TARGET_CHAT_ID = -1002408729915
ADMINS = [7473992492, 5860994210]

bot = telebot.TeleBot(TELEGRAM_TOKEN)
openai.api_key = OPENAI_API_KEY

BANNED_KEYWORDS = ["казино", "ставки", "1win", "pin-up", "играй и выигрывай"]
SUSPICIOUS_PHRASES = set()
USER_WARNINGS = {}

# Постоянный текст с нативной ссылкой
AD_LINK = "\n\n💬 Надёжный продавец оборудования: https://app.leadteh.ru/w/dTeKr"

# Системный промпт для GPT
system_prompt = (
    "Ты — эксперт по майнингу. Отвечай строго, профессионально и кратко. "
    "Разбираешься в Antminer, Whatsminer, ROI, доставке и сервисе."
)

# === GPT-ОТВЕТ ===
@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.lower()

    # --- 1. Команда: помощь ---
    if text.startswith("/помощь"):
        bot.reply_to(message, (
            "\u2705 Этот бот умеет:\n"
            "1. Отвечать на вопросы по теме майнинга\n"
            "2. Автоматически постить свежие новости каждые 3 часа\n"
            "3. Защищать чат от спама и казино\n"
            "4. Обучается: напишите 'ban' в ответ на сообщение — и он это запомнит\n"
            "5. Команда /стата — только для админов, показывает статистику чата"
        ))
        return

    # --- 2. Команда: стата ---
    if text.startswith("/стата") and user_id in ADMINS:
        stats = get_chat_statistics()
        bot.reply_to(message, stats)
        return

    # --- 3. Команда: ban (обучение) ---
    if text.startswith("ban") and message.reply_to_message:
        SUSPICIOUS_PHRASES.add(message.reply_to_message.text.lower())
        bot.reply_to(message, "Фраза добавлена в список подозрительных.")
        return

    # --- 4. Модерация: казино/спам ---
    if any(kw in text for kw in BANNED_KEYWORDS + list(SUSPICIOUS_PHRASES)):
        warnings = USER_WARNINGS.get(user_id, 0) + 1
        USER_WARNINGS[user_id] = warnings

        if warnings >= 3:
            try:
                bot.ban_chat_member(chat_id, user_id)
                bot.reply_to(message, "\u26d4 Пользователь забанен за спам.")
            except:
                pass
        else:
            bot.reply_to(message, f"\u26a0 Предупреждение {warnings}/3. Продолжите — получите бан.")
        return

    # --- 5. GPT ответ ---
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message.text}
            ],
            temperature=0.4,
            max_tokens=1000
        )
        reply = completion.choices[0].message.content.strip()
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, "\u274c Ошибка на стороне GPT. Попробуйте позже.")

# === КАЖДЫЕ 3 ЧАСА: НОВОСТИ ===
def fetch_crypto_news():
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API_KEY}&currencies=BTC,ETH&public=true"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            posts = data.get("results", [])[:3]
            if not posts:
                return

            text = "\ud83d\udcc8 Новости по майнингу:\n"
            for post in posts:
                headline = post.get("title", "")
                link = post.get("url", "")
                text += f"\n\u2022 <a href='{link}'>{headline}</a>"

            text += AD_LINK
            bot.send_message(TARGET_CHAT_ID, text, parse_mode="HTML")
    except Exception as e:
        print("[!] Ошибка при получении новостей:", e)

# === ПЕРИОДИЧЕСКИЙ ЦИКЛ ===
def run_scheduled_news():
    while True:
        fetch_crypto_news()
        time.sleep(3 * 60 * 60)  # каждые 3 часа

# === СТАТИСТИКА ===
def get_chat_statistics():
    try:
        members = bot.get_chat_members_count(TARGET_CHAT_ID)
        admins = bot.get_chat_administrators(TARGET_CHAT_ID)
        return (
            f"\ud83d\udcca Статистика чата:\n"
            f"\u2022 Участников: {members}\n"
            f"\u2022 Админов: {len(admins)}\n"
            f"\u2022 Подозрительных фраз: {len(SUSPICIOUS_PHRASES)}"
        )
    except:
        return "\u274c Не удалось получить статистику."

# === ЗАПУСК ===
if __name__ == "__main__":
    Thread(target=run_scheduled_news).start()
    bot.polling(none_stop=True)
