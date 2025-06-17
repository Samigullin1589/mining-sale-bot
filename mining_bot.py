# -*- coding: utf-8 -*-



# ========================================================================================

# 1. ИМПОРТЫ И КОНФИГУРАЦИЯ

# ========================================================================================

import os

import telebot

import requests

import time

import threading

import schedule

import json

from flask import Flask, request

import gspread

from google.oauth2.service_account import Credentials

from telebot import types

from openai import OpenAI

from datetime import datetime, timedelta

from bs4 import BeautifulSoup

import matplotlib.pyplot as plt

import io

import re

import random

import logging



# --- Настройка логирования ---

# 📌 ИЗМЕНЕНО: Добавлен более информативный формат логов

logging.basicConfig(

    level=logging.INFO,

    format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',

    datefmt='%d/%b/%Y %H:%M:%S'

)

logger = logging.getLogger(__name__)



# --- Ключи и Настройки (Загрузка из переменных окружения) ---

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")

NEWSAPI_KEY = os.getenv("CRYPTO_API_KEY") # CryptoPanic API Key

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "YourApiKeyToken")

NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

GOOGLE_JSON_STR = os.getenv("GOOGLE_JSON")

SHEET_ID = os.getenv("SHEET_ID")

SHEET_NAME = os.getenv("SHEET_NAME", "Лист1")



# --- Настройки Партнерской Ссылки ---

PARTNER_URL = "https://app.leadteh.ru/w/dTeKr"

PARTNER_BUTTON_TEXT_OPTIONS = [

    "🎁 Узнать спеццены", "🔥 Эксклюзивное предложение",

    "💡 Получить консультацию", "💎 Прайс от экспертов"

]



# --- Глобальные переменные и кэш ---

if not BOT_TOKEN:

    logger.critical("Критическая ошибка: не найдена переменная окружения TG_BOT_TOKEN")

    raise ValueError("Критическая ошибка: не найдена переменная окружения TG_BOT_TOKEN")



try:

    bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

    app = Flask(__name__)

    openai_client = OpenAI(api_key=OPENAI_API_KEY)

except Exception as e:

    logger.critical(f"Не удалось инициализировать одного из клиентов API: {e}")

    raise



# 📌 ИЗМЕНЕНО: Словари состояния объединены в один для удобства

user_states = {} # Хранит состояния типа {'weather_request': True, 'calculator_request': True, ...}



asic_cache = {"data": [], "timestamp": None}



# 🚀 НОВОЕ: Хранилище для игровой механики "Виртуальный майнинг"

# ВАЖНО: Эти данные не сохраняются между перезапусками бота.

# Для полноценной работы нужна база данных (например, SQLite или PostgreSQL).

user_rigs = {} # { user_id: {'last_collected': datetime, 'balance': float} }



# Список подсказок для вовлечения

BOT_HINTS = [

    "💡 Попробуйте команду `/price`",

    "⚙️ Нажмите на кнопку 'Топ-5 ASIC'",

    "🌦️ Узнайте погоду, просто написав 'погода'",

    "⛏️ Рассчитайте прибыль с помощью 'Калькулятора'",

    "📰 Хотите новости? Просто напишите 'новости'",

    "⛽️ Узнайте цену на газ командой `/gas`",

    "🤑 Начните свой виртуальный майнинг с `/my_rig`",

    "😱 Проверьте Индекс Страха и Жадности командой `/fear`",

    "⏳ Сколько до халвинга? Узнайте: `/halving`"

]



# Словарь для универсального парсера валют

CURRENCY_MAP = {

    'доллар': 'USD', 'usd': 'USD', '$': 'USD',

    'евро': 'EUR', 'eur': 'EUR', '€': 'EUR',

    'рубль': 'RUB', 'rub': 'RUB', '₽': 'RUB',

    'юань': 'CNY', 'cny': 'CNY',

    'биткоин': 'BTC', 'btc': 'BTC', 'бтс': 'BTC', 'втс': 'BTC',

    'эфир': 'ETH', 'eth': 'ETH',

}



# 🚀 НОВОЕ: Константы для халвинга

HALVING_INTERVAL = 210000

# Определяем следующий халвинг (840000, 1050000, и т.д.)

# Можно сделать функцией для автоматического определения следующего

NEXT_HALVING_BLOCK = 840000



# ========================================================================================

# 2. ФУНКЦИИ ДЛЯ РАБОТЫ С ВНЕШНИМИ API И СЕРВИСАМИ

# ========================================================================================



def get_gsheet():

    """Подключается к Google Sheets используя ключи из переменной окружения."""

    if not GOOGLE_JSON_STR:

        logger.error("Переменная окружения GOOGLE_JSON не установлена.")

        raise ValueError("Ключи Google Sheets не найдены.")

    try:

        creds_dict = json.loads(GOOGLE_JSON_STR)

        creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets'])

        gc = gspread.authorize(creds)

        return gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    except json.JSONDecodeError:

        logger.error("Неверный формат JSON в переменной GOOGLE_JSON.")

        raise

    except Exception as e:

        logger.error(f"Ошибка подключения к Google Sheets: {e}")

        raise



