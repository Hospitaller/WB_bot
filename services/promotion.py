import aiohttp
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

async def get_promotion_list(context, mongo, user_data, timezone):
    """Получение списка рекламных кампаний"""
    try:
        chat_id = context.job.chat_id if hasattr(context, 'job') else context._chat_id
        wb_token = user_data.get_user_token(chat_id)
        if not wb_token:
            await context.bot.send_message(chat_id=chat_id, text="❌ Токен WB не найден")
            return None
        
        headers = {
            'Accept': 'application/json',
            'Authorization': wb_token,
            'Content-Type': 'application/json',
            'User-Agent': 'WBAnalyticsBot/1.0 (+https://t.me/)'
        }
        
        # Получаем настройки пользователя (включая API URLs из глобальных настроек)
        settings = mongo.get_user_settings(chat_id)
        if not settings:
            logger.error(f"No settings found for user {chat_id}")
            await context.bot.send_message(chat_id=chat_id, text="❌ Не удалось получить настройки")
            return None
        
        # Получаем URL из настроек API
        promotion_url = settings.get('api', {}).get('urls', {}).get('promotion_count')
        
        if not promotion_url:
            # Пробуем получить из глобальных настроек напрямую (для обратной совместимости)
            try:
                global_settings = mongo.get_global_settings()
                promotion_url = global_settings.get('promotion_count')
                if not promotion_url:
                    promotion_url = global_settings.get('api', {}).get('urls', {}).get('promotion_count')
            except Exception as e:
                logger.error(f"Failed to get global settings: {str(e)}")
            
            if not promotion_url:
                logger.error(f"promotion_count URL not found in settings")
                await context.bot.send_message(chat_id=chat_id, text="❌ URL для получения списка РК не настроен")
                return None
        
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            response = await context.bot_data['make_api_request'](
                session,
                promotion_url,
                headers,
                context,
                chat_id,
                method='GET',
                timeout=120,
                max_retries=8
            )
            
            if not response:
                return None
            
            return response
    except Exception as e:
        logger.error(f"Ошибка при получении списка рекламных кампаний: {str(e)}", exc_info=True)
        return None

__all__ = [
    'get_promotion_list',
]

