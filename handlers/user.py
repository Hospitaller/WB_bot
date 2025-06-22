from telegram import Update
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

async def user_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        user_id = update.effective_user.id
        bot.mongo.update_user_activity(user_id, update.effective_user)
        subscription_level = bot.mongo.get_subscription_level(user_id)
        message = (
            f"Ваш user ID: {user_id}\n"
            f"Статус: {subscription_level}"
        )
        if subscription_level != "Base":
            subscription_end_date = bot.mongo.get_subscription_end_date(user_id)
            message += f"\nДата окончания подписки: {subscription_end_date}"
        await update.message.reply_text(message)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в user_account: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

__all__ = [
    'user_account',
] 