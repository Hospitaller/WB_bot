import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import aiohttp
import json
from datetime import datetime, time, timedelta
import os
import asyncio
import pytz
import signal
from dotenv import load_dotenv
from user_data import UserData
from config import CONFIG

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

# Настройка логгера для фильтрации
filter_logger = logging.getLogger('filter_logger')
filter_logger.setLevel(logging.INFO)
filter_handler = logging.FileHandler('logs/filter.log', encoding='utf-8')
filter_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
filter_logger.addHandler(filter_handler)

logger = logging.getLogger(__name__)
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
        self.user_data = UserData()

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
            wb_token = self.user_data.get_user_token(chat_id)
            if not wb_token:
                await context.bot.send_message(chat_id=chat_id, text="❌ Токен WB не найден. Пожалуйста, добавьте токен через команду /start")
                return

            headers = {
                'Accept': 'application/json',
                'Authorization': wb_token
            }
            
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                await context.bot.send_message(chat_id=chat_id, text="🔄 Считаю остатки...")
                first_response = await self.make_api_request(session, CONFIG['API_URLS']['first'], headers, context, chat_id)
                
                if not first_response:
                    return
                
                task_id = first_response.get('data', {}).get('taskId')
                if not task_id:
                    await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить task ID")
                    return
                
                await asyncio.sleep(CONFIG['DELAY_BETWEEN_REQUESTS'])
                
                second_url = CONFIG['API_URLS']['second'].format(task_id=task_id)
                stock_data = await self.make_api_request(session, second_url, headers, context, chat_id)
                
                if not stock_data:
                    return
                
                formatted_data = self.format_stock_data(stock_data)
                low_stock_data = self.format_stock_data(stock_data, highlight_low=True)
                
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
                    await asyncio.sleep(5)
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
            self.user_data.set_auto_check_status(chat_id, True)
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
                self.user_data.set_auto_check_status(chat_id, False)
                return True
            return False
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка остановки периодических проверок: {str(e)}", exc_info=True)
            raise

    async def get_warehouse_coefficients(self, context: ContextTypes.DEFAULT_TYPE):
        """Получение коэффициентов складов"""
        chat_id = context.job.chat_id if hasattr(context, 'job') else context._chat_id
        
        try:
            # Получаем токен пользователя
            wb_token = self.user_data.get_user_token(chat_id)
            if not wb_token:
                await context.bot.send_message(chat_id=chat_id, text="❌ Токен WB не найден. Пожалуйста, добавьте токен через команду /start. Требуются права Статистика, Аналитика, Поставки")
                return

            headers = {
                'Accept': 'application/json',
                'Authorization': wb_token
            }
            
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                await context.bot.send_message(chat_id=chat_id, text="🔄 Получаю коэффициенты складов...")
                
                response = await self.make_api_request(session, CONFIG['API_URLS']['coefficients'], headers, context, chat_id)
                
                if not response or not isinstance(response, list):
                    await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить данные о коэффициентах")
                    return
                
                # Добавляем задержку в 30 секунд
                await asyncio.sleep(30)
                
                # Подготовка списков ID складов
                target_warehouses = []
                if CONFIG['TARGET_WAREHOUSE_ID']:
                    # Очищаем строку от квадратных скобок и кавычек
                    target_str = str(CONFIG['TARGET_WAREHOUSE_ID']).replace('[', '').replace(']', '').replace("'", '')
                    target_warehouses = [int(id.strip()) for id in target_str.split(',') if id.strip()]
                
                excluded_warehouses = []
                if CONFIG['EX_WAREHOUSE_ID']:
                    # Очищаем строку от квадратных скобок и кавычек
                    excluded_str = str(CONFIG['EX_WAREHOUSE_ID']).replace('[', '').replace(']', '').replace("'", '')
                    excluded_warehouses = [int(id.strip()) for id in excluded_str.split(',') if id.strip()]
                
                filter_logger.info("="*50)
                filter_logger.info("Начало обработки данных")
                filter_logger.info(f"Target warehouses: {target_warehouses}")
                filter_logger.info(f"Excluded warehouses: {excluded_warehouses}")
                
                # Фильтруем и группируем данные
                filtered_data = {}
                total_processed = 0
                excluded_count = 0
                
                for item in response:
                    total_processed += 1
                    # Получаем ID склада и преобразуем его в число
                    warehouse_id = None
                    try:
                        # Проверяем все возможные варианты ключа
                        warehouse_id = item.get('warehouseId')
                        if warehouse_id is None:
                            filter_logger.warning(f"warehouseId не найден в записи: {json.dumps(item, ensure_ascii=False)}")
                            continue
                            
                        warehouse_id = int(warehouse_id)
                        warehouse_name = item.get('warehouseName', 'N/A')
                        filter_logger.info(f"Обработка склада: ID={warehouse_id}, Name={warehouse_name}")
                        
                        # Пропускаем склады из списка исключений
                        if excluded_warehouses and warehouse_id in excluded_warehouses:
                            filter_logger.info(f"СКЛАД ИСКЛЮЧЕН: ID={warehouse_id}, Name={warehouse_name}")
                            excluded_count += 1
                            continue
                        
                        # Если указаны целевые склады, пропускаем все остальные
                        if target_warehouses and warehouse_id not in target_warehouses:
                            filter_logger.info(f"СКЛАД НЕ В ЦЕЛЕВЫХ: ID={warehouse_id}, Name={warehouse_name}")
                            continue
                        
                        # Проверяем остальные условия фильтрации
                        if (item.get('boxTypeName') == "Короба" and 
                            item.get('coefficient') >= CONFIG['MIN_COEFFICIENT'] and 
                            item.get('coefficient') <= CONFIG['MAX_COEFFICIENT']):
                            
                            date = item.get('date', 'N/A')
                            coefficient = item.get('coefficient', 'N/A')
                            
                            # Преобразуем дату в формат дд-мм-гг
                            try:
                                # Убираем 'Z' и парсим ISO формат
                                date = date.replace('Z', '')
                                date_obj = datetime.fromisoformat(date)
                                formatted_date = date_obj.strftime('%d-%m-%y')
                            except:
                                formatted_date = date
                            
                            if warehouse_name not in filtered_data:
                                filtered_data[warehouse_name] = []
                            
                            filtered_data[warehouse_name].append({
                                'date': formatted_date,
                                'coefficient': coefficient
                            })
                            filter_logger.info(f"Данные добавлены для склада: ID={warehouse_id}, Name={warehouse_name}")
                        else:
                            filter_logger.info(f"Склад не прошел фильтрацию по условиям: ID={warehouse_id}, Name={warehouse_name}")
                            
                    except (ValueError, TypeError) as e:
                        filter_logger.error(f"Ошибка обработки записи: {e}")
                        filter_logger.error(f"Данные записи: {json.dumps(item, ensure_ascii=False)}")
                        continue
                
                filter_logger.info("="*50)
                filter_logger.info(f"Итоги обработки:")
                filter_logger.info(f"Всего обработано записей: {total_processed}")
                filter_logger.info(f"Исключено складов: {excluded_count}")
                filter_logger.info(f"Осталось складов после фильтрации: {len(filtered_data)}")
                filter_logger.info("="*50)
                
                # Сортируем данные по дате для каждого склада
                for warehouse in filtered_data:
                    filtered_data[warehouse].sort(key=lambda x: datetime.strptime(x['date'], '%d-%m-%y'))
                
                # Формируем сообщение
                MAX_MESSAGE_LENGTH = 4000
                current_message = "📊 Коэффициенты складов (Короба):\n\n"
                
                # Добавляем информацию о фильтрации
                if target_warehouses:
                    current_message += f"*Целевые склады:* {', '.join(map(str, target_warehouses))}\n"
                if excluded_warehouses:
                    current_message += f"*Исключенные склады:* {', '.join(map(str, excluded_warehouses))}\n"
                current_message += "\n"
                
                for warehouse_name, dates in filtered_data.items():
                    # Формируем строку с датами для текущего склада
                    new_line = f"*{warehouse_name}*:\n"
                    for item in dates:
                        new_line += f"--- {item['date']} = {item['coefficient']}\n"
                    new_line += "\n"
                    
                    # Если добавление новой строки превысит лимит, отправляем текущее сообщение
                    if len(current_message) + len(new_line) > MAX_MESSAGE_LENGTH:
                        await context.bot.send_message(chat_id=chat_id, text=current_message, parse_mode='Markdown')
                        current_message = new_line
                    else:
                        current_message += new_line
                
                # Отправляем оставшуюся часть сообщения, если она есть
                if current_message:
                    await context.bot.send_message(chat_id=chat_id, text=current_message, parse_mode='Markdown')
                
        except Exception as e:
            logger.critical(f"CRITICAL ERROR for chat {chat_id}: {str(e)}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Произошла критическая ошибка: {str(e)}")

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        if not bot:
            raise Exception("Бот не инициализирован")

        user_id = update.effective_user.id
        if not bot.user_data.is_user_exists(user_id):
            await update.message.reply_text(
                "👋 Привет! Я бот для работы с Wildberries.\n"
                "Для начала работы необходимо добавить ваш WB токен:\n"
                "Статистика, Аналитика, Поставки\n\n"
                "Введите ваш токен:"
            )
            context.user_data['waiting_for_token'] = True
        else:
            await update.message.reply_text(
                "Для управления ботом используйте главное меню"
            )
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в start: {str(e)}", exc_info=True)