def log_to_sheet(row_data: list):

    """Логирует данные в новую строку Google Sheets."""

    try:

        sheet = get_gsheet()

        sheet.append_row(row_data, value_input_option='USER_ENTERED')

        logger.info(f"Запись в Google Sheets: {row_data}")

    except Exception as e:

        logger.error(f"Ошибка записи в Google Sheets: {e}")



# 📌 ИЗМЕНЕНО: Упрощена логика получения цены BTC, т.к. Binance самый надежный

def get_crypto_price(coin_id="bitcoin", vs_currency="usd"):

    """

    Получает цену с Binance, при ошибке -> CoinGecko.

    Возвращает кортеж (цена, источник).

    """

    # 1. Binance (для BTCUSDT)

    if coin_id == 'bitcoin' and vs_currency == 'usd':

        try:

            res = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5).json()

            if 'price' in res: return (float(res['price']), "Binance")

        except Exception as e:

            logger.warning(f"Ошибка API Binance: {e}. Пробую CoinGecko.")



    # 2. CoinGecko (универсальный)

    try:

        res = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies={vs_currency}", timeout=5).json()

        if coin_id in res and vs_currency in res[coin_id]: return (float(res[coin_id][vs_currency]), "CoinGecko")

    except Exception as e:

        logger.error(f"Ошибка API CoinGecko: {e}.")



    return (None, None)



def get_eth_gas_price():

    """Получает актуальную цену газа в сети Ethereum."""

    try:

        res = requests.get(f"https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey={ETHERSCAN_API_KEY}", timeout=5).json()

        if res.get("status") == "1" and res.get("result"):

            gas_info = res["result"]

            return (f"⛽️ **Актуальная цена газа в Ethereum (Gwei):**\n\n"

                    f"🐢 **Медленно (≈5-10 мин):** `{gas_info['SafeGasPrice']}` Gwei\n"

                    f"🚶‍♂️ **Средне (≈2-3 мин):** `{gas_info['ProposeGasPrice']}` Gwei\n"

                    f"🚀 **Быстро (≈15-30 сек):** `{gas_info['FastGasPrice']}` Gwei")

        else:

            return "[❌ Не удалось получить данные о газе с Etherscan]"

    except requests.exceptions.RequestException as e:

        logger.error(f"Ошибка сети при запросе цены на газ: {e}")

        return f"[❌ Сетевая ошибка при запросе цены на газ]"

    except Exception as e:

        logger.error(f"Неизвестная ошибка при запросе цены на газ: {e}")

        return f"[❌ Ошибка при запросе цены на газ]"



def get_weather(city: str):

    """Получает погоду с сервиса wttr.in."""

    try:

        # 📌 ИЗМЕНЕНО: Добавлен заголовок для корректного получения ответа на русском

        headers = {'User-Agent': 'Mozilla/5.0', "Accept-Language": "ru"}

        r = requests.get(f"https://wttr.in/{city}?format=j1", headers=headers, timeout=7).json()

        current = r["current_condition"][0]

        # 📌 ИЗМЕНЕНО: Используется поле с описанием на русском языке

        weather_desc = current['lang_ru'][0]['value'] if 'lang_ru' in current and current['lang_ru'] else current['weatherDesc'][0]['value']

        return (f"🌍 {r['nearest_area'][0]['areaName'][0]['value']}\n"

                f"🌡 Температура: {current['temp_C']}°C (Ощущается как {current['FeelsLikeC']}°C)\n"

                f"☁️ Погода: {weather_desc}\n"

                f"💧 Влажность: {current['humidity']}%\n"

                f"💨 Ветер: {current['windspeedKmph']} км/ч")

    except Exception as e:

        logger.error(f"Ошибка получения погоды для '{city}': {e}")

        return f"[❌ Не удалось найти город '{city}' или произошла ошибка.]"



# ... (остальные функции API без изменений)

def get_currency_rate(base="USD", to="RUB"):

    """Получает курс валют с exchangerate.host с резервированием."""

    # 1. Попытка с ExchangeRate.host

    try:

        res = requests.get(f"https://api.exchangerate.host/latest?base={base.upper()}&symbols={to.upper()}", timeout=5).json()

        if res.get('rates') and res['rates'].get(to.upper()):

            rate = res['rates'][to.upper()]

            return f"💹 {base.upper()} → {to.upper()} = **{rate:.2f}**"

    except Exception as e:

        logger.warning(f"Ошибка API ExchangeRate.host: {e}. Пробую резервный API.")



    # 2. Резервная попытка с Exchangeratesapi.io

    try:

        res = requests.get(f"https://api.exchangerate-api.com/v4/latest/{base.upper()}", timeout=5).json()

        if res.get('rates') and res['rates'].get(to.upper()):

            rate = res['rates'][to.upper()]

            return f"💹 {base.upper()} → {to.upper()} = **{rate:.2f}** (резервный API)"

    except Exception as e:

        logger.error(f"Ошибка резервного API курсов валют: {e}")



    return f"[❌ Не удалось получить курс для {base.upper()} к {to.upper()} ни с одного источника]"



def ask_gpt(prompt: str, model: str = "gpt-4o"):

    """Отправляет запрос к OpenAI GPT."""

    try:

        res = openai_client.chat.completions.create(

            model=model,

            messages=[

                {"role": "system", "content": "Ты — полезный ассистент, который всегда отвечает на русском языке."},

                {"role": "user", "content": prompt}

            ],

            timeout=20.0

        )

        return res.choices[0].message.content.strip()

    except Exception as e:

        logger.error(f"Ошибка вызова OpenAI API: {e}")

        return f"[❌ Ошибка GPT: Не удалось получить ответ. Попробуйте позже.]"



