#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Bot для моніторингу наявності світла вдома
Перевіряє доступність IP-адреси через DDNS домен за допомогою ping
"""

import telebot
import subprocess
import logging
from datetime import datetime
from typing import Tuple

# ==================== КОНФІГУРАЦІЯ ====================
# Отримайте токен від @BotFather у Telegram
BOT_TOKEN = "7956450854:AAELUrRz00JlyLdZcLJnyRL5-u4-9kW4sGY"  # Ваш токен
CHAT_ID = "918294260"  # Ваш chat ID

# Конфігурація мониторингу
DOMAIN_TO_PING = "imilij.tplinkdns.com"
PING_TIMEOUT = 5  # секунд

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ІНІЦІАЛІЗАЦІЯ БОТА ====================
bot = telebot.TeleBot(BOT_TOKEN)

# Глобальна змінна для відстеження стану світла
light_status = {
    'is_on': None,  # None = невідомо, True = є світло, False = немає світла
    'last_check': None,
    'last_status_change': None,
    'consecutive_failures': 0
}

# ==================== ФУНКЦІЇ ПІНГУВАННЯ ====================

def ping_host(hostname: str, timeout: int = 5) -> Tuple[bool, str]:
    """
    Пінгує хост и повертає (успіх, деталі)
    
    Args:
        hostname: доменне ім'я або IP-адреса
        timeout: таймаут у секундах
        
    Returns:
        Tuple (success: bool, details: str)
    """
    try:
        # Використовуємо ping команду (кросс-платформна)
        # -W для Linux/Mac, -w для Windows
        cmd = ['ping', '-c', '1', '-W', str(timeout), hostname]
        
        result = subprocess.run(
            cmd,
            timeout=timeout + 2,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )
        
        if result.returncode == 0:
            # Парсимо час відповіді
            lines = result.stdout.split('\n')
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

# ==================== ОБРОБНИКИ КОМАНД БОТА ====================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Обробник команди /start та /help"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    button = telebot.types.KeyboardButton('💡 Перевірити світло')
    markup.add(button)
    
    welcome_text = """🏠 *Бот для моніторингу світла вдома*

Натискайте кнопку нижче для перевірки наявності світла\.

