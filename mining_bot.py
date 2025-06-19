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
import xml.etree.ElementTree as ET
from flask import Flask, request 
import gspread 
from google.oauth2.service_account import Credentials 
from telebot import types 
from openai import OpenAI 
from datetime import datetime, timedelta 
from bs4 import BeautifulSoup 
import matplotlib 
matplotlib.use('Agg') 
import matplotlib.pyplot as plt 
import io 
import re 
import random 
import logging 
import feedparser 
from dateutil import parser as date_parser 


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
    CRYPTO_API_KEY = os.getenv("CRYPTO_API_KEY") 
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
        "💡 Узнайте курс любой монеты командой `/price`", "⚙️ Посмотрите на самые доходные ASIC", 
        "⛏️ Рассчитайте прибыль с помощью 'Калькулятора'", "📰 Хотите свежие крипто-новости?", 
        "🤑 Попробуйте наш симулятор майнинга!", "😱 Проверьте Индекс Страха и Жадности", 
        "🏆 Сравните себя с лучшими в таблице лидеров", "🎓 Что такое 'HODL'? Узнайте: `/word`", 
        "🧠 Проверьте знания и заработайте в `/quiz`", "🛍️ Загляните в магазин улучшений" 
    ] 
    HALVING_INTERVAL = 210000 

    CRYPTO_TERMS = ["Блокчейн", "Газ (Gas)", "Халвинг", "ICO", "DeFi", "NFT", "Сатоши", "Кит (Whale)", "HODL", "DEX", "Смарт-контракт"] 
    
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
    
    QUIZ_QUESTIONS = [ 
        {"question": "Кто является анонимным создателем Bitcoin?", "options": ["Виталик Бутерин", "Сатоши Накамото", "Чарли Ли", "Илон Маск"], "correct_index": 1}, 
        {"question": "Как называется процесс уменьшения награды за блок в сети Bitcoin в два раза?", "options": ["Форк", "Аирдроп", "Халвинг", "Сжигание"], "correct_index": 2}, 
        {"question": "Какая криптовалюта является второй по рыночной капитализации после Bitcoin?", "options": ["Solana", "Ripple (XRP)", "Cardano", "Ethereum"], "correct_index": 3}, 
        {"question": "Что означает 'HODL' в крипто-сообществе?", "options": ["Продавать при падении", "Держать актив долгосрочно", "Быстрая спекуляция", "Обмен одной монеты на другую"], "correct_index": 1}, 
        {"question": "Как называется самая маленькая неделимая часть Bitcoin?", "options": ["Цент", "Гвей", "Сатоши", "Копейка"], "correct_index": 2}, 
    ] 
    
    SPAM_KEYWORDS = ['p2p', 'арбитраж', 'обмен', 'сигналы', 'обучение', 'заработок', 'инвестиции', 'вложения', 'схема', 'связка'] 
    TECH_QUESTION_KEYWORDS = ['почему', 'как', 'что делать', 'проблема', 'ошибка', 'не работает', 'отваливается', 'перегревается', 'настроить'] 
    TECH_SUBJECT_KEYWORDS = ['asic', 'асик', 'майнер', 'блок питания', 'прошивка', 'хешрейт', 'плата', 'пул'] 
    
    FALLBACK_ASICS = [ 
        {'name': 'Antminer S21', 'hashrate': '200.00 TH/s', 'power_watts': 3550.0, 'daily_revenue': 11.50}, 
        {'name': 'Whatsminer M60S', 'hashrate': '186.00 TH/s', 'power_watts': 3441.0, 'daily_revenue': 10.80}, 
        {'name': 'Antminer S19k Pro', 'hashrate': '120.00 TH/s', 'power_watts': 2760.0, 'daily_revenue': 6.50}, 
    ] 
    
    TICKER_ALIASES = { 
        'бтк': 'BTC', 'биткоин': 'BTC', 'биток': 'BTC', 
        'eth': 'ETH', 'эфир': 'ETH', 'эфириум': 'ETH', 
        'sol': 'SOL', 'солана': 'SOL', 
        'ltc': 'LTC', 'лайткоин': 'LTC', 'лайт': 'LTC', 
        'doge': 'DOGE', 'доги': 'DOGE', 'дог': 'DOGE', 
        'kas': 'KAS', 'каспа': 'KAS' 
    } 
    COINGECKO_MAP = { 
        'BTC': 'bitcoin', 'ETH': 'ethereum', 'LTC': 'litecoin', 
        'DOGE': 'dogecoin', 'KAS': 'kaspa', 'SOL': 'solana' 
    } 
    POPULAR_TICKERS = ['BTC', 'ETH', 'LTC', 'DOGE', 'KAS'] 
    NEWS_RSS_FEEDS = [ 
        "https://forklog.com/feed", 
        "https://cointelegraph.com/rss", 
        "https://bits.media/rss/", 
        "https://www.rbc.ru/crypto/feed" 
    ] 
    
    WARN_LIMIT = 3 
    MUTE_DURATION_HOURS = 24 

 # --- Инициализация клиентов --- 
class ExceptionHandler(telebot.ExceptionHandler): 
    def handle(self, exception): 
        logger.error("Произошла ошибка в обработчике pyTelegramBotAPI:", exc_info=exception) 
        return True 

bot = telebot.TeleBot(Config.BOT_TOKEN, threaded=False, parse_mode='HTML', exception_handler=ExceptionHandler()) 
app = Flask(__name__) 

try: 
    if Config.OPENAI_API_KEY: 
        openai_client = OpenAI(api_key=Config.OPENAI_API_KEY, http_client=httpx.Client()) 
    else: 
        openai_client = None 
        logger.warning("OPENAI_API_KEY не найден. Функциональность GPT будет отключена.") 
except Exception as e: 
    openai_client = None 
    logger.critical(f"Не удалось инициализировать клиент OpenAI: {e}", exc_info=True) 

user_quiz_states = {} 

 # ======================================================================================== 
 # 2. КЛАССЫ ЛОГИКИ (API, ИГРА, АНТИСПАМ) 
 # ======================================================================================== 