# ... (парсеры ASIC без изменений, они уже хорошо сделаны)

def _parse_asicminervalue():

    logger.info("Попытка парсинга asicminervalue.com")

    r = requests.get("https://www.asicminervalue.com/miners/sha-256", timeout=15)

    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    table_rows = soup.select("table tbody tr")

    if not table_rows:

        raise ValueError("Таблица ASIC не найдена на asicminervalue.com")



    parsed_asics = []

    for row in table_rows[:5]:

        cols = row.find_all("td")

        if len(cols) < 4: continue

        

        try:

            name_tag = cols[0].find('a')

            name = name_tag.get_text(strip=True) if name_tag else cols[0].get_text(strip=True)



            asic_data = {

                'name': name,

                'hashrate': cols[1].get_text(strip=True),

                'power_str': cols[2].get_text(strip=True),

                'revenue_str': cols[3].get_text(strip=True),

            }

            

            power_match = re.search(r'(\d+)', asic_data['power_str'])

            asic_data['power_watts'] = float(power_match.group(1)) if power_match else 0

            

            revenue_match = re.search(r'([\d\.]+)', asic_data['revenue_str'])

            asic_data['daily_revenue'] = float(revenue_match.group(1)) if revenue_match else 0

            

            if asic_data['power_watts'] > 0 and asic_data['daily_revenue'] > 0:

                parsed_asics.append(asic_data)

        except (AttributeError, ValueError, IndexError, TypeError) as e:

            logger.warning(f"AsicMinerValue: Ошибка парсинга строки. {e}")

            continue



    if not parsed_asics:

        raise ValueError("Не удалось извлечь данные ни одного ASIC с asicminervalue.com")

    

    logger.info(f"Успешно получено {len(parsed_asics)} ASIC с asicminervalue.com")

    return parsed_asics



def _parse_whattomine():

    logger.info("Попытка парсинга whattomine.com")

    headers = {'User-Agent': 'Mozilla/5.0'}

    r = requests.get("https://whattomine.com/asics.json", headers=headers, timeout=15)

    r.raise_for_status()

    data = r.json()

    asics_data = data.get('asics', {})



    if not asics_data:

        raise ValueError("Данные ASIC не найдены в JSON от whattomine.com")



    sha256_asics = []

    btc_price, _ = get_crypto_price()

    if not btc_price:

        raise ValueError("Не удалось получить цену BTC для калькулятора WhatToMine")



    for key, asic in asics_data.items():

        if asic.get('algorithm') == 'sha256' and asic.get('profitability_daily'):

            try:

                daily_revenue = float(asic['profitability_daily']) * btc_price

                

                sha256_asics.append({

                    "name": asic.get('name', f"ASIC ID: {key}").replace('_', ' '),

                    "hashrate": f"{asic.get('hashrate', 0) / 1e12:.2f}Th/s",

                    "power_watts": float(asic.get('power', 0)),

                    "power_str": f"{asic.get('power', 0)}W",

                    "daily_revenue": daily_revenue,

                    "revenue_str": f"${daily_revenue:.2f}",

                })

            except (KeyError, ValueError, TypeError) as e:

                logger.warning(f"WhatToMine JSON: Не удалось обработать ASIC {key}. Ошибка: {e}")

                continue

    

    if not sha256_asics:

        raise ValueError("Не удалось извлечь данные ни одного SHA-256 ASIC из JSON whattomine.com")



    sha256_asics.sort(key=lambda x: x['daily_revenue'], reverse=True)

    logger.info(f"Успешно получено {len(sha256_asics)} ASIC с whattomine.com")

    return sha256_asics[:5]



def get_top_asics(force_update: bool = False):

    """Получает топ-5 ASIC с двух источников с резервированием."""

    global asic_cache

    cache_is_valid = asic_cache.get("data") and asic_cache.get("timestamp") and \

                     (datetime.now() - asic_cache["timestamp"] < timedelta(hours=1))



    if cache_is_valid and not force_update:

        logger.info("Используется кэш ASIC.")

        return asic_cache["data"]



    try:

        asics = _parse_asicminervalue()

        asic_cache = {"data": asics, "timestamp": datetime.now()}

        return asics

    except Exception as e:

        logger.warning(f"Не удалось получить данные с основного источника (asicminervalue): {e}")

        try:

            asics = _parse_whattomine()

            asic_cache = {"data": asics, "timestamp": datetime.now()}

            return asics

        except Exception as e2:

            logger.error(f"Не удалось получить данные и с резервного источника (whattomine): {e2}")

            return ["[❌ Не удалось обновить список ASIC ни с одного из источников. Попробуйте позже.]"]



# 📌 ИЗМЕНЕНО: Функция новостей улучшена, чтобы не падать при ошибке GPT

