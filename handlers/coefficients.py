from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import get_coefficients_menu_kb
import logging

logger = logging.getLogger(__name__)

async def check_coefficients(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_id = update.effective_user.id
        mongo.log_activity(user_id, 'check_coefficients_requested')
        reply_markup = get_coefficients_menu_kb()
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в check_coefficients: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

__all__ = [
    'check_coefficients',
] 