class ApiHandler: 
    def __init__(self): 
        self.asic_cache = self._load_asic_cache_from_file() 
        self.currency_cache = {"rate": None, "timestamp": None} 
        atexit.register(self._save_asic_cache_to_file) 

    def _make_request(self, url, timeout=15, is_json=True): 
        """Централизованный и надежный метод для выполнения GET-запросов.""" 
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
        }
        try: 
            response = requests.get(url, headers=headers, timeout=timeout) 
            response.raise_for_status() 
            return response.json() if is_json else response 
        except (requests.exceptions.RequestException, json.JSONDecodeError) as e: 
            logger.warning(f"Сетевой запрос или декодирование JSON не удалось для {url}: {e}") 
            return None 

    def _load_asic_cache_from_file(self): 
        try: 
            if os.path.exists(Config.ASIC_CACHE_FILE): 
                with open(Config.ASIC_CACHE_FILE, 'r', encoding='utf-8') as f: 
                    cache = json.load(f) 
                    if "timestamp" in cache and cache["timestamp"]: 
                        cache["timestamp"] = datetime.fromisoformat(cache["timestamp"]) 
                        if datetime.now() - cache["timestamp"] > timedelta(hours=24): 
                            logger.warning("Кэш ASIC старше 24 часов, будет проигнорирован.") 
                            return {"data": [], "timestamp": None} 
                    else: 
                        cache["timestamp"] = None 
                    logger.info("Локальный кэш ASIC успешно загружен.") 
                    return cache 
        except json.JSONDecodeError: 
            logger.warning(f"Файл кэша {Config.ASIC_CACHE_FILE} пуст или поврежден. Будет создан новый.") 
        except Exception as e: 
            logger.error(f"Не удалось загрузить локальный кэш ASIC: {e}") 
        return {"data": [], "timestamp": None} 

    def _save_asic_cache_to_file(self): 
        try: 
            with open(Config.ASIC_CACHE_FILE, 'w', encoding='utf-8') as f: 
                cache_to_save = self.asic_cache.copy() 
                if cache_to_save.get("timestamp"): 
                    cache_to_save["timestamp"] = cache_to_save["timestamp"].isoformat() 
                json.dump(cache_to_save, f, indent=4) 
        except Exception as e: 
            logger.error(f"Ошибка при сохранении локального кэша ASIC: {e}") 

    def get_gsheet(self): 
        try: 
            if not Config.GOOGLE_JSON_STR or not Config.GOOGLE_JSON_STR.strip(): return None 
            if not Config.GOOGLE_JSON_STR.strip().startswith('{'): 
                logger.error("Переменная GOOGLE_JSON не является валидным JSON объектом.") 
                return None 
            creds_dict = json.loads(Config.GOOGLE_JSON_STR) 
            creds = Credentials.from_service_account_info(creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets']) 
            return gspread.authorize(creds).open_by_key(Config.SHEET_ID).worksheet(Config.SHEET_NAME) 
        except Exception as e: 
            logger.error(f"Ошибка подключения к Google Sheets: {e}", exc_info=True); return None 

    def log_to_sheet(self, row_data: list): 
        try: 
            sheet = self.get_gsheet() 
            if sheet: sheet.append_row(row_data, value_input_option='USER_ENTERED') 
        except Exception as e: logger.error(f"Ошибка записи в Google Sheets: {e}") 

    def _sanitize_html(self, html_string: str) -> str: 
        soup = BeautifulSoup(html_string, "html.parser") 
        allowed_tags = {'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del', 'a', 'code', 'pre'} 
        for tag in soup.find_all(True): 
            if tag.name not in allowed_tags: 
                tag.unwrap() 
        clean_text = str(soup) 
        clean_text = re.sub(r'</?p>|<br\s*/?>', '\n', clean_text, flags=re.I) 
        return re.sub(r'\n{2,}', '\n\n', clean_text).strip() 

    def ask_gpt(self, prompt: str, model: str = "gpt-4o"): 
        if not openai_client: return "[❌ Ошибка: Клиент OpenAI не инициализирован.]" 
        try: 
            res = openai_client.chat.completions.create(model=model, messages=[{"role": "system", "content": "Ты — полезный ассистент, отвечающий на русском с HTML-тегами: <b>, <i>, <a>, <code>, <pre>."}, {"role": "user", "content": prompt}], timeout=20.0) 
            raw_html = res.choices[0].message.content.strip() 
            return self._sanitize_html(raw_html) 
        except Exception as e: 
            logger.error(f"Ошибка вызова OpenAI API: {e}"); return "[❌ Ошибка GPT.]" 

    def get_crypto_price(self, ticker="BTC"): 
        ticker = ticker.upper() 
        coingecko_id = Config.COINGECKO_MAP.get(ticker) 
        
        sources = [ 
            {"name": "CoinGecko", "url": f"https://api.coingecko.com/api/v3/simple/price?ids={coingecko_id}&vs_currencies=usd", "parser": lambda data: data.get(coingecko_id, {}).get('usd'), "enabled": bool(coingecko_id)}, 
            {"name": "Bybit", "url": f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={ticker}USDT", "parser": lambda data: data.get('result', {}).get('list', [{}])[0].get('lastPrice'), "enabled": True}, 
            {"name": "KuCoin", "url": f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={ticker}-USDT", "parser": lambda data: data.get('data', {}).get('price'), "enabled": True}, 
            {"name": "Binance", "url": f"https://api.binance.com/api/v3/ticker/price?symbol={ticker}USDT", "parser": lambda data: data.get('price'), "enabled": True} 
        ] 

        for source in sources: 
            if not source['enabled']: continue 
            data = self._make_request(source['url'], timeout=4) 
            if data: 
                price_str = source['parser'](data) 
                if price_str: 
                    try: 
                        logger.info(f"Цена для {ticker} успешно получена с {source['name']}.") 
                        return (float(price_str), source['name']) 
                    except (ValueError, TypeError): 
                        logger.warning(f"Не удалось преобразовать цену от {source['name']}: {price_str}") 
                        continue 
        
        logger.error(f"Не удалось получить цену для {ticker} из всех источников.") 
        return (None, None) 

    # ========================================================================================
    # БЛОК ПОЛУЧЕНИЯ ДАННЫХ ОБ ASIC. ВЕРСИЯ 3.0 - МАКСИМАЛЬНАЯ НАДЕЖНОСТЬ
    # ========================================================================================
    def _get_asics_from_minerstat(self): 
        """Источник #1: API от Minerstat."""
        logger.info("Источник #1 (API): Пытаюсь получить данные с minerstat.com...")
        url = "https://api.minerstat.com/v2/hardware" 
        all_hardware = self._make_request(url, is_json=True) 
        if not all_hardware: return None 
        try: 
            asics = []
            for device in all_hardware:
                if not isinstance(device, dict) or device.get("type") != "asic":
                    continue
                best_algo = None
                max_revenue = -1
                for algo_name, algo_data in device.get("algorithms", {}).items():
                    revenue = float(algo_data.get("revenue_in_usd", "0").replace("$", ""))
                    if revenue > max_revenue:
                        max_revenue = revenue
                        best_algo = algo_data
                if best_algo and max_revenue > 0:
                    hashrate_val = float(best_algo.get('speed', 0))
                    if hashrate_val / 1e12 >= 1: hashrate_str = f"{hashrate_val / 1e12:.2f} TH/s"
                    elif hashrate_val / 1e9 >= 1: hashrate_str = f"{hashrate_val / 1e9:.2f} GH/s"
                    else: hashrate_str = f"{hashrate_val / 1e6:.2f} MH/s"
                    asics.append({ 
                        'name': device.get("name", "N/A"), 'hashrate': hashrate_str, 
                        'power_watts': float(best_algo.get("power", 0)), 'daily_revenue': max_revenue
                    })
            if not asics: raise ValueError("Не найдено доходных ASIC в API.") 
            return sorted(asics, key=lambda x: x['daily_revenue'], reverse=True) 
        except Exception as e: 
            logger.warning(f"Ошибка при обработке данных с minerstat.com: {e}"); return None 

    def _get_asics_from_whattomine(self):
        """Источник #2: JSON API от WhatToMine."""
        logger.info("Источник #2 (API): Пытаюсь получить данные с whattomine.com...")
        url = "https://whattomine.com/asics.json"
        data = self._make_request(url, is_json=True)
        if not data or 'asics' not in data: return None
        parsed_asics = []
        try:
            for name, asic_data in data['asics'].items():
                revenue_str = asic_data.get('revenue')
                if not revenue_str: continue
                revenue = float(re.sub(r'[^\d\.]', '', revenue_str))
                if revenue > 0 and asic_data.get('status') == 'Active':
                    parsed_asics.append({
                        'name': name, 'hashrate': f"{asic_data.get('hashrate')} {asic_data.get('algorithm')}",
                        'power_watts': float(asic_data.get('power', 0)), 'daily_revenue': revenue
                    })
            if not parsed_asics: raise ValueError("Не найдено доходных ASIC в API WhatToMine.") 
            return sorted(parsed_asics, key=lambda x: x['daily_revenue'], reverse=True)
        except Exception as e:
            logger.warning(f"Ошибка при обработке данных с whattomine.com: {e}"); return None

    def _get_asics_from_viabtc(self):
        """Источник #3: API от ViaBTC."""
        logger.info("Источник #3 (API): Пытаюсь получить данные с viabtc.com...")
        url = "https://www.viabtc.com/api/v1/tools/miner/revenue?coin=BTC&unit=T"
        response = self._make_request(url, is_json=True)
        if not response or response.get('code') != 0 or not response.get('data'): return None
        parsed_asics = []
        try:
            for miner in response['data']:
                revenue = float(miner.get('revenue_usd', 0))
                if revenue > 0:
                    parsed_asics.append({
                        'name': miner.get('miner_name', 'N/A'),
                        'hashrate': f"{float(miner.get('hashrate', 0)):.2f} TH/s",
                        'power_watts': float(miner.get('power', 0)) * 1000,
                        'daily_revenue': revenue
                    })
            if not parsed_asics: raise ValueError("API ViaBTC не вернул доходных ASIC.")
            return sorted(parsed_asics, key=lambda x: x['daily_revenue'], reverse=True)
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при парсинге API ViaBTC: {e}", exc_info=True); return None
            
    def _get_asics_from_asicminervalue(self): 
        """Источник #4: Парсинг сайта asicminervalue.com."""
        logger.info("Источник #4 (Парсинг): Пытаюсь получить данные с asicminervalue.com...")
        response = self._make_request("https://www.asicminervalue.com", is_json=False) 
        if not response: return None 
        try: 
            soup = BeautifulSoup(response.text, "lxml") 
            parsed_asics = [] 
            rows = soup.select("tbody > tr") 
            if not rows: raise ValueError("Парсинг (AMV): Тег tbody не найден.")
            logger.info(f"Парсинг (AMV): Найдено {len(rows)} строк.") 
            COL_MODEL, COL_HASHRATE, COL_POWER, COL_PROFIT = 0, 2, 3, 6
            for row in rows: 
                cols = row.find_all("td") 
                if len(cols) <= COL_PROFIT: continue 
                try: 
                    name_tag = cols[COL_MODEL].find('a')
                    name = name_tag.get_text(strip=True) if name_tag else cols[COL_MODEL].get_text(strip=True)
                    if not name or name.strip() in ['N/A', '']: continue
                    hashrate_text = cols[COL_HASHRATE].get_text(strip=True) 
                    power_text = cols[COL_POWER].get_text(strip=True) 
                    power_match = re.search(r'([\d,]+)', power_text)
                    if not power_match: continue
                    power_val = float(power_match.group(1).replace(',', ''))
                    full_revenue_text = cols[COL_PROFIT].get_text(strip=True) 
                    revenue_match = re.search(r'(-?)\$?([\d\.]+)', full_revenue_text) 
                    if not revenue_match: continue 
                    sign = -1 if revenue_match.group(1) == '-' else 1 
                    revenue_val = float(revenue_match.group(2)) * sign 
                    if revenue_val > 0: 
                        parsed_asics.append({'name': name.strip(), 'hashrate': hashrate_text, 'power_watts': power_val, 'daily_revenue': revenue_val}) 
                except Exception as e: 
                    logger.warning(f"Парсинг (AMV): ошибка обработки строки: {row.get_text(strip=True, separator='|')} - {e}") 
                    continue 
            if not parsed_asics: raise ValueError("Парсинг (AMV): не удалось извлечь данные ни из одной строки.") 
            return sorted(parsed_asics, key=lambda x: x['daily_revenue'], reverse=True) 
        except Exception as e: 
            logger.error(f"Непредвиденная ошибка при парсинге ASICMinerValue: {e}", exc_info=True); return None 

    def _get_asics_from_hashrate_no(self):
        """Источник #5: Парсинг сайта hashrate.no."""
        logger.info("Источник #5 (Парсинг): Пытаюсь получить данные с hashrate.no...")
        url = "https://www.hashrate.no/asics"
        response = self._make_request(url, is_json=False)
        if not response: return None
        try:
            soup = BeautifulSoup(response.text, 'lxml')
            parsed_asics = []
            table = soup.find('table', id='asic-table')
            if not table: raise ValueError("Парсинг (hashrate.no): Таблица с id='asic-table' не найдена.")
            rows = table.select('tbody tr')
            logger.info(f"Парсинг (hashrate.no): Найдено {len(rows)} строк.")
            for row in rows:
                try:
                    cols = row.find_all('td')
                    if len(cols) < 7: continue
                    name_tag = cols[0].find('a');
                    if not name_tag: continue
                    name = name_tag.get_text(strip=True)
                    hashrate = cols[2].get_text(strip=True)
                    power_str = cols[3].get_text(strip=True)
                    power_val = float(re.search(r'[\d,]+', power_str).group(0).replace(',', ''))
                    revenue_str = cols[5].get_text(strip=True).replace('$', '').replace(',', '')
                    revenue_val = float(revenue_str)
                    if revenue_val > 0:
                        parsed_asics.append({'name': name, 'hashrate': hashrate, 'power_watts': power_val, 'daily_revenue': revenue_val})
                except Exception as e:
                    logger.warning(f"Парсинг (hashrate.no): Ошибка обработки строки: {e}")
                    continue
            if not parsed_asics: raise ValueError("Парсинг (hashrate.no): не удалось извлечь данные.")
            return sorted(parsed_asics, key=lambda x: x['daily_revenue'], reverse=True)
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при парсинге hashrate.no: {e}", exc_info=True); return None

    def _get_asics_from_2cryptocalc(self):
        """Источник #6: API от 2CryptoCalc."""
        logger.info("Источник #6 (API): Пытаюсь получить данные с 2cryptocalc.com...")
        url = "https://2cryptocalc.com/api/v2/miners" # Этот эндпоинт больше не работает
        logger.warning(f"Источник #6 ({url}) больше не действителен и пропускается.")
        return None

    def _get_asics_from_nicehash(self):
        """Источник #7: API от NiceHash."""
        logger.info("Источник #7 (API): Пытаюсь получить данные с NiceHash...")
        url = "https://api2.nicehash.com/main/api/v2/public/profcalc/devices"
        response = self._make_request(url, is_json=True)
        if not response or not response.get('devices'): return None
        parsed_asics = []
        try:
            for device in response['devices']:
                revenue = float(device.get('paying', 0)) * 1000 * 1000 * 1000 # Конвертация из BTC/MH/day в BTC/TH/day
                power = float(device.get('power', 0))
                if revenue > 0:
                    parsed_asics.append({
                        'name': f"NiceHash: {device.get('name', 'N/A')}",
                        'hashrate': f"{device.get('speed')} {device.get('speed_unit')}",
                        'power_watts': power,
                        'daily_revenue': revenue
                    })
            if not parsed_asics: raise ValueError("API NiceHash не вернул доходных ASIC.")
            
            # Нужна конвертация в USD
            btc_price, _ = self.get_crypto_price('BTC')
            if not btc_price: 
                logger.warning("Не удалось получить цену BTC для расчета доходности с NiceHash.")
                return None
            
            for asic in parsed_asics:
                asic['daily_revenue'] *= btc_price

            return sorted(parsed_asics, key=lambda x: x['daily_revenue'], reverse=True)
        except Exception as e:
            logger.error(f"Непредвиденная ошибка при парсинге API NiceHash: {e}", exc_info=True); return None

    def get_top_asics(self, force_update: bool = False): 
        if not force_update and self.asic_cache.get("data") and self.asic_cache.get("timestamp") and (datetime.now() - self.asic_cache.get("timestamp") < timedelta(hours=1)): 
            logger.info("Использую свежие данные из кэша.")
            return self.asic_cache.get("data") 

        asics = None
        source_functions = [
            self._get_asics_from_viabtc,
            self._get_asics_from_minerstat,
            self._get_asics_from_whattomine,
            self._get_asics_from_nicehash,
            self._get_asics_from_hashrate_no,
            self._get_asics_from_asicminervalue,
        ]

        for i, get_asics_func in enumerate(source_functions):
            try:
                asics = get_asics_func()
                if asics:
                    logger.info(f"Данные успешно получены из источника #{i+1} ({get_asics_func.__name__}).")
                    break
                else:
                    logger.warning(f"Источник #{i+1} ({get_asics_func.__name__}) не вернул данные. Переключаюсь на следующий.")
            except Exception as e:
                logger.error(f"Произошла ошибка при вызове источника #{i+1} ({get_asics_func.__name__}): {e}", exc_info=True)
                continue

        if asics: 
            self.asic_cache = {"data": asics[:10], "timestamp": datetime.now()} 
            logger.info(f"Успешно получено и закэшировано {len(self.asic_cache['data'])} ASIC.") 
            self._save_asic_cache_to_file() 
            return self.asic_cache["data"] 
        
        if self.asic_cache.get("data"): 
            logger.warning("Все онлайн-источники недоступны, использую данные из старого кэша.") 
            return self.asic_cache.get("data") 
        
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Все онлайн-источники и кэш недоступны, использую аварийный список ASIC.") 
        return Config.FALLBACK_ASICS 
    
    def get_fear_and_greed_index(self): 
        data = self._make_request("https://api.alternative.me/fng/?limit=1") 
        if not data or 'data' not in data or not data['data']: 
            return None, "[❌ Ошибка при получении индекса]" 
        
        try: 
            value_data = data['data'][0] 
            value, classification = int(value_data['value']), value_data['value_classification'] 
            
            plt.style.use('dark_background'); fig, ax = plt.subplots(figsize=(8, 4.5), subplot_kw={'projection': 'polar'}) 
            ax.set_yticklabels([]); ax.set_xticklabels([]); ax.grid(False); ax.spines['polar'].set_visible(False); ax.set_ylim(0, 1) 
            colors = ['#d94b4b', '#e88452', '#ece36a', '#b7d968', '#73c269'] 
            for i in range(100): ax.barh(1, 0.0314, left=3.14 - (i * 0.0314), height=0.3, color=colors[min(len(colors) - 1, int(i / 25))]) 
            angle = 3.14 - (value * 0.0314) 
            ax.annotate('', xy=(angle, 1), xytext=(0, 0), arrowprops=dict(facecolor='white', shrink=0.05, width=4, headwidth=10)) 
            fig.text(0.5, 0.5, f"{value}", ha='center', va='center', fontsize=48, color='white', weight='bold') 
            fig.text(0.5, 0.35, classification, ha='center', va='center', fontsize=20, color='white') 
            buf = io.BytesIO(); plt.savefig(buf, format='png', dpi=150, transparent=True); buf.seek(0); plt.close(fig) 
            
            prompt = f"Кратко объясни для майнера, как 'Индекс страха и жадности' со значением '{value} ({classification})' влияет на рынок. Не более 2-3 предложений." 
            explanation = self.ask_gpt(prompt) 
            text = f"😱 <b>Индекс страха и жадности: {value} - {classification}</b>\n\n{explanation}" 
            return buf, text 
        except Exception as e: 
            logger.error(f"Ошибка при создании графика индекса страха: {e}", exc_info=True) 
            return None, "[❌ Ошибка при получении индекса]" 

    def get_usd_rub_rate(self):
        if self.currency_cache.get("rate") and (datetime.now() - self.currency_cache.get("timestamp", datetime.min) < timedelta(minutes=30)):
            return self.currency_cache["rate"], False

        # Источник #1: API Центробанка РФ (самый надежный)
        try:
            today = datetime.now().strftime('%d/%m/%Y')
            cbr_url = f"https://www.cbr.ru/scripts/XML_daily.asp?date_req={today}"
            response = self._make_request(cbr_url, is_json=False)
            if response:
                root = ET.fromstring(response.content)
                usd_rate_str = root.find("./Valute[CharCode='USD']/Value").text
                rate = float(usd_rate_str.replace(',', '.'))
                self.currency_cache = {"rate": rate, "timestamp": datetime.now()}
                logger.info(f"Курс USD/RUB получен с cbr.ru: {rate}")
                return rate, False
        except Exception as e:
            logger.warning(f"Источник #1 (cbr.ru) не удался: {e}")

        # Каскад резервных API
        sources = [
            ("https://api.exchangerate.host/latest?base=USD&symbols=RUB", lambda data: data.get('rates', {}).get('RUB')),
            ("https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json", lambda data: data.get('usd', {}).get('rub')),
            ("https://open.er-api.com/v6/latest/USD", lambda data: data.get('rates', {}).get('RUB')),
            ("https://api.frankfurter.app/latest?from=USD&to=RUB", lambda data: data.get('rates', {}).get('RUB')),
            ("https://api.exchangerate-api.com/v4/latest/USD", lambda data: data.get('rates', {}).get('RUB')),
        ]
        
        for i, (url, parser) in enumerate(sources):
            try:
                data = self._make_request(url)
                if not data:
                    logger.warning(f"Источник курса #{i+2} ({url}) не вернул данные.")
                    continue
                rate = parser(data)
                if rate:
                    logger.info(f"Курс USD/RUB получен с источника #{i+2}: {rate}")
                    self.currency_cache = {"rate": float(rate), "timestamp": datetime.now()}
                    return float(rate), False
            except Exception as e:
                logger.error(f"Ошибка при обработке источника курса #{i+2} ({url}): {e}")
                continue

        logger.error("Все онлайн-источники курса валют недоступны. Использую аварийный курс.")
        return 85.0, True # Аварийный курс и флаг, что он аварийный

    def get_halving_info(self): 
        response = self._make_request("https://blockchain.info/q/getblockcount", is_json=False) 
        if not response: return "[❌ Не удалось получить данные о халвинге]" 
        try: 
            current_block = int(response.text) 
            blocks_left = ((current_block // Config.HALVING_INTERVAL) + 1) * Config.HALVING_INTERVAL - current_block 
            if blocks_left <= 0: return "🎉 <b>Халвинг уже произошел!</b>" 
            days, rem_min = divmod(blocks_left * 10, 1440); hours, _ = divmod(rem_min, 60) 
            return f"⏳ <b>До халвинга Bitcoin осталось:</b>\n\n🗓 <b>Дней:</b> <code>{days}</code> | ⏰ <b>Часов:</b> <code>{hours}</code>\n🧱 <b>Блоков до халвинга:</b> <code>{blocks_left:,}</code>" 
        except Exception as e: 
            logger.error(f"Ошибка обработки данных для халвинга: {e}"); return "[❌ Не удалось получить данные о халвинге]" 

    def _get_news_from_cryptopanic(self): 
        if not Config.CRYPTO_API_KEY: return [] 
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={Config.CRYPTO_API_KEY}&public=true" 
        data = self._make_request(url) 
        if not data or 'results' not in data: return [] 
        
        news_items = [] 
        for post in data['results']: 
            try: 
                published_time = date_parser.parse(post.get('created_at')).replace(tzinfo=None) if post.get('created_at') else datetime.utcnow() 
                news_items.append({'title': post.get('title', 'Без заголовка'), 'link': post.get('url', ''), 'published': published_time}) 
            except Exception as e: 
                logger.warning(f"Ошибка парсинга даты для новости CryptoPanic: {e}") 
                continue 
        return news_items 

    def _get_news_from_rss(self, url): 
        try: 
            user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' 
            feed = feedparser.parse(url, agent=user_agent) 
            
            if feed.bozo: logger.warning(f"Лента {url} может быть некорректной (bozo-исключение): {feed.bozo_exception}") 

            news_items = [] 
            for entry in feed.entries: 
                try: 
                    published_time = date_parser.parse(entry.published).replace(tzinfo=None) if hasattr(entry, 'published') else datetime.utcnow() 
                    news_items.append({'title': entry.title, 'link': entry.link, 'published': published_time}) 
                except Exception as e: 
                    logger.warning(f"Ошибка парсинга даты для RSS-новости из {url}: {e}") 
                    continue 
            return news_items 
        except Exception as e: 
            logger.error(f"Не удалось получить новости из {url}: {e}") 
            return [] 

    def get_crypto_news(self): 
        all_news = [] 
        
        logger.info("Запрашиваю новости из RSS-лент...") 
        for url in Config.NEWS_RSS_FEEDS: 
            all_news.extend(self._get_news_from_rss(url)) 

        if len(all_news) < 3 and Config.CRYPTO_API_KEY: 
            logger.info("Из RSS получено мало новостей, пробую CryptoPanic...") 
            all_news.extend(self._get_news_from_cryptopanic()) 

        if not all_news: 
            return "[🧐 Не удалось загрузить новости ни из одного источника.]" 

        all_news.sort(key=lambda x: x['published'], reverse=True) 
        seen_titles = set() 
        unique_news = [] 
        for item in all_news: 
            if item['title'] not in seen_titles: 
                unique_news.append(item) 
                seen_titles.add(item['title']) 

        latest_news = unique_news[:3] 

        items = [] 
        for p in latest_news: 
            summary = self.ask_gpt(f"Сделай очень краткое саммари новости в одно предложение на русском языке: '{p['title']}'", "gpt-4o-mini") 
            clean_summary = summary.replace("[❌ Ошибка GPT.]", p['title']) 
            items.append(f"🔹 <a href=\"{p.get('link', '')}\">{clean_summary}</a>") 
            
        return "📰 <b>Последние крипто-новости:</b>\n\n" + "\n\n".join(items) 
    
    def get_eth_gas_price(self): 
        data = self._make_request("https://ethgas.watch/api/gas") 
        if not data: return "[❌ Не удалось получить данные о газе]" 
        try: 
            return (f"⛽️ <b>Актуальная цена газа (Gwei):</b>\n\n" 
                    f"🐢 <b>Медленно:</b> <code>{data.get('slow', {}).get('gwei', 'N/A')}</code>\n" 
                    f"🚶‍♂️ <b>Средне:</b> <code>{data.get('normal', {}).get('gwei', 'N/A')}</code>\n" 
                    f"🚀 <b>Быстро:</b> <code>{data.get('fast', {}).get('gwei', 'N/A')}</code>\n\n" 
                    f"<i>Данные от ethgas.watch</i>") 
        except Exception as e: 
            logger.error(f"Ошибка обработки данных о газе: {e}"); return "[❌ Не удалось получить данные о газе]" 

    def get_btc_network_status(self): 
        try: 
            session = requests.Session() 
            session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}) 
            
            height_res = session.get("https://mempool.space/api/blocks/tip/height", timeout=5) 
            fees_res = session.get("https://mempool.space/api/v1/fees/recommended", timeout=5) 
            mempool_res = session.get("https://mempool.space/api/mempool", timeout=5) 

            height_res.raise_for_status(); fees_res.raise_for_status(); mempool_res.raise_for_status() 

            height = int(height_res.text) 
            fees = fees_res.json() 
            mempool = mempool_res.json() 

            unconfirmed_txs = mempool.get('count', 'N/A') 
            fastest_fee = fees.get('fastestFee', 'N/A') 
            half_hour_fee = fees.get('halfHourFee', 'N/A') 
            hour_fee = fees.get('hourFee', 'N/A') 
            
            return (f"📡 <b>Статус сети Bitcoin:</b>\n\n" 
                    f"🧱 <b>Текущий блок:</b> <code>{height:,}</code>\n" 
                    f"📈 <b>Неподтвержденные транзакции:</b> <code>{unconfirmed_txs:,}</code>\n\n" 
                    f"💸 <b>Рекомендуемые комиссии (sat/vB):</b>\n" 
                    f"  - 🚀 <b>Высокий приоритет:</b> <code>{fastest_fee}</code>\n" 
                    f"  - 🚶‍♂️ <b>Средний приоритет:</b> <code>{half_hour_fee}</code>\n" 
                    f"  - 🐢 <b>Низкий приоритет:</b> <code>{hour_fee}</code>") 

        except Exception as e: 
            logger.error(f"Ошибка получения статуса сети Bitcoin: {e}") 
            return "[❌ Не удалось получить данные о сети Bitcoin.]" 
    
    def get_new_quiz_questions(self): 
        try: 
            count = min(Config.QUIZ_QUESTIONS_COUNT, len(Config.QUIZ_QUESTIONS)) 
            return random.sample(Config.QUIZ_QUESTIONS, count) 
        except Exception as e: 
            logger.error(f"Не удалось выбрать вопросы для викторины: {e}") 
            return None 


class GameLogic: 
    def __init__(self, data_file): 
        self.data_file = data_file 
        self.user_rigs = self.load_data() 
        atexit.register(self.save_data) 

    def load_data(self): 
        try: 
            if os.path.exists(self.data_file): 
                with open(self.data_file, 'r', encoding='utf-8') as f: 
                    loaded_data = json.load(f) 
                    rigs = {int(uid): data for uid, data in loaded_data.items()} 
                    for rig_data in rigs.values(): 
                        for key, value in rig_data.items(): 
                            if isinstance(value, str) and ('until' in key or 'collected' in key): 
                                try: rig_data[key] = datetime.fromisoformat(value) 
                                except ValueError: rig_data[key] = None 
                    logger.info(f"Данные {len(rigs)} пользователей успешно загружены.") 
                    return rigs 
        except Exception as e: 
            logger.error(f"Не удалось загрузить данные пользователей: {e}", exc_info=True) 
        return {} 

    def save_data(self): 
        try: 
            with open(self.data_file, 'w', encoding='utf-8') as f: 
                data_to_save = json.loads(json.dumps(self.user_rigs, default=str)) 
                json.dump(data_to_save, f, indent=4, ensure_ascii=False) 
        except Exception as e: 
            logger.error(f"Ошибка при сохранении данных пользователей: {e}", exc_info=True) 

    def create_rig(self, user_id, user_name, asic_data): 
        if user_id in self.user_rigs: return "У вас уже есть ферма!" 
        
        btc_price, _ = api.get_crypto_price("BTC") 
        if not btc_price: btc_price = 60000  
        
        self.user_rigs[user_id] = { 
            'last_collected': None, 'balance': 0.0, 'level': 1, 'streak': 0,  
            'name': user_name, 'boost_active_until': None, 
            'asic_model': asic_data['name'], 
            'base_rate': asic_data['daily_revenue'] / btc_price, 
            'overclock_bonus': 0.0, 
            'penalty_multiplier': 1.0 
        } 
        return f"🎉 Поздравляем! Ваша ферма с <b>{asic_data['name']}</b> успешно создана!" 

    def get_rig_info(self, user_id, user_name): 
        rig = self.user_rigs.get(user_id) 
        if not rig: 
            starter_asics = api.get_top_asics() 
            if not starter_asics: 
                return "К сожалению, сейчас не удается получить список оборудования для старта. Попробуйте позже.", None 
            
            markup = types.InlineKeyboardMarkup(row_width=1) 
            choices = random.sample(starter_asics, k=min(3, len(starter_asics))) 
            temp_user_choices[user_id] = choices 
            buttons = [types.InlineKeyboardButton(f"Выбрать {asic['name']}", callback_data=f"start_rig_{i}") for i, asic in enumerate(choices)] 
            markup.add(*buttons) 
            return "Добро пожаловать! Давайте создадим вашу первую виртуальную ферму. Выберите, с какого ASIC вы хотите начать:", markup 
        
        rig['name'] = user_name 

        next_level = rig['level'] + 1 
        upgrade_cost_text = f"Стоимость улучшения: <code>{Config.UPGRADE_COSTS.get(next_level, 'N/A')}</code> BTC." if next_level in Config.UPGRADE_COSTS else "Вы достигли максимального уровня!" 
        
        boost_status = "" 
        boost_until = rig.get('boost_active_until') 
        if boost_until and datetime.now() < boost_until: 
            time_left = boost_until - datetime.now() 
            h, rem = divmod(time_left.seconds, 3600); m, _ = divmod(rem, 60) 
            boost_status = f"⚡️ <b>Буст x2 активен еще: {h}ч {m}м</b>\n" 
        
        base_rate = rig.get('base_rate', 0.0001) 
        overclock_bonus = rig.get('overclock_bonus', 0.0) 
        current_rate = base_rate * (1 + overclock_bonus) * Config.LEVEL_MULTIPLIERS.get(rig['level'], 1) 
        overclock_text = f"(+ {overclock_bonus:.1%})" if overclock_bonus > 0 else "" 

        text = (f"🖥️ <b>Ферма «{telebot.util.escape(rig['name'])}»</b>\n" 
                f"<i>Оборудование: {rig.get('asic_model', 'Стандартное')}</i>\n\n" 
                f"<b>Уровень:</b> {rig['level']}\n" 
                f"<b>Базовая добыча:</b> <code>{current_rate:.8f} BTC/день</code> {overclock_text}\n" 
                f"<b>Баланс:</b> <code>{rig['balance']:.8f}</code> BTC\n" 
                f"<b>Дневная серия:</b> {rig['streak']} 🔥 (бонус <b>+{rig['streak'] * Config.STREAK_BONUS_MULTIPLIER:.0%}</b>)\n" 
                f"{boost_status}\n{upgrade_cost_text}") 
        return text, None 

    def collect_reward(self, user_id): 
        rig = self.user_rigs.get(user_id) 
        if not rig: return "🤔 У вас нет фермы. Начните с <code>/my_rig</code>." 
        
        now = datetime.now() 
        last_collected = rig.get('last_collected') 
        
        if last_collected and (now - last_collected) < timedelta(hours=23, minutes=55): 
            time_left = timedelta(hours=24) - (now - last_collected) 
            h, m = divmod(time_left.seconds, 3600)[0], divmod(time_left.seconds % 3600, 60)[0] 
            return f"Вы уже собирали награду. Попробуйте снова через <b>{h}ч {m}м</b>." 
        
        rig['streak'] = rig['streak'] + 1 if last_collected and (now - last_collected) < timedelta(hours=48) else 1 
        
        base_rate = rig.get('base_rate', 0.0001) 
        overclock_bonus = rig.get('overclock_bonus', 0.0) 
        level_multiplier = Config.LEVEL_MULTIPLIERS.get(rig['level'], 1) 
        base_mined = base_rate * (1 + overclock_bonus) * level_multiplier 

        streak_bonus = base_mined * rig['streak'] * Config.STREAK_BONUS_MULTIPLIER 
        
        boost_until = rig.get('boost_active_until') 
        boost_multiplier = 2 if boost_until and now < boost_until else 1 
        
        total_mined = (base_mined + streak_bonus) * boost_multiplier 
        
        penalty = rig.get('penalty_multiplier', 1.0) 
        total_mined *= penalty 
        penalty_text = "" 
        if penalty < 1.0: 
            penalty_text = f"\n📉 <i>Применен штраф {penalty:.0%} от прошлого события.</i>" 
            rig['penalty_multiplier'] = 1.0 

        rig['balance'] += total_mined 
        rig['last_collected'] = now 

        event_text = "" 
        if random.random() < Config.RANDOM_EVENT_CHANCE: 
            if random.random() < 0.5: 
                bonus_pct = random.randint(5, 15) 
                bonus_amount = total_mined * (bonus_pct / 100) 
                rig['balance'] += bonus_amount 
                event_text = f"\n\n🎉 <b>Событие: Памп курса!</b> Вы получили бонус в размере <b>{bonus_pct}%</b> (+{bonus_amount:.8f} BTC)!" 
            else: 
                penalty_pct = random.randint(10, 25) 
                rig['penalty_multiplier'] = 1 - (penalty_pct / 100) 
                event_text = f"\n\n💥 <b>Событие: Скачок напряжения!</b> Ваша следующая добыча будет снижена на <b>{penalty_pct}%</b>. Будьте осторожны!" 
        
        return (f"✅ Собрано <b>{total_mined:.8f}</b> BTC{' (x2 Буст!)' if boost_multiplier > 1 else ''}!\n" 
                f"  (База: {base_mined:.8f} + Серия: {streak_bonus:.8f}){penalty_text}\n" 
                f"🔥 Ваша серия: <b>{rig['streak']} дней!</b>\n" 
                f"💰 Ваш новый баланс: <code>{rig['balance']:.8f}</code> BTC.{event_text}") 

    def buy_item(self, user_id, item_key): 
        rig = self.user_rigs.get(user_id) 
        if not rig: return "🤔 У вас нет фермы." 
        
        item = Config.SHOP_ITEMS.get(item_key) 
        if not item: return "❌ Такого товара нет." 

        if rig['balance'] < item['cost']: 
            return f"❌ <b>Недостаточно средств.</b> Нужно {item['cost']:.4f} BTC." 

        rig['balance'] -= item['cost'] 
        
        if item_key == 'boost': 
            rig['boost_active_until'] = datetime.now() + timedelta(hours=24) 
            return f"⚡️ <b>Энергетический буст куплен!</b> Ваша добыча удвоена на 24 часа." 
        
        if item_key == 'overclock': 
            if rig.get('overclock_bonus', 0.0) > 0: 
                return "⚙️ У вас уже есть оверклокинг-чип!" 
            rig['overclock_bonus'] = item['effect'] 
            return f"⚙️ <b>Оверклокинг-чип установлен!</b> Ваша базовая добыча навсегда увеличена на {item['effect']:.0%}." 
        
        return "✅ Покупка совершена!" 

    def upgrade_rig(self, user_id): 
        rig = self.user_rigs.get(user_id) 
        if not rig: return "🤔 У вас нет фермы. Начните с <code>/my_rig</code>." 
        
        next_level = rig['level'] + 1 
        cost = Config.UPGRADE_COSTS.get(next_level) 
        if not cost: return "🎉 Поздравляем, у вас максимальный уровень фермы!" 
        
        if rig['balance'] >= cost: 
            rig['balance'] -= cost; rig['level'] = next_level 
            return f"🚀 <b>Улучшение завершено!</b>\n\nВаша ферма достигла <b>{next_level}</b> уровня!" 
        else: 
            return f"❌ <b>Недостаточно средств.</b>" 
            
    def get_top_miners(self): 
        if not self.user_rigs: return "Пока нет ни одного майнера для составления топа." 
        sorted_rigs = sorted(self.user_rigs.values(), key=lambda r: r.get('balance', 0), reverse=True) 
        response = ["🏆 <b>Топ-5 Виртуальных Майнеров:</b>\n"] 
        for i, rig in enumerate(sorted_rigs[:5]): 
            response.append(f"<b>{i+1}.</b> {telebot.util.escape(rig.get('name','N/A'))} - <code>{rig.get('balance',0):.6f}</code> BTC (Ур. {rig.get('level',1)})") 
        return "\n".join(response) 
        
    def apply_quiz_reward(self, user_id): 
        if user_id in self.user_rigs: 
            self.user_rigs[user_id]['balance'] += Config.QUIZ_REWARD 
            return f"\n\n🎁 За отличный результат вам начислено <b>{Config.QUIZ_REWARD:.4f} BTC!</b>" 
        return f"\n\n🎁 Вы бы получили <b>{Config.QUIZ_REWARD:.4f} BTC</b>, если бы у вас была ферма! Начните с <code>/my_rig</code>." 

class SpamAnalyzer: 
    def __init__(self, profiles_file, keywords_file): 
        self.profiles_file = profiles_file 
        self.keywords_file = keywords_file 
        self.user_profiles = self._load_json_file(self.profiles_file, is_profiles=True) 
        self.dynamic_keywords = self._load_json_file(self.keywords_file) 
        atexit.register(self.save_all_data) 

    def _load_json_file(self, file_path, is_profiles=False): 
        try: 
            if os.path.exists(file_path): 
                with open(file_path, 'r', encoding='utf-8') as f: 
                    data = json.load(f) 
                    return {int(k): v for k, v in data.items()} if is_profiles else data 
        except (json.JSONDecodeError, TypeError) as e: 
            logger.error(f"Файл {file_path} поврежден или пуст. Создается новый. Ошибка: {e}") 
        except Exception as e: 
            logger.error(f"Не удалось загрузить файл {file_path}: {e}") 
        return {} if is_profiles else [] 

    def save_all_data(self): 
        try: 
            with open(self.profiles_file, 'w', encoding='utf-8') as f: 
                json.dump(self.user_profiles, f, indent=4, ensure_ascii=False) 
        except Exception as e: 
            logger.error(f"Ошибка при сохранении профилей пользователей: {e}") 
        
        try: 
            with open(self.keywords_file, 'w', encoding='utf-8') as f: 
                json.dump(self.dynamic_keywords, f, indent=4, ensure_ascii=False) 
        except Exception as e: 
            logger.error(f"Ошибка при сохранении динамических ключевых слов: {e}") 

    def add_keywords_from_text(self, text): 
        if not text: return 
        words = re.findall(r'\b\w{5,}\b', text.lower()) 
        new_keywords = {word for word in words if not word.isdigit()} 
        
        added_count = 0 
        for keyword in new_keywords: 
            if keyword not in Config.SPAM_KEYWORDS and keyword not in self.dynamic_keywords: 
                self.dynamic_keywords.append(keyword) 
                added_count += 1 
        
        if added_count > 0: 
            logger.info(f"Добавлено {added_count} новых ключевых слов в динамический фильтр.") 
            self.save_all_data() 

    def process_message(self, msg: types.Message): 
        user = msg.from_user 
        text = msg.text or "" 
        
        profile = self.user_profiles.setdefault(user.id, { 
            'user_id': user.id, 'name': user.full_name, 'username': user.username, 
            'first_msg': datetime.utcnow().isoformat(), 'msg_count': 0, 'spam_count': 0, 
        }) 
        profile.update({'msg_count': profile.get('msg_count', 0) + 1, 'name': user.full_name, 'username': user.username, 'last_seen': datetime.utcnow().isoformat()}) 

        text_lower = text.lower() 
        all_keywords = Config.SPAM_KEYWORDS + self.dynamic_keywords 
        if any(keyword in text_lower for keyword in all_keywords): 
            self.handle_spam_detection(msg) 

    def handle_spam_detection(self, msg: types.Message):
        user = msg.from_user
        profile = self.user_profiles.get(user.id)
        if not profile: return

        original_text = msg.text or msg.caption or "[Сообщение без текста]"

        profile['spam_count'] = profile.get('spam_count', 0) + 1
        logger.warning(f"Обнаружено спам-сообщение от {user.full_name} ({user.id}). Счетчик спама: {profile['spam_count']}")

        try:
            bot.delete_message(msg.chat.id, msg.message_id)
        except Exception as e:
            logger.error(f"Не удалось удалить спам-сообщение: {e}")

        # Создаем кнопку для отмены действия
        markup = types.InlineKeyboardMarkup()
        callback_data = f"not_spam_{user.id}_{msg.chat.id}"
        markup.add(types.InlineKeyboardButton("✅ Не спам", callback_data=callback_data))

        # Отправляем лог администратору с кнопкой отмены
        if Config.ADMIN_CHAT_ID:
            try:
                admin_text = (f"❗️<b>Обнаружен возможный спам</b>\n\n"
                              f"<b>Пользователь:</b> {telebot.util.escape(user.full_name)} (<code>{user.id}</code>)\n"
                              f"<b>Чат ID:</b> <code>{msg.chat.id}</code>\n"
                              f"<b>Сообщение удалено.</b>\n\n"
                              f"<b>Текст:</b>\n<blockquote>{telebot.util.escape(original_text)}</blockquote>\n\n"
                              f"<i>Если это ошибка, нажмите кнопку ниже, чтобы восстановить сообщение и снять предупреждение.</i>")
                bot.send_message(Config.ADMIN_CHAT_ID, admin_text, reply_markup=markup)
            except Exception as e:
                logger.error(f"Не удалось отправить лог администратору: {e}")

        # Применяем наказание (мьют) или выводим предупреждение в чат
        if profile['spam_count'] >= Config.WARN_LIMIT:
            try:
                mute_until = datetime.now() + timedelta(hours=Config.MUTE_DURATION_HOURS)
                bot.restrict_chat_member(msg.chat.id, user.id, until_date=int(mute_until.timestamp()))
                bot.send_message(msg.chat.id, f"❗️ Пользователь {telebot.util.escape(user.full_name)} получил слишком много предупреждений и временно ограничен в отправке сообщений на {Config.MUTE_DURATION_HOURS} часов.")
                profile['spam_count'] = 0  # Сбрасываем счетчик после мьюта
            except Exception as e:
                logger.error(f"Не удалось выдать мьют пользователю {user.id}: {e}")
        else:
            remaining_warns = Config.WARN_LIMIT - profile['spam_count']
            bot.send_message(msg.chat.id, f"⚠️ Предупреждение для {telebot.util.escape(user.full_name)}! Ваше сообщение похоже на спам. Осталось предупреждений до мьюта: <b>{remaining_warns}</b>.\n\n<i>Если это ошибка, обратитесь к администратору.</i>")

    def get_user_info_text(self, user_id: int) -> str: 
        profile = self.user_profiles.get(user_id) 
        if not profile: 
            return "🔹 Информация о пользователе не найдена. Возможно, он еще ничего не писал." 
        
        spam_factor = (profile.get('spam_count', 0) / profile.get('msg_count', 1) * 100) 
        
        return (f"ℹ️ <b>Информация о пользователе</b>\n\n" 
                f"👤 <b>ID:</b> <code>{profile['user_id']}</code>\n" 
                f"🔖 <b>Имя:</b> {telebot.util.escape(profile.get('name', 'N/A'))}\n" 
                f"🌐 <b>Юзернейм:</b> @{profile.get('username', 'N/A')}\n\n" 
                f"💬 <b>Всего сообщений:</b> {profile.get('msg_count', 0)}\n" 
                f"🚨 <b>Предупреждений:</b> {profile.get('spam_count', 0)} (из {Config.WARN_LIMIT})\n" 
                f"📈 <b>Спам-фактор:</b> {spam_factor:.2f}%\n\n" 
                f"🗓️ <b>Первое сообщение:</b> {datetime.fromisoformat(profile['first_msg']).strftime('%d %b %Y, %H:%M') if profile.get('first_msg') else 'N/A'}\n" 
                f"👀 <b>Последняя активность:</b> {datetime.fromisoformat(profile['last_seen']).strftime('%d %b %Y, %H:%M') if profile.get('last_seen') else 'N/A'}") 
    
    def get_chat_statistics(self, days=7): 
        now = datetime.utcnow() 
        week_ago = now - timedelta(days=days) 
        total_users = len(self.user_profiles) 
        total_messages = sum(p.get('msg_count', 0) for p in self.user_profiles.values()) 

        active_users = 0; new_users = 0 
        
        for profile in self.user_profiles.values(): 
            if profile.get('last_seen') and datetime.fromisoformat(profile['last_seen']) > week_ago: 
                active_users += 1 
            if profile.get('first_msg') and datetime.fromisoformat(profile['first_msg']) > week_ago: 
                new_users += 1 
        
        if not self.user_profiles: return "📊 <b>Статистика чата:</b>\n\nПока не собрано данных." 

        first_message_date_str = min((p['first_msg'] for p in self.user_profiles.values() if p.get('first_msg')), default=None) 
        days_since_first_msg = (now - datetime.fromisoformat(first_message_date_str)).days if first_message_date_str else 0 
        avg_messages_per_day = total_messages / days_since_first_msg if days_since_first_msg > 0 else total_messages 

        return (f"📊 <b>Статистика чата:</b>\n\n" 
                f"👥 <b>Всего пользователей:</b> {total_users}\n" 
                f"🔥 <b>Активных за неделю:</b> {active_users}\n" 
                f"🌱 <b>Новых за неделю:</b> {new_users}\n\n" 
                f"💬 <b>Всего сообщений:</b> {total_messages}\n" 
                f"📈 <b>Сообщений в день (в среднем):</b> {avg_messages_per_day:.2f}") 

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
        max_caption_len = 1024 - len(hint) 
        if len(caption) > max_caption_len: 
            caption = caption[:max_caption_len - 3] + "..." 
            
        final_caption = f"{caption}{hint}" 
        
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton(random.choice(Config.PARTNER_BUTTON_TEXT_OPTIONS), url=Config.PARTNER_URL)) 
        bot.send_photo(chat_id, photo, caption=final_caption, reply_markup=markup) 
    except Exception as e:  
        logger.error(f"Не удалось отправить фото: {e}. Отправляю текстом.");  
        send_message_with_partner_button(chat_id, caption) 

def is_admin(chat_id, user_id): 
    try: 
        # Администратор бота в личном чате всегда админ
        if str(chat_id) == Config.ADMIN_CHAT_ID:
            return True
        return user_id in [admin.user.id for admin in bot.get_chat_administrators(chat_id)] 
    except Exception as e: 
        logger.error(f"Не удалось проверить права администратора для чата {chat_id}: {e}") 
        return False 

 # ======================================================================================== 
 # 5. ОБРАБОТЧИКИ КОМАНД И СООБЩЕНИЙ 
 # ======================================================================================== 
@bot.message_handler(commands=['start', 'help']) 
def handle_start_help(msg): 
    bot.send_message(msg.chat.id, "👋 Привет! Я ваш крипто-помощник.\n\n<b>Команды модерации (только для админов):</b>\n<code>/userinfo</code> - информация о пользователе\n<code>/spam</code> - пометить сообщение как спам\n<code>/ban</code> - забанить пользователя\n<code>/unban</code> - разбанить пользователя\n<code>/unmute</code> - снять временный мьют\n<code>/chatstats</code> - статистика по чату", reply_markup=get_main_keyboard()) 

@bot.message_handler(commands=['userinfo', 'ban', 'spam', 'unban', 'unmute', 'chatstats']) 
def handle_admin_commands(msg):
    command_raw = msg.text.split('@')[0].split(' ')[0]
    command = command_raw.lower()

    if not is_admin(msg.chat.id, msg.from_user.id):
        admin_command_descriptions = {
            '/userinfo': 'получения информации о пользователе.',
            '/ban': 'блокировки пользователя в чате.',
            '/spam': 'отметки сообщения как спам и наказания пользователя.',
            '/unban': 'разблокировки пользователя.',
            '/unmute': 'снятия временных ограничений с пользователя.',
            '/chatstats': 'просмотра статистики активности чата.'
        }
        description = admin_command_descriptions.get(command)
        if description:
            bot.reply_to(msg, f"🚫 Вы не можете использовать эту команду. Команда <code>{command}</code> предназначена для администраторов для {description}")
        return

    def get_target_user(message): 
        if message.reply_to_message: return message.reply_to_message.from_user, None 
        try: 
            user_id = int(message.text.split()[1]) 
            return bot.get_chat_member(message.chat.id, user_id).user, None 
        except (IndexError, ValueError): 
            return None, "Пожалуйста, ответьте на сообщение пользователя или укажите его ID." 
        except Exception as e: 
            return None, f"Не удалось найти пользователя: {e}" 

    if command == '/userinfo': 
        target_user, error = get_target_user(msg) 
        if error: return bot.reply_to(msg, error) 
        if target_user: bot.send_message(msg.chat.id, spam_analyzer.get_user_info_text(target_user.id)) 

    elif command == '/unban': 
        target_user, error = get_target_user(msg) 
        if error: return bot.reply_to(msg, error) 
        if target_user: 
            try: 
                bot.unban_chat_member(msg.chat.id, target_user.id) 
                bot.reply_to(msg, f"Пользователь {telebot.util.escape(target_user.full_name)} разбанен.") 
            except Exception as e: logger.error(e); bot.reply_to(msg, "Не удалось разбанить.") 

    elif command == '/unmute': 
        target_user, error = get_target_user(msg) 
        if error: return bot.reply_to(msg, error) 
        if target_user: 
            try: 
                bot.restrict_chat_member(msg.chat.id, target_user.id, can_send_messages=True, can_send_media_messages=True, can_send_other_messages=True, can_add_web_page_previews=True) 
                bot.reply_to(msg, f"С пользователя {telebot.util.escape(target_user.full_name)} сняты временные ограничения.") 
            except Exception as e: logger.error(e); bot.reply_to(msg, "Не удалось снять мьют.") 

    elif command in ['/ban', '/spam']: 
        if not msg.reply_to_message: return bot.reply_to(msg, "Пожалуйста, используйте эту команду в ответ на сообщение.") 
        
        user_to_act = msg.reply_to_message.from_user 
        original_message = msg.reply_to_message 
        
        try: 
            if command == '/ban': 
                spam_analyzer.add_keywords_from_text(original_message.text) 
                bot.ban_chat_member(msg.chat.id, user_to_act.id) 
                bot.delete_message(msg.chat.id, original_message.message_id) 
                bot.send_message(msg.chat.id, f"🚫 Пользователь {telebot.util.escape(user_to_act.full_name)} забанен.\n<i>Причина: Спам. Подозрительные слова из его сообщения добавлены в фильтр.</i>") 
            
            elif command == '/spam': 
                spam_analyzer.handle_spam_detection(original_message) 
                bot.delete_message(msg.chat.id, msg.message_id) 

        except Exception as e: 
            logger.error(f"Не удалось выполнить модерацию: {e}"); bot.reply_to(msg, "Не удалось выполнить действие.") 
            
    elif command == '/chatstats': 
        stats_text = spam_analyzer.get_chat_statistics() 
        bot.send_message(msg.chat.id, stats_text) 

@bot.message_handler(func=lambda msg: msg.text == "💹 Курс", content_types=['text']) 
def handle_price_request(msg): 
    markup = types.InlineKeyboardMarkup(row_width=3) 
    buttons = [types.InlineKeyboardButton(text=ticker, callback_data=f"price_{ticker}") for ticker in Config.POPULAR_TICKERS] 
    markup.add(*buttons) 
    markup.add(types.InlineKeyboardButton(text="➡️ Другая монета", callback_data="price_other")) 
    bot.send_message(msg.chat.id, "Курс какой криптовалюты вас интересует?", reply_markup=markup) 

@bot.callback_query_handler(func=lambda call: call.data.startswith('price_')) 
def handle_price_callback(call): 
    action = call.data.split('_')[1] 
    bot.answer_callback_query(call.id) 
    if action == "other": 
        sent = bot.send_message(call.message.chat.id, "Введите тикер монеты (например: XRP, ADA, TON):", reply_markup=types.ReplyKeyboardRemove()) 
        bot.register_next_step_handler(sent, process_price_step) 
        try: bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None) 
        except Exception: pass 
    else: 
        ticker = action 
        price, source = api.get_crypto_price(ticker) 
        text = f"💹 Курс {ticker.upper()}/USD: <b>${price:,.2f}</b>\n<i>(Данные от {source})</i>" if price else f"❌ Не удалось получить курс для {ticker.upper()}." 
        send_message_with_partner_button(call.message.chat.id, text) 
        bot.send_message(call.message.chat.id, "Выберите действие:", reply_markup=get_main_keyboard()) 


def process_price_step(msg): 
    user_input = msg.text.strip().lower() 
    ticker = Config.TICKER_ALIASES.get(user_input, user_input) 
    
    if not re.match(r'^[a-z0-9]{2,10}$', ticker): 
        text = f"❌ Некорректный ввод: «{msg.text}».\nПожалуйста, введите тикер монеты, например: <b>BTC</b>, <b>ETH</b>, <b>SOL</b>." 
    else: 
        price, source = api.get_crypto_price(ticker) 
        text = f"💹 Курс {ticker.upper()}/USD: <b>${price:,.2f}</b>\n<i>(Данные от {source})</i>" if price else f"❌ Не удалось получить курс для {ticker.upper()}." 
        
    send_message_with_partner_button(msg.chat.id, text) 
    bot.send_message(msg.chat.id, "Выберите действие:", reply_markup=get_main_keyboard()) 

@bot.message_handler(func=lambda msg: msg.text == "⚙️ Топ ASIC", content_types=['text']) 
def handle_asics_text(msg): 
    bot.send_message(msg.chat.id, "⏳ Загружаю актуальный список...") 
    asics = api.get_top_asics() 
    if not asics: return send_message_with_partner_button(msg.chat.id, "Не удалось получить данные об ASIC.") 
    rows = [f"{a['name']:<22.21}| {a['hashrate']:<18.17}| {a['power_watts']:<5.0f}| ${a['daily_revenue']:<10.2f}" for a in asics] 
    response = (f"<pre>Модель                       | H/s                 | P, W | Доход/день\n" 
                f"----------------------|---------------------|------|-----------\n" + "\n".join(rows) + "</pre>") 
    response += f"\n\n{api.ask_gpt('Напиши короткий мотивирующий комментарий (1-2 предложения) для майнинг-чата по списку доходных ASIC.', 'gpt-4o-mini')}" 
    send_message_with_partner_button(msg.chat.id, response) 

@bot.message_handler(func=lambda msg: msg.text == "⛏️ Калькулятор", content_types=['text']) 
def handle_calculator_request(msg): 
    sent = bot.send_message(msg.chat.id, "💡 Введите стоимость электроэнергии в <b>рублях</b> за кВт/ч:", reply_markup=types.ReplyKeyboardRemove()) 
    bot.register_next_step_handler(sent, process_calculator_step) 

def process_calculator_step(msg):
    try:
        cost_rub = float(msg.text.replace(',', '.'))
    except ValueError:
        text = "❌ Неверный формат. Пожалуйста, введите число (например: 4.5 или 5)."
        send_message_with_partner_button(msg.chat.id, text)
        bot.send_message(msg.chat.id, "Выберите действие:", reply_markup=get_main_keyboard())
        return

    rate, is_fallback = api.get_usd_rub_rate()
    
    asics_data = api.get_top_asics()
    if not asics_data:
        text = "❌ Не удалось получить данные о доходности ASIC. Попробуйте позже."
        send_message_with_partner_button(msg.chat.id, text)
        bot.send_message(msg.chat.id, "Выберите действие:", reply_markup=get_main_keyboard())
        return

    cost_usd = cost_rub / rate
    result = [f"💰 <b>Расчет профита (розетка {cost_rub:.2f} ₽/кВтч)</b>"]
    if is_fallback:
        result.append(f"<i>(Внимание! Используется резервный курс: 1 USD ≈ {rate:.2f} RUB)</i>")
    result.append("") # Пустая строка для отступа

    for asic in asics_data:
        daily_cost = (asic['power_watts'] / 1000) * 24 * cost_usd
        profit = asic['daily_revenue'] - daily_cost
        result.append(f"<b>{telebot.util.escape(asic['name'])}</b>\n  Профит: <b>${profit:.2f}/день</b>")
    
    text = "\n\n".join(result)
    send_message_with_partner_button(msg.chat.id, text)
    bot.send_message(msg.chat.id, "Выберите действие:", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "📰 Новости", content_types=['text']) 
def handle_news(msg): bot.send_chat_action(msg.chat.id, 'typing'); send_message_with_partner_button(msg.chat.id, api.get_crypto_news()) 

@bot.message_handler(func=lambda msg: msg.text == "😱 Индекс Страха", content_types=['text']) 
def handle_fear_and_greed(msg): bot.send_message(msg.chat.id, "⏳ Генерирую график индекса..."); image, text = api.get_fear_and_greed_index(); send_photo_with_partner_button(msg.chat.id, image, text) if image else send_message_with_partner_button(msg.chat.id, text) 

@bot.message_handler(func=lambda msg: msg.text == "⏳ Халвинг", content_types=['text']) 
def handle_halving(msg): send_message_with_partner_button(msg.chat.id, api.get_halving_info()) 

@bot.message_handler(func=lambda msg: msg.text == "📡 Статус BTC", content_types=['text']) 
def handle_btc_status(msg): 
    bot.send_message(msg.chat.id, "⏳ Получаю данные о сети Bitcoin...") 
    status_text = api.get_btc_network_status() 
    send_message_with_partner_button(msg.chat.id, status_text) 

@bot.message_handler(commands=['gas']) 
def handle_gas(msg): send_message_with_partner_button(msg.chat.id, api.get_eth_gas_price()) 

@bot.message_handler(func=lambda msg: msg.text == "🎓 Слово дня", content_types=['text']) 
def handle_word_of_the_day(msg): 
    term = random.choice(Config.CRYPTO_TERMS) 
    explanation = api.ask_gpt(f"Объясни термин '{term}' простыми словами для новичка в криптовалютах (2-3 предложения).", "gpt-4o-mini") 
    send_message_with_partner_button(msg.chat.id, f"🎓 <b>Слово дня: {term}</b>\n\n{explanation}") 

@bot.message_handler(func=lambda msg: msg.text == "🧠 Викторина", content_types=['text']) 
def handle_quiz(msg): 
    bot.send_message(msg.chat.id, "⏳ Ищу интересные вопросы для викторины...") 
    questions = Config.QUIZ_QUESTIONS 
    random.shuffle(questions) 
    
    user_quiz_states[msg.from_user.id] = {'score': 0, 'question_index': 0, 'questions': questions[:Config.QUIZ_QUESTIONS_COUNT]} 
    bot.send_message(msg.chat.id, f"🔥 <b>Начинаем крипто-викторину!</b>\nОтветьте на {Config.QUIZ_QUESTIONS_COUNT} вопросов.", reply_markup=types.ReplyKeyboardRemove()) 
    send_quiz_question(msg.from_user.id, msg.from_user.id) 

def send_quiz_question(chat_id, user_id): 
    state = user_quiz_states.get(user_id) 
    if not state: return 
    q_index, questions = state['question_index'], state['questions'] 
    
    if q_index >= len(questions): 
        reward_text = game.apply_quiz_reward(user_id) if state['score'] >= Config.QUIZ_MIN_CORRECT_FOR_REWARD else "" 
        bot.send_message(chat_id, f"🎉 <b>Викторина завершена!</b>\nВаш результат: <b>{state['score']} из {len(questions)}</b>.{reward_text}", reply_markup=get_main_keyboard()) 
        user_quiz_states.pop(user_id, None) 
        return 
        
    q_data = questions[q_index] 
    markup = types.InlineKeyboardMarkup(row_width=2).add(*[types.InlineKeyboardButton(opt, callback_data=f"quiz_{q_index}_{i}") for i, opt in enumerate(q_data['options'])]) 
    bot.send_message(chat_id, f"<b>Вопрос {q_index + 1}:</b>\n{q_data['question']}", reply_markup=markup) 

@bot.callback_query_handler(func=lambda call: call.data.startswith('quiz_')) 
def handle_quiz_answer(call): 
    user_id = call.from_user.id; state = user_quiz_states.get(user_id) 
    if not state: return bot.answer_callback_query(call.id, "Викторина уже не активна.") 
    
    try: _, q_index_str, answer_index_str = call.data.split('_'); q_index, answer_index = int(q_index_str), int(answer_index_str) 
    except (ValueError, IndexError): return bot.answer_callback_query(call.id, "Ошибка в данных викторины.") 

    if q_index != state.get('question_index'): return bot.answer_callback_query(call.id, "Вы уже ответили.") 
    
    q_data = state['questions'][q_index] 
    bot.edit_message_reply_markup(chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=None) 
    
    if answer_index == q_data['correct_index']: 
        state['score'] += 1; bot.send_message(call.message.chat.id, "✅ Правильно!") 
    else: 
        bot.send_message(call.message.chat.id, f"❌ Неверно. Правильный ответ: <b>{q_data['options'][q_data['correct_index']]}</b>") 
    
    state['question_index'] += 1; time.sleep(1.5); send_quiz_question(call.message.chat.id, user_id) 
    bot.answer_callback_query(call.id) 

@bot.message_handler(func=lambda msg: msg.text == "🕹️ Виртуальный Майнинг") 
def handle_game_hub(msg): 
    text, markup = get_game_menu(msg.from_user.id, msg.from_user.full_name) 
    bot.send_message(msg.chat.id, text, reply_markup=markup) 

def get_game_menu(user_id, user_name): 
    rig_info_text, rig_info_markup = game.get_rig_info(user_id, user_name) 
    if rig_info_markup: return rig_info_text, rig_info_markup 
    
    markup = types.InlineKeyboardMarkup(row_width=2) 
    buttons = [types.InlineKeyboardButton("💰 Собрать", callback_data="game_collect"), types.InlineKeyboardButton("🚀 Улучшить", callback_data="game_upgrade"), types.InlineKeyboardButton("🏆 Топ Майнеров", callback_data="game_top"), types.InlineKeyboardButton("🛍️ Магазин", callback_data="game_shop"), types.InlineKeyboardButton("💵 Вывести в реал", callback_data="game_withdraw"), types.InlineKeyboardButton("🔄 Обновить", callback_data="game_rig")] 
    markup.add(*buttons) 
    return rig_info_text, markup 

@bot.callback_query_handler(func=lambda call: call.data.startswith('game_')) 
def handle_game_callbacks(call): 
    action = call.data.split('_')[1] 
    user_id = call.from_user.id; user_name = call.from_user.full_name; message = call.message 
    response_text = "" 
    
    if action == 'collect': response_text = game.collect_reward(user_id) 
    elif action == 'upgrade': response_text = game.upgrade_rig(user_id) 
    elif action == 'top': response_text = game.get_top_miners(); bot.answer_callback_query(call.id); return send_message_with_partner_button(message.chat.id, response_text) 
    elif action == 'shop': 
        markup = types.InlineKeyboardMarkup(row_width=1) 
        for key, item in Config.SHOP_ITEMS.items(): 
            markup.add(types.InlineKeyboardButton(f"{item['name']} ({item['cost']:.4f} BTC)", callback_data=f"game_buy_{key}")) 
        markup.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="game_rig")) 
        bot.edit_message_text("🛍️ <b>Магазин улучшений:</b>", message.chat.id, message.message_id, reply_markup=markup) 
        bot.answer_callback_query(call.id); return 
    elif action == 'buy': 
        item_key = call.data.split('_')[2] 
        response_text = game.buy_item(user_id, item_key) 
    elif action == 'withdraw': 
        response_text = f"{random.choice(Config.PARTNER_AD_TEXT_OPTIONS)}" 
        bot.answer_callback_query(call.id); return send_message_with_partner_button(message.chat.id, response_text) 
    
    bot.answer_callback_query(call.id) 
    text, markup = get_game_menu(user_id, user_name) 
    final_text = f"{response_text}\n\n{text}" if response_text else text 
    try: bot.edit_message_text(final_text, message.chat.id, message.message_id, reply_markup=markup) 
    except telebot.apihelper.ApiTelegramException as e: 
        if "message is not modified" not in str(e): logger.error(f"Ошибка при обновлении игрового меню: {e}") 