def get_crypto_news(keywords: list = None):

    try:

        params = {"auth_token": NEWSAPI_KEY, "public": "true"}

        if keywords:

            params["currencies"] = ",".join(keywords).upper()

        else:

            params["currencies"] = "BTC,ETH"



        r = requests.get("https://cryptopanic.com/api/v1/posts/", params=params, timeout=10).json()

        posts = r.get("results", [])[:3]



        if not posts:

            return "[🧐 Новостей по вашему запросу не найдено]"



        items = []

        for post in posts:

            # Делаем саммари для каждой новости отдельно, чтобы одна ошибка не ломала все

            try:

                prompt_for_gpt = (

                    f"Сделай краткое саммари на русском (одно предложение) для следующего заголовка новости: "

                    f"'{post['title']}'. Верни только это одно предложение без лишнего текста."

                )

                summary = ask_gpt(prompt_for_gpt, 'gpt-3.5-turbo')

                # Проверка, что GPT не вернул ошибку

                if '[❌' in summary:

                    summary = post['title'] # Откат к оригинальному заголовку

            except Exception as e:

                logger.warning(f"Ошибка GPT-саммари для новости, использую заголовок. Ошибка: {e}")

                summary = post['title']

            

            items.append(f"🔹 [{summary}]({post.get('url', '')})")



        return "\n\n".join(items) if items else "[🤷‍♂️ Свежих новостей нет]"



    except Exception as e:

        logger.error(f"Ошибка получения новостей: {e}")

        return f"[❌ Ошибка API новостей]"



# ========================================================================================

# 🚀 3. НОВЫЕ ФУНКЦИИ (ИНТЕРАКТИВ И ГЕЙМИФИКАЦИЯ)

# ========================================================================================



def get_fear_and_greed_index():

    """Получает 'Индекс страха и жадности' и генерирует картинку."""

    try:

        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=5).json()

        if not r.get('data'):

            return None, "[❌ Не удалось получить данные об индексе страха и жадности]"



        data = r['data'][0]

        value = int(data['value'])

        classification = data['value_classification']



        # Создание "спидометра"

        plt.style.use('dark_background')

        fig, ax = plt.subplots(figsize=(8, 4), subplot_kw={'projection': 'polar'})

        ax.set_yticklabels([])

        ax.set_xticklabels([])

        ax.grid(False)

        ax.spines['polar'].set_visible(False)

        ax.set_ylim(0, 1)



        # Цвета для градиента

        colors = ['#ff0000', '#ff4500', '#ffff00', '#adff2f', '#00ff00']

        # Создаем 100 сегментов для градиента

        for i in range(100):

            color_index = min(len(colors) - 1, int(i / (100 / (len(colors)-1))))

            ax.barh(1, width=0.01 * 3.14/100, left=3.14 - (i * 0.01 * 3.14/100), height=0.2, color=colors[color_index])



        # Стрелка

        angle = 3.14 - (value / 100 * 3.14)

        ax.annotate(

            '', xy=(angle, 1), xytext=(0, 0),

            arrowprops=dict(facecolor='white', shrink=0.05, width=2, headwidth=8)

        )

        ax.barh(1, width=0.1, left=angle-0.05, height=0.3, color='black') # основание стрелки

        

        # Текст

        ax.text(0, 0, f"{value}\n{classification}", ha='center', va='center', fontsize=24, color='white', weight='bold')

        ax.text(3.14, 1.1, "Extreme Fear", ha='center', va='center', fontsize=12, color='white')

        ax.text(0, 1.1, "Extreme Greed", ha='center', va='center', fontsize=12, color='white')



        buf = io.BytesIO()

        plt.savefig(buf, format='png', dpi=150, transparent=True)

        buf.seek(0)

        plt.close(fig)

        

        text = (f"😱 **Индекс страха и жадности: {value} - {classification}**\n\n"

                f"Настроение рынка сейчас ближе к *{'страху' if value < 50 else 'жадности'}*.")



        return buf, text



    except Exception as e:

        logger.error(f"Ошибка при создании графика индекса страха: {e}")

        return None, f"[❌ Ошибка при получении индекса: {e}]"





def get_halving_info():

    """Получает информацию о времени до следующего халвинга."""

    try:

        # Получаем текущий номер блока

        current_block_height = int(requests.get("https://blockchain.info/q/getblockcount", timeout=5).text)

        

        blocks_left = NEXT_HALVING_BLOCK - current_block_height

        if blocks_left <= 0:

            return f"🎉 **Халвинг на блоке {NEXT_HALVING_BLOCK} уже произошел!**\nСледующий халвинг ожидается на блоке {NEXT_HALVING_BLOCK + HALVING_INTERVAL}."



        # Примерное время до халвинга (1 блок ~ 10 минут)

        minutes_left = blocks_left * 10

        days_left = int(minutes_left / (60 * 24))

        hours_left = int((minutes_left % (60 * 24)) / 60)



        return (f"⏳ **До следующего халвинга Bitcoin осталось:**\n\n"

                f"🗓 **Дней:** `{days_left}`\n"

                f"⏰ **Часов:** `{hours_left}`\n\n"

                f"🧱 **Блоков до халвинга:** `{blocks_left:,}`\n"

                f"🎯 **Целевой блок:** `{NEXT_HALVING_BLOCK:,}`\n"

                f"⛏ **Текущий блок:** `{current_block_height:,}`")



    except Exception as e:

        logger.error(f"Ошибка получения данных для халвинга: {e}")

        return f"[❌ Не удалось получить данные о халвинге: {e}]"





# ========================================================================================

# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И УТИЛИТЫ

# ========================================================================================



