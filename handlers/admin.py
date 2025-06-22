from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import get_broadcast_kb, get_admin_kb
import logging

logger = logging.getLogger(__name__)

async def admin_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        user_id = update.effective_user.id
        subscription_level = bot.mongo.get_subscription_level(user_id)
        if subscription_level != "Admin":
            await update.message.reply_text("❌ У вас нет доступа к этой команде")
            return
        stats = bot.mongo.get_user_statistics()
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

async def send_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        user_id = update.effective_user.id
        subscription_level = bot.mongo.get_subscription_level(user_id)
        if subscription_level != "Admin":
            await update.message.reply_text("❌ У вас нет доступа к этой функции")
            return
        context.user_data['waiting_for_broadcast'] = True
        reply_markup = get_broadcast_kb()
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
        user_id = update.effective_user.id
        subscription_level = bot.mongo.get_subscription_level(user_id)
        if subscription_level != "Admin":
            await update.message.reply_text("❌ У вас нет доступа к этой функции")
            return
        message_text = update.message.text
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
        await update.message.reply_text(
            f"✅ Отправка завершена\n"
            f"Успешно отправлено: {success_count}\n"
            f"Ошибок отправки: {fail_count}"
        )
        context.user_data['waiting_for_broadcast'] = False
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в broadcast_message: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка") 