from telegram import Update
from telegram.ext import ContextTypes
import logging

logger = logging.getLogger(__name__)

async def user_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_id = update.effective_user.id
        mongo.update_user_activity(user_id, update.effective_user)
        subscription_level = mongo.get_subscription_level(user_id)
        message = (
            f"Ваш user ID: {user_id}\n"
            f"Статус: {subscription_level}"
        )
        if subscription_level != "Base":
            subscription_end_date = mongo.get_subscription_end_date(user_id)
            message += f"\nДата окончания подписки: {subscription_end_date}"
        await update.message.reply_text(message)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в user_account: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

__all__ = [
    'user_account',
] 