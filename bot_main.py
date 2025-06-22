import logging
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from datetime import datetime, time, timedelta
import os
import asyncio
import pytz
import signal
from dotenv import load_dotenv
from user_data import UserData
from config import CONFIG
from mongo_db import MongoDB
# Импорт обработчиков
from handlers.common import start, info, handle_message
from handlers.admin import admin_statistics, send_messages, broadcast_message
from handlers.stock import check_stock, check_all_stock, start_auto_stock, stop_auto_stock
from handlers.coefficients import check_coefficients
from handlers.user import user_account
from handlers.buttons import button_handler
from handlers.sales import sales_menu

# Загрузка переменных окружения
load_dotenv()

# Создаем папку для логов, если её нет
os.makedirs('logs', exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(CONFIG['LOG_FILE']),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Настройка логгера для фильтрации
filter_logger = logging.getLogger('filter_logger')
filter_logger.setLevel(logging.INFO)
filter_handler = logging.FileHandler('logs/filter.log', encoding='utf-8')
filter_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
filter_logger.addHandler(filter_handler)

# Основная функция запуска бота
def main():
    """Запуск бота"""
    application = Application.builder().token(CONFIG['TG_API_KEY']).build()
    # Инициализация зависимостей
    mongo = MongoDB()
    user_data = UserData()
    timezone = pytz.timezone('Europe/Moscow')
    active_jobs = {}
    active_coefficient_jobs = {}
    warehouse_selection = {}
    warehouse_selection_order = {}
    # Загружаем сохранённые склады для всех пользователей
    users = mongo.settings.find({'user_id': {'$exists': True}})
    for user in users:
        user_id = user['user_id']
        warehouses = mongo.get_selected_warehouses(user_id)
        if warehouses:
            warehouse_selection[user_id] = set(warehouses)
            warehouse_selection_order[user_id] = warehouses
    # Сохраняем зависимости в application.bot_data
    application.bot_data['mongo'] = mongo
    application.bot_data['user_data'] = user_data
    application.bot_data['timezone'] = timezone
    application.bot_data['active_jobs'] = active_jobs
    application.bot_data['active_coefficient_jobs'] = active_coefficient_jobs
    application.bot_data['warehouse_selection'] = warehouse_selection
    application.bot_data['warehouse_selection_order'] = warehouse_selection_order
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("check_stock", check_stock))
    application.add_handler(CommandHandler("check_all_stock", check_all_stock))
    application.add_handler(CommandHandler("start_auto_stock", start_auto_stock))
    application.add_handler(CommandHandler("stop_auto_stock", stop_auto_stock))
    application.add_handler(CommandHandler("check_coefficients", check_coefficients))
    application.add_handler(CommandHandler("user_account", user_account))
    application.add_handler(CommandHandler("send_messages", send_messages))
    application.add_handler(CommandHandler("sales", sales_menu))
    application.add_handler(CommandHandler("admin_statistics", admin_statistics))
    application.add_handler(CommandHandler("broadcast_message", broadcast_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    # Обработчик сигналов завершения
    def signal_handler(signum, frame):
        print("\nБот остановлен")
        asyncio.create_task(application.stop())
    # Регистрация обработчиков сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    print("Бот запущен")
    application.run_polling()

if __name__ == '__main__':
    main()