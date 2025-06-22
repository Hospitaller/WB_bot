from telegram import Update
from telegram.ext import ContextTypes
from keyboards.layouts import get_premium_kb, get_admin_kb, get_sales_menu_kb
import logging

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_data = context.bot_data['user_data']
        timezone = context.bot_data['timezone']
        user_id = update.effective_user.id
        first_name = update.effective_user.first_name
        last_name = update.effective_user.last_name
        username = update.effective_user.username
        logger.info(f"Start command received from user {user_id}")
        mongo.log_activity(user_id, 'start_command')
        logger.info(f"User exists check: {user_data.is_user_exists(user_id)}")
        if not user_data.is_user_exists(user_id):
            logger.info(f"Initializing new user {user_id}")
            await update.message.reply_text(
                "👋 Привет! Я бот для работы с Wildberries.\n"
                "Для начала работы необходимо добавить ваш WB токен:\n"
                "Статистика, Аналитика, Поставки\n\n"
                "Введите ваш токен:"
            )
            context.user_data['waiting_for_token'] = True
            mongo.init_user(user_id, first_name, username, last_name)
            logger.info(f"User {user_id} initialized in MongoDB")
        else:
            mongo.update_user_activity(user_id, update.effective_user)
            logger.info(f"User {user_id} already exists")
            subscription_level = mongo.get_subscription_level(user_id)
            message = "Для управления ботом используйте главное меню"
            if subscription_level == "Premium":
                message += "\n\nPremium"
                reply_markup = get_premium_kb()
                await update.message.reply_text(message, reply_markup=reply_markup)
            elif subscription_level == "Admin":
                message += "\n\nПривет, Admin!"
                reply_markup = get_admin_kb()
                await update.message.reply_text(message, reply_markup=reply_markup)
            else:
                await update.message.reply_text(message)
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в start: {str(e)}", exc_info=True)

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_id = update.effective_user.id
        mongo.update_user_activity(user_id, update.effective_user)
        message = (
            "🤖 *Информация о боте*\n\n"
            "Бот показывает остатки вашего товара на складах (FBW) в ручном или автоматическом режиме. Умеет искать лимиты на бесплатную приемку по заданным параметрам, показывает коэффициенты на логистику. Работает в тестовом режиме.\n\n"
            "⚠️ *Важно:*\n"
            "Разработка ведется одним человеком, поэтому терпите ;-)\n"
            "Я такой-же селлер, как и вы, поэтому понимаю ваши запросы и трудности.\n"
            "Ошибки правлю, новый функционал добавляю.\n"
            "Возможны потери ваших настроек, но я стараюсь этого избежать.\n"
            "Нашли баг или появилась идея? Пишите в ТГ - @Tolfti \n"
        )
        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в info: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mongo = context.bot_data['mongo']
        user_data = context.bot_data['user_data']
        user_id = update.effective_user.id
        mongo.update_user_activity(user_id, update.effective_user)
        if context.user_data.get('waiting_for_token'):
            token = update.message.text.strip()
            user_data.add_user(user_id, token)
            mongo.init_user(user_id)
            mongo.update_user_activity(user_id, update.effective_user)
            mongo.log_activity(user_id, 'token_added')
            context.user_data['waiting_for_token'] = False
            await update.message.reply_text(
                "✅ Токен успешно добавлен!\n"
                "Теперь вы можете использовать бота. Удачи!\n\n"
                "Для управления ботом используйте главное меню"
            )
        elif context.user_data.get('waiting_for_broadcast'):
            subscription_level = mongo.get_subscription_level(user_id)
            if subscription_level != "Admin":
                await update.message.reply_text("❌ У вас нет доступа к этой функции")
                return
            context.user_data['broadcast_text'] = update.message.text
            await update.message.reply_text(
                "✅ Текст сообщения сохранен. Нажмите кнопку 'Отправить' для рассылки."
            )
        else:
            mongo.log_activity(user_id, 'message_received')
            await update.message.reply_text(
                "Для управления ботом используйте главное меню"
            )
    except Exception as e:
        logger.critical(f"CRITICAL: Ошибка в обработчике сообщений: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Произошла критическая ошибка")

__all__ = [
    'start',
    'info',
    'handle_message',
]
