import os
import logging
import asyncio
import httpx # Для выполнения асинхронных HTTP запросов
from cachetools import cached, TTLCache # Для кэширования данных

from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage # Для хранения состояний, если понадобится в будущем
from aiogram.client.default import DefaultBotProperties # *** НОВЫЙ ИМПОРТ ***

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Конфигурация бота ---
# Получаем токен бота из переменной окружения.
# Это безопаснее, чем хардкодить его в коде.
# Убедитесь, что вы установили переменную окружения `BOT_TOKEN`
# Например: export BOT_TOKEN='ВАШ_ТОКЕН_БОТА'
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN не установлен в переменных окружения. Бот не сможет запуститься.")
    exit("Ошибка: BOT_TOKEN не найден.")

# Инициализация хранилища состояний
# MemoryStorage подходит для небольших ботов и тестирования.
# Для продакшена рассмотрите RedisStorage или другую персистентную СУБД.
storage = MemoryStorage()

# Инициализация бота и диспетчера
# *** ОБНОВЛЕННАЯ ИНИЦИАЛИЗАЦИЯ BOT ***
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=storage)

# --- Кэширование для "Топ ASIC" ---
# asic_cache - это экземпляр TTLCache, который будет использоваться для хранения кэшированных данных.
# maxsize=100: Максимальное количество элементов в кэше.
# ttl=3600: Время жизни кэша в секундах (3600 секунд = 1 час).
# Если данные старше 1 часа, они будут перезапрошены.
asic_cache = TTLCache(maxsize=100, ttl=3600)

# --- Создание клавиатуры главного меню ---
# ReplyKeyboardMarkup - это клавиатура, которая отображается под полем ввода текста.
# Она более подходит для основного меню, как на вашем скриншоте.
main_menu_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="💰 Курс"), # Иконка для курса
            KeyboardButton(text="⚙️ Топ ASIC"), # Иконка для ASIC
        ],
        [
            KeyboardButton(text="🧮 Калькулятор"), # Иконка для калькулятора
            KeyboardButton(text="📰 Новости"), # Иконка для новостей
        ],
        [
            KeyboardButton(text="😱 Индекс Страха"), # Иконка для индекса страха
            KeyboardButton(text="⏳ Халвинг"), # Иконка для халвинга
        ],
        [
            KeyboardButton(text="📊 Статус ВТС"), # Иконка для статуса BTC
            KeyboardButton(text="🧠 Викторина"), # Иконка для викторины
        ],
        [
            KeyboardButton(text="🗓️ Слово дня"), # Иконка для слова дня
            KeyboardButton(text="⛏️ Виртуальный Майнинг"), # Иконка для виртуального майнинга
        ],
    ],
    resize_keyboard=True, # Клавиатура будет автоматически изменять размер под контент
    input_field_placeholder="Выберите функцию...", # Текст в поле ввода при открытой клавиатуре
)

# --- Обработчики команд и сообщений ---

@dp.message(F.text == "/start")
async def command_start_handler(message: types.Message) -> None:
    """
    Обрабатывает команду /start.
    Отправляет приветственное сообщение и отображает главное меню.
    """
    logger.info(f"Получена команда /start от пользователя {message.from_user.id}")
    await message.answer(
        "Привет! Я твой бот для майнинга и криптовалют. Выбери интересующую функцию из меню:",
        reply_markup=main_menu_keyboard # Показываем клавиатуру главного меню
    )

