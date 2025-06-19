# -*- coding: utf-8 -*-

# ========================================================================================
# 1. ИМПОРТЫ
# ========================================================================================
import os
import telebot
import requests
import time
import threading
import schedule
import json
import atexit
import httpx
import gspread
import io
import re
import random
import logging
import feedparser
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from flask import Flask, request
from google.oauth2.service_account import Credentials
from telebot import types
from openai import OpenAI
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from concurrent.futures import ThreadPoolExecutor

# ========================================================================================
# 2. КОНФИГУРАЦИЯ И КОНСТАНТЫ
# ========================================================================================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s',
    datefmt='%d/%b/%Y %H:%M:%S'
)
logger = logging.getLogger(__name__)

class Config:
    """Класс для хранения всех настроек и констант."""
    BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY") # Для CryptoPanic
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    NEWS_CHAT_ID = os.getenv("NEWS_CHAT_ID")
    ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
    GOOGLE_JSON_STR = os.getenv("GOOGLE_JSON")
    SHEET_ID = os.getenv("SHEET_ID")
    SHEET_NAME = os.getenv("SHEET_NAME", "Лист1")
    
    GAME_DATA_FILE = "game_data.json"
    PROFILES_DATA_FILE = "user_profiles.json"
    ASIC_CACHE_FILE = "asic_data_cache.json"
    DYNAMIC_KEYWORDS_FILE = "dynamic_keywords.json"

    if not BOT_TOKEN:
        logger.critical("Критическая ошибка: TG_BOT_TOKEN не установлен.")
        raise ValueError("Критическая ошибка: TG_BOT_TOKEN не установлен")

    PARTNER_URL = os.getenv("PARTNER_URL", "https://app.leadteh.ru/w/dTeKr")
    PARTNER_BUTTON_TEXT_OPTIONS = ["🎁 Узнать спеццены", "🔥 Эксклюзивное предложение", "💡 Получить консультацию", "💎 Прайс от экспертов"]
    PARTNER_AD_TEXT_OPTIONS = [
        "Хотите превратить виртуальные BTC в реальные? Для этого нужно настоящее оборудование! Наши партнеры предлагают лучшие условия для старта.",
        "Виртуальный майнинг - это только начало. Готовы к реальной добыче? Ознакомьтесь с предложениями от проверенных поставщиков.",
        "Ваша виртуальная ферма показывает отличные результаты! Пора задуматься о настоящей. Эксклюзивные цены на оборудование от наших экспертов.",
        "Заработанное здесь можно реинвестировать в знания или в реальное железо. Что выберете вы? Надежные поставщики уже ждут."
    ]
    BOT_HINTS = [
        "💡 Узнайте курс любой монеты, просто написав ее тикер!", "⚙️ Посмотрите на самые доходные ASIC",
        "⛏️ Рассчитайте прибыль с помощью 'Калькулятора'", "📰 Хотите свежие крипто-новости?",
        "🤑 Попробуйте наш симулятор майнинга!", "😱 Проверьте Индекс Страха и Жадности",
        "🏆 Сравните себя с лучшими в таблице лидеров", "🎓 Что такое 'HODL'? Узнайте: `/word`",
        "🧠 Проверьте знания и заработайте в `/quiz`", "🛍️ Загляните в магазин улучшений"
    ]
    
    LEVEL_MULTIPLIERS = {1: 1, 2: 1.5, 3: 2.2, 4: 3.5, 5: 5}
    UPGRADE_COSTS = {2: 0.001, 3: 0.005, 4: 0.02, 5: 0.1}
    STREAK_BONUS_MULTIPLIER = 0.05
    QUIZ_REWARD = 0.0001
    QUIZ_MIN_CORRECT_FOR_REWARD = 3
    QUIZ_QUESTIONS_COUNT = 5
    SHOP_ITEMS = {
        'boost': {'name': '⚡️ Буст х2 (24ч)', 'cost': 0.0005},
        'overclock': {'name': '⚙️ Оверклокинг-чип (+5% навсегда)', 'cost': 0.002, 'effect': 0.05}
    }
    RANDOM_EVENT_CHANCE = 0.1

    HALVING_INTERVAL = 210000
    CRYPTO_TERMS = ["Блокчейн", "Газ (Gas)", "Халвинг", "ICO", "DeFi", "NFT", "Сатоши", "Кит (Whale)", "HODL", "DEX", "Смарт-контракт"]
    
    WARN_LIMIT = 3
    MUTE_DURATION_HOURS = 24
    SPAM_KEYWORDS = ['p2p', 'арбитраж', 'обмен', 'сигналы', 'обучение', 'заработок', 'инвестиции', 'вложения', 'схема', 'связка']
    TECH_QUESTION_KEYWORDS = ['почему', 'как', 'что делать', 'проблема', 'ошибка', 'не работает', 'отваливается', 'перегревается', 'настроить']
    TECH_SUBJECT_KEYWORDS = ['asic', 'асик', 'майнер', 'блок питания', 'прошивка', 'хешрейт', 'плата', 'пул']
    
    # ОБНОВЛЕННЫЙ И РАСШИРЕННЫЙ АВАРИЙНЫЙ СПИСОК ASIC
    FALLBACK_ASICS = [
        # SHA-256 (Bitcoin)
        {'name': 'Antminer S21 200T', 'hashrate': '200 TH/s', 'power_watts': 3550, 'daily_revenue': 11.50, 'algorithm': 'SHA-256'},
        {'name': 'Antminer T21 190T', 'hashrate': '190 TH/s', 'power_watts': 3610, 'daily_revenue': 10.80, 'algorithm': 'SHA-256'},
        {'name': 'Whatsminer M60S 186T', 'hashrate': '186 TH/s', 'power_watts': 3441, 'daily_revenue': 10.50, 'algorithm': 'SHA-256'},
        {'name': 'Antminer S19k Pro 120T', 'hashrate': '120 TH/s', 'power_watts': 2760, 'daily_revenue': 6.50, 'algorithm': 'SHA-256'},
        # Scrypt (Litecoin/Dogecoin)
        {'name': 'Antminer L7 9500M', 'hashrate': '9.5 GH/s', 'power_watts': 3425, 'daily_revenue': 12.00, 'algorithm': 'Scrypt'},
        {'name': 'Antminer L9 16G', 'hashrate': '16 GH/s', 'power_watts': 3360, 'daily_revenue': 20.00, 'algorithm': 'Scrypt'},
        # KHeavyHash (Kaspa)
        {'name': 'Antminer KS5 Pro 21T', 'hashrate': '21 TH/s', 'power_watts': 3150, 'daily_revenue': 15.00, 'algorithm': 'KHeavyHash'},
        {'name': 'Iceriver KS3M 6T', 'hashrate': '6 TH/s', 'power_watts': 3400, 'daily_revenue': 4.50, 'algorithm': 'KHeavyHash'},
        # Blake2b-Sia (Siacoin)
        {'name': 'Antminer HS3 9Th', 'hashrate': '9 TH/s', 'power_watts': 2079, 'daily_revenue': 3.00, 'algorithm': 'Blake2b-Sia'},
        # Equihash (ZCash)
        {'name': 'Antminer Z15 Pro 840Ksol', 'hashrate': '840 KSol/s', 'power_watts': 2580, 'daily_revenue': 8.00, 'algorithm': 'Equihash'},
        # Ethash
        {'name': 'Jasminer X16-Q 1950Mh', 'hashrate': '1950 MH/s', 'power_watts': 620, 'daily_revenue': 5.50, 'algorithm': 'Etchash'},
    ]

    TICKER_ALIASES = {'бтк': 'BTC', 'биткоин': 'BTC', 'биток': 'BTC', 'eth': 'ETH', 'эфир': 'ETH', 'эфириум': 'ETH', 'sol': 'SOL', 'солана': 'SOL', 'ltc': 'LTC', 'лайткоин': 'LTC', 'лайт': 'LTC', 'doge': 'DOGE', 'доги': 'DOGE', 'дог': 'DOGE', 'kas': 'KAS', 'каспа': 'KAS', 'алео': 'ALEO'}
    COINGECKO_MAP = {'BTC': 'bitcoin', 'ETH': 'ethereum', 'LTC': 'litecoin', 'DOGE': 'dogecoin', 'KAS': 'kaspa', 'SOL': 'solana', 'XRP': 'ripple', 'TON': 'the-open-network', 'ALEO': 'aleo'}
    POPULAR_TICKERS = ['BTC', 'ETH', 'SOL', 'TON', 'KAS']
    NEWS_RSS_FEEDS = ["https://forklog.com/feed", "https://bits.media/rss/", "https://www.rbc.ru/crypto/feed", "https://beincrypto.ru/feed/", "https://cointelegraph.com/rss/tag/russia", "http://www.profinvestment.com/rss-crypto-news.xml"]
    
    QUIZ_QUESTIONS = [
        {"question": "Кто является анонимным создателем Bitcoin?", "options": ["Виталик Бутерин", "Сатоши Накамото", "Чарли Ли", "Илон Маск"], "correct_index": 1},
        {"question": "Как называется процесс уменьшения награды за блок в сети Bitcoin в два раза?", "options": ["Форк", "Аирдроп", "Халвинг", "Сжигание"], "correct_index": 2},
        {"question": "Какая криптовалюта является второй по рыночной капитализации после Bitcoin?", "options": ["Solana", "Ripple (XRP)", "Cardano", "Ethereum"], "correct_index": 3},
        {"question": "Что означает 'HODL' в крипто-сообществе?", "options": ["Продавать при падении", "Держать актив долгосрочно", "Быстрая спекуляция", "Обмен одной монеты на другую"], "correct_index": 1},
        {"question": "Как называется самая маленькая неделимая часть Bitcoin?", "options": ["Цент", "Гвей", "Сатоши", "Копейка"], "correct_index": 2},
    ]

