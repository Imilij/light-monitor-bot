#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot для моніторингу світла з журналом та статистикою
Підтримка декількох користувачів з персональними налаштуваннями
"""

import telebot
import subprocess
import json
import os
import time
import threading
import logging
import traceback
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
import dns.resolver

# ==================== КОНФІГУРАЦІЯ ====================
BOT_TOKEN = "7956450854:AAELUrRz00JlyLdZcLJnyRL5-u4-9kW4sGY"
PING_TIMEOUT = 5
PING_COUNT_AUTO = 5  # Для автомоніторингу
PING_COUNT_MANUAL = 2  # Для ручної перевірки
CHECK_INTERVAL = 60  # 1 хвилина

# DNS сервер Cloudflare
DNS_SERVER = "1.1.1.1"

# Директорії та файли
DATA_DIR = "/root/server/bot/user_data"
USER_LOG_FILE = "/home/bot_logs/user.log"
ERROR_LOG_FILE = "/home/bot_logs/error.log"

# ==================== НАЛАШТУВАННЯ ЛОГУВАННЯ ====================

def setup_logging():
    """Налаштування логування з ротацією файлів"""
    os.makedirs(os.path.dirname(ERROR_LOG_FILE), exist_ok=True)
    
    logger = logging.getLogger('LightMonitorBot')
    logger.setLevel(logging.DEBUG)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    file_handler = RotatingFileHandler(
        ERROR_LOG_FILE,
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()

# ==================== ІНІЦІАЛІЗАЦІЯ ====================
bot = telebot.TeleBot(BOT_TOKEN)

# Глобальні змінні для моніторингу
monitoring_threads = {}
monitoring_active = {}

# ==================== УПРАВЛІННЯ ФАЙЛАМИ ====================

def parse_timestamp(timestamp_str):
    """Парсинг timestamp у різних форматах (для сумісності)"""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S"
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue
    
    logger.warning("Не вдалося розпарсити timestamp: {}".format(timestamp_str))
    return datetime.now()

def get_user_dir(chat_id):
    """Отримати директорію користувача"""
    return os.path.join(DATA_DIR, str(chat_id))

def get_config_file(chat_id):
    """Отримати шлях до конфігу користувача"""
    return os.path.join(get_user_dir(chat_id), "config.json")

def get_log_file(chat_id):
    """Отримати шлях до журналу подій користувача"""
    return os.path.join(get_user_dir(chat_id), "events.json")

def load_config(chat_id):
    """Завантаження налаштувань користувача"""
    config_file = get_config_file(chat_id)
    default_config = {
        'notifications_enabled': True,
        'check_interval': CHECK_INTERVAL,
        'domain': None
    }
    
    try:
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.debug("Завантажено конфіг для chat_id={}: {}".format(chat_id, config))
                return config
    except Exception as e:
        logger.error("Помилка завантаження конфігу для chat_id={}: {}".format(chat_id, e), exc_info=True)
    
    os.makedirs(get_user_dir(chat_id), exist_ok=True)
    save_config(chat_id, default_config)
    return default_config

def save_config(chat_id, config):
    """Збереження налаштувань користувача"""
    try:
        os.makedirs(get_user_dir(chat_id), exist_ok=True)
        config_file = get_config_file(chat_id)
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.debug("Збережено конфіг для chat_id={}: {}".format(chat_id, config))
    except Exception as e:
        logger.error("Помилка збереження конфігу для chat_id={}: {}".format(chat_id, e), exc_info=True)

def load_events(chat_id):
    """Завантаження журналу подій користувача"""
    log_file = get_log_file(chat_id)
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                events = json.load(f)
                logger.debug("Завантажено {} подій для chat_id={}".format(len(events), chat_id))
                return events
    except Exception as e:
        logger.error("Помилка завантаження подій для chat_id={}: {}".format(chat_id, e), exc_info=True)
    return []

def save_event(chat_id, status, details):
    """Збереження події в журнал"""
    try:
        events = load_events(chat_id)
        event = {
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'status': 'on' if status else 'off',
            'details': details
        }
        events.append(event)
        
        if len(events) > 1000:
            events = events[-1000:]
        
        log_file = get_log_file(chat_id)
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(events, f, indent=2, ensure_ascii=False)
        
        logger.info("✅ ЗБЕРЕЖЕНО ПОДІЮ для chat_id={}: status={}, details={}".format(
            chat_id, 'on' if status else 'off', details))
    except Exception as e:
        logger.error("❌ Помилка збереження події для chat_id={}: {}".format(chat_id, e), exc_info=True)

def get_last_status(chat_id):
    """Отримати останній статус"""
    try:
        events = load_events(chat_id)
        if events:
            last_status = events[-1]['status'] == 'on'
            logger.debug("Останній статус для chat_id={}: {}".format(chat_id, last_status))
            return last_status
    except Exception as e:
        logger.error("Помилка отримання останнього статусу для chat_id={}: {}".format(chat_id, e), exc_info=True)
    return None

def log_user_action(chat_id, username, domain, action):
    """Логування дій користувачів (анонімно на сервері)"""
    try:
        os.makedirs(os.path.dirname(USER_LOG_FILE), exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = "{} | ChatID:{} | User:@{} | Domain:{} | Action:{}\n".format(
            timestamp, chat_id, username or "unknown", domain, action
        )
        with open(USER_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        logger.debug("Записано дію користувача: {}".format(action))
    except Exception as e:
        logger.error("Помилка логування дії користувача: {}".format(e), exc_info=True)

# ==================== DNS РЕЗОЛВІНГ ====================

def resolve_domain(domain):
    """Резолвінг домену через Cloudflare DNS 1.1.1.1"""
    try:
        resolver = dns.resolver.Resolver()
        resolver.nameservers = [DNS_SERVER]
        resolver.timeout = 3
        resolver.lifetime = 3
        
        answers = resolver.resolve(domain, 'A')
        if answers:
            ip = str(answers[0])
            logger.debug("Резолвінг {}: IP={}".format(domain, ip))
            return ip
    except Exception as e:
        logger.error("Помилка резолвінгу домену {}: {}".format(domain, e), exc_info=True)
    return None

# ==================== ПІНГУВАННЯ ====================

def ping_host(hostname, timeout=5, count=1):
    """Пінгує хост з множинними пакетами через резолвінг 1.1.1.1"""
    try:
        logger.debug("Початок пінгу домену: {} (пакетів: {})".format(hostname, count))
        
        ip_address = resolve_domain(hostname)
        if not ip_address:
            logger.warning("Не вдалося розв'язати домен: {}".format(hostname))
            return False, "❌ Не вдалося розв'язати домен"
        
        cmd = ['ping', '-c', str(count), '-W', str(timeout), ip_address]
        logger.debug("Виконання команди: {}".format(' '.join(cmd)))
        
        result = subprocess.run(
            cmd,
            timeout=(timeout + 2) * count,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            avg_time = None
            packet_loss = 100
            
            for line in lines:
                if 'packet loss' in line:
                    parts = line.split(',')
                    for part in parts:
                        if 'packet loss' in part:
                            try:
                                packet_loss = int(part.split('%')[0].strip().split()[-1])
                            except:
                                packet_loss = 100
                if 'avg' in line or 'rtt' in line:
                    try:
                        avg_time = line.split('/')[4]
                    except:
                        pass
            
            if packet_loss < 100:
                msg = "✅ Світло ВКЛ (пінг: {}ms, втрата: {}%)".format(avg_time if avg_time else "N/A", packet_loss)
                logger.info("Пінг успішний: {} -> {}".format(hostname, msg))
                return True, msg
            else:
                msg = "❌ Світла немає (100% втрата пакетів)"
                logger.warning("Пінг неуспішний: {} -> {}".format(hostname, msg))
                return False, msg
        else:
            logger.warning("Ping returncode={} для {}".format(result.returncode, hostname))
            return False, "❌ Світла немає"
    except subprocess.TimeoutExpired:
        logger.warning("Timeout при пінгу {}".format(hostname))
        return False, "❌ Світла немає (таймаут)"
    except Exception as e:
        logger.error("Помилка пінгу {}: {}".format(hostname, e), exc_info=True)
        return False, "❌ Помилка: {}".format(str(e))

# ==================== ОБРОБНИКИ ====================

@bot.message_handler(commands=['start'])
def start_handler(message):
    """Стартове меню з запитом домену"""
    chat_id = message.chat.id
    username = message.from_user.username
    logger.info("Команда /start від chat_id={}, username=@{}".format(chat_id, username))
    
    try:
        config = load_config(chat_id)
        
        if not config.get('domain'):
            msg = bot.send_message(
                chat_id,
                "👋 Вітаю! Це бот для моніторингу світла.\n\n"
                "📡 Введіть ваш DDNS домен для моніторингу:"
            )
            bot.register_next_step_handler(msg, process_initial_domain)
            log_user_action(chat_id, username, "none", "START_NEW_USER")
            return
        
        show_main_menu(chat_id, config['domain'])
        start_user_monitoring(chat_id)
        log_user_action(chat_id, username, config['domain'], "START_EXISTING_USER")
    except Exception as e:
        logger.error("Помилка в start_handler для chat_id={}: {}".format(chat_id, e), exc_info=True)
        bot.send_message(chat_id, "❌ Помилка запуску. Спробуйте ще раз.")

def process_initial_domain(message):
    """Обробка першого введення домену"""
    chat_id = message.chat.id
    username = message.from_user.username
    domain = message.text.strip()
    
    logger.info("Початкове налаштування домену для chat_id={}: {}".format(chat_id, domain))
    
    try:
        if not domain or ' ' in domain or '.' not in domain:
            msg = bot.send_message(
                chat_id,
                "❌ Невірний формат домену. Введіть коректний DDNS домен:"
            )
            bot.register_next_step_handler(msg, process_initial_domain)
            return
        
        config = load_config(chat_id)
        config['domain'] = domain
        save_config(chat_id, config)
        
        log_user_action(chat_id, username, domain, "INITIAL_SETUP")
        
        bot.send_message(
            chat_id,
            "✅ Домен `{}` налаштовано!\n\nМоніторинг розпочато.".format(domain),
            parse_mode='Markdown'
        )
        
        show_main_menu(chat_id, domain)
        start_user_monitoring(chat_id)
        
        logger.info("Домен успішно налаштовано для chat_id={}: {}".format(chat_id, domain))
    except Exception as e:
        logger.error("Помилка в process_initial_domain для chat_id={}: {}".format(chat_id, e), exc_info=True)
        bot.send_message(chat_id, "❌ Помилка налаштування. Спробуйте ще раз.")

def show_main_menu(chat_id, domain):
    """Показати головне меню"""
    try:
        markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        btn1 = telebot.types.KeyboardButton('💡 Перевірити')
        btn2 = telebot.types.KeyboardButton('📊 Журнал')
        btn3 = telebot.types.KeyboardButton('📈 Статистика')
        btn4 = telebot.types.KeyboardButton('⚙️ Налаштування')
        markup.add(btn1, btn2, btn3, btn4)
        
        text = "🏠 *Бот моніторингу світла*\n\n"
        text += "Можливості:\n"
        text += "💡 Перевірити - миттєва перевірка\n"
        text += "📊 Журнал - історія подій\n"
        text += "📈 Статистика - аналітика\n"
        text += "⚙️ Налаштування - налаштування\n\n"
        text += "📡 Домен: `{}`\n".format(domain)
        text += "⏱ Інтервал: 1 хв"
        
        bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)
        logger.debug("Показано головне меню для chat_id={}".format(chat_id))
    except Exception as e:
        logger.error("Помилка в show_main_menu для chat_id={}: {}".format(chat_id, e), exc_info=True)

@bot.message_handler(func=lambda m: m.text == '💡 Перевірити')
def check_handler(message):
    """Перевірка світла - 2 пакети"""
    chat_id = message.chat.id
    logger.info("Ручна перевірка від chat_id={}".format(chat_id))
    
    try:
        config = load_config(chat_id)
        
        if not config.get('domain'):
            bot.reply_to(message, "❌ Домен не налаштовано. Введіть /start")
            return
        
        is_on, details = ping_host(config['domain'], PING_TIMEOUT, PING_COUNT_MANUAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        bot.reply_to(message, "{}\n⏰ {}".format(details, timestamp))
        logger.info("Результат ручної перевірки chat_id={}: {}".format(chat_id, details))
    except Exception as e:
        logger.error("Помилка в check_handler для chat_id={}: {}".format(chat_id, e), exc_info=True)
        bot.reply_to(message, "❌ Помилка перевірки. Спробуйте ще раз.")

@bot.message_handler(func=lambda m: m.text == '📊 Журнал')
def journal_handler(message):
    """Показати журнал подій з тривалістю"""
    chat_id = message.chat.id
    logger.info("Запит журналу від chat_id={}".format(chat_id))
    
    try:
        events = load_events(chat_id)
        
        if not events:
            bot.reply_to(message, "📊 Журнал порожній")
            logger.warning("Журнал порожній для chat_id={}".format(chat_id))
            return
        
        recent = events[-30:]
        text = "📊 *Журнал подій (останні 15)*\n\n"
        
        displayed = 0
        for i in range(len(recent) - 1, -1, -1):
            if displayed >= 15:
                break
                
            event = recent[i]
            dt = parse_timestamp(event['timestamp'])
            time_str = dt.strftime("%d.%m %H:%M")
            status_emoji = "🟢" if event['status'] == 'on' else "🔴"
            status_text = "ВКЛ" if event['status'] == 'on' else "ВИМК"
            
            duration_text = ""
            if i > 0:
                prev_event = recent[i - 1]
                prev_dt = parse_timestamp(prev_event['timestamp'])
                duration_minutes = int((dt - prev_dt).total_seconds() / 60)
                
                if event['status'] == 'on' and prev_event['status'] == 'off':
                    hours = duration_minutes // 60
                    mins = duration_minutes % 60
                    if hours > 0:
                        duration_text = " (не було {} год {} хв)".format(hours, mins)
                    else:
                        duration_text = " (не було {} хв)".format(mins)
                elif event['status'] == 'off' and prev_event['status'] == 'on':
                    hours = duration_minutes // 60
                    mins = duration_minutes % 60
                    if hours > 0:
                        duration_text = " (було {} год {} хв)".format(hours, mins)
                    else:
                        duration_text = " (було {} хв)".format(mins)
            
            text += "{} {} *{}*{}\n".format(time_str, status_emoji, status_text, duration_text)
            displayed += 1
        
        bot.send_message(chat_id, text, parse_mode='Markdown')
        logger.info("Надіслано журнал для chat_id={}, подій: {}".format(chat_id, displayed))
    except Exception as e:
        logger.error("Помилка в journal_handler для chat_id={}: {}".format(chat_id, e), exc_info=True)
        bot.reply_to(message, "❌ Помилка завантаження журналу.")

@bot.message_handler(func=lambda m: m.text == '📈 Статистика')
def stats_handler(message):
    """Показати статистику"""
    chat_id = message.chat.id
    logger.info("Запит статистики від chat_id={}".format(chat_id))
    
    try:
        events = load_events(chat_id)
        
        if len(events) < 2:
            bot.reply_to(message, "📈 Недостатньо даних для статистики")
            return
        
        week_ago = datetime.now() - timedelta(days=7)
        week_events = [e for e in events if parse_timestamp(e['timestamp']) > week_ago]
        
        if not week_events:
            bot.reply_to(message, "📈 Немає даних за тиждень")
            return
        
        off_count = sum(1 for e in week_events if e['status'] == 'off')
        total_downtime = 0
        downtimes = []
        
        for i in range(len(week_events) - 1):
            if week_events[i]['status'] == 'off' and week_events[i + 1]['status'] == 'on':
                off_time = parse_timestamp(week_events[i]['timestamp'])
                on_time = parse_timestamp(week_events[i + 1]['timestamp'])
                downtime = (on_time - off_time).total_seconds() / 60
                downtimes.append(downtime)
                total_downtime += downtime
        
        avg_downtime = total_downtime / len(downtimes) if downtimes else 0
        max_downtime = max(downtimes) if downtimes else 0
        
        text = "📈 *Статистика за тиждень*\n\n"
        text += "🔴 Відключень: {}\n".format(off_count)
        text += "⏱ Загальний час: {} год {} хв\n".format(int(total_downtime // 60), int(total_downtime % 60))
        text += "📊 Середня тривалість: {} хв\n".format(int(avg_downtime))
        text += "📉 Найдовше: {} год {} хв".format(int(max_downtime // 60), int(max_downtime % 60))
        
        bot.reply_to(message, text, parse_mode='Markdown')
        logger.info("Надіслано статистику для chat_id={}".format(chat_id))
    except Exception as e:
        logger.error("Помилка в stats_handler для chat_id={}: {}".format(chat_id, e), exc_info=True)
        bot.reply_to(message, "❌ Помилка завантаження статистики.")

@bot.message_handler(func=lambda m: m.text == '⚙️ Налаштування')
def settings_handler(message):
    """Налаштування"""
    chat_id = message.chat.id
    logger.info("Запит налаштувань від chat_id={}".format(chat_id))
    
    try:
        config = load_config(chat_id)
        
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        notif_status = "✅ ВКЛ" if config['notifications_enabled'] else "❌ ВИМК"
        btn1 = telebot.types.InlineKeyboardButton(
            "🔔 Оповіщення: {}".format(notif_status),
            callback_data="toggle_notif"
        )
        btn2 = telebot.types.InlineKeyboardButton("📡 Змінити домен", callback_data="change_domain")
        btn3 = telebot.types.InlineKeyboardButton("🗑 Очистити журнал", callback_data="clear_log")
        btn4 = telebot.types.InlineKeyboardButton("🔄 Статус моніторингу", callback_data="check_monitoring")
        markup.add(btn1)
        markup.add(btn2)
        markup.add(btn3)
        markup.add(btn4)
        
        monitoring_status = "🟢 Активний" if chat_id in monitoring_active and monitoring_active[chat_id] else "🔴 Неактивний"
        
        text = "⚙️ *Налаштування*\n\n"
        text += "🔔 Оповіщення: {}\n".format(notif_status)
        text += "📡 Домен: {}\n".format(config.get('domain', 'не налаштовано'))
        text += "⏱ Інтервал: 1 хв\n"
        text += "🔄 Моніторинг: {}\n".format(monitoring_status)
        text += "📊 Подій у журналі: {}".format(len(load_events(chat_id)))
        
        bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        logger.error("Помилка в settings_handler для chat_id={}: {}".format(chat_id, e), exc_info=True)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    """Обробник кнопок"""
    chat_id = call.message.chat.id
    logger.info("Callback від chat_id={}: {}".format(chat_id, call.data))
    
    try:
        config = load_config(chat_id)
        
        if call.data == "toggle_notif":
            config['notifications_enabled'] = not config['notifications_enabled']
            save_config(chat_id, config)
            status = "✅ увімкнено" if config['notifications_enabled'] else "❌ вимкнено"
            bot.answer_callback_query(call.id, "Оповіщення {}".format(status))
            settings_handler(call.message)
        
        elif call.data == "change_domain":
            msg = bot.send_message(chat_id, "📡 Введіть новий DDNS домен:")
            bot.register_next_step_handler(msg, process_domain_change)
            bot.answer_callback_query(call.id)
        
        elif call.data == "clear_log":
            log_file = get_log_file(chat_id)
            if os.path.exists(log_file):
                os.remove(log_file)
            bot.answer_callback_query(call.id, "✅ Журнал очищено")
            bot.send_message(chat_id, "🗑 Журнал подій очищено")
        
        elif call.data == "check_monitoring":
            is_active = chat_id in monitoring_active and monitoring_active[chat_id]
            is_thread_alive = chat_id in monitoring_threads and monitoring_threads[chat_id].is_alive()
            
            status_msg = "🔄 *Статус моніторингу*\n\n"
            status_msg += "Активний: {}\n".format("✅ Так" if is_active else "❌ Ні")
            status_msg += "Потік живий: {}\n".format("✅ Так" if is_thread_alive else "❌ Ні")
            
            if not is_active or not is_thread_alive:
                status_msg += "\n⚠️ Перезапускаю моніторинг..."
                bot.send_message(chat_id, status_msg, parse_mode='Markdown')
                start_user_monitoring(chat_id)
            else:
                bot.answer_callback_query(call.id, "Моніторинг працює нормально")
            
    except Exception as e:
        logger.error("Помилка в callback_handler для chat_id={}: {}".format(chat_id, e), exc_info=True)

def process_domain_change(message):
    """Обробка зміни домену"""
    chat_id = message.chat.id
    username = message.from_user.username
    domain = message.text.strip()
    
    logger.info("Зміна домену для chat_id={}: {}".format(chat_id, domain))
    
    try:
        if not domain or ' ' in domain or '.' not in domain:
            msg = bot.send_message(chat_id, "❌ Невірний формат домену. Спробуйте ще раз:")
            bot.register_next_step_handler(msg, process_domain_change)
            return
        
        config = load_config(chat_id)
        old_domain = config.get('domain', 'не було')
        config['domain'] = domain
        save_config(chat_id, config)
        
        log_user_action(chat_id, username, domain, "DOMAIN_CHANGE from {}".format(old_domain))
        
        stop_user_monitoring(chat_id)
        start_user_monitoring(chat_id)
        
        bot.send_message(
            chat_id,
            "✅ Домен змінено на `{}`\nМоніторинг перезапущено.".format(domain),
            parse_mode='Markdown'
        )
        logger.info("Домен успішно змінено для chat_id={}: {} -> {}".format(chat_id, old_domain, domain))
    except Exception as e:
        logger.error("Помилка в process_domain_change для chat_id={}: {}".format(chat_id, e), exc_info=True)
        bot.send_message(chat_id, "❌ Помилка зміни домену.")

# ==================== АВТОМОНІТОРИНГ ====================

def monitoring_loop(chat_id):
    """Фоновий моніторинг - 5 пакетів кожну хвилину"""
    logger.info("🚀🚀🚀 ЗАПУЩЕНО моніторинг для chat_id={}".format(chat_id))
    
    try:
        config = load_config(chat_id)
        domain = config.get('domain')
        
        if not domain:
            logger.warning("❌ Домен не налаштований для chat_id={}".format(chat_id))
            return
        
        last_status = get_last_status(chat_id)
        last_event_time = None
        
        logger.info("📌 Початковий статус для chat_id={}: {}".format(chat_id, last_status))
        
        iteration = 0
        while chat_id in monitoring_active and monitoring_active[chat_id]:
            iteration += 1
            try:
                logger.info("🔄 ІТЕРАЦІЯ #{} для chat_id={}".format(iteration, chat_id))
                
                config = load_config(chat_id)
                is_on, details = ping_host(domain, PING_TIMEOUT, PING_COUNT_AUTO)
                
                logger.info("📊 Моніторинг chat_id={}: status={}, details={}".format(chat_id, is_on, details))
                
                if last_status is None:
                    logger.info("🆕 Перша перевірка для chat_id={}: status={}".format(chat_id, is_on))
                    save_event(chat_id, is_on, details)
                    last_status = is_on
                    last_event_time = datetime.now()
                    
                elif last_status != is_on:
                    logger.warning("⚠️⚠️⚠️ ЗМІНА СТАТУСУ для chat_id={}: {} -> {}".format(chat_id, last_status, is_on))
                    save_event(chat_id, is_on, details)
                    
                    if config['notifications_enabled']:
                        timestamp = datetime.now().strftime("%H:%M")
                        
                        duration_text = ""
                        if last_event_time:
                            duration_minutes = int((datetime.now() - last_event_time).total_seconds() / 60)
                            hours = duration_minutes // 60
                            mins = duration_minutes % 60
                            
                            if is_on:
                                if hours > 0:
                                    duration_text = "\n⏱ Не було {} год {} хв".format(hours, mins)
                                else:
                                    duration_text = "\n⏱ Не було {} хв".format(mins)
                            else:
                                if hours > 0:
                                    duration_text = "\n⏱ Було {} год {} хв".format(hours, mins)
                                else:
                                    duration_text = "\n⏱ Було {} хв".format(mins)
                        
                        if is_on:
                            emoji = "🟢"
                            msg = "{} *Світло УВІМКНЕНО*\n⏰ {}{}".format(emoji, timestamp, duration_text)
                        else:
                            emoji = "🔴"
                            msg = "{} *Світло ВИМКНЕНО*\n⏰ {}{}".format(emoji, timestamp, duration_text)
                        
                        try:
                            bot.send_message(chat_id, msg, parse_mode='Markdown')
                            logger.info("✅✅✅ НАДІСЛАНО оповіщення для chat_id={}: {}".format(chat_id, msg.replace('\n', ' ')))
                        except Exception as e:
                            logger.error("❌ Помилка надсилання оповіщення chat_id={}: {}".format(chat_id, e), exc_info=True)
                    else:
                        logger.info("🔕 Оповіщення вимкнені для chat_id={}".format(chat_id))
                    
                    last_status = is_on
                    last_event_time = datetime.now()
                else:
                    logger.debug("➡️ Статус не змінився для chat_id={}: {}".format(chat_id, is_on))
                
                logger.info("💤 Сплю {} секунд до наступної перевірки (chat_id={})".format(config['check_interval'], chat_id))
                time.sleep(config['check_interval'])
                
            except Exception as e:
                logger.error("❌ Помилка в циклі моніторингу для chat_id={}: {}".format(chat_id, e), exc_info=True)
                time.sleep(60)
                
    except Exception as e:
        logger.error("❌❌❌ Критична помилка моніторингу для chat_id={}: {}".format(chat_id, e), exc_info=True)
    finally:
        logger.info("🛑🛑🛑 ЗАВЕРШЕНО моніторинг для chat_id={}".format(chat_id))

def start_user_monitoring(chat_id):
    """Запуск моніторингу для користувача"""
    try:
        if chat_id in monitoring_active and monitoring_active[chat_id]:
            if chat_id in monitoring_threads and monitoring_threads[chat_id].is_alive():
                logger.warning("⚠️ Моніторинг вже активний для chat_id={}".format(chat_id))
                return
        
        monitoring_active[chat_id] = True
        thread = threading.Thread(target=monitoring_loop, args=(chat_id,), daemon=False, name="Monitor-{}".format(chat_id))
        monitoring_threads[chat_id] = thread
        thread.start()
        logger.info("🚀 Моніторинг СТАРТОВАНО для chat_id={}, thread={}".format(chat_id, thread.name))
    except Exception as e:
        logger.error("❌ Помилка запуску моніторингу для chat_id={}: {}".format(chat_id, e), exc_info=True)

def stop_user_monitoring(chat_id):
    """Зупинка моніторингу для користувача"""
    try:
        if chat_id in monitoring_active:
            monitoring_active[chat_id] = False
            if chat_id in monitoring_threads:
                del monitoring_threads[chat_id]
            logger.info("🛑 Моніторинг ЗУПИНЕНО для chat_id={}".format(chat_id))
    except Exception as e:
        logger.error("❌ Помилка зупинки моніторингу для chat_id={}: {}".format(chat_id, e), exc_info=True)

# ==================== ЗАПУСК ====================

def main():
    """Запуск бота"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(os.path.dirname(USER_LOG_FILE), exist_ok=True)
        
        logger.info("="*60)
        logger.info("🤖 Бот запущено")
        logger.info("⏱ Автомоніторинг: {} пакетів кожну хвилину".format(PING_COUNT_AUTO))
        logger.info("💡 Ручна перевірка: {} пакети".format(PING_COUNT_MANUAL))
        logger.info("🌐 DNS сервер: {}".format(DNS_SERVER))
        logger.info("📊 Логи користувачів: {}".format(USER_LOG_FILE))
        logger.info("🔥 Логи помилок: {}".format(ERROR_LOG_FILE))
        logger.info("="*60)
        
        print("🤖 Бот запущено")
        print("⏱ Автомоніторинг: {} пакетів кожну хвилину".format(PING_COUNT_AUTO))
        print("💡 Ручна перевірка: {} пакети".format(PING_COUNT_MANUAL))
        print("🌐 DNS сервер: {}".format(DNS_SERVER))
        print("📊 Логи користувачів: {}".format(USER_LOG_FILE))
        print("🔥 Логи помилок: {}".format(ERROR_LOG_FILE))
        
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except KeyboardInterrupt:
        logger.info("Отримано сигнал зупинки (Ctrl+C)")
        for chat_id in list(monitoring_active.keys()):
            stop_user_monitoring(chat_id)
        print("\n🛑 Бот зупинено")
        logger.info("🛑 Бот зупинено")
    except Exception as e:
        logger.critical("❌ Критична помилка: {}".format(e), exc_info=True)
        print("❌ Критична помилка: {}".format(e))

if __name__ == '__main__':
    main()

