import logging
from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import get_warehouse_nav_kb
import aiohttp
from datetime import datetime
from services.api_utils import make_api_request

logger = logging.getLogger(__name__)

async def get_warehouse_list(context, chat_id, mongo, user_data, use_cache=True):
    # Кэшируем список складов в context.user_data['cached_warehouses']
    if use_cache and hasattr(context, 'user_data') and 'cached_warehouses' in context.user_data:
        return context.user_data['cached_warehouses']
    wb_token = user_data.get_user_token(chat_id)
    if not wb_token:
        return None
    headers = {
        'Accept': 'application/json',
        'Authorization': wb_token
    }
    settings = mongo.get_user_settings(chat_id)
    async with aiohttp.ClientSession() as session:
        response = await make_api_request(session, settings['api']['urls']['coefficients'], headers, context, chat_id)
        if not response or not isinstance(response, list):
            return None
        warehouses = {}
        for item in response:
            warehouse_id = item.get('warehouseID')
            warehouse_name = item.get('warehouseName')
            if warehouse_id and warehouse_name:
                warehouses[warehouse_id] = warehouse_name
        if hasattr(context, 'user_data'):
            context.user_data['cached_warehouses'] = warehouses
        return warehouses

async def show_warehouse_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, mongo, user_data, page=0, reset_cache=False):
    chat_id = update.effective_chat.id
    warehouses = await get_warehouse_list(context, chat_id, mongo, user_data, use_cache=not reset_cache)
    if not warehouses:
        if hasattr(context, 'user_data') and 'cached_warehouses' in context.user_data:
            del context.user_data['cached_warehouses']
        if update.callback_query:
            await update.callback_query.message.edit_text("❌ Не удалось получить список складов")
        else:
            await update.message.reply_text("❌ Не удалось получить список складов")
        return
    sorted_warehouses = dict(sorted(warehouses.items(), key=lambda x: x[1]))
    selected_warehouses = set(mongo.get_selected_warehouses(chat_id))
    available_warehouses = {k: v for k, v in sorted_warehouses.items() if k not in selected_warehouses}
    if not available_warehouses:
        if update.callback_query:
            await update.callback_query.message.edit_text("❌ Нет доступных складов для выбора")
        else:
            await update.message.reply_text("❌ Нет доступных складов для выбора")
        return
    warehouse_items = list(available_warehouses.items())
    total_pages = (len(warehouse_items) + 24) // 25
    start_idx = page * 25
    end_idx = min(start_idx + 25, len(warehouse_items))
    reply_markup = get_warehouse_nav_kb(
        warehouse_items[start_idx:end_idx],
        selected_warehouses,
        page,
        total_pages
    )
    message_text = "Выберите склады для мониторинга коэффициентов:\n"
    if selected_warehouses:
        message_text += "\nВыбранные склады:\n"
        for warehouse_id in selected_warehouses:
            message_text += f"- {warehouses.get(warehouse_id, 'Неизвестный склад')}\n"
    if update.callback_query:
        await update.callback_query.message.edit_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)

