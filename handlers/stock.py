from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import get_stock_menu_kb
import logging

logger = logging.getLogger(__name__)

async def check_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        user_id = update.effective_user.id
        bot.mongo.log_activity(user_id, 'check_stock_menu_opened')
        reply_markup = get_stock_menu_kb()
        await update.message.reply_text("Выберите действие:", reply_markup=reply_markup)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в check_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

async def check_all_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        user_id = update.effective_user.id
        bot.mongo.log_activity(user_id, 'check_stock_requested')
        class FakeContext:
            def __init__(self, chat_id, bot):
                self._chat_id = chat_id
                self.bot = bot
        fake_context = FakeContext(update.effective_chat.id, context.bot)
        await bot.fetch_wb_data(fake_context)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в check_all_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

async def start_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        user_id = update.effective_user.id
        bot.mongo.log_activity(user_id, 'auto_stock_started')
        await bot.start_periodic_checks(update.effective_chat.id)
        await update.message.reply_text(
            f"✅ Автоматические проверки запущены (каждые {{bot.CONFIG['CHECK_STOCK_INTERVAL']}} минут(ы) в рабочее время)"
        )
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в start_auto_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

async def stop_auto_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bot = context.bot_data.get('wb_bot')
        user_id = update.effective_user.id
        bot.mongo.log_activity(user_id, 'auto_stock_stopped')
        if await bot.stop_periodic_checks(update.effective_chat.id):
            await update.message.reply_text("🛑 Автоматические проверки остановлены")
        else:
            await update.message.reply_text("ℹ️ Нет активных автоматических проверок")
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в stop_auto_stock: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка") 