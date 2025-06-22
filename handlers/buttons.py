from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import (
    get_premium_kb, get_admin_kb, get_broadcast_kb, get_coefficients_menu_kb, get_stock_menu_kb,
    get_sales_menu_kb, get_warehouse_nav_kb, get_disable_warehouses_kb
)
import logging

logger = logging.getLogger(__name__)

# Полный перенос содержимого button_handler из bot_main.py
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
            subscription_level = bot.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await query.message.edit_text("❌ У вас нет доступа к этой функции")
                return
            context.user_data['waiting_for_broadcast'] = True
            reply_markup = get_broadcast_kb()
            await query.message.edit_text(
                "Введите текст сообщения для отправки всем пользователям:",
                reply_markup=reply_markup
            )
            return
        elif query.data == 'broadcast_message':
            subscription_level = bot.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await query.message.edit_text("❌ У вас нет доступа к этой функции")
                return
            if 'broadcast_text' not in context.user_data:
                await query.message.edit_text("❌ Сначала введите текст сообщения")
                return
            message_text = context.user_data['broadcast_text']
            users = bot.mongo.get_all_users()
            banned_users = bot.mongo.get_banned_users()
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
            await query.message.edit_text(
                f"✅ Отправка завершена\n"
                f"Успешно отправлено: {success_count}\n"
                f"Ошибок отправки: {fail_count}"
            )
            del context.user_data['broadcast_text']
            context.user_data['waiting_for_broadcast'] = False
            return
        elif query.data == 'admin_statistics':
            subscription_level = bot.mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await query.message.edit_text("❌ У вас нет доступа к этой функции")
                return
            stats = bot.mongo.get_user_statistics()
            message = (
                f"📊 Статистика:\n\n"
                f"Всего пользователей: {stats['total']}\n"
                f"Base: {stats['base']}\n"
                f"Premium: {stats['premium']}"
            )
            await query.message.edit_text(message)
            return
        elif query.data == 'check_coefficients':
            bot.mongo.log_activity(user_id, 'coefficients_menu_opened')
            reply_markup = get_coefficients_menu_kb()
            await query.message.edit_text("Выберите действие:", reply_markup=reply_markup)
            return
        elif query.data == 'check_all_stock':
            bot.mongo.log_activity(user_id, 'check_all_stock_requested')
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            await bot.fetch_wb_data(fake_context)
        elif query.data == 'start_auto_stock':
            try:
                bot.mongo.log_activity(user_id, 'start_auto_stock_requested')
                await bot.start_periodic_checks(update.effective_chat.id)
                await query.message.edit_text(
                    f"✅ Автоматические проверки запущены (каждые {{bot.CONFIG['CHECK_STOCK_INTERVAL']}} минут(ы) в рабочее время)"
                )
            except Exception as e:
                logger.critical(f"CRITICAL: Ошибка в start_auto_stock: {str(e)}", exc_info=True)
                await query.message.edit_text("❌ Произошла ошибка при запуске автоматических проверок")
        elif query.data == 'stop_auto_stock':
            bot.mongo.log_activity(user_id, 'stop_auto_stock_requested')
            if await bot.stop_periodic_checks(update.effective_chat.id):
                await query.message.edit_text("🛑 Автоматические проверки остановлены")
            else:
                await query.message.edit_text("ℹ️ Нет активных автоматических проверок")
        elif query.data == 'check_all_coefficients':
            bot.mongo.log_activity(user_id, 'check_all_coefficients_requested')
            bot.mongo.save_selected_warehouses(user_id, [])
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            await bot.get_warehouse_coefficients(fake_context)
        elif query.data == 'start_auto_coefficients':
            try:
                bot.mongo.log_activity(user_id, 'start_auto_coefficients_requested')
                if not bot.CONFIG['TARGET_WAREHOUSE_ID']:
                    await bot.show_warehouse_selection(update, context)
                else:
                    await bot.start_auto_coefficients(update.effective_chat.id)
                    await query.message.edit_text(
                        f"✅ Автоматические проверки запущены (каждые {{bot.CONFIG['CHECK_COEFFICIENTS_INTERVAL']}} минут(ы) в рабочее время)"
                    )
            except Exception as e:
                logger.critical(f"CRITICAL: Ошибка в start_auto_coefficients: {str(e)}", exc_info=True)
                await query.message.edit_text("❌ Произошла ошибка при запуске автоматических проверок")
        elif query.data == 'stop_auto_coefficients':
            bot.mongo.log_activity(user_id, 'stop_auto_coefficients_requested')
            if await bot.stop_auto_coefficients(update.effective_chat.id):
                await query.message.edit_text("🛑 Автоматические проверки остановлены")
            else:
                await query.message.edit_text("ℹ️ Нет активных автоматических проверок")
        elif query.data.startswith('select_warehouse_'):
            warehouse_id = int(query.data.split('_')[-1])
            chat_id = update.effective_chat.id
            bot.mongo.log_activity(user_id, f'warehouse_selected_{warehouse_id}')
            current_warehouses = bot.mongo.get_selected_warehouses(chat_id)
            current_warehouses.append(warehouse_id)
            bot.mongo.save_selected_warehouses(chat_id, current_warehouses)
            await bot.show_warehouse_selection(update, context)
        elif query.data.startswith('warehouse_page_'):
            page = int(query.data.split('_')[-1])
            bot.mongo.log_activity(user_id, f'warehouse_page_{page}')
            await bot.show_warehouse_selection(update, context, page)
        elif query.data == 'remove_last_warehouse':
            try:
                chat_id = update.effective_chat.id
                current_warehouses = bot.mongo.get_selected_warehouses(chat_id)
                if current_warehouses:
                    bot.mongo.log_activity(user_id, 'remove_last_warehouse')
                    warehouses = await bot.get_warehouse_list(context, chat_id)
                    if not warehouses:
                        raise Exception("Не удалось получить список складов")
                    removed_warehouse = current_warehouses.pop()
                    bot.mongo.save_selected_warehouses(chat_id, current_warehouses)
                    removed_name = warehouses.get(removed_warehouse, 'Неизвестный склад')
                    await bot.show_warehouse_selection(update, context, 0)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"🗑 Удален склад: {removed_name}"
                    )
            except Exception as e:
                logger.critical(f"CRITICAL: Ошибка при удалении последнего склада: {str(e)}", exc_info=True)
                await query.message.edit_text("❌ Произошла ошибка при удалении склада")
        elif query.data == 'finish_warehouse_selection':
            chat_id = update.effective_chat.id
            bot.mongo.log_activity(user_id, 'finish_warehouse_selection')
            current_warehouses = bot.mongo.get_selected_warehouses(chat_id)
            if current_warehouses:
                await bot.start_auto_coefficients(chat_id)
                await query.message.edit_text(
                    f"✅ Автоматические проверки запущены (каждые {{bot.CONFIG['CHECK_COEFFICIENTS_INTERVAL']}} минут(ы) в рабочее время)"
                )
            else:
                await query.message.edit_text("❌ Не выбрано ни одного склада")
                await start(update, context)
        elif query.data.startswith('disable_warehouses:'):
            bot.mongo.log_activity(user_id, 'disable_warehouses_until_tomorrow')
            await bot.process_disable_warehouses(update, context)
        elif query.data == 'stop_auto_coefficients':
            bot.mongo.log_activity(user_id, 'stop_auto_coefficients_completely')
            await bot.process_stop_auto_coefficients(update, context)
        elif query.data == 'sales_day':
            bot.mongo.log_activity(user_id, 'sales_day_requested')
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            sales_data = await bot.get_sales_data(fake_context, 'day')
            if not sales_data:
                await query.message.edit_text("❌ Не удалось получить данные о продажах")
                return
            message = await bot.format_sales_message(sales_data, 'day')
            await query.message.edit_text(message)
        elif query.data == 'sales_week':
            bot.mongo.log_activity(user_id, 'sales_week_requested')
            class FakeContext:
                def __init__(self, chat_id, bot):
                    self._chat_id = chat_id
                    self.bot = bot
            fake_context = FakeContext(update.effective_chat.id, context.bot)
            sales_data = await bot.get_sales_data(fake_context, 'week')
            if not sales_data:
                await query.message.edit_text("❌ Не удалось получить данные о продажах")
                return
            message = await bot.format_sales_message(sales_data, 'week')
            await query.message.edit_text(message)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в обработчике кнопок: {str(e)}", exc_info=True)
        await query.message.reply_text("❌ Произошла критическая ошибка")

__all__ = [
    'button_handler',
] 