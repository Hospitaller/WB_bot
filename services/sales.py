import aiohttp
import logging
from datetime import datetime, timedelta
from services.utils import format_sales_message

logger = logging.getLogger(__name__)

async def get_sales_data(context, period_type, mongo, user_data, timezone):
    """Получение данных о продажах"""
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
        settings = mongo.get_user_settings(chat_id)
        if not settings:
            logger.error(f"No settings found for user {chat_id}")
            return None
        now = datetime.now(timezone)
        if period_type == 'day':
            begin_date = now.replace(hour=0, minute=0, second=1)
            end_date = now.replace(hour=23, minute=59, second=59)
        else:  # week
            end_date = now.replace(hour=23, minute=59, second=59)
            begin_date = (now - timedelta(days=6)).replace(hour=0, minute=0, second=1)
        request_data = {
            "brandNames": [],
            "objectIDs": [],
            "tagIDs": [],
            "nmIDs": [],
            "timezone": "Europe/Moscow",
            "period": {
                "begin": begin_date.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end_date.strftime("%Y-%m-%d %H:%M:%S")
            },
            "orderBy": {
                "field": "ordersSumRub",
                "mode": "asc"
            },
            "page": 1,
            "pageSize": 100
        }
        # Увеличиваем общий таймаут с 60 до 90 секунд, так как WB иногда отвечает медленнее
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # Пагинация: собираем все страницы, пока isNextPage = True
            all_cards = []
            combined_data = None
            page = 1
            while True:
                request_data["page"] = page
                response = await context.bot_data['make_api_request'](
                    session,
                    settings['api']['urls']['sales'],
                    headers,
                    context,
                    chat_id,
                    method='POST',
                    json_data=request_data,
                    timeout=120,
                    max_retries=8
                )
                if not response or 'data' not in response:
                    break
                data = response['data']
                if combined_data is None:
                    # Сохраняем метаданные первой страницы
                    combined_data = {k: v for k, v in data.items() if k != 'cards'}
                cards = data.get('cards', [])
                if cards:
                    all_cards.extend(cards)
                # Проверяем флаг следующей страницы
                is_next = bool(data.get('isNextPage'))
                if not is_next:
                    break
                page += 1
                # Небольшая пауза между страницами, чтобы не давить на API во время деградации
                await asyncio.sleep(0.4)
            if combined_data is None:
                return None
            combined_data['cards'] = all_cards
            return combined_data
    except Exception as e:
        logger.error(f"Ошибка при получении данных о продажах: {str(e)}")
        return None

async def format_sales_message(sales_data, period_type, timezone):
    """Форматирование сообщения со статистикой продаж (deprecated, используйте из utils)"""
    from services.utils import format_sales_message as _fsm
    return _fsm(sales_data, period_type, timezone)

__all__ = [
    'get_sales_data',
    'format_sales_message',
] 