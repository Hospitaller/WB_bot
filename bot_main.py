import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import aiohttp
import json
from datetime import datetime, time, timedelta
import os
import asyncio
import pytz
import signal
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфиг
CONFIG = {
    'AUTH_TOKEN': os.getenv('AUTH_TOKEN'),
    'TG_API_KEY': os.getenv('TG_API_KEY'),
    'API_URLS': {
        'first': "https://seller-analytics-api.wildberries.ru/api/v1/warehouse_remains?groupBySa=true",
        'second': "https://seller-analytics-api.wildberries.ru/api/v1/warehouse_remains/tasks/{task_id}/download"
    },
    'LOW_STOCK_THRESHOLD': 20,
    'WORKING_HOURS': "08-22",  # Часы работы (МСК)
    'CHECK_INTERVAL': 240,  # Интервал проверки в минутах
    'DELAY_BETWEEN_REQUESTS': 30,
    'LOG_FILE': 'wb_bot_critical.log'
}

# Проверка наличия необходимых переменных окружения
if not CONFIG['AUTH_TOKEN'] or not CONFIG['TG_API_KEY']:
    raise ValueError("Не найдены необходимые переменные окружения AUTH_TOKEN и/или TG_API_KEY")

# Настройка логирования в файл
logging.basicConfig(
    level=logging.CRITICAL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(CONFIG['LOG_FILE']),
    ]
)

# Логирование в консоль
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.addHandler(console_handler)

# Класс бота
class WBStockBot:
    def __init__(self, application):
        self.working_hours_start, self.working_hours_end = map(int, CONFIG['WORKING_HOURS'].split('-'))
        self.timezone = pytz.timezone('Europe/Moscow')
        self.application = application
        self.active_jobs = {}

    # Проверка на рабочее время
    def is_working_time(self):
        now = datetime.now(self.timezone)
        current_hour = now.hour
        return self.working_hours_start <= current_hour < self.working_hours_end

    # Форматирование данных о складе
    def format_stock_data(self, data, highlight_low=False):
        if not isinstance(data, list):
            return None
        result = []
        low_stock_items = []
        
        for item in data:
            vendor_code = item.get('vendorCode', 'N/A')
            warehouses = item.get('warehouses', [])
            
            total_warehouse = next(
                (wh for wh in warehouses if wh.get('warehouseName') == "Всего находится на складах"),
                None
            )
            
            if not total_warehouse:
                continue
                
            quantity = total_warehouse.get('quantity', 0)
            
            item_text = (
                f"Артикул: {vendor_code}\n"
                f"Остаток: {quantity}\n"
                f"{'-'*30}"
            )
            
            result.append(item_text)
            
            if quantity <= CONFIG['LOW_STOCK_THRESHOLD']:
                low_stock_items.append(item_text)
        
        if highlight_low:
            return low_stock_items
        return result

    async def fetch_wb_data(self, context: ContextTypes.DEFAULT_TYPE):
        """Основная функция получения данных"""
        chat_id = context.job.chat_id if hasattr(context, 'job') else context._chat_id
        
        if not self.is_working_time():
            logger.info(f"Сейчас нерабочее время для чата {chat_id}")
            return
            
        try:
            headers = {
                'Accept': 'application/json',
                'Authorization': CONFIG['AUTH_TOKEN']
            }
            
            timeout = aiohttp.ClientTimeout(total=60)  # Общий таймаут 60 секунд
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Первый запрос
                await context.bot.send_message(chat_id=chat_id, text="🔄 Автоматическая проверка остатков...")
                first_response = await self.make_api_request(session, CONFIG['API_URLS']['first'], headers, context, chat_id)
                
                if not first_response:
                    return
                
                task_id = first_response.get('data', {}).get('taskId')
                if not task_id:
                    await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить task ID")
                    return
                
                # Ожидание перед вторым запросом
                await asyncio.sleep(CONFIG['DELAY_BETWEEN_REQUESTS'])
                
                # Второй запрос
                second_url = CONFIG['API_URLS']['second'].format(task_id=task_id)
                stock_data = await self.make_api_request(session, second_url, headers, context, chat_id)
                
                if not stock_data:
                    return
                
                # Форматируем вывод
                formatted_data = self.format_stock_data(stock_data)
                low_stock_data = self.format_stock_data(stock_data, highlight_low=True)
                
                # Отправка результатов
                if formatted_data:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="📦 Остатки на складах:\n" + "\n".join(formatted_data)
                    )
                
                if low_stock_data:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="⚠️ ТОВАРЫ ЗАКАНЧИВАЮТСЯ! ⚠️\n" + "\n".join(low_stock_data)
                    )
                
        except Exception as e:
            logger.critical(f"CRITICAL ERROR for chat {chat_id}: {str(e)}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Произошла критическая ошибка: {str(e)}")

    async def make_api_request(self, session, url, headers, context, chat_id, max_retries=3, timeout=30):
        """Выполняет API запрос с повторными попытками"""
        for attempt in range(max_retries):
            try:
                async with session.get(url, headers=headers, timeout=timeout) as response:
                    if response.status != 200:
                        error_msg = f"Ошибка запроса: {response.status}"
                        logger.critical(f"CRITICAL: {error_msg} для URL: {url}")
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"❌ {error_msg}"
                        )
                        return None
                    return await response.json()
            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    logger.warning(f"Таймаут при попытке {attempt + 1}/{max_retries}, повторная попытка...")
                    await asyncio.sleep(5)  # Пауза перед повторной попыткой
                    continue
                error_msg = "Превышено время ожидания ответа от сервера"
                logger.critical(f"CRITICAL: {error_msg} для URL: {url}")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ {error_msg}"
                )
                return None
            except Exception as e:
                error_msg = f"Ошибка при выполнении запроса: {str(e)}"
                logger.critical(f"CRITICAL: {error_msg} для URL: {url}", exc_info=True)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ {error_msg}"
                )
                return None

    async def start_periodic_checks(self, chat_id: int):
        """Запускает периодические проверки для указанного чата"""
        try:
            if chat_id in self.active_jobs:
                self.active_jobs[chat_id].schedule_removal()
            
            job = self.application.job_queue.run_repeating(
                callback=self.fetch_wb_data,
                interval=timedelta(minutes=CONFIG['CHECK_INTERVAL']),
                first=0,
                chat_id=chat_id,
                name=str(chat_id)
            )
            self.active_jobs[chat_id] = job
            return job
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка запуска периодических проверок: {str(e)}", exc_info=True)
            raise

    async def stop_periodic_checks(self, chat_id: int):
        """Останавливает периодические проверки для указанного чата"""
        try:
            if chat_id in self.active_jobs:
                self.active_jobs[chat_id].schedule_removal()
                del self.active_jobs[chat_id]
                return True
            return False
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка остановки периодических проверок: {str(e)}", exc_info=True)
            raise

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text(
            "Привет! Я бот для мониторинга остатков Wildberries.\n"
            "Используй /get_stock для разовой проверки\n"
            "/auto_check для запуска автоматических проверок\n"
            "/stop_check для остановки автоматических проверок"
        )
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в start: {str(e)}", exc_info=True)