@bot.callback_query_handler(func=lambda call: call.data.startswith('start_rig_')) 
def handle_start_rig_callback(call): 
    try: 
        user_id, user_name = call.from_user.id, call.from_user.full_name 
        starter_asics = temp_user_choices.get(user_id) 
        if not starter_asics: 
            starter_asics = api.get_top_asics() 
            if not starter_asics: return bot.answer_callback_query(call.id, "Ошибка: не удалось получить список ASIC.", show_alert=True) 
        
        asic_index = int(call.data.split('_')[-1]) 
        selected_asic = starter_asics[asic_index] 

        creation_message = game.create_rig(user_id, user_name, selected_asic) 
        bot.answer_callback_query(call.id, "Ферма создается...") 
        
        text, markup = get_game_menu(user_id, user_name) 
        bot.edit_message_text(f"{creation_message}\n\n{text}", call.message.chat.id, call.message.message_id, reply_markup=markup) 
        if user_id in temp_user_choices: del temp_user_choices[user_id] 
    except Exception as e: 
        logger.error(f"Критическая ошибка при создании фермы: {e}", exc_info=True) 
        bot.answer_callback_query(call.id, "Произошла критическая ошибка.", show_alert=True) 

@bot.callback_query_handler(func=lambda call: call.data.startswith('not_spam_'))
def handle_not_spam_callback(call):
    try:
        _, user_id_str, chat_id_str = call.data.split('_')
        user_id = int(user_id_str)
        original_chat_id = int(chat_id_str)
    except Exception as e:
        logger.error(f"Ошибка парсинга callback_data для not_spam: {e}")
        return bot.answer_callback_query(call.id, "Ошибка данных.", show_alert=True)
    
    # Проверяем, является ли нажавший администратором оригинального чата
    if not is_admin(original_chat_id, call.from_user.id):
        return bot.answer_callback_query(call.id, "Это действие только для администраторов чата.", show_alert=True)

    # Уменьшаем счетчик спама для пользователя
    profile = spam_analyzer.user_profiles.get(user_id)
    if profile:
        profile['spam_count'] = max(0, profile.get('spam_count', 0) - 1)
        logger.info(f"Администратор {call.from_user.full_name} отменил спам-предупреждение для пользователя {user_id}. Новый счетчик: {profile['spam_count']}")
    
    # Извлекаем оригинальный текст из сообщения в логе
    try:
        original_text = call.message.html_text.split("Текст:\n")[1].split("\n\n<i>Если это ошибка")[0]
        original_text = original_text.replace("<blockquote>", "").replace("</blockquote>", "").strip()
    except IndexError:
        original_text = "[Не удалось восстановить текст]"
        logger.error("Не удалось извлечь текст из сообщения лога для восстановления.")

    # Пересылаем восстановленное сообщение в оригинальный чат
    try:
        user_info = spam_analyzer.user_profiles.get(user_id, {'name': 'Неизвестный пользователь'})
        repost_text = f"✅ Сообщение от <b>{telebot.util.escape(user_info['name'])}</b> было восстановлено администратором:\n\n<blockquote>{telebot.util.escape(original_text)}</blockquote>"
        bot.send_message(original_chat_id, repost_text)
    except Exception as e:
        logger.error(f"Не удалось переслать восстановленное сообщение в чат {original_chat_id}: {e}")

    # Обновляем сообщение в логе администратора
    try:
        updated_admin_text = call.message.html_text + f"\n\n<b>✅ Восстановлено администратором:</b> {call.from_user.full_name}"
        bot.edit_message_text(updated_admin_text, call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception as e:
        logger.error(f"Не удалось обновить сообщение в логе администратора: {e}")
    
    bot.answer_callback_query(call.id, "Сообщение восстановлено, предупреждение снято.")

@bot.message_handler(content_types=['text'], func=lambda msg: not msg.text.startswith('/')) 
def handle_non_command_text(msg): 
    spam_analyzer.process_message(msg) 
    
    try: 
        if msg.chat.type in ('group', 'supergroup'): 
            bot_username = f"@{bot.get_me().username}" 
            if not (msg.reply_to_message and msg.reply_to_message.from_user.id == bot.get_me().id) and bot_username not in msg.text: 
                return 

        text_lower = msg.text.lower() 
        if any(kw in text_lower for kw in Config.TECH_QUESTION_KEYWORDS) and any(kw in text_lower for kw in Config.TECH_SUBJECT_KEYWORDS) and '?' in msg.text: 
            handle_technical_question(msg) 
        elif any(w in text_lower for w in ["продам", "купить", "в наличии"]) and any(w in text_lower for w in ["asic", "асик", "whatsminer", "antminer"]): 
            api.log_to_sheet([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg.from_user.username or "N/A", msg.text]) 
            prompt = f"Пользователь прислал объявление в майнинг-чат. Кратко и неформально прокомментируй его, поддержи диалог. Текст: '{msg.text}'" 
            response = api.ask_gpt(prompt) 
            send_message_with_partner_button(msg.chat.id, response) 
        else: 
            bot.send_chat_action(msg.chat.id, 'typing') 
            response = api.ask_gpt(msg.text) 
            send_message_with_partner_button(msg.chat.id, response) 
    except Exception as e: 
        logger.error("Критическая ошибка в handle_other_text!", exc_info=e) 

def handle_technical_question(msg): 
    try: 
        bot.send_chat_action(msg.chat.id, 'typing') 
        prompt = ("Ты — опытный и дружелюбный эксперт в чате по майнингу. " f"Пользователь задал технический вопрос: \"{msg.text}\"\n\n" "Твоя задача — дать полезный, структурированный совет. " "Если точного ответа нет, предложи возможные направления для диагностики проблемы (например, 'проверь блок питания', 'обнови прошивку', 'проверь температуру'). " "Отвечай развернуто, но по делу. Твой ответ должен быть максимально полезным.") 
        response = api.ask_gpt(prompt, "gpt-4o") 
        bot.reply_to(msg, response) 
    except Exception as e: 
        logger.error(f"Ошибка при обработке технического вопроса: {e}") 


 # ======================================================================================== 
 # 6. ЗАПУСК БОТА И ПЛАНИРОВЩИКА 
 # ======================================================================================== 
@app.route('/webhook', methods=['POST']) 
def webhook(): 
    if request.headers.get('content-type') == 'application/json': 
        bot.process_new_updates([telebot.types.Update.de_json(request.stream.read().decode("utf-8"))]) 
        return '', 200 
    return 'Forbidden', 403 

@app.route("/") 
def index(): return "Bot is running!" 

def run_scheduler(): 
    if Config.WEBHOOK_URL: schedule.every(25).minutes.do(lambda: requests.get(Config.WEBHOOK_URL.rsplit('/', 1)[0])) 
    schedule.every(4).hours.do(auto_send_news) 
    schedule.every(6).hours.do(auto_check_status) 
    schedule.every(1).hours.do(api.get_top_asics, force_update=True) 
    schedule.every(5).minutes.do(game.save_data) 
    schedule.every(5).minutes.do(spam_analyzer.save_all_data) 
    
    logger.info("Планировщик запущен.") 
    while True: 
        try: schedule.run_pending(); time.sleep(1) 
        except Exception as e: logger.error(f"Ошибка в планировщике: {e}", exc_info=True) 

def auto_send_news(): 
    if Config.NEWS_CHAT_ID: 
        logger.info("Отправка новостей по расписанию...") 
        news_text = api.get_crypto_news() 
        send_message_with_partner_button(Config.NEWS_CHAT_ID, news_text) 

def auto_check_status(): 
    if not Config.ADMIN_CHAT_ID: return 
    logger.info("Проверка состояния систем...") 
    errors = [] 
    rate, _ = api.get_usd_rub_rate()
    if not rate: errors.append("API курса валют")
    if openai_client and "[❌" in api.ask_gpt("Тест"): errors.append("API OpenAI") 
    if Config.GOOGLE_JSON_STR and not api.get_gsheet(): errors.append("Google Sheets") 
    if not api.get_top_asics(force_update=True): errors.append("Парсинг ASIC") 
    
    status = "✅ Все системы в норме." if not errors else f"⚠️ Сбой в: {', '.join(errors)}" 
    try: bot.send_message(Config.ADMIN_CHAT_ID, f"<b>Отчет о состоянии ({datetime.now().strftime('%H:%M')})</b>\n{status}") 
    except Exception as e: logger.error(f"Не удалось отправить отчет о состоянии администратору: {e}") 

if __name__ == '__main__': 
    logger.info("Запуск бота...") 
    threading.Thread(target=run_scheduler, daemon=True).start() 
    
    if Config.WEBHOOK_URL: 
        logger.info("Режим: вебхук.") 
        bot.remove_webhook() 
        time.sleep(0.5) 
        bot.set_webhook(url=f"{Config.WEBHOOK_URL.rstrip('/')}/webhook") 
        app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 10000))) 
    else: 
        logger.info("Режим: long-polling.") 
        bot.remove_webhook() 
        bot.polling(none_stop=True)
