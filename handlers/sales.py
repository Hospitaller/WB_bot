from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import get_sales_menu_kb
import logging

logger = logging.getLogger(__name__)

async def sales_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        user_id = update.effective_user.id
        bot.mongo.log_activity(user_id, 'sales_menu_opened')
        reply_markup = get_sales_menu_kb()
        await update.message.reply_text(
            "Статистика продаж (до 23:59:59 Мск):",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка при открытии меню статистики: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка при открытии меню статистики")

__all__ = [
    'sales_menu',
] 