def get_main_keyboard():

    """Создает основную клавиатуру с кнопками."""

    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)

    buttons = [

        types.KeyboardButton("💹 Курс BTC"), types.KeyboardButton("⛽️ Газ ETH"),

        types.KeyboardButton("⚙️ Топ-5 ASIC"), types.KeyboardButton("⛏️ Калькулятор"),

        types.KeyboardButton("📰 Новости"), types.KeyboardButton("🌦️ Погода"),

        # 🚀 НОВОЕ: Кнопки для новых функций

        types.KeyboardButton("😱 Индекс Страха"), types.KeyboardButton("⏳ Халвинг")

    ]

    markup.add(*buttons)

    return markup



def get_random_partner_button():

    """Создает инлайн-кнопку со случайным текстом."""

    markup = types.InlineKeyboardMarkup()

    markup.add(types.InlineKeyboardButton(random.choice(PARTNER_BUTTON_TEXT_OPTIONS), url=PARTNER_URL))

    return markup



def send_message_with_partner_button(chat_id, text, **kwargs):

    """

    Обертка для отправки сообщения с прикрепленной партнерской кнопкой

    и добавлением случайной подсказки.

    """

    try:

        hint = random.choice(BOT_HINTS)

        full_text = f"{text}\n\n---\n_{hint}_"



        kwargs.setdefault('parse_mode', 'Markdown')

        kwargs.setdefault('reply_markup', get_random_partner_button())

        kwargs.setdefault('disable_web_page_preview', True)

        bot.send_message(chat_id, full_text, **kwargs)

    except Exception as e:

        logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")



# ... (остальные вспомогательные функции без критических изменений)

def get_usd_to_rub_rate():

    try:

        res = requests.get("https://api.exchangerate.host/latest?base=USD&symbols=RUB", timeout=5).json()

        if res.get('rates') and 'RUB' in res['rates']:

            return res['rates']['RUB']

    except Exception as e:

        logger.warning(f"API ExchangeRate.host для калькулятора не ответил: {e}. Пробую резервный.")



    try:

        res = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=5).json()

        if res.get('rates') and 'RUB' in res['rates']:

            return res['rates']['RUB']

    except Exception as e:

        logger.error(f"Резервный API курсов для калькулятора тоже не ответил: {e}")



    return None



def calculate_and_format_profit(electricity_cost_rub: float):

    usd_to_rub_rate = get_usd_to_rub_rate()

    if usd_to_rub_rate is None:

        return "Не удалось получить курс доллара для расчета. Попробуйте позже."



    electricity_cost_usd = electricity_cost_rub / usd_to_rub_rate

    asics_data = get_top_asics()



    if not asics_data or isinstance(asics_data[0], str):

        error_message = asics_data[0] if asics_data else "Не удалось получить данные по ASIC для расчета."

        return error_message



    result = [f"💰 **Расчет чистой прибыли при цене розетки {electricity_cost_rub:.2f} ₽/кВтч (~${electricity_cost_usd:.3f}/кВтч)**\n"]

    successful_calcs = 0

    for asic in asics_data:

        try:

            power_watts = asic['power_watts']

            daily_revenue = asic['daily_revenue']



            daily_power_kwh = (power_watts / 1000) * 24

            daily_electricity_cost = daily_power_kwh * electricity_cost_usd

            net_profit = daily_revenue - daily_electricity_cost



            result.append(

                f"**{asic['name']}**\n"

                f"  - Доход: `${daily_revenue:.2f}`\n"

                f"  - Расход: `${daily_electricity_cost:.2f}`\n"

                f"  - **Чистая прибыль: `${net_profit:.2f}`/день**"

            )

            successful_calcs += 1

        except (KeyError, ValueError, TypeError) as e:

            logger.warning(f"Ошибка расчета для ASIC '{asic.get('name', 'N/A')}': {e}")

            continue



    if successful_calcs == 0:

        return "Не удалось рассчитать прибыль ни для одного ASIC. Возможно, изменился формат данных на сайте-источнике."

    

    return "\n".join(result)





# ========================================================================================

# 5. ЗАДАЧИ, ВЫПОЛНЯЕМЫЕ ПО РАСПИСАНИЮ (SCHEDULE)

# ========================================================================================



def keep_alive():

    if WEBHOOK_URL:

        try:

            base_url = WEBHOOK_URL.rsplit('/', 1)[0]

            requests.get(base_url, timeout=10)

            logger.info(f"Keep-alive пинг на {base_url} отправлен.")

        except Exception as e:

            logger.warning(f"Ошибка keep-alive пинга: {e}")



def auto_send_news():

    if not NEWS_CHAT_ID: return

    try:

        logger.info("Запуск авторассылки новостей...")

        news = get_crypto_news()

        bot.send_message(NEWS_CHAT_ID, news, disable_web_page_preview=True, parse_mode='Markdown', reply_markup=get_random_partner_button())

        logger.info(f"Новости успешно отправлены в чат {NEWS_CHAT_ID}")

    except Exception as e:

        logger.error(f"Ошибка при авторассылке новостей: {e}")

        if ADMIN_CHAT_ID:

            bot.send_message(ADMIN_CHAT_ID, f"⚠️ Не удалось выполнить авторассылку новостей:\n{e}")