async def handle_warehouse_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, mongo, user_data):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Callback query is too old or invalid: {str(e)}")
    chat_id = update.effective_chat.id
    if query.data.startswith("select_warehouse_"):
        warehouse_id = int(query.data.split("_")[-1])
        current_warehouses = mongo.get_selected_warehouses(chat_id)
        if len(current_warehouses) >= 5:
            await query.answer("⚠️ Нельзя выбрать более 5 складов для отслеживания!", show_alert=True)
            return
        current_warehouses.append(warehouse_id)
        mongo.save_selected_warehouses(chat_id, current_warehouses)
        await show_warehouse_selection(update, context, mongo, user_data)
    elif query.data.startswith("warehouse_page_"):
        page = int(query.data.split("_")[-1])
        await show_warehouse_selection(update, context, mongo, user_data, page)
    elif query.data == "remove_last_warehouse":
        try:
            current_warehouses = mongo.get_selected_warehouses(chat_id)
            if current_warehouses:
                removed_warehouse = current_warehouses.pop()
                mongo.save_selected_warehouses(chat_id, current_warehouses)
                warehouses = await get_warehouse_list(context, chat_id, mongo, user_data) if 'cached_warehouses' not in context.user_data else context.user_data['cached_warehouses']
                removed_name = warehouses.get(removed_warehouse, 'Неизвестный склад')
                await show_warehouse_selection(update, context, mongo, user_data, 0)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🗑 Удален склад: {removed_name}"
                )
        except Exception as e:
            logger.critical(f"CRITICAL: Ошибка при удалении последнего склада: {str(e)}", exc_info=True)
            await query.message.edit_text("❌ Произошла ошибка при удалении склада")
    elif query.data == "finish_warehouse_selection":
        # После завершения выбора очищаем кэш складов
        if hasattr(context, 'user_data') and 'cached_warehouses' in context.user_data:
            del context.user_data['cached_warehouses']
        current_warehouses = mongo.get_selected_warehouses(chat_id)
        if current_warehouses:
            from services.coefficients import start_auto_coefficients
            await start_auto_coefficients(context.application, chat_id, mongo, context.bot_data['timezone'])
            await query.message.edit_text(
                f"✅ Автоматические проверки запущены (каждые {context.bot_data['CHECK_COEFFICIENTS_INTERVAL']} минут(ы) в рабочее время)"
            )
        else:
            await query.message.edit_text("❌ Не выбрано ни одного склада")
            from handlers.common import start
            await start(update, context)

async def process_disable_warehouses(update: Update, context: ContextTypes.DEFAULT_TYPE, mongo, user_data):
    query = update.callback_query
    user_id = query.from_user.id
    warehouses = query.data.split(':')[1].split(',')
    try:
        settings = mongo.get_user_settings(user_id)
        if not settings:
            await query.answer("❌ Ошибка: не удалось получить настройки")
            return
        warehouse_ids = [str(wh_id) for wh_id in warehouses if wh_id]
        if warehouse_ids:
            mongo.update_user_settings(user_id, {
                'warehouses': {
                    'paused': warehouse_ids
                }
            })
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

async def process_stop_auto_coefficients(update: Update, context: ContextTypes.DEFAULT_TYPE, mongo):
    query = update.callback_query
    user_id = query.from_user.id
    try:
        from services.coefficients import stop_auto_coefficients
        await stop_auto_coefficients(context.application, user_id, mongo)
        await query.answer("✅ Автоматическое отслеживание остановлено")
    except Exception as e:
        logger.error(f"Ошибка при остановке автоотслеживания: {str(e)}")
        await query.answer("❌ Произошла ошибка при остановке автоотслеживания")

async def get_warehouse_tariffs(context, chat_id, mongo, user_data):
    try:
        if chat_id is None:
            if hasattr(context, 'job') and context.job:
                chat_id = context.job.chat_id
            elif hasattr(context, '_chat_id'):
                chat_id = context._chat_id
            else:
                return None
        wb_token = user_data.get_user_token(chat_id)
        if not wb_token:
            return None
        headers = {
            'Accept': 'application/json',
            'Authorization': wb_token
        }
        settings = mongo.get_user_settings(chat_id)
        current_date = datetime.now().strftime('%Y-%m-%d')
        url = settings['api']['urls']['warehouse_tariffs'].format(date_now=current_date)
        async with aiohttp.ClientSession() as session:
            response = await make_api_request(session, url, headers, context, chat_id)
            if not response or 'response' not in response or 'data' not in response['response']:
                return None
            return response['response']['data']
    except Exception as e:
        logger.critical(f"CRITICAL ERROR getting warehouse tariffs for chat {chat_id}: {str(e)}", exc_info=True)
        return None

__all__ = [
    'get_warehouse_list',
    'show_warehouse_selection',
    'handle_warehouse_selection',
    'process_disable_warehouses',
    'process_stop_auto_coefficients',
    'get_warehouse_tariffs',
]
