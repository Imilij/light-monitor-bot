#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import telebot
import subprocess
import logging
from datetime import datetime
from typing import Tuple

BOT_TOKEN = "7956450854:AAELUrRz00JlyLdZcLJnyRL5-u4-9kW4sGY"
CHAT_ID = "918294260"

DOMAIN_TO_PING = "imilij.tplinkdns.com"
PING_TIMEOUT = 5

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

light_status = {
    'is_on': None,
    'last_check': None,
    'last_status_change': None,
    'consecutive_failures': 0
}

def ping_host(hostname: str, timeout: int = 5) -> Tuple[bool, str]:
    try:
        cmd = ['ping', '-c', '1', '-W', str(timeout), hostname]
        
        result = subprocess.run(
            cmd,
            timeout=timeout + 2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        if result.returncode == 0:
            lines = result.stdout.split('\\n')
            for line in lines:
                if 'time=' in line:
                    time_ms = line.split('time=')[1].split(' ')[0]
                    return True, f"✅ Світло ВКЛ (пінг: {time_ms}ms)"
            return True, "✅ Світло ВКЛ"
        else:
            return False, "❌ Світла немає (пакет втрачений)"
            
    except subprocess.TimeoutExpired:
        return False, "❌ Світла немає (таймаут відповіді)"
    except FileNotFoundError:
        logger.error("Команда 'ping' не знайдена. Переконайтеся, що ping встановлений.")
        return False, "❌ Помилка: ping не знайдений"
    except Exception as e:
        logger.error(f"Помилка під час пінгування: {e}")
        return False, f"❌ Помилка: {str(e)}"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    button = telebot.types.KeyboardButton('💡 Перевірити світло')
    markup.add(button)
    
    welcome_text = """🏠 *Бот для моніторингу світла вдома*

Натискайте кнопку нижче для перевірки наявності світла\\.

📡 Домен: `{}`
⏱ Таймаут: {} сек""".format(DOMAIN_TO_PING.replace('.', '\\.'), PING_TIMEOUT)
    
    bot.reply_to(message, welcome_text, parse_mode='MarkdownV2', reply_markup=markup)

@bot.message_handler(commands=['status'])
def check_status(message):
    is_on, details = ping_host(DOMAIN_TO_PING, PING_TIMEOUT)
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    response = f"{details}\\n⏰ Перевірено: {timestamp}"
    
    bot.reply_to(message, response, parse_mode='Markdown')
    logger.info(f"Користувач перевірив статус: {response}")

@bot.message_handler(commands=['start_monitoring'])
def start_monitoring(message):
    bot.reply_to(message, "▶️ Моніторинг розпочато...\\n\\nВи будете отримувати повідомлення про зміни статусу світла.")
    logger.info("Моніторинг розпочато користувачем")
    
    monitoring_thread = threading.Thread(
        target=monitoring_loop,
        args=(message.chat.id,),
        daemon=True
    )
    monitoring_thread.start()

@bot.message_handler(commands=['history'])
def show_history(message):
    status_text = "📊 **Статус світла:**\\n\\n"
    status_text += f"Поточний статус: {'✅ ВКЛ' if light_status['is_on'] else '❌ ВИМКНЕНО'}\\n"
    status_text += f"Остання перевірка: {light_status['last_check'] or 'ще не було'}\\n"
    status_text += f"Остання зміна: {light_status['last_status_change'] or 'ще не було'}\\n"
    status_text += f"Послідовні помилки: {light_status['consecutive_failures']}\\n"
    
    bot.reply_to(message, status_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '💡 Перевірити світло')
def handle_check_button(message):
    is_on, details = ping_host(DOMAIN_TO_PING, PING_TIMEOUT)
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    response = f"{details}\\n⏰ Перевірено: {timestamp}"
    
    bot.reply_to(message, response)
    logger.info(f"Користувач перевірив світло: {details}")

@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    bot.reply_to(
        message,
        "Невідома команда. Використовуйте кнопку нижче або /help для допомоги."
    )

def monitoring_loop(chat_id: int):
    logger.info(f"Розпочат моніторинг для chat_id: {chat_id}")
    
    try:
        while True:
            is_on, details = ping_host(DOMAIN_TO_PING, PING_TIMEOUT)
            
            light_status['last_check'] = datetime.now().strftime("%H:%M:%S")
            
            if light_status['is_on'] is None:
                light_status['is_on'] = is_on
                light_status['last_status_change'] = light_status['last_check']
                
                emoji = "🟢" if is_on else "🔴"
                status_msg = "ВКЛ" if is_on else "ВИМКНЕНО"
                message = f"{emoji} Моніторинг активний. Поточний статус: **{status_msg}**\\n{details}"
                bot.send_message(chat_id, message, parse_mode='Markdown')
                
            elif light_status['is_on'] != is_on:
                light_status['is_on'] = is_on
                light_status['last_status_change'] = light_status['last_check']
                light_status['consecutive_failures'] = 0
                
                emoji = "🟢" if is_on else "🔴"
                status_msg = "ВКЛ" if is_on else "ВИМКНЕНО"
                
                alert_message = f"{emoji} **ЗМІНА СТАТУСУ!**\\n"
                alert_message += f"Світло тепер: **{status_msg}**\\n"
                alert_message += f"⏰ Час: {light_status['last_check']}\\n"
                alert_message += f"{details}"
                
                bot.send_message(chat_id, alert_message, parse_mode='Markdown')
                logger.warning(f"Зміна статусу світла: {status_msg}")
                
            else:
                if is_on:
                    light_status['consecutive_failures'] = 0
                else:
                    light_status['consecutive_failures'] += 1
                    
                    if light_status['consecutive_failures'] % 2 == 0:
                        reminder = f"⚠️ Напоминання: Світло ще вимкнено\\n⏰ {light_status['last_check']}\\nЧас без світла: {light_status['consecutive_failures'] * CHECK_INTERVAL // 60} хвилин"
                        bot.send_message(chat_id, reminder, parse_mode='Markdown')
                        logger.info(f"Відправлено нагадування про відсутність світла")
            
            time.sleep(CHECK_INTERVAL)
            
    except Exception as e:
        logger.error(f"Помилка у циклі моніторингу: {e}")
        bot.send_message(chat_id, f"❌ Помилка моніторингу: {e}")

def main():
    logger.info("Запуск Telegram бота для моніторингу світла...")
    logger.info(f"Домен для моніторингу: {DOMAIN_TO_PING}")
    
    try:
        print("🤖 Бот запущено. Очікування на команди...")
        print("📡 Домен для моніторингу: {}".format(DOMAIN_TO_PING))
        print("👤 CHAT_ID: {}".format(CHAT_ID))
        print("\\n✅ Напишіть боту /start у Telegram та натискайте кнопку для перевірки світла\\n")
        
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
        
    except KeyboardInterrupt:
        logger.info("Бот зупинено користувачем")
        print("Бот зупинено.")
    except Exception as e:
        logger.error(f"Критична помилка: {e}")
        print(f"❌ Помилка: {e}")

if __name__ == '__main__':
    main()