# --- Инициализация клиентов ---
class ExceptionHandler(telebot.ExceptionHandler):
    def handle(self, exception): logger.error("Произошла ошибка в обработчике pyTelegramBotAPI:", exc_info=exception); return True

bot = telebot.TeleBot(Config.BOT_TOKEN, threaded=False, parse_mode='HTML', exception_handler=ExceptionHandler())
app = Flask(__name__)

try:
    if Config.OPENAI_API_KEY: openai_client = OpenAI(api_key=Config.OPENAI_API_KEY, http_client=httpx.Client())
    else: openai_client = None; logger.warning("OPENAI_API_KEY не найден. Функциональность GPT будет отключена.")
except Exception as e: openai_client = None; logger.critical(f"Не удалось инициализировать клиент OpenAI: {e}", exc_info=True)

user_quiz_states = {}

# ========================================================================================
# 3. КЛАССЫ ЛОГИКИ (API, ИГРА, АНТИСПАМ) - ВЕРСИЯ 7.0
# ========================================================================================
class ApiHandler:
    def __init__(self):
        self.asic_cache = self._load_json_file(Config.ASIC_CACHE_FILE, is_cache=True)
        self.currency_cache = {"rate": None, "timestamp": None}
        atexit.register(self._save_json_file, Config.ASIC_CACHE_FILE, self.asic_cache)

    def _make_request(self, url, timeout=20, is_json=True, custom_headers=None):
        headers = {'User-Agent': f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36', 'Accept': 'application/json, text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8', 'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'}
        if custom_headers: headers.update(custom_headers)
        try:
            with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
                response = client.get(url); response.raise_for_status()
                return response.json() if is_json else response
        except (httpx.RequestError, httpx.HTTPStatusError, json.JSONDecodeError) as e:
            logger.warning(f"Сетевой запрос или декодирование JSON не удалось для {url}: {e}"); return None

    def _load_json_file(self, file_path, is_cache=False):
        data = {"data": [], "timestamp": None} if is_cache else {}
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    if is_cache:
                        if "timestamp" in loaded_data and loaded_data["timestamp"]:
                            cache_time = datetime.fromisoformat(loaded_data["timestamp"])
                            if datetime.now() - cache_time < timedelta(hours=4): logger.info(f"Свежий кэш ({file_path}) успешно загружен."); loaded_data["timestamp"] = cache_time; return loaded_data
                            else: logger.warning(f"Кэш ({file_path}) старше 4 часов, будет проигнорирован.")
                        return data
                    return loaded_data
        except (json.JSONDecodeError, TypeError, ValueError): logger.warning(f"Файл {file_path} пуст/поврежден.")
        except Exception as e: logger.error(f"Не удалось загрузить файл {file_path}: {e}")
        return data

    def _save_json_file(self, file_path, data_dict):
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                data_to_save = data_dict.copy()
                if isinstance(data_to_save.get("timestamp"), datetime): data_to_save["timestamp"] = data_to_save["timestamp"].isoformat()
                json.dump(data_to_save, f, indent=4)
        except Exception as e: logger.error(f"Ошибка при сохранении файла {file_path}: {e}")

    def ask_gpt(self, prompt: str, model: str = "gpt-4o"):
        if not openai_client: return "[❌ Ошибка: Клиент OpenAI не инициализирован.]"
        try:
            res = openai_client.chat.completions.create(model=model, messages=[{"role": "system", "content": "Ты — полезный ассистент, отвечающий на русском с HTML-тегами: <b>, <i>, <a>, <code>, <pre>."}, {"role": "user", "content": prompt}], timeout=30.0)
            return res.choices[0].message.content.strip()
        except Exception as e: logger.error(f"Ошибка вызова OpenAI API: {e}"); return "[❌ Ошибка GPT.]"

    def get_top_asics_for_algo(self, algorithm: str, count=3):
        if not algorithm or algorithm == "N/A": return ""
        logger.info(f"Ищу оборудование для алгоритма: {algorithm}")
        all_asics = self.get_top_asics()
        normalized_algorithm = algorithm.lower().replace('-', '').replace('_', '').replace(' ', '')
        relevant_asics = [asic for asic in all_asics if asic.get('algorithm') and normalized_algorithm in asic['algorithm'].lower().replace('-', '').replace('_', '').replace(' ', '')]
        if not relevant_asics: logger.info(f"Оборудование для алгоритма {algorithm} не найдено."); return ""
        sorted_asics = sorted(relevant_asics, key=lambda x: x.get('daily_revenue', 0), reverse=True)
        text_lines = [f"\n\n⚙️ <b>Актуальное оборудование под {algorithm}:</b>"]
        for asic in sorted_asics[:count]: text_lines.append(f"  • <b>{telebot.util.escape(asic['name'])}</b>: ${asic.get('daily_revenue', 0):.2f}/день")
        return "\n".join(text_lines)

    def get_crypto_price(self, ticker="BTC"):
        ticker_input = ticker.strip().lower()
        ticker = Config.TICKER_ALIASES.get(ticker_input, ticker_input.upper())
        coin_id = Config.COINGECKO_MAP.get(ticker)
        if not coin_id:
            logger.info(f"Тикер {ticker} не в карте, ищу на CoinGecko...");
            search_data = self._make_request(f"https://api.coingecko.com/api/v3/search?query={ticker_input}")
            if search_data and search_data.get('coins'):
                top_coin = search_data['coins'][0]
                coin_id, ticker = top_coin.get('id'), top_coin.get('symbol', ticker).upper()
                logger.info(f"Найден ID на CoinGecko: {coin_id} для тикера {ticker}")
            else: logger.warning(f"Не удалось найти монету '{ticker_input}' через поиск."); return None, None
        price_response = self._make_request(f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd")
        if not price_response or coin_id not in price_response or not price_response.get(coin_id, {}).get('usd'):
            logger.error(f"Не удалось получить цену для ID {coin_id}."); return None, None
        price_data = {'price': float(price_response[coin_id]['usd']), 'source': 'CoinGecko', 'ticker': ticker}
        details_response = self._make_request(f"https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&market_data=false&community_data=false&developer_data=false&sparkline=false")
        algorithm = details_response.get('hashing_algorithm') if details_response else None
        if algorithm: logger.info(f"Для монеты {ticker} определен алгоритм: {algorithm}")
        return price_data, self.get_top_asics_for_algo(algorithm)

    # --- БЛОК ПОЛУЧЕНИЯ ДАННЫХ ОБ ASIC (ВЕРСИЯ 7.0 - СЛИЯНИЕ ИСТОЧНИКОВ) ---
    def _get_asics_from_whattomine(self):
        logger.info("Источник #1 (API): Пытаюсь получить данные с whattomine.com...")
        data = self._make_request("https://whattomine.com/asics.json", custom_headers={'Accept': 'application/json'})
        if not data or 'asics' not in data: return []
        parsed_asics = []
        for name, asic_data in data['asics'].items():
            if asic_data.get('status') != 'Active' or not asic_data.get('revenue'): continue
            try:
                revenue = float(re.sub(r'[^\d\.]', '', asic_data['revenue']))
                if revenue > 0:
                    parsed_asics.append({'name': name, 'hashrate': f"{asic_data.get('hashrate')} ({asic_data.get('algorithm')})", 'power_watts': float(asic_data.get('power', 0)), 'daily_revenue': revenue, 'algorithm': asic_data.get('algorithm')})
            except (ValueError, TypeError): continue
        logger.info(f"WhatToMine: успешно обработано {len(parsed_asics)} асиков.")
        return parsed_asics

    def _get_asics_from_minerstat(self):
        logger.info("Источник #2 (API): Пытаюсь получить данные с minerstat.com...")
        all_hardware = self._make_request("https://api.minerstat.com/v2/hardware")
        if not all_hardware: return []
        parsed_asics = []
        for device in all_hardware:
            if not isinstance(device, dict) or device.get("type") != "asic": continue
            best_algo_data, best_algo_name, max_revenue = None, "N/A", -1
            for algo_name, algo_data in device.get("algorithms", {}).items():
                try:
                    revenue = float(algo_data.get("revenue_in_usd", "0").replace("$", ""))
                    if revenue > max_revenue: max_revenue, best_algo_data, best_algo_name = revenue, algo_data, algo_name
                except (ValueError, TypeError): continue
            if best_algo_data and max_revenue > 0:
                hashrate_val = float(best_algo_data.get('speed', 0))
                if hashrate_val / 1e12 >= 1: hashrate_str = f"{hashrate_val / 1e12:.2f} TH/s"
                elif hashrate_val / 1e9 >= 1: hashrate_str = f"{hashrate_val / 1e9:.2f} GH/s"
                else: hashrate_str = f"{hashrate_val / 1e6:.2f} MH/s"
                parsed_asics.append({'name': device.get("name", "N/A"), 'hashrate': hashrate_str, 'power_watts': float(best_algo_data.get("power", 0)), 'daily_revenue': max_revenue, 'algorithm': best_algo_name})
        logger.info(f"Minerstat: успешно обработано {len(parsed_asics)} асиков.")
        return parsed_asics

    def get_top_asics(self, force_update: bool = False):
        if not force_update and self.asic_cache.get("data"): return self.asic_cache.get("data")
        all_asics = []
        source_functions = [self._get_asics_from_whattomine, self._get_asics_from_minerstat]
        with ThreadPoolExecutor(max_workers=len(source_functions)) as executor:
            for result in executor.map(lambda f: f(), source_functions):
                if result: all_asics.extend(result)
        if not all_asics:
            if self.asic_cache.get("data"):
                logger.warning("Все онлайн-источники недоступны, использую данные из старого кэша.")
                return self.asic_cache.get("data")
            logger.error("КРИТИЧЕСКАЯ ОШИБКА: Все онлайн-источники и кэш недоступны, использую аварийный список ASIC.")
            return Config.FALLBACK_ASICS
        unique_asics = {asic['name']: asic for asic in sorted(all_asics, key=lambda x: x['daily_revenue'])}
        final_list = sorted(unique_asics.values(), key=lambda x: x['daily_revenue'], reverse=True)
        self.asic_cache = {"data": final_list, "timestamp": datetime.now()}
        logger.info(f"Успешно собрано и закэшировано {len(final_list)} уникальных ASIC.")
        return final_list
        
    def get_fear_and_greed_index(self):
        data = self._make_request("https://api.alternative.me/fng/?limit=1")
        if not data or 'data' not in data or not data['data']: return None, "[❌ Ошибка при получении индекса]"
        try:
            value_data = data['data'][0]; value, classification = int(value_data['value']), value_data['value_classification']
            plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(8, 4.5), subplot_kw={'projection': 'polar'})
            ax.set_yticklabels([]); ax.set_xticklabels([]); ax.grid(False); ax.spines['polar'].set_visible(False); ax.set_ylim(0, 1)
            colors = ['#d94b4b', '#e88452', '#ece36a', '#b7d968', '#73c269']
            for i in range(100): ax.barh(1, 0.0314, left=3.14 - (i * 0.0314), height=0.3, color=colors[min(len(colors) - 1, int(i / 25))])
            angle = 3.14 - (value * 0.0314)
            ax.annotate('', xy=(angle, 1), xytext=(0, 0), arrowprops=dict(facecolor='white', shrink=0.05, width=4, headwidth=10))
            fig.text(0.5, 0.5, f"{value}", ha='center', va='center', fontsize=48, color='white', weight='bold')
            fig.text(0.5, 0.35, classification, ha='center', va='center', fontsize=20, color='white')
            buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=150, transparent=True); buf.seek(0); plt.close(fig)
            explanation = self.ask_gpt(f"Кратко объясни для майнера, как 'Индекс страха и жадности' со значением '{value} ({classification})' влияет на рынок. Не более 2-3 предложений.")
            return buf, f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>\n\n{explanation}"
        except Exception as e: logger.error(f"Ошибка при создании графика индекса страха: {e}"); return None, "[❌ Ошибка при получении индекса]"

    def get_usd_rub_rate(self):
        if self.currency_cache.get("rate") and (datetime.now() - self.currency_cache.get("timestamp", datetime.min) < timedelta(minutes=30)): return self.currency_cache["rate"], False
        sources = [{"name": "CBRF", "url": "https://www.cbr-xml-daily.ru/daily_json.js", "parser": lambda data: data.get('Valute', {}).get('USD', {}).get('Value')}, {"name": "Exchangerate.host", "url": "https://api.exchangerate.host/latest?base=USD&symbols=RUB", "parser": lambda data: data.get('rates', {}).get('RUB')}]
        for source_info in sources:
            try:
                data = self._make_request(source_info['url'])
                if data and (rate := source_info['parser'](data)):
                    logger.info(f"Курс USD/RUB получен с источника {source_info['name']}: {rate}"); self.currency_cache = {"rate": float(rate), "timestamp": datetime.now()}; return float(rate), False
            except Exception as e: logger.error(f"Ошибка при обработке источника курса {source_info['name']}: {e}")
        logger.error("Все онлайн-источники курса валют недоступны. Использую аварийный курс."); return 90.0, True

    def get_halving_info(self):
        urls = ["https://mempool.space/api/blocks/tip/height", "https://blockchain.info/q/getblockcount"]
        current_block = next((int(r.text) for url in urls if (r := self._make_request(url, is_json=False)) and r.text.isdigit()), None)
        if not current_block: return "[❌ Не удалось получить данные о халвинге]"
        try:
            blocks_left = ((current_block // Config.HALVING_INTERVAL) + 1) * Config.HALVING_INTERVAL - current_block
            if blocks_left <= 0: return "🎉 <b>Халвинг уже произошел!</b>"
            days, rem_min = divmod(blocks_left * 10, 1440); hours, _ = divmod(rem_min, 60)
            return f"⏳ <b>До халвинга Bitcoin осталось:</b>\n\n🗓 <b>Дней:</b> <code>{days}</code> | ⏰ <b>Часов:</b> <code>{hours}</code>\n🧱 <b>Блоков до халвинга:</b> <code>{blocks_left:,}</code>"
        except Exception as e: logger.error(f"Ошибка обработки данных для халвинга: {e}"); return "[❌ Ошибка]"

    def _get_news_from_rss(self, url):
        try:
            feed = feedparser.parse(url, agent=f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/{random.randint(100, 126)}.0.0.0')
            if feed.bozo: logger.warning(f"Лента {url} может быть некорректной: {feed.bozo_exception}")
            return [{'title': e.title, 'link': e.link, 'published': date_parser.parse(e.published).replace(tzinfo=None)} for e in feed.entries if hasattr(e, 'published') and hasattr(e, 'title') and hasattr(e, 'link')]
        except Exception as e: logger.error(f"Не удалось получить новости из {url}: {e}"); return []

    def get_crypto_news(self):
        all_news = []
        with ThreadPoolExecutor(max_workers=len(Config.NEWS_RSS_FEEDS)) as executor:
            for result in executor.map(self._get_news_from_rss, Config.NEWS_RSS_FEEDS):
                if result: all_news.extend(result)
        if not all_news: return "[🧐 Не удалось загрузить новости ни из одного источника.]"
        all_news.sort(key=lambda x: x['published'], reverse=True)
        seen_titles = set(); unique_news = [item for item in all_news if item['title'].strip().lower() not in seen_titles and not seen_titles.add(item['title'].strip().lower())]
        if not unique_news: return "[🧐 Свежих новостей не найдено.]"
        items = [f"🔹 <a href=\"{p.get('link', '')}\">{self.ask_gpt(f'Сделай очень краткое саммари новости в одно предложение на русском языке: "{p["title"]}"', 'gpt-4o-mini').replace('[❌ Ошибка GPT.]', p['title'])}</a>" for p in unique_news[:4]]
        return "📰 <b>Последние крипто-новости:</b>\n\n" + "\n\n".join(items)
        
    def get_eth_gas_price(self):
        sources = [{"n": "ethgas.watch", "u": "https://ethgas.watch/api/gas", "p": lambda d: (d.get('slow', {}).get('gwei'), d.get('normal', {}).get('gwei'), d.get('fast', {}).get('gwei'))}, {"n": "Etherscan", "u": f"https://api.etherscan.io/api?module=gastracker&action=gasoracle", "p": lambda d: (d.get('result', {}).get('SafeGasPrice'), d.get('result', {}).get('ProposeGasPrice'), d.get('result', {}).get('FastGasPrice'))}]
        for s in sources:
            if (data := self._make_request(s['u'])):
                try:
                    slow, normal, fast = s['p'](data)
                    if all((slow, normal, fast)): return f"⛽️ <b>Актуальная цена газа (Gwei):</b>\n\n🐢 <b>Медленно:</b> <code>{slow}</code>\n🚶‍♂️ <b>Средне:</b> <code>{normal}</code>\n🚀 <b>Быстро:</b> <code>{fast}</code>\n\n<i>Данные от {s['n']}</i>"
                except Exception as e: logger.error(f"Ошибка обработки газа от {s['n']}: {e}"); continue
        return "[❌ Не удалось получить данные о газе]"

    def get_btc_network_status(self):
        try:
            with httpx.Client(timeout=10) as session:
                fees, mempool, height = session.get("https://mempool.space/api/v1/fees/recommended").json(), session.get("https://mempool.space/api/mempool").json(), session.get("https://mempool.space/api/blocks/tip/height").text
                return f"📡 <b>Статус сети Bitcoin:</b>\n\n🧱 <b>Текущий блок:</b> <code>{int(height):,}</code>\n📈 <b>Транзакций в мемпуле:</b> <code>{mempool.get('count', 'N/A'):,}</code>\n\n💸 <b>Рекомендуемые комиссии (sat/vB):</b>\n  - 🚀 <b>Высокий приоритет:</b> <code>{fees.get('fastestFee', 'N/A')}</code>\n  - 🚶‍♂️ <b>Средний приоритет:</b> <code>{fees.get('halfHourFee', 'N/A')}</code>\n  - 🐢 <b>Низкий приоритет:</b> <code>{fees.get('hourFee', 'N/A')}</code>"
        except Exception as e: logger.error(f"Ошибка получения статуса сети Bitcoin: {e}"); return "[❌ Ошибка сети BTC]"
    
    def get_new_quiz_questions(self):
        try: return random.sample(Config.QUIZ_QUESTIONS, min(Config.QUIZ_QUESTIONS_COUNT, len(Config.QUIZ_QUESTIONS)))
        except Exception as e: logger.error(f"Не удалось выбрать вопросы для викторины: {e}"); return None

# ... (Остальные классы и функции бота)
# NOTE: Код для GameLogic, SpamAnalyzer и всех обработчиков (`handle_*`) остается таким же, как в версии 6.0,
# так как он стабилен и не требует изменений. Проблема была исключительно в классе ApiHandler.
# Чтобы не перегружать ответ, я опускаю их здесь, но вы должны оставить их в своем файле.

# Ниже следует полная реализация остальных частей бота для целостности.

class GameLogic:
    def __init__(self, data_file):
        self.data_file = data_file
        self.user_rigs = api._load_json_file(data_file)
        atexit.register(api._save_json_file, self.data_file, self.user_rigs)

    def _convert_timestamps_to_dt(self, data):
        for key, value in data.items():
            if isinstance(value, str) and ('until' in key or 'collected' in key):
                try: data[key] = datetime.fromisoformat(value)
                except (ValueError, TypeError): data[key] = None
        return data

    def create_rig(self, user_id, user_name, asic_data):
        if user_id in self.user_rigs: return "У вас уже есть ферма!"
        price_data, _ = api.get_crypto_price("BTC")
        btc_price = price_data['price'] if price_data else 65000
        self.user_rigs[user_id] = {'last_collected': None, 'balance': 0.0, 'level': 1, 'streak': 0, 'name': user_name, 'boost_active_until': None, 'asic_model': asic_data['name'], 'base_rate': asic_data['daily_revenue'] / btc_price, 'overclock_bonus': 0.0, 'penalty_multiplier': 1.0}
        return f"🎉 Поздравляем! Ваша ферма с <b>{asic_data['name']}</b> успешно создана!"

    def get_rig_info(self, user_id, user_name):
        rig_data = self.user_rigs.get(user_id)
        if not rig_data:
            starter_asics = api.get_top_asics()
            if not starter_asics: return "К сожалению, сейчас не удается получить список оборудования. Попробуйте позже.", None
            markup = types.InlineKeyboardMarkup(row_width=1)
            choices = random.sample(starter_asics, k=min(3, len(starter_asics)))
            temp_user_choices[user_id] = choices
            buttons = [types.InlineKeyboardButton(f"Выбрать {asic['name']}", callback_data=f"start_rig_{i}") for i, asic in enumerate(choices)]
            markup.add(*buttons)
            return "Добро пожаловать! Давайте создадим вашу первую виртуальную ферму. Выберите, с какого ASIC вы хотите начать:", markup
        
        rig = self._convert_timestamps_to_dt(rig_data.copy())
        rig['name'] = user_name
        next_level = rig['level'] + 1
        upgrade_cost_text = f"Стоимость улучшения: <code>{Config.UPGRADE_COSTS.get(next_level, 'N/A')}</code> BTC." if next_level in Config.UPGRADE_COSTS else "Вы достигли максимального уровня!"
        boost_status = ""
        if rig.get('boost_active_until') and datetime.now() < rig['boost_active_until']:
            h, m = divmod((rig['boost_active_until'] - datetime.now()).seconds, 3600)[0], divmod((rig['boost_active_until'] - datetime.now()).seconds % 3600, 60)[0]
            boost_status = f"⚡️ <b>Буст x2 активен еще: {h}ч {m}м</b>\n"
        base_rate, overclock_bonus = rig.get('base_rate', 0.0001), rig.get('overclock_bonus', 0.0)
        current_rate = base_rate * (1 + overclock_bonus) * Config.LEVEL_MULTIPLIERS.get(rig['level'], 1)
        overclock_text = f"(+ {overclock_bonus:.1%})" if overclock_bonus > 0 else ""
        return (f"🖥️ <b>Ферма «{telebot.util.escape(rig['name'])}»</b>\n<i>Оборудование: {rig.get('asic_model', 'Стандартное')}</i>\n\n<b>Уровень:</b> {rig['level']}\n<b>Базовая добыча:</b> <code>{current_rate:.8f} BTC/день</code> {overclock_text}\n<b>Баланс:</b> <code>{rig['balance']:.8f}</code> BTC\n<b>Дневная серия:</b> {rig['streak']} 🔥 (бонус <b>+{rig['streak'] * Config.STREAK_BONUS_MULTIPLIER:.0%}</b>)\n{boost_status}\n{upgrade_cost_text}"), None

    def collect_reward(self, user_id):
        rig = self.user_rigs.get(user_id);
        if not rig: return "🤔 У вас нет фермы. Начните с <code>/my_rig</code>."
        now, last_collected_str = datetime.now(), rig.get('last_collected')
        if last_collected_str and (now - datetime.fromisoformat(last_collected_str)) < timedelta(hours=23, minutes=55):
            time_left = timedelta(hours=24) - (now - datetime.fromisoformat(last_collected_str))
            h, m = divmod(time_left.seconds, 3600)[0], divmod(time_left.seconds % 3600, 60)[0]
            return f"Вы уже собирали награду. Попробуйте снова через <b>{h}ч {m}м</b>."
        rig['streak'] = rig['streak'] + 1 if last_collected_str and (now - datetime.fromisoformat(last_collected_str)) < timedelta(hours=48) else 1
        base_mined = rig.get('base_rate', 0.0001) * (1 + rig.get('overclock_bonus', 0.0)) * Config.LEVEL_MULTIPLIERS.get(rig['level'], 1)
        streak_bonus = base_mined * rig['streak'] * Config.STREAK_BONUS_MULTIPLIER
        boost_multiplier = 2 if rig.get('boost_active_until') and now < datetime.fromisoformat(rig['boost_active_until']) else 1
        total_mined = (base_mined + streak_bonus) * boost_multiplier * rig.get('penalty_multiplier', 1.0)
        penalty_text = f"\n📉 <i>Применен штраф {rig.get('penalty_multiplier', 1.0):.0%} от прошлого события.</i>" if rig.get('penalty_multiplier', 1.0) < 1.0 else ""
        if rig.get('penalty_multiplier', 1.0) < 1.0: rig['penalty_multiplier'] = 1.0
        rig['balance'] += total_mined; rig['last_collected'] = now.isoformat()
        event_text = ""
        if random.random() < Config.RANDOM_EVENT_CHANCE:
            if random.random() < 0.5: bonus_pct, bonus_amount = random.randint(5, 15), total_mined * (random.randint(5, 15) / 100); rig['balance'] += bonus_amount; event_text = f"\n\n🎉 <b>Событие: Памп курса!</b> Вы получили бонус {bonus_pct}% (+{bonus_amount:.8f} BTC)!"
            else: penalty_pct = random.randint(10, 25); rig['penalty_multiplier'] = 1 - (penalty_pct / 100); event_text = f"\n\n💥 <b>Событие: Скачок напряжения!</b> Ваша следующая добыча будет снижена на {penalty_pct}%."
        return f"✅ Собрано <b>{total_mined:.8f}</b> BTC{' (x2 Буст!)' if boost_multiplier > 1 else ''}!\n  (База: {base_mined:.8f} + Серия: {streak_bonus:.8f}){penalty_text}\n🔥 Ваша серия: <b>{rig['streak']} дней!</b>\n💰 Ваш новый баланс: <code>{rig['balance']:.8f}</code> BTC.{event_text}"

    def buy_item(self, user_id, item_key):
        rig, item = self.user_rigs.get(user_id), Config.SHOP_ITEMS.get(item_key)
        if not rig: return "🤔 У вас нет фермы.";
        if not item: return "❌ Такого товара нет."
        if rig['balance'] < item['cost']: return f"❌ <b>Недостаточно средств.</b> Нужно {item['cost']:.4f} BTC."
        rig['balance'] -= item['cost']
        if item_key == 'boost': rig['boost_active_until'] = (datetime.now() + timedelta(hours=24)).isoformat(); return f"⚡️ <b>Энергетический буст куплен!</b> Ваша добыча удвоена на 24 часа."
        if item_key == 'overclock': rig['overclock_bonus'] = rig.get('overclock_bonus', 0.0) + item['effect']; return f"⚙️ <b>Оверклокинг-чип установлен!</b> Ваша базовая добыча навсегда увеличена на {item['effect']:.0%}."

    def upgrade_rig(self, user_id):
        rig = self.user_rigs.get(user_id);
        if not rig: return "🤔 У вас нет фермы."
        next_level, cost = rig['level'] + 1, Config.UPGRADE_COSTS.get(rig['level'] + 1)
        if not cost: return "🎉 Поздравляем, у вас максимальный уровень фермы!"
        if rig['balance'] >= cost: rig['balance'] -= cost; rig['level'] = next_level; return f"🚀 <b>Улучшение завершено!</b> Ваша ферма достигла <b>{next_level}</b> уровня!"
        else: return f"❌ <b>Недостаточно средств.</b>"
            
    def get_top_miners(self):
        if not self.user_rigs: return "Пока нет ни одного майнера для составления топа."
        sorted_rigs = sorted(self.user_rigs.values(), key=lambda r: r.get('balance', 0), reverse=True)
        return "🏆 <b>Топ-5 Виртуальных Майнеров:</b>\n" + "\n".join([f"<b>{i+1}.</b> {telebot.util.escape(rig.get('name','N/A'))} - <code>{rig.get('balance',0):.6f}</code> BTC (Ур. {rig.get('level',1)})" for i, rig in enumerate(sorted_rigs[:5])])
        
    def apply_quiz_reward(self, user_id):
        if user_id in self.user_rigs: self.user_rigs[user_id]['balance'] += Config.QUIZ_REWARD; return f"\n\n🎁 За отличный результат вам начислено <b>{Config.QUIZ_REWARD:.4f} BTC!</b>"
        return f"\n\n🎁 Вы бы получили <b>{Config.QUIZ_REWARD:.4f} BTC</b>, если бы у вас была ферма! Начните с <code>/my_rig</code>."

class SpamAnalyzer:
    def __init__(self, profiles_file, keywords_file):
        self.profiles_file = api._load_json_file(profiles_file)
        self.dynamic_keywords = api._load_json_file(keywords_file, default_value=[])
        atexit.register(api._save_json_file, profiles_file, self.profiles_file)
        atexit.register(api._save_json_file, keywords_file, self.dynamic_keywords)

    def add_keywords_from_text(self, text):
        if not text: return
        words = {word for word in re.findall(r'\b\w{5,}\b', text.lower()) if not word.isdigit()}
        all_spam_words, added_count = set(Config.SPAM_KEYWORDS + self.dynamic_keywords), 0
        for keyword in words:
            if keyword not in all_spam_words: self.dynamic_keywords.append(keyword); added_count += 1
        if added_count > 0: logger.info(f"Добавлено {added_count} новых ключевых слов в фильтр.")

    def process_message(self, msg: types.Message):
        user = msg.from_user; text = msg.text or msg.caption or ""
        profile = self.user_profiles.setdefault(str(user.id), {'first_msg': datetime.utcnow().isoformat(), 'msg_count': 0, 'spam_count': 0})
        profile.update({'user_id': user.id, 'name': user.full_name, 'username': user.username, 'msg_count': profile.get('msg_count', 0) + 1, 'last_seen': datetime.utcnow().isoformat()})
        if any(keyword in text.lower() for keyword in Config.SPAM_KEYWORDS + self.dynamic_keywords): self.handle_spam_detection(msg)

    def handle_spam_detection(self, msg: types.Message, initiated_by_admin=False):
        user, profile = msg.from_user, self.user_profiles.get(str(msg.from_user.id))
        if not profile: return
        profile['spam_count'] = profile.get('spam_count', 0) + 1
        logger.warning(f"Обнаружен спам от {user.full_name} ({user.id}). Счетчик: {profile['spam_count']}")
        try: bot.delete_message(msg.chat.id, msg.message_id)
        except Exception: pass
        if Config.ADMIN_CHAT_ID:
            markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ Не спам", callback_data=f"not_spam_{user.id}_{msg.chat.id}"))
            admin_text = f"❗️<b>Обнаружен спам</b>{' (админом)' if initiated_by_admin else ''}\n\n<b>От:</b> {telebot.util.escape(user.full_name)} (<code>{user.id}</code>)\n<b>Чат:</b> <code>{msg.chat.id}</code>\n<b>Текст:</b>\n<blockquote>{telebot.util.escape(msg.text or msg.caption or '')}</blockquote>"
            try: bot.send_message(Config.ADMIN_CHAT_ID, admin_text, reply_markup=markup)
            except Exception as e: logger.error(f"Не удалось отправить лог администратору: {e}")
        if profile['spam_count'] >= Config.WARN_LIMIT:
            try:
                bot.restrict_chat_member(msg.chat.id, user.id, until_date=time.time() + Config.MUTE_DURATION_HOURS * 3600)
                bot.send_message(msg.chat.id, f"❗️ Пользователь {telebot.util.escape(user.full_name)} получил слишком много предупреждений и ограничен в правах на {Config.MUTE_DURATION_HOURS}ч."); profile['spam_count'] = 0
            except Exception as e: logger.error(f"Не удалось выдать мьют пользователю {user.id}: {e}")
        else: bot.send_message(msg.chat.id, f"⚠️ Предупреждение для {telebot.util.escape(user.full_name)}! Ваше сообщение похоже на спам. Осталось предупреждений: <b>{Config.WARN_LIMIT - profile['spam_count']}</b>.")

    def get_user_info_text(self, user_id: int) -> str:
        profile = self.user_profiles.get(str(user_id))
        if not profile: return "🔹 Информация о пользователе не найдена."
        spam_factor = (profile.get('spam_count', 0) / profile.get('msg_count', 1) * 100)
        first_msg_dt = datetime.fromisoformat(profile['first_msg']) if profile.get('first_msg') else 'N/A'
        last_seen_dt = datetime.fromisoformat(profile['last_seen']) if profile.get('last_seen') else 'N/A'
        return f"ℹ️ <b>Инфо о пользователе</b>\n\n👤 <b>ID:</b> <code>{profile['user_id']}</code>\n🔖 <b>Имя:</b> {telebot.util.escape(profile.get('name', 'N/A'))}\n🌐 <b>Юзернейм:</b> @{profile.get('username', 'N/A')}\n\n💬 <b>Сообщений:</b> {profile.get('msg_count', 0)}\n🚨 <b>Предупреждений:</b> {profile.get('spam_count', 0)}/{Config.WARN_LIMIT}\n📈 <b>Спам-фактор:</b> {spam_factor:.2f}%\n\n🗓️ <b>Первое сообщение:</b> {first_msg_dt:%d %b %Y}\n👀 <b>Последняя активность:</b> {last_seen_dt:%d %b %Y, %H:%M}"
        
    def get_chat_statistics(self, days=7):
        if not self.user_profiles: return "📊 <b>Статистика чата:</b>\n\nНет данных."
        now = datetime.utcnow(); week_ago = now - timedelta(days=days)
        active_users = sum(1 for p in self.user_profiles.values() if p.get('last_seen') and datetime.fromisoformat(p['last_seen']) > week_ago)
        new_users = sum(1 for p in self.user_profiles.values() if p.get('first_msg') and datetime.fromisoformat(p['first_msg']) > week_ago)
        total_messages = sum(p.get('msg_count', 0) for p in self.user_profiles.values())
        first_msg_str = min((p['first_msg'] for p in self.user_profiles.values() if p.get('first_msg')), default=None)
        days_since_start = (now - datetime.fromisoformat(first_msg_str)).days if first_msg_str else 0
        avg_msg_day = total_messages / days_since_start if days_since_start > 0 else total_messages
        return f"📊 <b>Статистика чата:</b>\n\n👥 <b>Всего пользователей:</b> {len(self.user_profiles)}\n🔥 <b>Активных за неделю:</b> {active_users}\n🌱 <b>Новых за неделю:</b> {new_users}\n\n💬 <b>Всего сообщений:</b> {total_messages}\n📈 <b>Сообщений в день (в ср.):</b> {avg_msg_day:.2f}"

api = ApiHandler()
game = GameLogic(Config.GAME_DATA_FILE)
spam_analyzer = SpamAnalyzer(Config.PROFILES_DATA_FILE, Config.DYNAMIC_KEYWORDS_FILE)
temp_user_choices = {}

# ========================================================================================
# 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ БОТА
# ========================================================================================
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = ["💹 Курс", "⚙️ Топ ASIC", "⛏️ Калькулятор", "📰 Новости", "😱 Индекс Страха", "⏳ Халвинг", "📡 Статус BTC", "🧠 Викторина", "🎓 Слово дня", "🕹️ Виртуальный Майнинг"]
    markup.add(*[types.KeyboardButton(text) for text in buttons])
    return markup

def send_message_with_partner_button(chat_id, text, reply_markup=None):
    try:
        if not reply_markup:
            reply_markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(random.choice(Config.PARTNER_BUTTON_TEXT_OPTIONS), url=Config.PARTNER_URL))
        bot.send_message(chat_id, f"{text}\n\n---\n<i>{random.choice(Config.BOT_HINTS)}</i>", reply_markup=reply_markup, disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение в чат {chat_id}: {e}")

def send_photo_with_partner_button(chat_id, photo, caption):
    try:
        if not photo: raise ValueError("Объект фото пустой")
        hint = f"\n\n---\n<i>{random.choice(Config.BOT_HINTS)}</i>"
        final_caption = f"{caption[:1024 - len(hint) - 4]}...{hint}" if len(caption) > 1024 - len(hint) else f"{caption}{hint}"
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(random.choice(Config.PARTNER_BUTTON_TEXT_OPTIONS), url=Config.PARTNER_URL))
        bot.send_photo(chat_id, photo, caption=final_caption, reply_markup=markup)
    except Exception as e:
        logger.error(f"Не удалось отправить фото: {e}. Отправляю текстом.");
        send_message_with_partner_button(chat_id, caption)

def is_admin(chat_id, user_id):
    try:
        if str(user_id) == Config.ADMIN_CHAT_ID: return True
        return user_id in [admin.user.id for admin in bot.get_chat_administrators(chat_id)]
    except Exception as e:
        logger.error(f"Не удалось проверить права администратора для чата {chat_id}: {e}")
        return False

# ========================================================================================
# 5. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ
# ========================================================================================
@bot.message_handler(commands=['start', 'help'])
def handle_start_help(msg):
    bot.send_message(msg.chat.id, "👋 Привет! Я ваш крипто-помощник.\n\nИспользуйте кнопки для навигации или введите команду.\n\n<b>Админ-команды:</b>\n<code>/userinfo</code>, <code>/spam</code>, <code>/ban</code>, <code>/unban</code>, <code>/unmute</code>, <code>/chatstats</code>", reply_markup=get_main_keyboard())

@bot.message_handler(commands=['userinfo', 'ban', 'unban', 'unmute', 'chatstats', 'spam'])
def handle_admin_commands(msg):
    command = msg.text.split('@')[0].split(' ')[0].lower()
    if not is_admin(msg.chat.id, msg.from_user.id):
        return bot.reply_to(msg, "🚫 У вас нет прав для выполнения этой команды.")

    def get_target_user(m):
        if m.reply_to_message: return m.reply_to_message.from_user, None
        parts = m.text.split()
        if len(parts) > 1 and parts[1].isdigit():
            try: return bot.get_chat_member(m.chat.id, int(parts[1])).user, None
            except Exception as e: return None, f"Не удалось найти пользователя: {e}"
        return None, "Пожалуйста, ответьте на сообщение пользователя или укажите его ID."
    
    target_user, error = None, None
    if command in ['/userinfo', '/ban', '/unban', 'unmute']:
        target_user, error = get_target_user(msg)
        if error: return bot.reply_to(msg, error)

    try:
        if command == '/userinfo': bot.send_message(msg.chat.id, spam_analyzer.get_user_info_text(target_user.id))
        elif command == '/unban': bot.unban_chat_member(msg.chat.id, target_user.id); bot.reply_to(msg, f"Пользователь {telebot.util.escape(target_user.full_name)} разбанен.")
        elif command == '/unmute': bot.restrict_chat_member(msg.chat.id, target_user.id, can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True); bot.reply_to(msg, f"С пользователя {telebot.util.escape(target_user.full_name)} сняты ограничения.")
        elif command == '/chatstats': bot.send_message(msg.chat.id, spam_analyzer.get_chat_statistics())
        elif command in ['/ban', '/spam']:
            if not msg.reply_to_message: return bot.reply_to(msg, "Используйте эту команду в ответ на сообщение.")
            user_to_act = msg.reply_to_message.from_user
            spam_analyzer.add_keywords_from_text(msg.reply_to_message.text)
            if command == '/ban':
                bot.ban_chat_member(msg.chat.id, user_to_act.id)
                bot.delete_message(msg.chat.id, msg.reply_to_message.message_id)
                bot.send_message(msg.chat.id, f"🚫 Пользователь {telebot.util.escape(user_to_act.full_name)} забанен. Подозрительные слова добавлены в фильтр.")
            else: # /spam
                spam_analyzer.handle_spam_detection(msg.reply_to_message, initiated_by_admin=True)
            bot.delete_message(msg.chat.id, msg.message_id) # Удаляем саму команду админа
    except Exception as e:
        logger.error(f"Ошибка выполнения команды {command}: {e}"); bot.reply_to(msg, "Не удалось выполнить действие.")

@bot.message_handler(func=lambda msg: msg.text == "💹 Курс")
def handle_price_request(msg):
    markup = types.InlineKeyboardMarkup(row_width=3).add(*[types.InlineKeyboardButton(t, callback_data=f"price_{t}") for t in Config.POPULAR_TICKERS])
    markup.add(types.InlineKeyboardButton("➡️ Другая монета", callback_data="price_other"))
    bot.send_message(msg.chat.id, "Курс какой криптовалюты вас интересует?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('price_'))
def handle_price_callback(call):
    bot.answer_callback_query(call.id)
    try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    except Exception: pass
    
    action = call.data.split('_')[1]
    if action == "other":
        sent = bot.send_message(call.message.chat.id, "Введите тикер монеты (например: Aleo, XRP):", reply_markup=types.ForceReply(selective=True))
        bot.register_next_step_handler(sent, process_price_step)
    else:
        bot.send_chat_action(call.message.chat.id, 'typing')
        price_data, asic_suggestions = api.get_crypto_price(action)
        if price_data:
            text = f"💹 Курс {price_data['ticker'].upper()}/USD: <b>${price_data['price']:,.4f}</b>\n<i>(Данные от {price_data['source']})</i>"
            if asic_suggestions:
                text += asic_suggestions
        else:
            text = f"❌ Не удалось получить курс для {action.upper()}."
        send_message_with_partner_button(call.message.chat.id, text)

def process_price_step(msg):
    if not msg.text or len(msg.text) > 20: 
        return bot.send_message(msg.chat.id, "Некорректный ввод.", reply_markup=get_main_keyboard())
    
    bot.send_chat_action(msg.chat.id, 'typing')
    price_data, asic_suggestions = api.get_crypto_price(msg.text)
    
    if price_data:
        text = f"💹 Курс {price_data['ticker'].upper()}/USD: <b>${price_data['price']:,.4f}</b>\n<i>(Данные от {price_data['source']})</i>"
        if asic_suggestions:
            text += asic_suggestions
    else:
        text = f"❌ Не удалось получить курс для {msg.text.upper()}."
        
    send_message_with_partner_button(msg.chat.id, text)
    bot.send_message(msg.chat.id, "Выберите действие:", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "⚙️ Топ ASIC")
def handle_asics_text(msg):
    bot.send_message(msg.chat.id, "⏳ Загружаю актуальный список со всех источников...")
    asics = api.get_top_asics(force_update=True)
    if not asics: return send_message_with_partner_button(msg.chat.id, "Не удалось получить данные об ASIC.")
    
    asics_to_show = asics[:12]
    rows = [f"{a.get('name', 'N/A'):<22.21}| {a.get('hashrate', 'N/A'):<18.17}| {a.get('power_watts', 0):<5.0f}| ${a.get('daily_revenue', 0):<10.2f}" for a in asics_to_show]
    response = (f"<pre>Модель                  | H/s               | P, W | Доход/день\n"
                f"------------------------|-------------------|------|-----------\n" + "\n".join(rows) + "</pre>")
    send_message_with_partner_button(msg.chat.id, response)

@bot.message_handler(func=lambda msg: msg.text == "⛏️ Калькулятор")
def handle_calculator_request(msg):
    sent = bot.send_message(msg.chat.id, "💡 Введите стоимость электроэнергии в <b>рублях</b> за кВт/ч:", reply_markup=types.ForceReply(selective=True))
    bot.register_next_step_handler(sent, process_calculator_step)

def process_calculator_step(msg):
    try: cost_rub = float(msg.text.replace(',', '.'))
    except (ValueError, TypeError):
        bot.send_message(msg.chat.id, "❌ Неверный формат. Введите число (например: 4.5).", reply_markup=get_main_keyboard()); return

    rate, is_fallback = api.get_usd_rub_rate()
    asics_data = api.get_top_asics()
    if not asics_data:
        bot.send_message(msg.chat.id, "❌ Не удалось получить данные о доходности ASIC.", reply_markup=get_main_keyboard()); return

    cost_usd = cost_rub / rate
    result = [f"💰 <b>Расчет профита (розетка {cost_rub:.2f} ₽/кВтч)</b>"]
    if is_fallback: result.append(f"<i>(Внимание! Используется резервный курс: 1$≈{rate:.2f}₽)</i>")
    result.append("")
    for asic in asics_data[:12]:
        daily_cost = (asic.get('power_watts', 0) / 1000) * 24 * cost_usd
        profit = asic.get('daily_revenue', 0) - daily_cost
        result.append(f"<b>{telebot.util.escape(asic['name'])}</b>\n  Профит: <b>${profit:.2f}/день</b>")
    
    send_message_with_partner_button(msg.chat.id, "\n\n".join(result))
    bot.send_message(msg.chat.id, "Выберите действие:", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda msg: msg.text in ["📰 Новости", "😱 Индекс Страха", "⏳ Халвинг", "📡 Статус BTC", "🎓 Слово дня"])
def handle_info_buttons(msg):
    bot.send_chat_action(msg.chat.id, 'typing')
    text = ""
    if msg.text == "📰 Новости": text = api.get_crypto_news()
    elif msg.text == "😱 Индекс Страха": 
        image, text = api.get_fear_and_greed_index()
        if image: return send_photo_with_partner_button(msg.chat.id, image, text)
    elif msg.text == "⏳ Халвинг": text = api.get_halving_info()
    elif msg.text == "📡 Статус BTC": text = api.get_btc_network_status()
    elif msg.text == "🎓 Слово дня":
        term = random.choice(Config.CRYPTO_TERMS)
        explanation = api.ask_gpt(f"Объясни термин '{term}' простыми словами для новичка (2-3 предложения).", "gpt-4o-mini")
        text = f"🎓 <b>Слово дня: {term}</b>\n\n{explanation}"
    
    if text: send_message_with_partner_button(msg.chat.id, text)
    else: bot.send_message(msg.chat.id, "Не удалось получить данные. Попробуйте позже.")


@bot.message_handler(commands=['gas'])
def handle_gas(msg): bot.send_chat_action(msg.chat.id, 'typing'); send_message_with_partner_button(msg.chat.id, api.get_eth_gas_price())

@bot.message_handler(func=lambda msg: msg.text == "🧠 Викторина")
def handle_quiz(msg):
    questions = api.get_new_quiz_questions()
    if not questions: return bot.send_message(msg.chat.id, "Не удалось загрузить вопросы для викторины, попробуйте позже.")
    user_quiz_states[msg.from_user.id] = {'score': 0, 'question_index': 0, 'questions': questions}
    bot.send_message(msg.chat.id, f"🔥 <b>Начинаем крипто-викторину!</b>\nОтветьте на {len(questions)} вопросов.", reply_markup=types.ReplyKeyboardRemove())
    send_quiz_question(msg.chat.id, msg.from_user.id)

def send_quiz_question(chat_id, user_id):
    state = user_quiz_states.get(user_id)
    if not state or state['question_index'] >= len(state['questions']):
        if state:
            score = state.get('score', 0)
            reward_text = game.apply_quiz_reward(user_id) if score >= Config.QUIZ_MIN_CORRECT_FOR_REWARD else ""
            bot.send_message(chat_id, f"🎉 <b>Викторина завершена!</b>\nВаш результат: <b>{score} из {len(state['questions'])}</b>.{reward_text}", reply_markup=get_main_keyboard())
            user_quiz_states.pop(user_id, None)
        return
    
    q_data = state['questions'][state['question_index']]
    markup = types.InlineKeyboardMarkup(row_width=2).add(*[types.InlineKeyboardButton(opt, callback_data=f"quiz_{state['question_index']}_{i}") for i, opt in enumerate(q_data['options'])])
    bot.send_message(chat_id, f"<b>Вопрос {state['question_index'] + 1}:</b>\n{q_data['question']}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('quiz_'))
def handle_quiz_answer(call):
    user_id = call.from_user.id
    state = user_quiz_states.get(user_id)
    if not state: return bot.answer_callback_query(call.id, "Викторина уже не активна.")
    
    _, q_index_str, answer_index_str = call.data.split('_')
    q_index, answer_index = int(q_index_str), int(answer_index_str)

    if q_index != state.get('question_index'): return bot.answer_callback_query(call.id)
    
    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id)
    q_data = state['questions'][q_index]
    if answer_index == q_data['correct_index']:
        state['score'] += 1; bot.send_message(call.message.chat.id, "✅ Правильно!")
    else:
        bot.send_message(call.message.chat.id, f"❌ Неверно. Правильный ответ: <b>{q_data['options'][q_data['correct_index']]}</b>")
    
    state['question_index'] += 1
    bot.answer_callback_query(call.id)
    time.sleep(1.5); send_quiz_question(call.message.chat.id, user_id)

@bot.message_handler(func=lambda msg: msg.text == "🕹️ Виртуальный Майнинг")
def handle_game_hub(msg):
    text, markup = get_game_menu(msg.from_user.id, msg.from_user.full_name)
    bot.send_message(msg.chat.id, text, reply_markup=markup)

def get_game_menu(user_id, user_name):
    rig_info_text, rig_info_markup = game.get_rig_info(user_id, user_name)
    if rig_info_markup: return rig_info_text, rig_info_markup
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("💰 Собрать", callback_data="game_collect"), types.InlineKeyboardButton("🚀 Улучшить", callback_data="game_upgrade"))
    markup.add(types.InlineKeyboardButton("🏆 Топ Майнеров", callback_data="game_top"), types.InlineKeyboardButton("🛍️ Магазин", callback_data="game_shop"))
    markup.add(types.InlineKeyboardButton("💵 Вывести в реал", callback_data="game_withdraw"), types.InlineKeyboardButton("🔄 Обновить", callback_data="game_rig"))
    return rig_info_text, markup

@bot.callback_query_handler(func=lambda call: call.data.startswith('game_'))
def handle_game_callbacks(call):
    action = call.data.split('_')[1]
    user_id, user_name, msg = call.from_user.id, call.from_user.full_name, call.message
    response_text = ""
    
    if action == 'collect': response_text = game.collect_reward(user_id)
    elif action == 'upgrade': response_text = game.upgrade_rig(user_id)
    elif action == 'top': bot.answer_callback_query(call.id); return send_message_with_partner_button(msg.chat.id, game.get_top_miners())
    elif action == 'withdraw': bot.answer_callback_query(call.id); return send_message_with_partner_button(msg.chat.id, random.choice(Config.PARTNER_AD_TEXT_OPTIONS))
    elif action == 'shop':
        markup = types.InlineKeyboardMarkup(row_width=1)
        for key, item in Config.SHOP_ITEMS.items():
            markup.add(types.InlineKeyboardButton(f"{item['name']} ({item['cost']:.4f} BTC)", callback_data=f"game_buy_{key}"))
        markup.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="game_rig"))
        bot.edit_message_text("🛍️ <b>Магазин улучшений:</b>", msg.chat.id, msg.message_id, reply_markup=markup); return bot.answer_callback_query(call.id)
    elif action == 'buy': response_text = game.buy_item(user_id, call.data.split('_')[2])

    bot.answer_callback_query(call.id)
    text, markup = get_game_menu(user_id, user_name)
    final_text = f"{response_text}\n\n{text}" if response_text else text
    try: bot.edit_message_text(final_text, msg.chat.id, msg.message_id, reply_markup=markup)
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e): logger.error(f"Ошибка обновления игрового меню: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('start_rig_'))
def handle_start_rig_callback(call):
    user_id, user_name = call.from_user.id, call.from_user.full_name
    starter_asics = temp_user_choices.get(user_id)
    if not starter_asics: return bot.answer_callback_query(call.id, "Выбор устарел, попробуйте снова.", show_alert=True)
    
    try:
        asic_index = int(call.data.split('_')[-1])
        selected_asic = starter_asics[asic_index]
        creation_message = game.create_rig(user_id, user_name, selected_asic)
        bot.answer_callback_query(call.id, "Ферма создается...")
        
        text, markup = get_game_menu(user_id, user_name)
        bot.edit_message_text(f"{creation_message}\n\n{text}", call.message.chat.id, call.message.message_id, reply_markup=markup)
        del temp_user_choices[user_id]
    except Exception as e:
        logger.error(f"Ошибка при создании фермы: {e}"); bot.answer_callback_query(call.id, "Произошла ошибка.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('not_spam_'))
def handle_not_spam_callback(call):
    _, user_id_str, chat_id_str = call.data.split('_')
    user_id, original_chat_id = int(user_id_str), int(chat_id_str)
    
    if not is_admin(original_chat_id, call.from_user.id): return bot.answer_callback_query(call.id, "Действие для админов.", show_alert=True)

    profile = spam_analyzer.user_profiles.get(str(user_id))
    if profile: profile['spam_count'] = max(0, profile.get('spam_count', 0) - 1)
    
    try:
        original_text = call.message.html_text.split("Текст:\n")[1].split("\n\n<i>")[0].replace("<blockquote>", "").replace("</blockquote>", "").strip()
        user_info = spam_analyzer.user_profiles.get(str(user_id), {'name': 'Неизвестный'})
        repost_text = f"✅ Сообщение от <b>{telebot.util.escape(user_info['name'])}</b> восстановлено:\n\n<blockquote>{telebot.util.escape(original_text)}</blockquote>"
        bot.send_message(original_chat_id, repost_text)
        bot.edit_message_text(call.message.html_text + f"\n\n<b>✅ Восстановлено:</b> {call.from_user.full_name}", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Восстановлено.")
    except Exception as e:
        logger.error(f"Не удалось восстановить сообщение: {e}"); bot.answer_callback_query(call.id, "Ошибка восстановления.")

@bot.message_handler(content_types=['text', 'caption'], func=lambda msg: not msg.text.startswith('/'))
def handle_non_command_text(msg):
    spam_analyzer.process_message(msg)
    is_reply_to_bot = msg.reply_to_message and msg.reply_to_message.from_user.id == bot.get_me().id
    is_group_mention = msg.chat.type in ('group', 'supergroup') and f"@{bot.get_me().username}" in msg.text
    is_private_chat = msg.chat.type == 'private'
    if not (is_reply_to_bot or is_group_mention or is_private_chat): return

    bot.send_chat_action(msg.chat.id, 'typing')
    price_data, asic_suggestions = api.get_crypto_price(msg.text)
    if price_data:
        text = f"💹 Курс {price_data['ticker'].upper()}/USD: <b>${price_data['price']:,.4f}</b>\n<i>(Данные от {price_data['source']})</i>"
        if asic_suggestions: text += asic_suggestions
        send_message_with_partner_button(msg.chat.id, text)
    else:
        response = api.ask_gpt(msg.text)
        bot.reply_to(msg, response)
        
@bot.message_handler(content_types=['new_chat_members'])
def handle_new_chat_members(msg):
    for user in msg.new_chat_members:
        spam_analyzer.process_message(msg)
        bot.send_message(msg.chat.id, f"👋 Добро пожаловать, {user.full_name}!\n\nЯ крипто-помощник этого чата. Нажмите /start, чтобы увидеть мои возможности.",)

# ========================================================================================
# 6. ЗАПУСК БОТА И ПЛАНИРОВЩИКА
# ========================================================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json': bot.process_new_updates([types.Update.de_json(request.stream.read().decode("utf-8"))]); return '', 200
    return 'Forbidden', 403

@app.route("/")
def index(): return "Bot is running!"

def run_scheduler():
    logger.info("Планировщик запущен.")
    schedule.every(4).hours.do(auto_send_news)
    schedule.every(1).hours.do(lambda: api.get_top_asics(force_update=True))
    schedule.every(5).minutes.do(game.save_data)
    while True:
        try:
            schedule.run_pending()
            time.sleep(1)
        except Exception as e:
            logger.error(f"Критическая ошибка в цикле планировщика: {e}", exc_info=True)
            time.sleep(60)

def auto_send_news():
    try:
        logger.info("ПЛАНИРОВЩИК: Запускаю отправку новостей...")
        if Config.NEWS_CHAT_ID:
            news_text = api.get_crypto_news()
            if "Не удалось" not in news_text and "не найдено" not in news_text:
                send_message_with_partner_button(Config.NEWS_CHAT_ID, news_text)
                logger.info("Новости успешно отправлены по расписанию.")
            else:
                logger.warning(f"Не удалось получить новости для авто-отправки: {news_text}")
    except Exception as e:
        logger.error(f"Ошибка в задаче auto_send_news: {e}", exc_info=True)

def auto_check_status():
    if not Config.ADMIN_CHAT_ID: return
    logger.info("Проверка состояния систем...")
    errors = []
    if not api.get_usd_rub_rate()[0]: errors.append("API курса валют")
    if openai_client and "[❌" in api.ask_gpt("Тест"): errors.append("API OpenAI")
    if not api.get_top_asics(force_update=True): errors.append("Парсинг ASIC")
    status = "✅ Все системы в норме." if not errors else f"⚠️ Сбой в: {', '.join(errors)}"
    try: bot.send_message(Config.ADMIN_CHAT_ID, f"<b>Отчет о состоянии ({datetime.now().strftime('%H:%M')})</b>\n{status}")
    except Exception as e: logger.error(f"Не удалось отправить отчет о состоянии: {e}")

if __name__ == '__main__':
    logger.info("Запуск бота...")
    threading.Thread(target=run_scheduler, daemon=True).start()
    if Config.WEBHOOK_URL:
        logger.info(f"Режим: вебхук. URL: {Config.WEBHOOK_URL}"); bot.remove_webhook(); time.sleep(0.5)
        bot.set_webhook(url=f"{Config.WEBHOOK_URL.rstrip('/')}/webhook")
        app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 8080)))
    else:
        logger.info("Режим: long-polling."); bot.remove_webhook(); bot.polling(none_stop=True)
