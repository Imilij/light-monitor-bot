#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простий скрипт для отримання CHAT_ID (сумісний з Python 3.6+)
Не вимагає встановлення додаткових бібліотек
"""

import json
import time
from urllib.request import urlopen
from urllib.error import URLError

BOT_TOKEN = "7956450854:AAELUrRz00JlyLdZcLJnyRL5-u4-9kW4sGY"

def get_updates(offset=0):
    """Отримати оновлення від Telegram API"""
    try:
        url = "https://api.telegram.org/bot{}/getUpdates?offset={}".format(BOT_TOKEN, offset)
        response = urlopen(url, timeout=5)
        data = json.loads(response.read().decode('utf-8'))
        return data
    except URLError as e:
        print("Помилка мережі: {}".format(e))
        return None
    except Exception as e:
        print("Помилка: {}".format(e))
        return None

def main():
    print("="*60)
    print("Бот для отримання CHAT_ID")
    print("="*60)
    print("\nІнструкція:")
    print("1. Напишіть своєму боту у Telegram будь-яке повідомлення")
    print("2. Скрипт покаже ваш CHAT_ID")
    print("\nОчікування повідомлення... (Ctrl+C для виходу)\n")
    
    offset = 0
    found_ids = set()
    
    try:
        while True:
            data = get_updates(offset)
            
            if data and data.get('ok'):
                updates = data.get('result', [])
                
                if updates:
                    for update in updates:
                        offset = update['update_id'] + 1
                        
                        if 'message' in update:
                            msg = update['message']
                            chat_id = msg['chat']['id']
                            
                            if chat_id not in found_ids:
                                found_ids.add(chat_id)
                                
                                first_name = msg['chat'].get('first_name', 'N/A')
                                username = msg['chat'].get('username', 'N/A')
                                text = msg.get('text', '(без тексту)')
                                
                                print("="*60)
                                print("НОВИЙ CHAT_ID!")
                                print("="*60)
                                print("Ім'я: {}".format(first_name))
                                print("Username: @{}".format(username))
                                print("Текст: {}".format(text))
                                print("\nCHAT_ID: {}".format(chat_id))
                                print("\nСкопіюйте це значення та вставте у код:")
                                print('   CHAT_ID = "{}"'.format(chat_id))
                                print("="*60 + "\n")
                
                time.sleep(1)
            else:
                print("Не вдалося отримати дані від Telegram API")
                print("Перевірте BOT_TOKEN")
                time.sleep(2)
                
    except KeyboardInterrupt:
        print("\n\nСкрипт зупинено користувачем")

if __name__ == '__main__':
    main()