def auto_check_status():

    if not ADMIN_CHAT_ID: return

    logger.info("Запуск плановой проверки систем...")

    errors = []

    # 📌 ИЗМЕНЕНО: Более надежная проверка GPT

    if "ошибка" in ask_gpt("Тест", "gpt-3.5-turbo").lower():

        errors.append("API OpenAI (GPT) вернул ошибку.")

    try:

        get_gsheet()

    except Exception as e:

        errors.append(f"Не удалось подключиться к Google Sheets: {e}")

    if get_crypto_price()[0] is None:

        errors.append("API цены (Binance/CoinGecko) вернул ошибку.")



    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not errors:

        status_msg = f"✅ **Плановая проверка ({ts})**\n\nВсе системы работают."

    else:

        error_list = "\n".join([f"🚨 {e}" for e in errors])

        status_msg = f"⚠️ **Проблемы в работе бота ({ts}):**\n{error_list}"

    try:

        bot.send_message(ADMIN_CHAT_ID, status_msg, parse_mode="Markdown")

        logger.info("Отчет о состоянии отправлен админу.")

    except Exception as e:

        logger.error(f"Не удалось отправить отчет админу: {e}")



# ========================================================================================

# 6. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ TELEGRAM

# ========================================================================================



@bot.message_handler(commands=['start', 'help'])

def handle_start_help(msg):

    """Обработчик команд /start и /help."""

    # 📌 ИЗМЕНЕНО: Добавлены новые команды

    help_text = (

        "👋 Привет! Я ваш помощник в мире криптовалют и майнинга.\n\n"

        "Используйте кнопки ниже или отправьте мне команду.\n\n"

        "**Основные команды:**\n"

        "`/price` - узнать курс BTC (или `/price ETH`).\n"

        "`/gas` - цена на газ в сети Ethereum.\n"

        "`/news` - свежие крипто-новости.\n\n"

        "**Полезные утилиты:**\n"

        "`/fear` - Индекс страха и жадности.\n"

        "`/halving` - таймер до халвинга BTC.\n"

        "`/chart` - график доходности из Google Sheets.\n\n"

        "**Игровые команды:**\n"

        "`/my_rig` - ваша виртуальная ферма.\n"

        "`/collect` - собрать намайненное (раз в 24ч).\n\n"

        "Просто напишите мне что-нибудь, и я постараюсь помочь!"

    )

    bot.send_message(msg.chat.id, help_text, parse_mode="Markdown", reply_markup=get_main_keyboard())



# 📌 ИЗМЕНЕНО: Улучшена логика парсинга для команды /price

@bot.message_handler(commands=['price'])

def handle_price(msg):

    try:

        parts = msg.text.split()

        coin_symbol = parts[1].upper() if len(parts) > 1 else "BTC"

        

        # Используем словарь для сопоставления символов и ID для CoinGecko

        coin_id_map = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'SOL': 'solana'} # Можно расширить

        coin_id = coin_id_map.get(coin_symbol, coin_symbol.lower())

        currency = "usd"



        price, source = get_crypto_price(coin_id, currency)

        if price:

            send_message_with_partner_button(msg.chat.id, f"💹 Курс {coin_symbol}/USD: **${price:,.2f}**\n_(Данные от {source})_")

        else:

            bot.send_message(msg.chat.id, f"❌ Не удалось получить курс для {coin_symbol}. Проверьте тикер или попробуйте позже.")

    except Exception as e:

        logger.error(f"Ошибка в handle_price: {e}")

        bot.send_message(msg.chat.id, "Произошла ошибка при обработке команды. Попробуйте еще раз.")



# 🚀 НОВЫЕ ОБРАБОТЧИКИ КОМАНД

@bot.message_handler(commands=['fear', 'fng'])

def handle_fear_and_greed(msg):

    bot.send_message(msg.chat.id, "⏳ Генерирую актуальный Индекс страха и жадности...")

    photo, text = get_fear_and_greed_index()

    if photo:

        bot.send_photo(msg.chat.id, photo, caption=text, parse_mode="Markdown", reply_markup=get_random_partner_button())

    else:

        send_message_with_partner_button(msg.chat.id, text)



@bot.message_handler(commands=['halving'])

def handle_halving(msg):

    send_message_with_partner_button(msg.chat.id, get_halving_info())

    

@bot.message_handler(commands=['my_rig'])

def handle_my_rig(msg):

    user_id = msg.from_user.id

    if user_id not in user_rigs:

        user_rigs[user_id] = {'last_collected': None, 'balance': 0.0}

        response = "🎉 Поздравляю! Вы только что запустили свою виртуальную майнинг-ферму!\n\n" \

                   "Теперь раз в 24 часа вы можете собирать намайненное командой `/collect`.\n" \

                   "Ваш текущий баланс: `0.000000` BTC."

    else:

        balance = user_rigs[user_id]['balance']

        response = f"🖥️ **Ваша виртуальная ферма:**\n\n" \

                   f"💰 **Баланс:** `{balance:.6f}` BTC\n\n" \

                   f"Используйте `/collect`, чтобы собрать награду."

    

    send_message_with_partner_button(msg.chat.id, response)



@bot.message_handler(commands=['collect'])

