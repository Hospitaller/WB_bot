import logging
import aiohttp
import asyncio
from datetime import datetime, time, timedelta
from config import CONFIG
from services.api_utils import make_api_request
from services.utils import format_stock_message

logger = logging.getLogger(__name__)

# Форматирование данных о складе

def format_stock_data(data, user_id: int, mongo, highlight_low=False):
    if not isinstance(data, list):
        return None
    result = []
    low_stock_items = []
    user_settings = mongo.get_user_settings(user_id)
    global_settings = mongo.get_global_settings()
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

# Основная функция получения данных
async def fetch_wb_data(context, user_data, mongo, timezone):
    chat_id = context.job.chat_id if hasattr(context, 'job') else context._chat_id
    is_auto_check = hasattr(context, 'job')
    from services.utils import is_working_time
    if is_auto_check and not is_working_time(chat_id, mongo, timezone, True):
        logger.info(f"Сейчас нерабочее время для чата {chat_id}")
        return
    try:
        wb_token = user_data.get_user_token(chat_id)
        if not wb_token:
            await context.bot.send_message(chat_id=chat_id, text="❌ Токен WB не найден. Пожалуйста, добавьте токен через команду /start")
            return
        headers = {
            'Accept': 'application/json',
            'Authorization': wb_token
        }
        settings = mongo.get_user_settings(chat_id)
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await context.bot.send_message(chat_id=chat_id, text="🔄 Считаю остатки..")
            first_response = await make_api_request(session, settings['api']['urls']['stock_request'], headers, context, chat_id)
            if not first_response:
                return
            task_id = first_response.get('data', {}).get('taskId')
            if not task_id:
                await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить task ID")
                return
            await asyncio.sleep(settings['api']['request_delay'])
            second_url = settings['api']['urls']['stock_download'].format(task_id=task_id)
            stock_data = await make_api_request(session, second_url, headers, context, chat_id)
            if not stock_data:
                return
            formatted_data = format_stock_data(stock_data, chat_id, mongo)
            low_stock_data = format_stock_data(stock_data, chat_id, mongo, highlight_low=True)
            messages = format_stock_message(formatted_data, low_stock_data)
            for message in messages:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=message
                )
    except Exception as e:
        logger.critical(f"CRITICAL ERROR for chat {chat_id}: {str(e)}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Произошла критическая ошибка: {str(e)}")

# Запускает периодические проверки для указанного чата
async def start_periodic_checks(application, chat_id, user_data, mongo):
    try:
        # Для совместимости с WBStockBot.active_jobs
        if hasattr(application, 'active_jobs') and chat_id in application.active_jobs:
            application.active_jobs[chat_id].schedule_removal()
        job = application.job_queue.run_repeating(
            callback=lambda context: fetch_wb_data(context, user_data, mongo, pytz.timezone('Europe/Moscow')),
            interval=timedelta(minutes=CONFIG['CHECK_STOCK_INTERVAL']),
            first=0,
            chat_id=chat_id,
            name=str(chat_id)
        )
        if hasattr(application, 'active_jobs'):
            application.active_jobs[chat_id] = job
        user_data.set_auto_check_status(chat_id, True)
        return job
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка запуска периодических проверок: {str(e)}", exc_info=True)
        raise

# Останавливает периодические проверки для указанного чата
async def stop_periodic_checks(application, chat_id, user_data):
    try:
        if hasattr(application, 'active_jobs') and chat_id in application.active_jobs:
            application.active_jobs[chat_id].schedule_removal()
            del application.active_jobs[chat_id]
            user_data.set_auto_check_status(chat_id, False)
            return True
        return False
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка остановки периодических проверок: {str(e)}", exc_info=True)
        raise

__all__ = [
    'format_stock_data',
    'fetch_wb_data',
    'start_periodic_checks',
    'stop_periodic_checks',
]
