import os
import openai
import requests
from flask import Flask, request
import telebot

# Загрузка переменных окружения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

app = Flask(__name__)
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Доступ только для админов
ADMINS = [7473992492, 5860994210]
CHAT_ID = -1002408729915

# Хранилище подозрительных слов
ban_phrases = ["casino", "казино", "easy money", "profit every hour"]
custom_ban_list = []
warned_users = {}

# Хендлер входящих сообщений
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text.lower()
    user_id = message.from_user.id

    # Проверка на бан-фразы
    if any(bad in text for bad in ban_phrases + custom_ban_list):
        warned_users[user_id] = warned_users.get(user_id, 0) + 1

        if warned_users[user_id] >= 3:
            bot.ban_chat_member(CHAT_ID, user_id)
            bot.send_message(CHAT_ID, f"Пользователь {user_id} заблокирован за спам")
        else:
            bot.send_message(CHAT_ID, f"Предупреждение за подозрительную активность. {3 - warned_users[user_id]} до блокировки.")
        return

    # Команда /бан (обучение фразам)
    if text.startswith("/бан") and message.reply_to_message:
        reply_text = message.reply_to_message.text.lower()
        custom_ban_list.append(reply_text)
        bot.send_message(CHAT_ID, f"Фраза добавлена в список подозрительных")
        return

    # Ответ через GPT
    prompt = (
        "Ты — ИИ помощник по майнингу. Отвечай строго, профессионально и кратко."
        "Разбираешься в Antminer, Whatsminer, доставке, ROI, ремонте, поставках."
    )

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message.text},
            ],
            temperature=0.4,
            max_tokens=1000,
        )
        reply = completion.choices[0].message.content.strip()
        bot.send_message(message.chat.id, reply)
    except Exception as e:
        bot.send_message(message.chat.id, "⚠️ GPT временно недоступен. Попробуйте позже.")

# Ендпоинт от Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'ok'

# Ручная установка Webhook (вызывается один раз)
@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    s = bot.set_webhook(url=WEBHOOK_URL)
    return f'Webhook установлен: {s}'

# Автопостинг новостей каждые 3 часа
@app.route('/post_news', methods=['GET'])
def post_news():
    url = "https://cryptopanic.com/api/v1/posts/?auth_token=" + CRYPTO_API_KEY + "&kind=news"
    try:
        response = requests.get(url)
        news = response.json().get("results", [])[:3]

        if news:
            msg = "📰 Актуальные новости по майнингу:\n\n"
            for item in news:
                msg += f"{item['title']}\n{item['url']}\n\n"
            msg += "\n🤝 Продвижение оплачено. Проверяйте продавцов лично.\n🔗 https://app.leadteh.ru/w/dTeKr"
            bot.send_message(CHAT_ID, msg)
            return 'Опубликовано'
        else:
            return 'Нет новостей'

    except Exception as e:
        return f'Ошибка при получении новостей: {str(e)}'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
