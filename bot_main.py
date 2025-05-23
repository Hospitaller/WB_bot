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
        self.active_coefficient_jobs = {}  # Для хранения задач проверки коэффициентов
        self.user_data = UserData()
        self.warehouse_selection = {}  # Для хранения выбранных складов пользователями
        self.warehouse_selection_order = {}  # Для хранения порядка добавления складов

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
    
    #Основная функция получения данных
    async def fetch_wb_data(self, context: ContextTypes.DEFAULT_TYPE):
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

    #Выполняет API запрос с повторными попытками
    async def make_api_request(self, session, url, headers, context, chat_id, max_retries=3, timeout=30):
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

    #Запускает периодические проверки для указанного чата
    async def start_periodic_checks(self, chat_id: int):
        try:
            if chat_id in self.active_jobs:
                self.active_jobs[chat_id].schedule_removal()
            
            job = self.application.job_queue.run_repeating(
                callback=self.fetch_wb_data,
                interval=timedelta(minutes=CONFIG['CHECK_STOCK_INTERVAL']),
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

    #Останавливает периодические проверки для указанного чата
    async def stop_periodic_checks(self, chat_id: int):
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

    #Получение коэффициентов складов
    async def get_warehouse_coefficients(self, context: ContextTypes.DEFAULT_TYPE):
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
                # Отправляем сообщение только если это не автоматическая проверка
                if not hasattr(context, 'job'):
                    await context.bot.send_message(chat_id=chat_id, text="🔄 Получаю коэффициенты складов...")
                
                response = await self.make_api_request(session, CONFIG['API_URLS']['coefficients'], headers, context, chat_id)
                
                if not response or not isinstance(response, list):
                    await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить данные о коэффициентах")
                    return
                
                # Подготовка списков ID складов
                target_warehouses = []
                target_names = set()  # Для хранения названий целевых складов
                if CONFIG['TARGET_WAREHOUSE_ID']:
                    target_str = str(CONFIG['TARGET_WAREHOUSE_ID']).replace('[', '').replace(']', '').replace("'", '')
                    target_warehouses = [int(id.strip()) for id in target_str.split(',') if id.strip()]
                
                # Добавляем выбранные пользователем склады
                if chat_id in self.warehouse_selection:
                    target_warehouses.extend(self.warehouse_selection[chat_id])
                
                excluded_warehouses = []
                excluded_names = set()
                if CONFIG['EX_WAREHOUSE_ID']:
                    excluded_str = str(CONFIG['EX_WAREHOUSE_ID']).replace('[', '').replace(']', '').replace("'", '')
                    excluded_warehouses = [int(id.strip()) for id in excluded_str.split(',') if id.strip()]
                
                # Фильтруем и группируем данные
                filtered_data = {}
                
                for item in response:
                    warehouse_id = None
                    try:
                        warehouse_id = item.get('warehouseID')
                        if warehouse_id is None:
                            continue
                            
                        warehouse_id = int(warehouse_id)
                        warehouse_name = item.get('warehouseName', 'N/A')
                        
                        # Собираем названия целевых складов
                        if warehouse_id in target_warehouses:
                            target_names.add(warehouse_name)
                        
                        # Пропускаем склады из списка исключений
                        if excluded_warehouses and warehouse_id in excluded_warehouses:
                            excluded_names.add(warehouse_name)
                            continue
                        
                        # Если указаны целевые склады, пропускаем все остальные
                        if target_warehouses and warehouse_id not in target_warehouses:
                            continue
                        
                        # Проверяем остальные условия фильтрации
                        if (item.get('boxTypeName') == "Короба" and 
                            item.get('coefficient') >= CONFIG['MIN_COEFFICIENT'] and 
                            item.get('coefficient') <= CONFIG['MAX_COEFFICIENT']):
                            
                            date = item.get('date', 'N/A')
                            coefficient = item.get('coefficient', 'N/A')
                            
                            try:
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
                            
                    except (ValueError, TypeError):
                        continue
                
                # Сортируем данные по дате для каждого склада
                for warehouse in filtered_data:
                    filtered_data[warehouse].sort(key=lambda x: datetime.strptime(x['date'], '%d-%m-%y'))
                
                # Формируем сообщение
                MAX_MESSAGE_LENGTH = 4000
                current_message = "📊 Коэффициенты складов (Короба):\n\n"
                
                # Добавляем информацию о фильтрации
                if target_names:
                    current_message += f"*Целевые склады:* {', '.join(sorted(target_names))}\n"
                if excluded_names:
                    current_message += f"*Исключенные склады:* {', '.join(sorted(excluded_names))}\n"
                current_message += "\n"
                
                # Формируем все сообщения заранее
                messages = []
                for warehouse_name, dates in filtered_data.items():
                    new_line = f"*{warehouse_name}*:\n"
                    for item in dates:
                        new_line += f"--- {item['date']} = {item['coefficient']}\n"
                    new_line += "\n"
                    
                    if len(current_message) + len(new_line) > MAX_MESSAGE_LENGTH:
                        messages.append(current_message)
                        current_message = new_line
                    else:
                        current_message += new_line
                
                if current_message:
                    messages.append(current_message)
                
                # Отправляем все сообщения
                for message in messages:
                    await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
                
        except Exception as e:
            logger.critical(f"CRITICAL ERROR for chat {chat_id}: {str(e)}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Произошла критическая ошибка: {str(e)}")

    async def start_auto_coefficients(self, chat_id: int):
        try:
            if chat_id in self.active_coefficient_jobs:
                self.active_coefficient_jobs[chat_id].schedule_removal()
            
            job = self.application.job_queue.run_repeating(
                callback=self.get_warehouse_coefficients,
                interval=timedelta(minutes=CONFIG['CHECK_COEFFICIENTS_INTERVAL']),
                first=0,
                chat_id=chat_id,
                name=f"coefficients_{chat_id}"
            )
            self.active_coefficient_jobs[chat_id] = job
            return job
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка запуска автоматических проверок коэффициентов: {str(e)}", exc_info=True)
            raise

    async def stop_auto_coefficients(self, chat_id: int):
        try:
            if chat_id in self.active_coefficient_jobs:
                self.active_coefficient_jobs[chat_id].schedule_removal()
                del self.active_coefficient_jobs[chat_id]
                return True
            return False
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка остановки автоматических проверок коэффициентов: {str(e)}", exc_info=True)
            raise

    async def get_warehouse_list(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
        try:
            if chat_id is None:
                if hasattr(context, 'job') and context.job:
                    chat_id = context.job.chat_id
                elif hasattr(context, '_chat_id'):
                    chat_id = context._chat_id
                else:
                    return None

            wb_token = self.user_data.get_user_token(chat_id)
            if not wb_token:
                return None

            headers = {
                'Accept': 'application/json',
                'Authorization': wb_token
            }
            
            async with aiohttp.ClientSession() as session:
                response = await self.make_api_request(session, CONFIG['API_URLS']['coefficients'], headers, context, chat_id)
                
                if not response or not isinstance(response, list):
                    return None
                
                warehouses = {}
                for item in response:
                    warehouse_id = item.get('warehouseID')
                    warehouse_name = item.get('warehouseName')
                    if warehouse_id and warehouse_name:
                        warehouses[warehouse_id] = warehouse_name
                
                return warehouses
        except Exception as e:
            logger.critical(f"CRITICAL ERROR for chat {chat_id}: {str(e)}", exc_info=True)
            return None

    async def show_warehouse_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE, page=0):
        try:
            chat_id = update.effective_chat.id
            warehouses = await self.get_warehouse_list(context, chat_id)
            
            if not warehouses:
                if update.callback_query:
                    await update.callback_query.message.edit_text("❌ Не удалось получить список складов")
                else:
                    await update.message.reply_text("❌ Не удалось получить список складов")
                return
            
            # Сортируем склады по имени
            sorted_warehouses = dict(sorted(warehouses.items(), key=lambda x: x[1]))
            
            # Получаем уже выбранные склады
            selected_warehouses = self.warehouse_selection.get(chat_id, set())
            
            # Фильтруем уже выбранные склады
            available_warehouses = {k: v for k, v in sorted_warehouses.items() if k not in selected_warehouses}
            
            if not available_warehouses:
                if update.callback_query:
                    await update.callback_query.message.edit_text("❌ Нет доступных складов для выбора")
                else:
                    await update.message.reply_text("❌ Нет доступных складов для выбора")
                return
            
            # Разбиваем на страницы по 25 складов
            warehouse_items = list(available_warehouses.items())
            total_pages = (len(warehouse_items) + 24) // 25
            start_idx = page * 25
            end_idx = min(start_idx + 25, len(warehouse_items))
            
            keyboard = []
            for warehouse_id, warehouse_name in warehouse_items[start_idx:end_idx]:
                keyboard.append([InlineKeyboardButton(f"-- {warehouse_name} --", callback_data=f"select_warehouse_{warehouse_id}")])
            
            # Добавляем навигационные кнопки
            nav_buttons = []
            if page > 0:
                nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"warehouse_page_{page-1}"))
            if page < total_pages - 1:
                nav_buttons.append(InlineKeyboardButton("Далее ▶️", callback_data=f"warehouse_page_{page+1}"))
            if nav_buttons:
                keyboard.append(nav_buttons)
            
            # Добавляем кнопку удаления последнего склада, если есть выбранные склады
            if selected_warehouses:
                keyboard.append([InlineKeyboardButton("🗑 Удалить последний", callback_data="remove_last_warehouse")])
            
            keyboard.append([InlineKeyboardButton("✅ Завершить", callback_data="finish_warehouse_selection")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message_text = "Выберите склады для мониторинга коэффициентов:\n"
            if selected_warehouses:
                message_text += "\nВыбранные склады:\n"
                # Используем порядок добавления для отображения
                if chat_id in self.warehouse_selection_order:
                    for warehouse_id in self.warehouse_selection_order[chat_id]:
                        if warehouse_id in selected_warehouses:
                            message_text += f"- {warehouses.get(warehouse_id, 'Неизвестный склад')}\n"
            
            if update.callback_query:
                await update.callback_query.message.edit_text(message_text, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message_text, reply_markup=reply_markup)
                
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в show_warehouse_selection: {str(e)}", exc_info=True)
            if update.callback_query:
                await update.callback_query.message.edit_text("❌ Произошла ошибка при получении списка складов")
            else:
                await update.message.reply_text("❌ Произошла ошибка при получении списка складов")

    async def handle_warehouse_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        chat_id = update.effective_chat.id
        
        if query.data.startswith("select_warehouse_"):
            warehouse_id = int(query.data.split("_")[-1])
            if chat_id not in self.warehouse_selection:
                self.warehouse_selection[chat_id] = set()
            self.warehouse_selection[chat_id].add(warehouse_id)
            await self.show_warehouse_selection(update, context)
            
        elif query.data.startswith("warehouse_page_"):
            page = int(query.data.split("_")[-1])
            await self.show_warehouse_selection(update, context, page)
            
        elif query.data == "remove_last_warehouse":
            try:
                if chat_id in self.warehouse_selection and self.warehouse_selection[chat_id]:
                    # Преобразуем множество в список, удаляем последний элемент и создаем новое множество
                    warehouses_list = list(self.warehouse_selection[chat_id])
                    removed_warehouse = warehouses_list.pop()
                    self.warehouse_selection[chat_id] = set(warehouses_list)
                    
                    # Получаем список всех складов для отображения названия удаленного склада
                    warehouses = await self.get_warehouse_list(context, chat_id)
                    removed_name = warehouses.get(removed_warehouse, 'Неизвестный склад')
                    
                    # Обновляем страницу с текущим списком складов
                    await self.show_warehouse_selection(update, context, 0)
                    
                    # Отправляем уведомление об удалении
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🗑 Удален склад: {removed_name}"
                    )
            except Exception as e:
                logger.critical(f"CRITICAL: Ошибка при удалении последнего склада: {str(e)}", exc_info=True)
                await query.message.edit_text("❌ Произошла ошибка при удалении склада")
            
        elif query.data == "finish_warehouse_selection":
            if chat_id in self.warehouse_selection and self.warehouse_selection[chat_id]:
                await self.start_auto_coefficients(chat_id)
                await query.message.edit_text(
                    f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_COEFFICIENTS_INTERVAL']} минут(ы) в рабочее время)"
                )
            else:
                await query.message.edit_text("❌ Не выбрано ни одного склада")
                # Вызываем команду /start
                await start(update, context)

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
        
        if query.data == 'check_coefficients':
            keyboard = [
                [InlineKeyboardButton("Все склады", callback_data='check_all_coefficients')],
                [InlineKeyboardButton("Запустить авто лимиты", callback_data='start_auto_coefficients')],
                [InlineKeyboardButton("Остановить авто лимиты", callback_data='stop_auto_coefficients')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("Выберите действие:", reply_markup=reply_markup)
            return
            
        elif query.data == 'check_all_coefficients':
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            await bot.get_warehouse_coefficients(fake_context)
            
        elif query.data == 'start_auto_coefficients':
            try:
                if not CONFIG['TARGET_WAREHOUSE_ID']:
                    await bot.show_warehouse_selection(update, context)
                else:
                    await bot.start_auto_coefficients(update.effective_chat.id)
                    await query.message.edit_text(
                        f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_COEFFICIENTS_INTERVAL']} минут(ы) в рабочее время)"
                    )
            except Exception as e:
                logger.critical(f"CRITICAL: Ошибка в start_auto_coefficients: {str(e)}", exc_info=True)
                await query.message.edit_text("❌ Произошла ошибка при запуске автоматических проверок")
                
        elif query.data == 'stop_auto_coefficients':
            if await bot.stop_auto_coefficients(update.effective_chat.id):
                await query.message.edit_text("🛑 Автоматические проверки остановлены")
            else:
                await query.message.edit_text("ℹ️ Нет активных автоматических проверок")

        # Обработка выбора складов
        elif query.data.startswith('select_warehouse_'):
            warehouse_id = int(query.data.split('_')[-1])
            chat_id = update.effective_chat.id
            
            if chat_id not in bot.warehouse_selection:
                bot.warehouse_selection[chat_id] = set()
            if chat_id not in bot.warehouse_selection_order:
                bot.warehouse_selection_order[chat_id] = []
            
            bot.warehouse_selection[chat_id].add(warehouse_id)
            bot.warehouse_selection_order[chat_id].append(warehouse_id)
            await bot.show_warehouse_selection(update, context)
            
        elif query.data.startswith('warehouse_page_'):
            page = int(query.data.split('_')[-1])
            await bot.show_warehouse_selection(update, context, page)
            
        elif query.data == 'remove_last_warehouse':
            try:
                chat_id = update.effective_chat.id
                if chat_id in bot.warehouse_selection and bot.warehouse_selection[chat_id]:
                    # Получаем список всех складов для отображения названия удаленного склада
                    warehouses = await bot.get_warehouse_list(context, chat_id)
                    if not warehouses:
                        raise Exception("Не удалось получить список складов")
                    
                    # Удаляем последний добавленный склад
                    if chat_id in bot.warehouse_selection_order and bot.warehouse_selection_order[chat_id]:
                        removed_warehouse = bot.warehouse_selection_order[chat_id].pop()
                        bot.warehouse_selection[chat_id].remove(removed_warehouse)
                        
                        removed_name = warehouses.get(removed_warehouse, 'Неизвестный склад')
                        
                        # Обновляем страницу с текущим списком складов
                        await bot.show_warehouse_selection(update, context, 0)
                        
                        # Отправляем уведомление об удалении
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"🗑 Удален склад: {removed_name}"
                        )
            except Exception as e:
                logger.critical(f"CRITICAL: Ошибка при удалении последнего склада: {str(e)}", exc_info=True)
                await query.message.edit_text("❌ Произошла ошибка при удалении склада")
            
        elif query.data == 'finish_warehouse_selection':
            chat_id = update.effective_chat.id
            if chat_id in bot.warehouse_selection and bot.warehouse_selection[chat_id]:
                await bot.start_auto_coefficients(chat_id)
                await query.message.edit_text(
                    f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_COEFFICIENTS_INTERVAL']} минут(ы) в рабочее время)"
                )
            else:
                await query.message.edit_text("❌ Не выбрано ни одного склада")
                # Вызываем команду /start
                await start(update, context)
                
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
    
    # Обработчики команд
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
            f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_STOCK_INTERVAL']} минут(ы) в рабочее время)"
        )
    
    async def stop_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if await bot.stop_periodic_checks(update.effective_chat.id):
            await update.message.reply_text("🛑 Автоматические проверки остановлены")
        else:
            await update.message.reply_text("ℹ️ Нет активных автоматических проверок")
    
    async def check_coefficients(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")

            keyboard = [
                [InlineKeyboardButton("Все склады", callback_data='check_all_coefficients')],
                [InlineKeyboardButton("Запустить авто лимиты", callback_data='start_auto_coefficients')],
                [InlineKeyboardButton("Остановить авто лимиты", callback_data='stop_auto_coefficients')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в check_coefficients: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("check_stock", check_stock))
    application.add_handler(CommandHandler("start_auto_stock", start_auto_stock))
    application.add_handler(CommandHandler("stop_auto_stock", stop_auto_stock))
    application.add_handler(CommandHandler("check_coefficients", check_coefficients))
    
    # Регистрация обработчиков callback-запросов
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