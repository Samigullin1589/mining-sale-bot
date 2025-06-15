import openai
import telebot
import os
import threading
import time

# Получение ключей из переменных окружения
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

openai.api_key = OPENAI_API_KEY
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Системный промпт для ИИ
system_prompt = (
    "Ты — эксперт по майнингу. Отвечай строго, профессионально, кратко."
    " Разбираешься в Antminer, Whatsminer, доставке, ROI, техобслуживании."
)

# Обработка входящих сообщений
def handle_message(message):
    user_text = message.text
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            temperature=0.4,
            max_tokens=1000
        )
        reply = completion.choices[0].message.content.strip()
    except Exception:
        reply = "Извините, произошла ошибка на стороне GPT. Попробуйте позже."

    bot.reply_to(message, reply)

@bot.message_handler(func=lambda message: True)
def message_router(message):
    handle_message(message)

# Автопостинг раз в 3 часа
def auto_posting():
    while True:
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": (
                        "Ты — Telegram-бот по майнингу. Пиши каждые 3 часа короткий, актуальный, полезный пост."
                        " Пиши как живой человек, кратко, строго по теме. В конце добавь нативную рекламу и закреп контактов."
                    )},
                    {"role": "user", "content": (
                        "Напиши пост для Telegram-чата по теме майнинга."
                        " Упомяни одну новость, совет по охлаждению или питанию, и в конце — краткая нативная реклама, например:"
                        " 'по всем вопросам — @контакт'. Без эмодзи, без воды."
                    )}
                ],
                temperature=0.5,
                max_tokens=800
            )
            post_text = completion.choices[0].message.content.strip()
            bot.send_message(chat_id="@Mining_Sale", text=post_text)
        except Exception:
            pass
        time.sleep(60 * 60 * 3)  # 3 часа

threading.Thread(target=auto_posting, daemon=True).start()

# Запуск бота
bot.polling()
