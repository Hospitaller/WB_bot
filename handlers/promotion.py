from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import get_promotion_menu_kb
import logging

logger = logging.getLogger(__name__)

async def promotion_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_id = update.effective_user.id
        mongo.update_user_activity(user_id, update.effective_user)
        mongo.log_activity(user_id, 'promotion_menu_opened')
        reply_markup = get_promotion_menu_kb()
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в promotion_menu: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

__all__ = [
    'promotion_menu',
]

