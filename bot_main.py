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
from mongo_db import MongoDB
import telegram

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

# Класс бота
class WBStockBot:
    def __init__(self, application):
        self.application = application
        self.active_jobs = {}
        self.active_coefficient_jobs = {}  # Для хранения задач проверки коэффициентов
        self.user_data = UserData()
        self.mongo = MongoDB()
        self.timezone = pytz.timezone('Europe/Moscow')
        self.warehouse_selection = {}  # Инициализация словаря для хранения выбранных складов
        self.warehouse_selection_order = {}  # Инициализация словаря для хранения порядка складов
        
        # Загружаем сохраненные склады для всех пользователей
        self.load_saved_warehouses()

    def load_saved_warehouses(self):
        """Загрузка сохраненных складов для всех пользователей"""
        users = self.mongo.settings.find({'user_id': {'$exists': True}})
        for user in users:
            user_id = user['user_id']
            warehouses = self.mongo.get_selected_warehouses(user_id)
            if warehouses:
                self.warehouse_selection[user_id] = set(warehouses)
                self.warehouse_selection_order[user_id] = warehouses

    # Проверка на рабочее время
    def is_working_time(self, user_id: int, is_auto_check: bool = False):
        """Проверка на рабочее время"""
        try:
            # Если это не автоматическая проверка, пропускаем проверку рабочего времени
            if not is_auto_check:
                return True
                
            settings = self.mongo.get_user_settings(user_id)
            if not settings:
                logger.error(f"No settings found for user {user_id} in is_working_time")
                return False
                
            now = datetime.now(self.timezone)
            current_time = now.time()
            
            # Получаем время начала и конца рабочего дня
            working_hours = settings.get('working_hours', {})
            working_hours_start = working_hours.get('start', 9)
            working_hours_end = working_hours.get('end', 22)
            
            # Если start=0 и end=0, значит ограничений по времени нет
            if working_hours_start == 0 and working_hours_end == 0:
                logger.info(f"No working hours restrictions for user {user_id}")
                return True
            
            working_hours_start = time(hour=working_hours_start)
            working_hours_end = time(hour=working_hours_end)
            
            logger.info(f"Checking working hours for user {user_id}:")
            logger.info(f"Current time: {current_time}")
            logger.info(f"Working hours start: {working_hours_start}")
            logger.info(f"Working hours end: {working_hours_end}")
            logger.info(f"Settings: {settings}")
            
            is_working = working_hours_start <= current_time < working_hours_end
            logger.info(f"Is working time: {is_working}")
            
            return is_working
        except Exception as e:
            logger.error(f"Error checking working hours for user {user_id}: {str(e)}", exc_info=True)
            return False

    # Форматирование данных о складе
    def format_stock_data(self, data, user_id: int, highlight_low=False):
        if not isinstance(data, list):
            return None
        result = []
        low_stock_items = []
        
        user_settings = self.mongo.get_user_settings(user_id)
        global_settings = self.mongo.get_global_settings()
        
        # Используем пользовательские настройки, если они есть, иначе глобальные
        low_stock_threshold = user_settings.get('low_stock_threshold', global_settings.get('low_stock_threshold', 20))
        
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
            
            if quantity <= low_stock_threshold:
                low_stock_items.append(item_text)
        
        if highlight_low:
            return low_stock_items
        return result
    
    #Основная функция получения данных
    async def fetch_wb_data(self, context: ContextTypes.DEFAULT_TYPE):
        chat_id = context.job.chat_id if hasattr(context, 'job') else context._chat_id
        
        # Проверяем рабочее время только для автоматических проверок
        is_auto_check = hasattr(context, 'job')
        if is_auto_check and not self.is_working_time(chat_id, True):
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
            
            settings = self.mongo.get_user_settings(chat_id)
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                await context.bot.send_message(chat_id=chat_id, text="🔄 Считаю остатки..")
                first_response = await self.make_api_request(session, settings['api']['urls']['stock_request'], headers, context, chat_id)
                
                if not first_response:
                    return
                
                task_id = first_response.get('data', {}).get('taskId')
                if not task_id:
                    await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить task ID")
                    return
                
                await asyncio.sleep(settings['api']['request_delay'])
                
                second_url = settings['api']['urls']['stock_download'].format(task_id=task_id)
                stock_data = await self.make_api_request(session, second_url, headers, context, chat_id)
                
                if not stock_data:
                    return
                
                formatted_data = self.format_stock_data(stock_data, chat_id)
                low_stock_data = self.format_stock_data(stock_data, chat_id, highlight_low=True)
                
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
            # Получаем настройки
            settings = self.mongo.get_user_settings(chat_id)
            if not settings:
                logger.error(f"No settings found for user {chat_id} in get_warehouse_coefficients")
                return
            
            # Проверяем, нужно ли сбросить отключенные склады
            warehouses = settings.get('warehouses', {})
            paused_warehouses = warehouses.get('paused', [])
            target_warehouses = warehouses.get('target', [])
            
            # Если это не автоматическая проверка (запрос "Все склады"), 
            # то пропускаем проверку на отключенные склады
            is_auto_check = hasattr(context, 'job')
            
            if is_auto_check and paused_warehouses:
                last_notification = self.mongo.get_last_notification(chat_id)
                if last_notification:
                    working_hours = settings.get('working_hours', {})
                    next_day_start = datetime.combine(
                        last_notification.date() + timedelta(days=1),
                        time(hour=working_hours.get('start', 9))
                    )
                    # Преобразуем next_day_start в aware datetime с нужным часовым поясом
                    next_day_start = self.timezone.localize(next_day_start)
                    current_time = datetime.now(self.timezone)
                    
                    if current_time >= next_day_start:
                        # Очищаем paused склады
                        self.mongo.update_user_settings(chat_id, {
                            'warehouses': {
                                'paused': []
                            }
                        })
                        logger.info(f"Reset paused warehouses for user {chat_id} as it's next day")
                        # Обновляем настройки после сброса
                        settings = self.mongo.get_user_settings(chat_id)
            
            # Получаем токен пользователя
            wb_token = self.user_data.get_user_token(chat_id)
            if not wb_token:
                await context.bot.send_message(chat_id=chat_id, text="❌ Токен WB не найден. Пожалуйста, добавьте токен через команду /start. Требуются права Статистика, Аналитика, Поставки")
                return

            # Проверяем, есть ли отключенные склады
            warehouses = settings.get('warehouses', {})
            paused_warehouses = warehouses.get('paused', [])
            target_warehouses = warehouses.get('target', [])
            
            # Если все целевые склады отключены, пропускаем проверку
            if target_warehouses and all(str(wh) in paused_warehouses for wh in target_warehouses):
                logger.info(f"All target warehouses are paused for user {chat_id}, skipping check")
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
                
                # Получаем коэффициенты и тарифы параллельно
                coefficients_response = await self.make_api_request(session, settings['api']['urls']['coefficients'], headers, context, chat_id)
                tariffs_data = await self.get_warehouse_tariffs(context, chat_id)
                
                if not coefficients_response or not isinstance(coefficients_response, list):
                    await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить данные о коэффициентах")
                    return
                
                # Получаем настройки складов
                warehouses = settings.get('warehouses', {})
                target_warehouses = warehouses.get('target', [])
                excluded_warehouses = warehouses.get('excluded', [])
                paused_warehouses = warehouses.get('paused', [])
                
                target_names = set()  # Для хранения названий целевых складов
                excluded_names = set()  # Для хранения названий исключенных складов
                
                # Фильтруем и группируем данные
                filtered_data = {}
                
                for item in coefficients_response:
                    warehouse_id = None
                    try:
                        warehouse_id = item.get('warehouseID')
                        if warehouse_id is None:
                            continue
                            
                        warehouse_id = int(warehouse_id)
                        warehouse_name = item.get('warehouseName', 'N/A')
                        
                        # Пропускаем временно отключенные склады
                        if str(warehouse_id) in paused_warehouses:
                            continue
                        
                        # Собираем названия целевых складов
                        if warehouse_id in target_warehouses:
                            target_names.add(warehouse_name)
                        
                        # Пропускаем склады из списка исключений
                        if str(warehouse_id) in excluded_warehouses:
                            excluded_names.add(warehouse_name)
                            continue
                        
                        # Если указаны целевые склады, пропускаем все остальные
                        if target_warehouses and warehouse_id not in target_warehouses:
                            continue
                        
                        # Проверяем остальные условия фильтрации
                        thresholds = settings.get('thresholds', {})
                        if (item.get('boxTypeName') == "Короба" and 
                            item.get('coefficient') >= thresholds.get('min_coefficient', 0) and 
                            item.get('coefficient') <= thresholds.get('max_coefficient', 6)):
                            
                            date = item.get('date', 'N/A')
                            coefficient = item.get('coefficient', 'N/A')
                            
                            try:
                                date = date.replace('Z', '')
                                date_obj = datetime.fromisoformat(date)
                                formatted_date = date_obj.strftime('%d.%m.%Y')
                            except:
                                formatted_date = date
                            
                            if warehouse_name not in filtered_data:
                                filtered_data[warehouse_name] = {
                                    'dates': [],
                                    'tariff': None,
                                    'base_cost': None,
                                    'liter_cost': None
                                }
                            
                            filtered_data[warehouse_name]['dates'].append({
                                'date': formatted_date,
                                'coefficient': coefficient
                            })
                            
                    except (ValueError, TypeError):
                        continue
                
                # Добавляем информацию о тарифах
                if tariffs_data and 'warehouseList' in tariffs_data:
                    for warehouse in tariffs_data['warehouseList']:
                        warehouse_name = warehouse.get('warehouseName')
                        base_cost = warehouse.get('boxDeliveryBase', 0)
                        liter_cost = warehouse.get('boxDeliveryLiter', 0)
                        # Специальный случай для Новосемейкино
                        if warehouse_name == "Самара (Новосемейкино)":
                            if "Новосемейкино" in filtered_data:
                                filtered_data["Новосемейкино"]['tariff'] = warehouse.get('boxDeliveryAndStorageExpr')
                                filtered_data["Новосемейкино"]['base_cost'] = base_cost
                                filtered_data["Новосемейкино"]['liter_cost'] = liter_cost
                        elif warehouse_name == "Краснодар":
                            if "Краснодар (Тихорецкая)" in filtered_data:
                                filtered_data["Краснодар (Тихорецкая)"]['tariff'] = warehouse.get('boxDeliveryAndStorageExpr')
                                filtered_data["Краснодар (Тихорецкая)"]['base_cost'] = base_cost
                                filtered_data["Краснодар (Тихорецкая)"]['liter_cost'] = liter_cost
                        elif warehouse_name in filtered_data:
                            filtered_data[warehouse_name]['tariff'] = warehouse.get('boxDeliveryAndStorageExpr')
                            filtered_data[warehouse_name]['base_cost'] = base_cost
                            filtered_data[warehouse_name]['liter_cost'] = liter_cost
                
                # Сортируем данные по дате для каждого склада
                for warehouse in filtered_data:
                    filtered_data[warehouse]['dates'].sort(key=lambda x: datetime.strptime(x['date'], '%d.%m.%Y'))
                
                # Формируем сообщение
                MAX_MESSAGE_LENGTH = 3500  # Уменьшаем лимит для надежности
                current_message = "📊 Коэффициенты складов (Короба):\n\n"
                
                # Добавляем информацию о фильтрации
                if target_names:
                    current_message += f"*Целевые склады:* {', '.join(sorted(target_names))}\n"
                if excluded_names:
                    current_message += f"*Исключенные склады:* {', '.join(sorted(excluded_names))}\n"
                current_message += "\n"
                
                # Формируем все сообщения заранее
                messages = []
                has_data = False
                for warehouse_name, data in filtered_data.items():
                    if not data['dates']:  # Пропускаем склады без данных
                        continue
                    has_data = True
                    new_line = f"*{warehouse_name}*:\n"
                    if data['tariff']:
                        tariff = int(data['tariff'])
                        base_cost = data.get('base_cost', 0)
                        liter_cost = data.get('liter_cost', 0)
                        if 0 <= tariff <= 130:
                            new_line += f"Кф. склада: `{data['tariff']}%` ✅\n"
                            new_line += f"Логистика: `{base_cost} руб.+ {liter_cost} доп.л`\n"
                        elif 131 <= tariff <= 150:
                            new_line += f"Кф. склада: `{data['tariff']}%` ⚠️\n"
                            new_line += f"Логистика: `{base_cost} руб.+ {liter_cost} доп.л`\n"
                        else:
                            new_line += f"Кф. склада: `{data['tariff']}%` ❌\n"
                            new_line += f"Логистика: `{base_cost} руб.+ {liter_cost} доп.л`\n"
                    for item in data['dates']:
                        new_line += f"--- {item['date']} = {item['coefficient']}\n"
                    new_line += "\n"
                    
                    if len(current_message) + len(new_line) > MAX_MESSAGE_LENGTH:
                        messages.append(current_message)
                        current_message = new_line
                    else:
                        current_message += new_line
                
                if current_message:
                    messages.append(current_message)
                
                # Если нет данных и это автоматическая проверка, не отправляем сообщение
                if not has_data and hasattr(context, 'job'):
                    return
                
                # Отправляем все сообщения
                keyboard = None
                if target_warehouses and hasattr(context, 'job'):
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "🔕 Выключить до завтра",
                            callback_data=f"disable_warehouses:{','.join(target_names)}"
                        )],
                        [InlineKeyboardButton(
                            "🛑 Выключить совсем",
                            callback_data="stop_auto_coefficients"
                        )]
                    ])

                for i, message in enumerate(messages):
                    try:
                        # Добавляем кнопки только к последнему сообщению, если это автоматическая проверка
                        if i == len(messages) - 1 and keyboard:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode='Markdown',
                                reply_markup=keyboard
                            )
                        else:
                            await context.bot.send_message(
                                chat_id=chat_id,
                                text=message,
                                parse_mode='Markdown'
                            )
                    except Exception as e:
                        logger.error(f"Ошибка при отправке сообщения {i+1}/{len(messages)}: {str(e)}")
                        # Пробуем отправить сообщение частями
                        try:
                            # Разбиваем сообщение на части по 3000 символов
                            parts = [message[i:i+3000] for i in range(0, len(message), 3000)]
                            for j, part in enumerate(parts):
                                # Добавляем кнопки только к последней части последнего сообщения, если это автоматическая проверка
                                if i == len(messages) - 1 and j == len(parts) - 1 and keyboard:
                                    await context.bot.send_message(
                                        chat_id=chat_id,
                                        text=f"Часть {j+1} из {len(parts)}:\n{part}",
                                        parse_mode='Markdown',
                                        reply_markup=keyboard
                                    )
                                else:
                                    await context.bot.send_message(
                                        chat_id=chat_id,
                                        text=f"Часть {j+1} из {len(parts)}:\n{part}",
                                        parse_mode='Markdown'
                                    )
                        except Exception as e:
                            logger.error(f"Не удалось отправить даже разбитое сообщение: {str(e)}")
                
                # Обновляем время последнего уведомления
                self.mongo.update_last_notification(chat_id)
                
                # Проверяем, нужно ли сбросить отключенные склады
                if paused_warehouses:
                    last_notification = self.mongo.get_last_notification(chat_id)
                    if last_notification:
                        working_hours = settings.get('working_hours', {})
                        next_day_start = datetime.combine(
                            last_notification.date() + timedelta(days=1),
                            time(hour=working_hours.get('start', 9))
                        )
                        if datetime.utcnow() >= next_day_start:
                            # Очищаем paused склады
                            self.mongo.update_user_settings(chat_id, {
                                'warehouses': {
                                    'paused': []
                                }
                            })
            
        except Exception as e:
            logger.critical(f"CRITICAL ERROR for chat {chat_id}: {str(e)}", exc_info=True)
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Произошла критическая ошибка: {str(e)}")

    async def process_disable_warehouses(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатия кнопки 'Выключить до завтра'"""
        query = update.callback_query
        user_id = query.from_user.id
        warehouses = query.data.split(':')[1].split(',')
        
        try:
            # Получаем настройки
            settings = self.mongo.get_user_settings(user_id)
            if not settings:
                await query.answer("❌ Ошибка: не удалось получить настройки")
                return
            
            # Получаем ID складов из названий
            warehouses_data = await self.get_warehouse_list(context, user_id)
            if not warehouses_data:
                await query.answer("❌ Ошибка: не удалось получить список складов")
                return
                
            # Находим ID складов по их названиям
            warehouse_ids = []
            for warehouse_name in warehouses:
                warehouse_id = next((id for id, name in warehouses_data.items() if name == warehouse_name), None)
                if warehouse_id:
                    warehouse_ids.append(str(warehouse_id))
            
            if warehouse_ids:
                # Добавляем ID складов в paused
                self.mongo.update_user_settings(user_id, {
                    'warehouses': {
                        'paused': warehouse_ids
                    }
                })
                
                # Отправляем сообщение об отключении
                await context.bot.send_message(
                    chat_id=user_id,
                    text="✅ Уведомления по выбранным складам отключены до завтра"
                )
                await query.answer()
            else:
                await query.answer("❌ Ошибка: не удалось найти ID складов")
                
        except Exception as e:
            logger.error(f"Ошибка при отключении складов: {str(e)}")
            await query.answer("❌ Произошла ошибка при отключении складов")

    async def process_stop_auto_coefficients(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатия кнопки 'Выключить совсем'"""
        query = update.callback_query
        user_id = query.from_user.id
        
        try:
            await self.stop_auto_coefficients(user_id)
            await query.answer("✅ Автоматическое отслеживание остановлено")
        except Exception as e:
            logger.error(f"Ошибка при остановке автоотслеживания: {str(e)}")
            await query.answer("❌ Произошла ошибка при остановке автоотслеживания")

    async def start_auto_coefficients(self, chat_id: int):
        try:
            logger.info(f"Starting auto coefficients for user {chat_id}")
            
            if chat_id in self.active_coefficient_jobs:
                logger.info(f"Removing existing job for user {chat_id}")
                self.active_coefficient_jobs[chat_id].schedule_removal()
            
            settings = self.mongo.get_user_settings(chat_id)
            if not settings:
                logger.error(f"No settings found for user {chat_id} in start_auto_coefficients")
                return None
                
            # Используем интервал из настроек
            interval = settings.get('intervals', {}).get('check_coefficients', 1)
            logger.info(f"Using interval {interval} minutes for user {chat_id}")
            
            job = self.application.job_queue.run_repeating(
                callback=self.get_warehouse_coefficients,
                interval=timedelta(minutes=interval),
                first=0,
                chat_id=chat_id,
                name=f"coefficients_{chat_id}"
            )
            
            logger.info(f"Created new job for user {chat_id}")
            self.active_coefficient_jobs[chat_id] = job
            self.mongo.update_auto_coefficients(chat_id, True)
            self.mongo.log_activity(chat_id, 'start_auto_coefficients')
            
            # Проверяем рабочее время
            is_working = self.is_working_time(chat_id, True)
            logger.info(f"Working time check for user {chat_id}: {is_working}")
            
            return job
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка запуска автоматических проверок коэффициентов: {str(e)}", exc_info=True)
            raise

    async def stop_auto_coefficients(self, chat_id: int):
        try:
            if chat_id in self.active_coefficient_jobs:
                self.active_coefficient_jobs[chat_id].schedule_removal()
                del self.active_coefficient_jobs[chat_id]
                self.mongo.update_auto_coefficients(chat_id, False)
                # Очищаем paused и target склады
                self.mongo.update_user_settings(chat_id, {
                    'warehouses': {
                        'paused': [],
                        'target': []
                    }
                })
                self.mongo.log_activity(chat_id, 'stop_auto_coefficients')
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
            
            settings = self.mongo.get_user_settings(chat_id)
            async with aiohttp.ClientSession() as session:
                response = await self.make_api_request(session, settings['api']['urls']['coefficients'], headers, context, chat_id)
                
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
            
            # Получаем уже выбранные склады из БД
            selected_warehouses = set(self.mongo.get_selected_warehouses(chat_id))
            
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
                for warehouse_id in selected_warehouses:
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
        try:
            await query.answer()
        except telegram.error.BadRequest as e:
            if "Query is too old" in str(e) or "query id is invalid" in str(e):
                logger.warning(f"Callback query is too old or invalid: {str(e)}")
            else:
                raise e
        
        chat_id = update.effective_chat.id
        
        if query.data.startswith("select_warehouse_"):
            warehouse_id = int(query.data.split("_")[-1])
            # Получаем текущие склады из БД
            current_warehouses = self.mongo.get_selected_warehouses(chat_id)
            # Добавляем новый склад
            current_warehouses.append(warehouse_id)
            # Сохраняем обновленный список в БД
            self.mongo.save_selected_warehouses(chat_id, current_warehouses)
            await self.show_warehouse_selection(update, context)
            
        elif query.data.startswith("warehouse_page_"):
            page = int(query.data.split("_")[-1])
            await self.show_warehouse_selection(update, context, page)
            
        elif query.data == "remove_last_warehouse":
            try:
                # Получаем текущие склады из БД
                current_warehouses = self.mongo.get_selected_warehouses(chat_id)
                if current_warehouses:
                    # Удаляем последний склад
                    removed_warehouse = current_warehouses.pop()
                    # Сохраняем обновленный список в БД
                    self.mongo.save_selected_warehouses(chat_id, current_warehouses)
                    
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
            # Получаем текущие склады из БД
            current_warehouses = self.mongo.get_selected_warehouses(chat_id)
            if current_warehouses:
                await self.start_auto_coefficients(chat_id)
                await query.message.edit_text(
                    f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_COEFFICIENTS_INTERVAL']} минут(ы) в рабочее время)"
                )
            else:
                await query.message.edit_text("❌ Не выбрано ни одного склада")
                # Вызываем команду /start
                await start(update, context)

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            user_id = update.effective_user.id
            # Передаем telegram_user при обновлении активности
            self.mongo.update_user_activity(user_id, update.effective_user)
            
            if context.user_data.get('waiting_for_token'):
                token = update.message.text.strip()
                self.user_data.add_user(user_id, token)
                self.mongo.init_user(user_id)
                # Логируем добавление токена
                self.mongo.log_activity(user_id, 'token_added')
                context.user_data['waiting_for_token'] = False
                
                await update.message.reply_text(
                    "✅ Токен успешно добавлен!\n"
                    "Теперь вы можете использовать бота. Удачи!\n\n"
                    "Для управления ботом используйте главное меню"
                )
            elif context.user_data.get('waiting_for_broadcast'):
                # Проверяем уровень подписки
                subscription_level = self.mongo.get_subscription_level(user_id)
                if subscription_level != "Admin":
                    await update.message.reply_text("❌ У вас нет доступа к этой функции")
                    return
                # Сохраняем текст сообщения
                context.user_data['broadcast_text'] = update.message.text
                await update.message.reply_text(
                    "✅ Текст сообщения сохранен. Нажмите кнопку 'Отправить' для рассылки."
                )
            else:
                # Логируем обычное сообщение
                self.mongo.log_activity(user_id, 'message_received')
                await update.message.reply_text(
                    "Для управления ботом используйте главное меню"
                )
                
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в обработчике сообщений: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")

    async def get_warehouse_tariffs(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int = None):
        """Получение тарифов складов"""
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
            
            settings = self.mongo.get_user_settings(chat_id)
            # Формируем текущую дату в нужном формате
            current_date = datetime.now().strftime('%Y-%m-%d')
            url = settings['api']['urls']['warehouse_tariffs'].format(date_now=current_date)
            
            async with aiohttp.ClientSession() as session:
                response = await self.make_api_request(session, url, headers, context, chat_id)
                
                if not response or 'response' not in response or 'data' not in response['response']:
                    return None
                
                return response['response']['data']
        except Exception as e:
            logger.critical(f"CRITICAL ERROR getting warehouse tariffs for chat {chat_id}: {str(e)}", exc_info=True)
            return None

    async def admin_statistics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /admin_statistics"""
        try:
            user_id = update.effective_user.id
            
            # Проверяем уровень подписки
            subscription_level = self.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await update.message.reply_text("❌ У вас нет доступа к этой команде")
                return
            
            # Получаем статистику
            stats = self.mongo.get_user_statistics()
            
            # Формируем сообщение
            message = (
                f"📊 Статистика:\n\n"
                f"Всего пользователей: {stats['total']}\n"
                f"Base: {stats['base']}\n"
                f"Premium: {stats['premium']}"
            )
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {str(e)}")
            await update.message.reply_text("❌ Произошла ошибка при получении статистики")
            
    async def get_sales_data(self, context: ContextTypes.DEFAULT_TYPE, period_type: str = 'day'):
        """Получение данных о продажах"""
        try:
            chat_id = context.job.chat_id if hasattr(context, 'job') else context._chat_id
            
            wb_token = self.user_data.get_user_token(chat_id)
            if not wb_token:
                await context.bot.send_message(chat_id=chat_id, text="❌ Токен WB не найден")
                return None

            headers = {
                'Accept': 'application/json',
                'Authorization': wb_token
            }
            
            settings = self.mongo.get_user_settings(chat_id)
            if not settings:
                logger.error(f"No settings found for user {chat_id}")
                return None

            # Формируем даты для периода
            now = datetime.now(self.timezone)
            if period_type == 'day':
                begin_date = now.replace(hour=0, minute=0, second=1)
                end_date = now.replace(hour=23, minute=59, second=59)
            else:  # week
                begin_date = (now - timedelta(days=7)).replace(hour=0, minute=0, second=1)
                end_date = now.replace(hour=23, minute=59, second=59)

            # Формируем тело запроса
            request_data = {
                "brandNames": [],
                "objectIDs": [],
                "tagIDs": [],
                "nmIDs": [],
                "timezone": "Europe/Moscow",
                "period": {
                    "begin": begin_date.strftime("%Y-%m-%d %H:%M:%S"),
                    "end": end_date.strftime("%Y-%m-%d %H:%M:%S")
                },
                "orderBy": {
                    "field": "ordersSumRub",
                    "mode": "asc"
                },
                "page": 1
            }

            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                response = await self.make_api_request(
                    session,
                    settings['api']['urls']['sales_request'],
                    headers,
                    context,
                    chat_id,
                    method='POST',
                    json_data=request_data
                )

                if not response or 'data' not in response:
                    return None

                return response['data']

        except Exception as e:
            logger.error(f"Ошибка при получении данных о продажах: {str(e)}")
            return None

    async def format_sales_message(self, sales_data: dict, period_type: str) -> str:
        """Форматирование сообщения со статистикой продаж"""
        try:
            if not sales_data or 'cards' not in sales_data:
                return "❌ Нет данных о продажах"

            # Группируем данные по дням и артикулам
            sales_by_day = {}
            total_orders = 0
            total_sum = 0

            for card in sales_data['cards']:
                vendor_code = card.get('vendorCode', 'N/A')
                stats = card.get('statistics', {}).get('selectedPeriod', {})
                orders_count = stats.get('ordersCount', 0)
                orders_sum = stats.get('ordersSumRub', 0)

                if orders_count > 0:
                    total_orders += orders_count
                    total_sum += orders_sum

                    # Получаем дату из периода
                    begin_date = datetime.fromisoformat(stats.get('begin', '').replace('Z', ''))
                    date_str = begin_date.strftime('%d.%m.%Y')

                    if date_str not in sales_by_day:
                        sales_by_day[date_str] = []

                    sales_by_day[date_str].append({
                        'vendor_code': vendor_code,
                        'orders_count': orders_count
                    })

            # Формируем сообщение
            if period_type == 'day':
                message = f"Продажи за {list(sales_by_day.keys())[0]}:\n"
            else:
                message = f"Продажи за период {list(sales_by_day.keys())[0]} - {list(sales_by_day.keys())[-1]}:\n"

            for date, sales in sales_by_day.items():
                for sale in sales:
                    message += f"- Артикул: {sale['vendor_code']}\n"
                    message += f"- Заказали: {sale['orders_count']}\n"
                    message += "---------------------------\n"

            message += f"\nИтого:\n"
            message += f"-- {total_orders} шт.\n"
            message += f"-- на {total_sum} руб."

            return message

        except Exception as e:
            logger.error(f"Ошибка при форматировании сообщения о продажах: {str(e)}")
            return "❌ Ошибка при формировании статистики"

    async def sales_day(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик статистики продаж за день"""
        try:
            user_id = update.effective_user.id
            # Логируем запрос статистики за день
            self.mongo.log_activity(user_id, 'sales_day_requested')
            
            # Получаем данные о продажах
            sales_data = await self.get_sales_data(context, 'day')
            if not sales_data:
                await update.message.reply_text("❌ Не удалось получить данные о продажах")
                return

            # Форматируем и отправляем сообщение
            message = await self.format_sales_message(sales_data, 'day')
            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"Ошибка при получении статистики за день: {str(e)}")
            await update.message.reply_text("❌ Произошла ошибка при получении статистики")

    async def sales_week(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик статистики продаж за неделю"""
        try:
            user_id = update.effective_user.id
            # Логируем запрос статистики за неделю
            self.mongo.log_activity(user_id, 'sales_week_requested')
            
            # Получаем данные о продажах
            sales_data = await self.get_sales_data(context, 'week')
            if not sales_data:
                await update.message.reply_text("❌ Не удалось получить данные о продажах")
                return

            # Форматируем и отправляем сообщение
            message = await self.format_sales_message(sales_data, 'week')
            await update.message.reply_text(message)

        except Exception as e:
            logger.error(f"Ошибка при получении статистики за неделю: {str(e)}")
            await update.message.reply_text("❌ Произошла ошибка при получении статистики")

    async def sales_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /sales"""
        try:
            user_id = update.effective_user.id
            # Логируем открытие меню статистики
            self.mongo.log_activity(user_id, 'sales_menu_opened')
            
            keyboard = [
                [InlineKeyboardButton("День", callback_data='sales_day')],
                [InlineKeyboardButton("Неделя", callback_data='sales_week')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "Статистика продаж:",
                reply_markup=reply_markup
            )

        except Exception as e:
            logger.error(f"Ошибка при открытии меню статистики: {str(e)}")
            await update.message.reply_text("❌ Произошла ошибка при открытии меню статистики")

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        if not bot:
            raise Exception("Бот не инициализирован")

        user_id = update.effective_user.id
        first_name = update.effective_user.first_name
        last_name = update.effective_user.last_name
        username = update.effective_user.username
        
        logger.info(f"Start command received from user {user_id}")
        
        # Логируем начало взаимодействия до проверки существования пользователя
        bot.mongo.log_activity(user_id, 'start_command')
        
        logger.info(f"User exists check: {bot.user_data.is_user_exists(user_id)}")
        
        if not bot.user_data.is_user_exists(user_id):
            logger.info(f"Initializing new user {user_id}")
            await update.message.reply_text(
                "👋 Привет! Я бот для работы с Wildberries.\n"
                "Для начала работы необходимо добавить ваш WB токен:\n"
                "Статистика, Аналитика, Поставки\n\n"
                "Введите ваш токен:"
            )
            context.user_data['waiting_for_token'] = True
            # Инициализируем пользователя в MongoDB
            bot.mongo.init_user(user_id, first_name, username, last_name)
            logger.info(f"User {user_id} initialized in MongoDB")
        else:
            # Обновляем информацию о пользователе
            bot.mongo.update_user_activity(user_id, update.effective_user)
            logger.info(f"User {user_id} already exists")
            
            # Получаем уровень подписки пользователя
            subscription_level = bot.mongo.get_subscription_level(user_id)
            
            # Базовое сообщение
            message = "Для управления ботом используйте главное меню"
            
            # Добавляем информацию о подписке в зависимости от уровня
            if subscription_level == "Premium":
                message += "\n\nPremium"
                keyboard = [[InlineKeyboardButton("Premium", callback_data='premium_info')]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(message, reply_markup=reply_markup)
            elif subscription_level == "Admin":
                message += "\n\nПривет, Admin!"
                keyboard = [
                    [InlineKeyboardButton("✉️ Сообщение", callback_data='send_messages')],
                    [InlineKeyboardButton("📋 Статистика", callback_data='admin_statistics')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в start: {str(e)}", exc_info=True)

# Обработчик нажатий на кнопки
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    bot = context.bot_data.get('wb_bot')
    
    if not bot:
        await query.message.edit_text("❌ Бот не инициализирован")
        return
        
    try:
        user_id = update.effective_user.id
        # Обновляем информацию о пользователе при каждом взаимодействии
        bot.mongo.update_user_activity(user_id, update.effective_user)
        
        if query.data == 'premium_info':
            await query.message.edit_text("Premium")
            return
            
        elif query.data == 'send_messages':
            # Проверяем уровень подписки
            subscription_level = bot.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await query.message.edit_text("❌ У вас нет доступа к этой функции")
                return
            # Сохраняем состояние ожидания сообщения
            context.user_data['waiting_for_broadcast'] = True
            keyboard = [[InlineKeyboardButton("Отправить", callback_data='broadcast_message')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                "Введите текст сообщения для отправки всем пользователям:",
                reply_markup=reply_markup
            )
            return
            
        elif query.data == 'broadcast_message':
            # Проверяем уровень подписки
            subscription_level = bot.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await query.message.edit_text("❌ У вас нет доступа к этой функции")
                return
            # Проверяем, есть ли сохраненное сообщение
            if 'broadcast_text' not in context.user_data:
                await query.message.edit_text("❌ Сначала введите текст сообщения")
                return
            # Получаем текст сообщения
            message_text = context.user_data['broadcast_text']
            # Получаем список всех пользователей
            users = bot.mongo.get_all_users()
            # Получаем список заблокированных пользователей
            banned_users = bot.mongo.get_banned_users()
            # Отправляем сообщение всем пользователям, кроме заблокированных
            success_count = 0
            fail_count = 0
            for user in users:
                if user['user_id'] not in banned_users:
                    try:
                        await context.bot.send_message(
                            chat_id=user['user_id'],
                            text=message_text
                        )
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Ошибка отправки сообщения пользователю {user['user_id']}: {str(e)}")
                        fail_count += 1
            # Отправляем отчет об отправке
            await query.message.edit_text(
                f"✅ Отправка завершена\n"
                f"Успешно отправлено: {success_count}\n"
                f"Ошибок отправки: {fail_count}"
            )
            # Очищаем сохраненное сообщение
            del context.user_data['broadcast_text']
            # Сбрасываем состояние ожидания сообщения
            context.user_data['waiting_for_broadcast'] = False
            return
            
        elif query.data == 'admin_statistics':
            # Проверяем уровень подписки
            subscription_level = bot.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await query.message.edit_text("❌ У вас нет доступа к этой функции")
                return
            
            # Получаем статистику
            stats = bot.mongo.get_user_statistics()
            
            # Формируем сообщение
            message = (
                f"📊 Статистика:\n\n"
                f"Всего пользователей: {stats['total']}\n"
                f"Base: {stats['base']}\n"
                f"Premium: {stats['premium']}"
            )
            
            await query.message.edit_text(message)
            return
            
        elif query.data == 'check_coefficients':
            # Логируем открытие меню коэффициентов
            bot.mongo.log_activity(user_id, 'coefficients_menu_opened')
            keyboard = [
                [InlineKeyboardButton("Все склады", callback_data='check_all_coefficients')],
                [InlineKeyboardButton("Запустить авто лимиты", callback_data='start_auto_coefficients')],
                [InlineKeyboardButton("Остановить авто лимиты", callback_data='stop_auto_coefficients')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text("Выберите действие:", reply_markup=reply_markup)
            return
            
        elif query.data == 'check_all_stock':
            # Логируем запрос на проверку всех остатков
            bot.mongo.log_activity(user_id, 'check_all_stock_requested')
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            await bot.fetch_wb_data(fake_context)
            
        elif query.data == 'start_auto_stock':
            try:
                # Логируем запрос на запуск авто остатков
                bot.mongo.log_activity(user_id, 'start_auto_stock_requested')
                await bot.start_periodic_checks(update.effective_chat.id)
                await query.message.edit_text(
                    f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_STOCK_INTERVAL']} минут(ы) в рабочее время)"
                )
            except Exception as e:
                logger.critical(f"CRITICAL: Ошибка в start_auto_stock: {str(e)}", exc_info=True)
                await query.message.edit_text("❌ Произошла ошибка при запуске автоматических проверок")
                
        elif query.data == 'stop_auto_stock':
            # Логируем запрос на остановку авто остатков
            bot.mongo.log_activity(user_id, 'stop_auto_stock_requested')
            if await bot.stop_periodic_checks(update.effective_chat.id):
                await query.message.edit_text("🛑 Автоматические проверки остановлены")
            else:
                await query.message.edit_text("ℹ️ Нет активных автоматических проверок")
                
        elif query.data == 'check_all_coefficients':
            # Логируем запрос на проверку всех коэффициентов
            bot.mongo.log_activity(user_id, 'check_all_coefficients_requested')
            # Очищаем выбранные склады в БД
            bot.mongo.save_selected_warehouses(user_id, [])
                
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            await bot.get_warehouse_coefficients(fake_context)
            
        elif query.data == 'start_auto_coefficients':
            try:
                # Логируем запрос на запуск авто коэффициентов
                bot.mongo.log_activity(user_id, 'start_auto_coefficients_requested')
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
            # Логируем запрос на остановку авто коэффициентов
            bot.mongo.log_activity(user_id, 'stop_auto_coefficients_requested')
            if await bot.stop_auto_coefficients(update.effective_chat.id):
                await query.message.edit_text("🛑 Автоматические проверки остановлены")
            else:
                await query.message.edit_text("ℹ️ Нет активных автоматических проверок")

        # Обработка выбора складов
        elif query.data.startswith('select_warehouse_'):
            warehouse_id = int(query.data.split('_')[-1])
            chat_id = update.effective_chat.id
            
            # Логируем выбор склада
            bot.mongo.log_activity(user_id, f'warehouse_selected_{warehouse_id}')
            
            # Получаем текущие склады из БД
            current_warehouses = bot.mongo.get_selected_warehouses(chat_id)
            # Добавляем новый склад
            current_warehouses.append(warehouse_id)
            # Сохраняем обновленный список в БД
            bot.mongo.save_selected_warehouses(chat_id, current_warehouses)
            await bot.show_warehouse_selection(update, context)
            
        elif query.data.startswith('warehouse_page_'):
            page = int(query.data.split('_')[-1])
            # Логируем переход по страницам складов
            bot.mongo.log_activity(user_id, f'warehouse_page_{page}')
            await bot.show_warehouse_selection(update, context, page)
            
        elif query.data == 'remove_last_warehouse':
            try:
                chat_id = update.effective_chat.id
                # Получаем текущие склады из БД
                current_warehouses = bot.mongo.get_selected_warehouses(chat_id)
                if current_warehouses:
                    # Логируем удаление последнего склада
                    bot.mongo.log_activity(user_id, 'remove_last_warehouse')
                    
                    # Получаем список всех складов для отображения названия удаленного склада
                    warehouses = await bot.get_warehouse_list(context, chat_id)
                    if not warehouses:
                        raise Exception("Не удалось получить список складов")
                    
                    # Удаляем последний добавленный склад
                    removed_warehouse = current_warehouses.pop()
                    # Сохраняем обновленный список в БД
                    bot.mongo.save_selected_warehouses(chat_id, current_warehouses)
                    
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
            # Логируем завершение выбора складов
            bot.mongo.log_activity(user_id, 'finish_warehouse_selection')
            
            # Получаем текущие склады из БД
            current_warehouses = bot.mongo.get_selected_warehouses(chat_id)
            if current_warehouses:
                await bot.start_auto_coefficients(chat_id)
                await query.message.edit_text(
                    f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_COEFFICIENTS_INTERVAL']} минут(ы) в рабочее время)"
                )
            else:
                await query.message.edit_text("❌ Не выбрано ни одного склада")
                # Вызываем команду /start
                await start(update, context)

        # Обработка новых кнопок
        elif query.data.startswith('disable_warehouses:'):
            # Логируем отключение складов до завтра
            bot.mongo.log_activity(user_id, 'disable_warehouses_until_tomorrow')
            await bot.process_disable_warehouses(update, context)
            
        elif query.data == 'stop_auto_coefficients':
            # Логируем полное отключение автоотслеживания
            bot.mongo.log_activity(user_id, 'stop_auto_coefficients_completely')
            await bot.process_stop_auto_coefficients(update, context)
                
        elif query.data == 'sales_day':
            # Логируем запрос статистики за день
            bot.mongo.log_activity(user_id, 'sales_day_requested')
            # Получаем данные о продажах
            sales_data = await bot.get_sales_data(context, 'day')
            if not sales_data:
                await query.message.edit_text("❌ Не удалось получить данные о продажах")
                return
            # Форматируем и отправляем сообщение
            message = await bot.format_sales_message(sales_data, 'day')
            await query.message.edit_text(message)
            
        elif query.data == 'sales_week':
            # Логируем запрос статистики за неделю
            bot.mongo.log_activity(user_id, 'sales_week_requested')
            # Получаем данные о продажах
            sales_data = await bot.get_sales_data(context, 'week')
            if not sales_data:
                await query.message.edit_text("❌ Не удалось получить данные о продажах")
                return
            # Форматируем и отправляем сообщение
            message = await bot.format_sales_message(sales_data, 'week')
            await query.message.edit_text(message)

    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в обработчике кнопок: {str(e)}", exc_info=True)
        await query.message.reply_text("❌ Произошла критическая ошибка")

# Основная функция запуска бота
def main():
    """Запуск бота"""
    application = Application.builder().token(CONFIG['TG_API_KEY']).build()
    bot = WBStockBot(application)
    application.bot_data['wb_bot'] = bot
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    
    # Обработчики команд
    async def check_all_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Логируем запрос на проверку остатков
            bot.mongo.log_activity(user_id, 'check_stock_requested')
            
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            await bot.fetch_wb_data(fake_context)
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в check_all_stock: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")
    
    async def check_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Логируем запрос на проверку остатков
            bot.mongo.log_activity(user_id, 'check_stock_menu_opened')

            keyboard = [
                [InlineKeyboardButton("Остатки на складах", callback_data='check_all_stock')],
                [InlineKeyboardButton("Запустить авто остатки", callback_data='start_auto_stock')],
                [InlineKeyboardButton("Остановить авто остатки", callback_data='stop_auto_stock')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в check_stock: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")
    
    async def start_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Логируем запуск автоматических проверок
            bot.mongo.log_activity(user_id, 'auto_stock_started')
            
            await bot.start_periodic_checks(update.effective_chat.id)
            await update.message.reply_text(
                f"✅ Автоматические проверки запущены (каждые {CONFIG['CHECK_STOCK_INTERVAL']} минут(ы) в рабочее время)"
            )
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в start_auto_stock: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")
    
    async def stop_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Логируем остановку автоматических проверок
            bot.mongo.log_activity(user_id, 'auto_stock_stopped')
            
            if await bot.stop_periodic_checks(update.effective_chat.id):
                await update.message.reply_text("🛑 Автоматические проверки остановлены")
            else:
                await update.message.reply_text("ℹ️ Нет активных автоматических проверок")
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в stop_auto_stock: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")
    
    async def check_coefficients(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Логируем запрос на проверку коэффициентов
            bot.mongo.log_activity(user_id, 'check_coefficients_requested')

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
    
    async def user_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Обновляем информацию о пользователе
            bot.mongo.update_user_activity(user_id, update.effective_user)
            
            # Получаем уровень подписки
            subscription_level = bot.mongo.get_subscription_level(user_id)
            
            # Формируем базовое сообщение
            message = (
                f"Ваш user ID: {user_id}\n"
                f"Статус: {subscription_level}"
            )
            
            # Добавляем дату окончания подписки только для Premium и Admin
            if subscription_level != "Base":
                subscription_end_date = bot.mongo.get_subscription_end_date(user_id)
                message += f"\nДата окончания подписки: {subscription_end_date}"
            
            await update.message.reply_text(message)
            
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в user_account: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")
    
    async def send_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Проверяем уровень подписки
            subscription_level = bot.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await update.message.reply_text("❌ У вас нет доступа к этой функции")
                return
            
            # Сохраняем состояние ожидания сообщения
            context.user_data['waiting_for_broadcast'] = True
            
            keyboard = [[InlineKeyboardButton("Отправить", callback_data='broadcast_message')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "Введите текст сообщения для отправки всем пользователям:",
                reply_markup=reply_markup
            )
            
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в send_messages: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")

    async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Проверяем уровень подписки
            subscription_level = bot.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await update.message.reply_text("❌ У вас нет доступа к этой функции")
                return
            
            # Получаем текст сообщения
            message_text = update.message.text
            
            # Получаем список всех пользователей
            users = bot.mongo.get_all_users()
            
            # Получаем список заблокированных пользователей
            banned_users = bot.mongo.get_banned_users()
            
            # Отправляем сообщение всем пользователям, кроме заблокированных
            success_count = 0
            fail_count = 0
            
            for user in users:
                if user['user_id'] not in banned_users:
                    try:
                        await context.bot.send_message(
                            chat_id=user['user_id'],
                            text=message_text
                        )
                        success_count += 1
                    except Exception as e:
                        logger.error(f"Ошибка отправки сообщения пользователю {user['user_id']}: {str(e)}")
                        fail_count += 1
            
            # Отправляем отчет об отправке
            await update.message.reply_text(
                f"✅ Отправка завершена\n"
                f"Успешно отправлено: {success_count}\n"
                f"Ошибок отправки: {fail_count}"
            )
            
            # Сбрасываем состояние ожидания сообщения
            context.user_data['waiting_for_broadcast'] = False
            
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в broadcast_message: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("check_stock", check_stock))
    application.add_handler(CommandHandler("check_all_stock", check_all_stock))
    application.add_handler(CommandHandler("start_auto_stock", start_auto_stock))
    application.add_handler(CommandHandler("stop_auto_stock", stop_auto_stock))
    application.add_handler(CommandHandler("check_coefficients", check_coefficients))
    application.add_handler(CommandHandler("user_account", user_account))
    application.add_handler(CommandHandler("send_messages", send_messages))
    application.add_handler(CommandHandler("sales", bot.sales_menu))  # Добавляем обработчик команды /sales
    
    async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            bot = context.bot_data.get('wb_bot')
            if not bot:
                raise Exception("Бот не инициализирован")
            
            user_id = update.effective_user.id
            # Обновляем информацию о пользователе
            bot.mongo.update_user_activity(user_id, update.effective_user)
            
            # Формируем демонстрационное сообщение с различными элементами форматирования
            message = (
                "🤖 *Информация о боте*\n\n"
                "Бот показывает остатки вашего товара на складах (FBW) в ручном или автоматическом режиме. Умеет искать лимиты на бесплатную приемку по заданным параметрам, показывает коэффициенты на логистику. Работает в тестовом режиме.\n\n"
                "⚠️ *Важно:*\n"
                "Разработка ведется одним человеком, поэтому терпите ;-)\n"
                "Я такой-же селлер, как и вы, поэтому понимаю ваши запросы и трудности.\n"
                "Ошибки правлю, новый функционал добавляю.\n"
                "Возможны потери ваших настроек, но я стараюсь этого избежать.\n"
            )
            
            await update.message.reply_text(
                message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка в info: {str(e)}", exc_info=True)
            await update.message.reply_text("❌ Произошла критическая ошибка")
    
    # Добавляем обработчик команды /info
    application.add_handler(CommandHandler("info", info))
    
    # Регистрация обработчиков callback-запросов
    application.add_handler(CallbackQueryHandler(button_handler))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    
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