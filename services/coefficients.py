import logging
import aiohttp
import asyncio
from datetime import datetime, time, timedelta
import pytz
from services.api_utils import make_api_request
from services.utils import format_coefficients_message
from services.warehouses import get_warehouse_tariffs

logger = logging.getLogger(__name__)

async def get_warehouse_coefficients(context, mongo, user_data, timezone):
    chat_id = context.job.chat_id if hasattr(context, 'job') else context._chat_id
    try:
        settings = mongo.get_user_settings(chat_id)
        if not settings:
            logger.error(f"No settings found for user {chat_id} in get_warehouse_coefficients")
            return
        warehouses = settings.get('warehouses', {})
        paused_warehouses = warehouses.get('paused', [])
        target_warehouses = warehouses.get('target', [])
        is_auto_check = hasattr(context, 'job')
        wb_token = user_data.get_user_token(chat_id)
        if not wb_token:
            await context.bot.send_message(chat_id=chat_id, text="❌ Токен WB не найден. Пожалуйста, добавьте токен через команду /start. Требуются права Статистика, Аналитика, Поставки")
            return
        if target_warehouses and all(str(wh) in paused_warehouses for wh in target_warehouses):
            logger.info(f"All target warehouses are paused for user {chat_id}, skipping check")
            return
        headers = {
            'Accept': 'application/json',
            'Authorization': wb_token
        }
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if not hasattr(context, 'job'):
                await context.bot.send_message(chat_id=chat_id, text="🔄 Получаю коэффициенты складов...")
            tariffs_data = await get_warehouse_tariffs(context, chat_id, mongo, user_data)
            coefficients_response = await make_api_request(
                session, settings['api']['urls']['coefficients'], headers, context, chat_id
            )
            if not coefficients_response or not isinstance(coefficients_response, list):
                await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить данные о коэффициентах")
                return

            messages, has_data, target_warehouses, target_names = format_coefficients_message(coefficients_response, tariffs_data, settings)
            if not has_data and hasattr(context, 'job'):
                return
            keyboard = None
            if target_warehouses and hasattr(context, 'job'):
                from keyboards.layouts import get_disable_warehouses_kb
                callback_data = f"disable_warehouses:{','.join(str(wh) for wh in target_warehouses)}"
                if len(callback_data) <= 64:
                    keyboard = get_disable_warehouses_kb([target_warehouses])
                else:
                    logger.warning(f"Не добавляю inline-клавиатуру: callback_data слишком длинная ({len(callback_data)} символов)")
                    keyboard = None
            for i, message in enumerate(messages):
                try:
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
                    try:
                        parts = [message[i:i+3000] for i in range(0, len(message), 3000)]
                        for j, part in enumerate(parts):
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
            mongo.update_last_notification(chat_id)
    except Exception as e:
        logger.critical(f"CRITICAL ERROR for chat {chat_id}: {str(e)}", exc_info=True)
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Произошла критическая ошибка: {str(e)}")

async def start_auto_coefficients(application, chat_id, mongo, timezone):
    try:
        logger.info(f"Starting auto coefficients for user {chat_id}")
        if hasattr(application, 'active_coefficient_jobs') and chat_id in application.active_coefficient_jobs:
            logger.info(f"Removing existing job for user {chat_id}")
            application.active_coefficient_jobs[chat_id].schedule_removal()
        settings = mongo.get_user_settings(chat_id)
        if not settings:
            logger.error(f"No settings found for user {chat_id} in start_auto_coefficients")
            return None
        interval = settings.get('intervals', {}).get('check_coefficients', 1)
        logger.info(f"Using interval {interval} minutes for user {chat_id}")
        job = application.job_queue.run_repeating(
            callback=lambda context: get_warehouse_coefficients(context, mongo, application.bot_data['user_data'], timezone),
            interval=timedelta(minutes=interval),
            first=0,
            chat_id=chat_id,
            name=f"coefficients_{chat_id}"
        )
        if hasattr(application, 'active_coefficient_jobs'):
            application.active_coefficient_jobs[chat_id] = job
        mongo.update_auto_coefficients(chat_id, True)
        mongo.log_activity(chat_id, 'start_auto_coefficients')
        return job
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка запуска автоматических проверок коэффициентов: {str(e)}", exc_info=True)
        raise

async def stop_auto_coefficients(application, chat_id, mongo):
    try:
        job_name = f"coefficients_{chat_id}"
        jobs = application.job_queue.get_jobs_by_name(job_name)
        stopped = False
        if jobs:
            for job in jobs:
                job.schedule_removal()
            stopped = True
        if hasattr(application, 'active_coefficient_jobs') and chat_id in application.active_coefficient_jobs:
            del application.active_coefficient_jobs[chat_id]
        mongo.update_auto_coefficients(chat_id, False)
        mongo.update_user_settings(chat_id, {
            'warehouses': {
                'paused': [],
                'target': []
            }
        })
        mongo.log_activity(chat_id, 'stop_auto_coefficients')
        return stopped
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка остановки автоматических проверок коэффициентов: {str(e)}", exc_info=True)
        raise

__all__ = [
    'get_warehouse_coefficients',
    'start_auto_coefficients',
    'stop_auto_coefficients',
]