# Обработчик команды получения остатков
async def get_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        if not bot:
            raise Exception("Бот не инициализирован")
        
        # Создаем искусственный контекст для разовой проверки
        class FakeContext:
            def __init__(self, chat_id, bot):
                self._chat_id = chat_id
                self.bot = bot
        fake_context = FakeContext(update.effective_chat.id, context.bot)
        await bot.fetch_wb_data(fake_context)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в get_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка при получении остатков")

# Обработчик команды запуска автоматических проверок
async def auto_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        if not bot:
            raise Exception("Бот не инициализирован")
        
        chat_id = update.effective_chat.id
        await bot.start_periodic_checks(chat_id)
        await update.message.reply_text(
            f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_INTERVAL']} минут в рабочее время)"
        )
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в auto_check: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка при запуске автоматических проверок")

# Обработчик команды остановки автоматических проверок
async def stop_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        if not bot:
            raise Exception("Бот не инициализирован")
        
        chat_id = update.effective_chat.id
        if await bot.stop_periodic_checks(chat_id):
            await update.message.reply_text("🛑 Автоматические проверки остановлены")
        else:
            await update.message.reply_text("ℹ️ Нет активных автоматических проверок")
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в stop_check: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка при остановке автоматических проверок")

# Основная функция запуска бота
def main():
    try:
        application = Application.builder().token(CONFIG['TG_API_KEY']).build()
        
        # Инициализация бота
        application.bot_data['wb_bot'] = WBStockBot(application)
        
        # Регистрация обработчиков команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("get_stock", get_stock))
        application.add_handler(CommandHandler("auto_check", auto_check))
        application.add_handler(CommandHandler("stop_check", stop_check))
        
        # Обработчик сигналов завершения
        def signal_handler(signum, frame):
            print("\nБот остановлен")
            # Создаем и запускаем новую задачу для остановки приложения
            asyncio.create_task(application.stop())
        
        # Регистрация обработчиков сигналов
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        print("Бот запущен")
        application.run_polling()
       

    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка при запуске бота: {str(e)}", exc_info=True)
        raise

if __name__ == '__main__':
    main()