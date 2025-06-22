import aiohttp
import logging
from datetime import datetime, timedelta

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
            'Content-Type': 'application/json'
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
                "field": "orders",
                "mode": "desc"
            },
            "page": 1
        }
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            response = await context.bot_data['make_api_request'](
                session,
                settings['api']['urls']['sales'],
                headers,
                context,
                chat_id,
                method='POST',
                json_data=request_data
            )
            if not response or 'data' not in response:
                return None
            return response['data']
    except Exception as e:
        logger.error(f"Ошибка при получении данных о продажах: {str(e)}")
        return None

async def format_sales_message(sales_data, period_type, timezone):
    """Форматирование сообщения со статистикой продаж"""
    try:
        if not sales_data or 'cards' not in sales_data:
            return "❌ Нет данных о продажах"
        sales_by_day = {}
        total_orders = 0
        total_sum = 0
        for card in sales_data['cards']:
            vendor_code = card.get('vendorCode', 'N/A')
            stats = card.get('statistics', {}).get('selectedPeriod', {})
            orders_count = stats.get('ordersCount', 0)
            orders_sum = stats.get('ordersSumRub', 0)
            if orders_count > 0:
                total_orders += orders_count
                total_sum += orders_sum
                begin_date = datetime.fromisoformat(stats.get('begin', '').replace('Z', ''))
                date_str = begin_date.strftime('%d.%m.%Y')
                if date_str not in sales_by_day:
                    sales_by_day[date_str] = []
                sales_by_day[date_str].append({
                    'vendor_code': vendor_code,
                    'orders_count': orders_count
                })
        if period_type == 'day':
            message = f"Продажи за {list(sales_by_day.keys())[0]}:\n"
        else:
            now = datetime.now(timezone)
            end_date = now.replace(hour=23, minute=59, second=59)
            begin_date = (now - timedelta(days=6)).replace(hour=0, minute=0, second=1)
            message = f"Продажи за период {begin_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}:\n"
        for date, sales in sales_by_day.items():
            for sale in sales:
                message += f"- Артикул: {sale['vendor_code']}\n"
                message += f"- Заказали: {sale['orders_count']}\n"
                message += "---------------------------\n"
        message += f"\nИтого:\n"
        message += f"-- {total_orders} шт.\n"
        message += f"-- на {total_sum} руб."
        return message
    except Exception as e:
        logger.error(f"Ошибка при форматировании сообщения о продажах: {str(e)}")
        return "❌ Ошибка при формировании статистики"

__all__ = [
    'get_sales_data',
    'format_sales_message',
] 