📡 Домен: `{}`
⏱ Таймаут: {} сек""".format(DOMAIN_TO_PING.replace('.', '\.'), PING_TIMEOUT)
    
    bot.reply_to(message, welcome_text, parse_mode='MarkdownV2', reply_markup=markup)

@bot.message_handler(commands=['status'])
def check_status(message):
    """Обробник команди /status - перевіра поточного статусу"""
    is_on, details = ping_host(DOMAIN_TO_PING, PING_TIMEOUT)
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    response = f"{details}\n⏰ Перевірено: {timestamp}"
    
    bot.reply_to(message, response, parse_mode='Markdown')
    logger.info(f"Користувач перевірив статус: {response}")

@bot.message_handler(commands=['start_monitoring'])
def start_monitoring(message):
    """Обробник команди /start_monitoring"""
    bot.reply_to(message, "▶️ Моніторинг розпочато...\n\nВи будете отримувати повідомлення про зміни статусу світла.")
    logger.info("Моніторинг розпочато користувачем")
    
    # Запустимо фоновий моніторинг
    monitoring_thread = threading.Thread(
        target=monitoring_loop,
        args=(message.chat.id,),
        daemon=True
    )
    monitoring_thread.start()

@bot.message_handler(commands=['history'])
def show_history(message):
    """Обробник команди /history"""
    status_text = "📊 **Статус світла:**\n\n"
    status_text += f"Поточний статус: {'✅ ВКЛ' if light_status['is_on'] else '❌ ВИМКНЕНО'}\n"
    status_text += f"Остання перевірка: {light_status['last_check'] or 'ще не було'}\n"
    status_text += f"Остання зміна: {light_status['last_status_change'] or 'ще не було'}\n"
    status_text += f"Послідовні помилки: {light_status['consecutive_failures']}\n"
    
    bot.reply_to(message, status_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == '💡 Перевірити світло')
def handle_check_button(message):
    """Обробник кнопки перевірки світла"""
    is_on, details = ping_host(DOMAIN_TO_PING, PING_TIMEOUT)
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    response = f"{details}\n⏰ Перевірено: {timestamp}"
    
    bot.reply_to(message, response)
    logger.info(f"Користувач перевірив світло: {details}")

@bot.message_handler(func=lambda message: True)
def handle_unknown(message):
    """Обробник невідомих команд"""
    bot.reply_to(
        message,
        "Невідома команда. Використовуйте кнопку нижче або /help для допомоги."
    )

# ==================== ФОНОВИЙ МОНІТОРИНГ ====================

def monitoring_loop(chat_id: int):
    """
    Головний цикл моніторингу
    Перевіряє статус світла і надсилає сповіщення про зміни
    """
    logger.info(f"Розпочат моніторинг для chat_id: {chat_id}")
    
    try:
        while True:
            is_on, details = ping_host(DOMAIN_TO_PING, PING_TIMEOUT)
            
            # Оновлюємо час останньої перевірки
            light_status['last_check'] = datetime.now().strftime("%H:%M:%S")
            
            # Перевіряємо, чи змінився статус
            if light_status['is_on'] is None:
                # Перша перевірка
                light_status['is_on'] = is_on
                light_status['last_status_change'] = light_status['last_check']
                
                # Надсилаємо початкове сповіщення
                emoji = "🟢" if is_on else "🔴"
                status_msg = "ВКЛ" if is_on else "ВИМКНЕНО"
                message = f"{emoji} Моніторинг активний. Поточний статус: **{status_msg}**\n{details}"
                bot.send_message(chat_id, message, parse_mode='Markdown')
                
            elif light_status['is_on'] != is_on:
                # Статус змінився!
                light_status['is_on'] = is_on
                light_status['last_status_change'] = light_status['last_check']
                light_status['consecutive_failures'] = 0
                
                # Надсилаємо ВАЖЛИВЕ сповіщення про зміну
                emoji = "🟢" if is_on else "🔴"
                status_msg = "ВКЛ" if is_on else "ВИМКНЕНО"
                
                alert_message = f"{emoji} **ЗМІНА СТАТУСУ!**\n"
                alert_message += f"Світло тепер: **{status_msg}**\n"
                alert_message += f"⏰ Час: {light_status['last_check']}\n"
                alert_message += f"{details}"
                
                bot.send_message(chat_id, alert_message, parse_mode='Markdown')
                logger.warning(f"Зміна статусу світла: {status_msg}")
                
            else:
                # Статус не змінився
                if is_on:
                    light_status['consecutive_failures'] = 0
                else:
                    light_status['consecutive_failures'] += 1
                    
                    # Якщо світла немає довше, надсилаємо періодичні нагадування
                    if light_status['consecutive_failures'] % 2 == 0:
                        reminder = f"⚠️ Напоминание: Світло ще вимкнено\n⏰ {light_status['last_check']}\nЧас без світла: {light_status['consecutive_failures'] * CHECK_INTERVAL // 60} хвилин"
                        bot.send_message(chat_id, reminder, parse_mode='Markdown')
                        logger.info(f"Відправлено нагадування про відсутність світла")
            
            # Чекаємо перед наступною перевіркою
            time.sleep(CHECK_INTERVAL)
            
    except Exception as e:
        logger.error(f"Помилка у циклі моніторингу: {e}")
        bot.send_message(chat_id, f"❌ Помилка моніторингу: {e}")

# ==================== ОСНОВНА ПРОГРАМА ====================

def main():
    """Запуск бота"""
    logger.info("Запуск Telegram бота для моніторингу світла...")
    logger.info(f"Домен для моніторингу: {DOMAIN_TO_PING}")
    
    try:
        print("🤖 Бот запущено. Очікування на команди...")
        print("📡 Домен для моніторингу: {}".format(DOMAIN_TO_PING))
        print("👤 CHAT_ID: {}".format(CHAT_ID))
        print("\n✅ Напишіть боту /start у Telegram та натискайте кнопку для перевірки світла\n")
        
        # Нескінченний цикл опитування повідомлень
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
        
    except KeyboardInterrupt:
        logger.info("Бот зупинено користувачем")
        print("Бот зупинено.")
    except Exception as e:
        logger.error(f"Критична помилка: {e}")
        print(f"❌ Помилка: {e}")

if __name__ == '__main__':
    main()