def handle_collect(msg):

    user_id = msg.from_user.id

    if user_id not in user_rigs:

        response = "🤔 У вас еще нет виртуальной фермы. Создайте ее командой `/my_rig`."

        send_message_with_partner_button(msg.chat.id, response)

        return



    user_rig = user_rigs[user_id]

    now = datetime.now()



    if user_rig['last_collected'] and (now - user_rig['last_collected']) < timedelta(hours=24):

        time_left = timedelta(hours=24) - (now - user_rig['last_collected'])

        hours, remainder = divmod(time_left.seconds, 3600)

        minutes, _ = divmod(remainder, 60)

        response = f"Вы уже собирали награду недавно. Попробуйте снова через **{hours}ч {minutes}м**."

    else:

        # "Майним" случайное небольшое количество BTC

        mined_amount = random.uniform(0.00005, 0.00025)

        user_rig['balance'] += mined_amount

        user_rig['last_collected'] = now

        response = f"✅ Вы успешно собрали **{mined_amount:.6f}** BTC!\n\n" \

                   f"Ваш новый баланс: `{user_rig['balance']:.6f}` BTC."

    

    send_message_with_partner_button(msg.chat.id, response)



@bot.message_handler(commands=['chart'])

def handle_chart(msg):

    bot.send_message(msg.chat.id, "⏳ Строю график, это может занять немного времени...")

    try:

        sheet = get_gsheet()

        records = sheet.get_all_values()[1:]

        dates, profits = [], []

        error_lines = []



        for i, row in enumerate(records):

            try:

                if not row or len(row) < 3 or not row[0] or not row[2]: continue

                date_obj = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")

                profit_match = re.search(r'\$([\d\.]+)', row[2])

                if profit_match:

                    profits.append(float(profit_match.group(1)))

                    dates.append(date_obj)

            except (ValueError, IndexError):

                error_lines.append(str(i + 2))

                continue



        if len(dates) < 2:

            bot.send_message(msg.chat.id, "Недостаточно данных для построения графика. Нужно минимум 2 корректные записи в таблице.")

            return



        if error_lines:

            bot.send_message(msg.chat.id, f"⚠️ **Предупреждение:** Не удалось обработать строки: {', '.join(error_lines)}. Убедитесь, что дата в формате `ГГГГ-ММ-ДД ЧЧ:ММ:СС` и в тексте есть цена в `$`. График построен по остальным данным.")



        plt.style.use('dark_background')

        fig, ax = plt.subplots(figsize=(12, 6))

        ax.plot(dates, profits, marker='o', linestyle='-', color='#00aaff', label='Чистая прибыль ($)')

        ax.set_title('Динамика доходности майнинга', fontsize=16, color='white')

        ax.set_ylabel('Прибыль, $', color='white')

        ax.tick_params(axis='x', colors='white', rotation=30)

        ax.tick_params(axis='y', colors='white')

        ax.grid(True, which='both', linestyle='--', linewidth=0.5, color='#555555')

        ax.legend()

        fig.tight_layout()



        buf = io.BytesIO()

        plt.savefig(buf, format='png', dpi=150, transparent=True)

        buf.seek(0)

        bot.send_photo(msg.chat.id, buf, caption="📈 График динамики доходности на основе ваших данных из Google Sheets.")

        plt.close(fig)



    except Exception as e:

        logger.error(f"Ошибка построения графика: {e}")

        bot.send_message(msg.chat.id, f"❌ Не удалось построить график: {e}")



@bot.message_handler(content_types=['text'])