# Обработчик нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        bot = context.bot_data.get('wb_bot')
        if not bot:
            raise Exception("Бот не инициализирован")
        
        user_id = update.effective_user.id
        
        if query.data == 'start_bot':
            if not bot.user_data.is_user_exists(user_id):
                keyboard = [
                    [InlineKeyboardButton("➕ Новый пользователь", callback_data='new_user')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text(
                    "👋 Привет! Я бот для работы с Wildberries.\n"
                    "Для начала работы необходимо добавить ваш WB токен:\n"
                    "Статистика, Аналитика, Поставки",
                    reply_markup=reply_markup
                )
            else:
                keyboard = [
                    [
                        InlineKeyboardButton("🔄 Проверить остатки", callback_data='check_stock'),
                        InlineKeyboardButton("✅ Запустить авто", callback_data='start_auto_stock')
                    ],
                    [
                        InlineKeyboardButton("🛑 Остановить авто", callback_data='stop_auto_stock'),
                        InlineKeyboardButton("📊 Доступность", callback_data='check_coefficients')
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.edit_text(
                    "Выберите действие:",
                    reply_markup=reply_markup
                )
            return
            
        if query.data == 'new_user':
            await query.message.edit_text(
                "🔑 Пожалуйста, введите ваш токен WB:"
            )
            context.user_data['waiting_for_token'] = True
            return
            
        if not bot.user_data.is_user_exists(user_id):
            await query.message.reply_text(
                "❌ Сначала необходимо добавить токен WB через команду /start"
            )
            return
            
        if query.data == 'check_stock':
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            await bot.fetch_wb_data(fake_context)
            
        elif query.data == 'start_auto_stock':
            chat_id = update.effective_chat.id
            await bot.start_periodic_checks(chat_id)
            await query.message.reply_text(
                f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_INTERVAL']} минут в рабочее время)"
            )
            
        elif query.data == 'stop_auto_stock':
            chat_id = update.effective_chat.id
            if await bot.stop_periodic_checks(chat_id):
                await query.message.reply_text("🛑 Автоматические проверки остановлены")
            else:
                await query.message.reply_text("ℹ️ Нет активных автоматических проверок")
                
        elif query.data == 'check_coefficients':
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            await bot.get_warehouse_coefficients(fake_context)
                
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в обработчике кнопок: {str(e)}", exc_info=True)
        await query.message.reply_text("❌ Произошла критическая ошибка")

# Обработчик текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        if not bot:
            raise Exception("Бот не инициализирован")

        user_id = update.effective_user.id
        
        if context.user_data.get('waiting_for_token'):
            token = update.message.text.strip()
            bot.user_data.add_user(user_id, token)
            context.user_data['waiting_for_token'] = False
            
            await update.message.reply_text(
                "✅ Токен успешно добавлен!\n"
                "Теперь вы можете использовать бота. Удачи!\n\n"
                "Для управления ботом используйте главное меню"
            )
        else:
            await update.message.reply_text(
                "Для управления ботом используйте главное меню"
            )
            
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в обработчике сообщений: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

# Основная функция запуска бота
def main():
    """Запуск бота"""
    application = Application.builder().token(CONFIG['TG_API_KEY']).build()
    bot = WBStockBot(application)
    application.bot_data['wb_bot'] = bot
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    
    # Обработчики команд с правильной передачей контекста
    async def check_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
        class FakeContext:
            def __init__(self, chat_id, bot):
                self._chat_id = chat_id
                self.bot = bot
        fake_context = FakeContext(update.effective_chat.id, context.bot)
        await bot.fetch_wb_data(fake_context)
    
    async def start_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await bot.start_periodic_checks(update.effective_chat.id)
        await update.message.reply_text(
            f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_INTERVAL']} минут в рабочее время)"
        )
    
    async def stop_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await bot.stop_periodic_checks(update.effective_chat.id):
            await update.message.reply_text("🛑 Автоматические проверки остановлены")
        else:
            await update.message.reply_text("ℹ️ Нет активных автоматических проверок")
    
    async def check_coefficients(update: Update, context: ContextTypes.DEFAULT_TYPE):
        class FakeContext:
            def __init__(self, chat_id, bot):
                self._chat_id = chat_id
                self.bot = bot
        fake_context = FakeContext(update.effective_chat.id, context.bot)
        await bot.get_warehouse_coefficients(fake_context)
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("check_stock", check_stock))
    application.add_handler(CommandHandler("start_auto_stock", start_auto_stock))
    application.add_handler(CommandHandler("stop_auto_stock", stop_auto_stock))
    application.add_handler(CommandHandler("check_coefficients", check_coefficients))
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