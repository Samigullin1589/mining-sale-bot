import openai
import telebot
import os

# Получение ключей из переменных окружения
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')

openai.api_key = OPENAI_API_KEY
bot = telebot.TeleBot(TELEGRAM_TOKEN)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_text = message.text

    system_prompt = (
        "Ты — эксперт по майнингу. Отвечай строго, профессионально, кратко. "
        "Разбираешься в Antminer, Whatsminer, доставке, ROI, техобслуживании."
    )

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-4o",  # Или 'gpt-4', если у вас есть доступ
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            temperature=0.4,
            max_tokens=1000
        )
        reply = completion.choices[0].message.content.strip()
    except Exception as e:
        reply = "Ошибка на стороне GPT. Попробуйте позже."

    bot.reply_to(message, reply)

bot.polling()