def handle_all_text_messages(msg):

    """Основной обработчик текстовых сообщений."""

    user_id = msg.from_user.id

    text_lower = msg.text.lower().strip()

    

    # 📌 ИЗМЕНЕНО: Более чистое управление состоянием пользователя

    current_state = user_states.get(user_id, {})



    if current_state.get('weather_request'):

        del user_states[user_id]

        bot.send_message(msg.chat.id, "⏳ Ищу погоду...", reply_markup=get_main_keyboard())

        send_message_with_partner_button(msg.chat.id, get_weather(msg.text))

        return



    if current_state.get('calculator_request'):

        try:

            electricity_cost = float(text_lower.replace(',', '.'))

            del user_states[user_id]

            bot.send_message(msg.chat.id, "⏳ Считаю прибыль...", reply_markup=get_main_keyboard())

            calculation_result = calculate_and_format_profit(electricity_cost)

            send_message_with_partner_button(msg.chat.id, calculation_result)

        except ValueError:

            bot.send_message(msg.chat.id, "❌ Неверный формат. Пожалуйста, введите число, например: `7.5` или `3`")

        return



    # Карта для текстовых команд с клавиатуры

    command_map = {

        "💹 курс btc": lambda: handle_price(types.Message(message_id=0, from_user=None, date=0, chat=msg.chat, content_type='text', options={}, json_string='{"text": "/price BTC"}')),

        "⛽️ газ eth": lambda: send_message_with_partner_button(msg.chat.id, get_eth_gas_price()),

        "😱 индекс страха": lambda: handle_fear_and_greed(msg),

        "⏳ халвинг": lambda: handle_halving(msg),

        "⚙️ топ-5 asic": lambda: handle_asics_text(msg),

        "📰 новости": lambda: handle_news_text(msg),

    }



    if text_lower in command_map:

        command_map[text_lower]()

        return



    if text_lower in ["⛏️ калькулятор", "/calc"]:

        user_states[user_id] = {'calculator_request': True}

        bot.send_message(msg.chat.id, "💡 Введите стоимость вашей электроэнергии в **рублях** за кВт/ч (например: `7.5`)", reply_markup=types.ReplyKeyboardRemove())

        return



    if text_lower in ["🌦️ погода", "/weather"]:

        user_states[user_id] = {'weather_request': True}

        bot.send_message(msg.chat.id, "🌦 В каком городе показать погоду?", reply_markup=types.ReplyKeyboardRemove())

        return



    match = re.search(r'(\S+)\s+(?:в|to|к)\s+(\S+)', text_lower)

    if match and ('курс' in text_lower or 'конверт' in text_lower):

        base_word, quote_word = match.groups()

        base_currency = CURRENCY_MAP.get(base_word)

        quote_currency = CURRENCY_MAP.get(quote_word)

        if base_currency and quote_currency:

            send_message_with_partner_button(msg.chat.id, get_currency_rate(base_currency, quote_currency))

            return



    sale_words = ["продам", "продать", "куплю", "купить", "в наличии", "предзаказ"]

    item_words = ["asic", "асик", "whatsminer", "antminer", "карта", "ферма"]

    if any(word in text_lower for word in sale_words) and any(word in text_lower for word in item_words):

        log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or msg.from_user.first_name, msg.text])

        prompt = (f"Пользователь прислал прайс-лист или объявление о продаже майнинг-оборудования в наш чат. "

                  f"Выступи в роли эксперта в этом чате. Кратко и неформально прокомментируй предложение "

                  f"(например, 'цены выглядят интересно' или 'хороший выбор для новичков'). "

                  f"НЕ ПРЕДЛАГАЙ размещать объявление на других площадках (Avito, Юла и т.д.). "

                  f"Твоя задача - поддержать диалог в ЭТОМ чате.\n\nТекст объявления:\n{msg.text}")

        analysis = ask_gpt(prompt)

        send_message_with_partner_button(msg.chat.id, analysis)

        return



    bot.send_chat_action(msg.chat.id, 'typing')

    send_message_with_partner_button(msg.chat.id, ask_gpt(msg.text))



# Вспомогательные функции для текстового обработчика, чтобы не дублировать код

def handle_asics_text(msg):

    bot.send_message(msg.chat.id, "⏳ Загружаю актуальный список...")

    asics_data = get_top_asics()

    if not asics_data or isinstance(asics_data[0], str):

        error_message = asics_data[0] if asics_data else "Не удалось получить данные."

        send_message_with_partner_button(msg.chat.id, error_message)

        return



    formatted_list = [f"• {asic['name']}: {asic['hashrate']}, {asic['power_str']}, доход ~{asic['revenue_str']}/день" for asic in asics_data]

    response_text = "**Топ-5 самых доходных ASIC на сегодня:**\n" + "\n".join(formatted_list)

    send_message_with_partner_button(msg.chat.id, response_text)



def handle_news_text(msg):

    bot.send_message(msg.chat.id, "⏳ Ищу свежие новости...")

    keywords = [word.upper() for word in msg.text.lower().split() if word.upper() in ['BTC', 'ETH', 'SOL', 'MINING']]

    send_message_with_partner_button(msg.chat.id, get_crypto_news(keywords or None))





# ========================================================================================

# 7. ЗАПУСК БОТА, ВЕБХУКА И ПЛАНИРОВЩИКА

# ========================================================================================



@app.route('/webhook', methods=['POST'])

def webhook():

    """Обработчик вебхука от Telegram."""

    if request.headers.get('content-type') == 'application/json':

        json_string = request.get_data().decode('utf-8')

        update = telebot.types.Update.de_json(json_string)

        bot.process_new_updates([update])

        return '', 200

    else:

        return 'Forbidden', 403



@app.route("/")

def index():

    """Страница для проверки, что бот запущен."""

    return "Bot is running!", 200



def run_scheduler():

    """Запускает фоновые задачи по расписанию."""

    schedule.every(25).minutes.do(keep_alive)

    schedule.every(4).hours.do(auto_send_news)

    schedule.every(6).hours.do(auto_check_status)

    # 📌 ИЗМЕНЕНО: Обновление кэша ASIC теперь тоже по расписанию

    schedule.every(1).hours.do(get_top_asics, force_update=True)



    logger.info("Первоначальный запуск фоновых задач...")

    get_top_asics(force_update=True)

    auto_check_status()

    keep_alive()



    while True:

        schedule.run_pending()

        time.sleep(1)



if __name__ == '__main__':

    logger.info("Запуск бота...")

    if WEBHOOK_URL:

        logger.info("Режим вебхука. Установка...")

        bot.remove_webhook()

        time.sleep(0.5)

        full_webhook_url = WEBHOOK_URL.rstrip("/") + "/webhook"

        bot.set_webhook(url=full_webhook_url)

        logger.info(f"Вебхук установлен на: {full_webhook_url}")



        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)

        scheduler_thread.start()

        logger.info("Планировщик запущен.")



        port = int(os.environ.get('PORT', 10000))

        app.run(host="0.0.0.0", port=port)

    else:

        logger.info("Вебхук не найден. Запуск в режиме long-polling для отладки...")

        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)

        scheduler_thread.start()

        bot.remove_webhook()

        bot.polling(none_stop=True)
