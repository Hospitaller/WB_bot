from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import get_stock_menu_kb
import logging

logger = logging.getLogger(__name__)

async def check_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_id = update.effective_user.id
        mongo.log_activity(user_id, 'check_stock_menu_opened')
        reply_markup = get_stock_menu_kb()
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в check_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

async def check_all_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_data = context.bot_data['user_data']
        timezone = context.bot_data['timezone']
        user_id = update.effective_user.id
        mongo.log_activity(user_id, 'check_stock_requested')
        from services.stock import fetch_wb_data
        class FakeContext:
            def __init__(self, chat_id, bot):
                self._chat_id = chat_id
                self.bot = bot
        fake_context = FakeContext(update.effective_chat.id, context.bot)
        await fetch_wb_data(fake_context, mongo, user_data, timezone)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в check_all_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

async def start_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_data = context.bot_data['user_data']
        timezone = context.bot_data['timezone']
        active_jobs = context.bot_data['active_jobs']
        user_id = update.effective_user.id
        mongo.log_activity(user_id, 'auto_stock_started')
        from services.stock import start_periodic_checks
        await start_periodic_checks(update.effective_chat.id, mongo, user_data, timezone, active_jobs)
        await update.message.reply_text(
            f"✅ Автоматические проверки запущены (каждые {context.bot_data['CHECK_STOCK_INTERVAL']} минут(ы) в рабочее время)"
        )
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в start_auto_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

async def stop_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        active_jobs = context.bot_data['active_jobs']
        user_id = update.effective_user.id
        mongo.log_activity(user_id, 'auto_stock_stopped')
        from services.stock import stop_periodic_checks
        if await stop_periodic_checks(update.effective_chat.id, active_jobs):
            await update.message.reply_text("🛑 Автоматические проверки остановлены")
        else:
            await update.message.reply_text("ℹ️ Нет активных автоматических проверок")
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в stop_auto_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

__all__ = [
    'check_stock',
    'check_all_stock',
    'start_auto_stock',
    'stop_auto_stock',
] 