@dp.message(F.text == "💰 Курс")
async def show_rates(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Курс".
    Здесь должна быть логика получения и отображения курсов криптовалют.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Курс.")
    await message.answer("Загружаю актуальные курсы криптовалют...")
    try:
        # Пример заглушки для получения курса BTC/USD
        # В реальном приложении вы бы использовали API, например, CoinGecko.
        async with httpx.AsyncClient() as client:
            # Пример запроса к публичному API CoinGecko для цены Bitcoin
            response = await client.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd")
            response.raise_for_status() # Вызывает исключение для ошибок HTTP (4xx/5xx)
            data = response.json()
            btc_price = data.get('bitcoin', {}).get('usd', 'N/A')

        await message.answer(f"Текущий курс Bitcoin (BTC): <b>{btc_price}$</b>\n"
                             "<i>(Данные предоставлены CoinGecko)</i>")
    except httpx.RequestError as e:
        logger.error(f"Ошибка при запросе курсов: {e}")
        await message.answer("Не удалось получить курсы криптовалют. Попробуйте позже.")
    except Exception as e:
        logger.error(f"Неизвестная ошибка при обработке курсов: {e}")
        await message.answer("Произошла ошибка при получении курсов.")


@dp.message(F.text == "⚙️ Топ ASIC")
@cached(cache=asic_cache, key=lambda: 'top_asics') # Используем декоратор @cached с нашим asic_cache
async def get_top_asics(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Топ ASIC".
    Функция кэшируется на 1 час (ttl=3600), чтобы не запрашивать данные слишком часто.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Топ ASIC.")
    await message.answer("Ищу информацию о топовых ASIC майнерах...")
    try:
        # Здесь должна быть логика получения данных о топ ASIC майнерах.
        # Например, парсинг сайта или запрос к специализированному API.
        # В этом примере это просто заглушка.
        top_asics_data = (
            "<b>Топ ASIC майнеры (примерные данные):</b>\n"
            "1. Bitmain Antminer S19 Pro (110 TH/s)\n"
            "2. Whatsminer M30S++ (112 TH/s)\n"
            "3. Canaan AvalonMiner 1246 (90 TH/s)\n"
            "\n<i>(Данные могут быть устаревшими, для актуальной информации обращайтесь к специализированным ресурсам.)</i>"
        )
        await message.answer(top_asics_data)
    except Exception as e:
        logger.error(f"Ошибка при получении Топ ASIC: {e}")
        await message.answer("Не удалось получить информацию о топ ASIC майнерах. Попробуйте позже.")


@dp.message(F.text == "🧮 Калькулятор")
async def show_calculator(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Калькулятор".
    Это пример простого калькулятора. В реальном приложении можно реализовать
    более сложную логику, например, калькулятор прибыльности майнинга.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Калькулятор.")
    await message.answer(
        "Я могу помочь с базовыми расчетами. Отправьте мне выражение, например '2+2' или '10*5'.\n"
        "<i>(Функционал ограничен, для сложных вычислений используйте другие инструменты.)</i>"
    )

    # Примечание: Для полноценного калькулятора вам понадобится FSM (Finite State Machine),
    # чтобы отслеживать состояние пользователя и ждать от него математическое выражение.
    # Сейчас бот просто ответит на любое сообщение, но не будет ожидать конкретного ввода.


@dp.message(F.text == "📰 Новости")
async def show_news(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Новости".
    Здесь должна быть логика получения и отображения последних новостей.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Новости.")
    await message.answer("Загружаю последние новости из мира криптовалют и майнинга...")
    try:
        # Заглушка для новостей. В реальном приложении интегрируйте новостной API.
        news_articles = [
            "<b>Заголовок новости 1:</b> Ethereum переходит на PoS, что это значит для майнеров?",
            "<b>Заголовок новости 2:</b> Bitcoin достигает нового исторического максимума!",
            "<b>Заголовок новости 3:</b> Новые регуляции в области DeFi.",
        ]
        response_text = "<b>Последние новости:</b>\n\n" + "\n\n".join(news_articles)
        await message.answer(response_text)
    except Exception as e:
        logger.error(f"Ошибка при получении новостей: {e}")
        await message.answer("Не удалось получить новости. Попробуйте позже.")


@dp.message(F.text == "😱 Индекс Страха")
async def show_fear_index(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Индекс Страха".
    Здесь должна быть логика получения и отображения индекса страха и жадности.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Индекс Страха.")
    await message.answer("Загружаю текущий индекс страха и жадности...")
    try:
        # Пример заглушки. В реальном приложении вы бы запросили данные с
        # API, например, Crypto Fear & Greed Index API.
        fear_index_value = "55 (Нейтрально)"
        fear_index_description = (
            f"Текущий индекс страха и жадности: <b>{fear_index_value}</b>.\n"
            "<i>(Индекс измеряет общее настроение на рынке криптовалют. "
            "0-24: Экстремальный страх, 25-49: Страх, 50-74: Нейтрально, 75-100: Жадность.)</i>"
        )
        await message.answer(fear_index_description)
    except Exception as e:
        logger.error(f"Ошибка при получении Индекса Страха: {e}")
        await message.answer("Не удалось получить индекс страха. Попробуйте позже.")


@dp.message(F.text == "⏳ Халвинг")
async def show_halving_info(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Халвинг".
    Предоставляет информацию о халвинге Bitcoin.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Халвинг.")
    await message.answer("Предоставляю информацию о халвинге Bitcoin...")
    try:
        # Заглушка для информации о халвинге.
        # Можно сделать динамическое получение следующей даты халвинга.
        halving_info = (
            "<b>Что такое халвинг Bitcoin?</b>\n"
            "Халвинг — это событие, которое происходит примерно каждые четыре года "
            "или после добычи каждых 210 000 блоков. В результате халвинга "
            "награда майнерам за добычу нового блока сокращается вдвое.\n\n"
            "Последний халвинг произошел в мае 2024 года, сократив награду до 3.125 BTC.\n"
            "Следующий халвинг ожидается примерно в <b>2028 году</b>."
        )
        await message.answer(halving_info)
    except Exception as e:
        logger.error(f"Ошибка при получении информации о Халвинге: {e}")
        await message.answer("Произошла ошибка при получении информации о халвинге.")


@dp.message(F.text == "📊 Статус ВТС")
async def show_btc_status(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Статус ВТС".
    Предоставляет информацию о текущем статусе сети Bitcoin.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Статус ВТС.")
    await message.answer("Загружаю текущий статус сети Bitcoin...")
    try:
        # Заглушка. В реальном приложении вы бы запросили данные с API
        # (например, Blockchair, Blockchain.com)
        btc_status_info = (
            "<b>Статус сети Bitcoin (примерные данные):</b>\n"
            "Текущий блок: <b>850,123</b>\n"
            "Хешрейт сети: <b>~550 EH/s</b>\n"
            "Примерное время следующего блока: <b>~10 минут</b>\n"
            "Сложность: <b>~100.2 T</b>\n"
            "\n<i>(Данные могут быть устаревшими. Для актуальной информации обращайтесь к обозревателям блоков.)</i>"
        )
        await message.answer(btc_status_info)
    except Exception as e:
        logger.error(f"Ошибка при получении Статуса ВТС: {e}")
        await message.answer("Не удалось получить статус сети Bitcoin. Попробуйте позже.")


@dp.message(F.text == "🧠 Викторина")
async def start_quiz(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Викторина".
    Начинает простую викторину. Для полноценной викторины
    потребуется управление состоянием пользователя (FSM).
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Викторину.")
    await message.answer(
        "Добро пожаловать в крипто-викторину! Я задам тебе вопрос. "
        "Какой год считается годом создания Bitcoin?"
    )
    # В реальной викторине здесь вы бы сохраняли состояние, чтобы ожидать ответ.
    # Например: await state.set_state(QuizStates.waiting_for_answer)


@dp.message(F.text == "🗓️ Слово дня")
async def get_word_of_the_day(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Слово дня".
    Предоставляет случайное крипто-слово и его определение.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Слово дня.")
    await message.answer("Загружаю слово дня...")
    try:
        # Можно создать список слов и выбирать случайное.
        words_of_the_day = {
            "HODL": "Популярный мем и стратегия в криптосообществе, означающая 'держать' "
                    "криптовалюту, не продавая ее, несмотря на падения цен.",
            "DeFi": "Сокращение от 'децентрализованные финансы' — это экосистема "
                    "финансовых приложений, построенных на блокчейне.",
            "NFT": "Сокращение от 'невзаимозаменяемый токен' — уникальный цифровой "
                   "актив, который может представлять собой что угодно, "
                   "от произведений искусства до коллекционных предметов."
        }
        import random
        word, definition = random.choice(list(words_of_the_day.items()))
        await message.answer(f"<b>Слово дня: {word}</b>\n\n{definition}")
    except Exception as e:
        logger.error(f"Ошибка при получении Слова дня: {e}")
        await message.answer("Не удалось получить слово дня. Попробуйте позже.")


@dp.message(F.text == "⛏️ Виртуальный Майнинг")
async def start_virtual_mining(message: types.Message) -> None:
    """
    Обрабатывает нажатие кнопки "Виртуальный Майнинг".
    Это может быть заглушка для будущей игры или симуляции.
    """
    logger.info(f"Пользователь {message.from_user.id} запросил Виртуальный Майнинг.")
    await message.answer(
        "Добро пожаловать в симулятор виртуального майнинга! "
        "Здесь вы сможете попробовать себя в роли майнера без реального оборудования. "
        "<i>(Функционал в разработке!)</i>"
    )

# --- Главная функция запуска бота ---
async def main() -> None:
    """
    Основная асинхронная функция для запуска бота.
    """
    logger.info("Запуск бота...")
    # Запускаем все зарегистрированные обработчики
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при запуске бота: {e}")


