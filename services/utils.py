import logging
from datetime import datetime, time
import pytz

logger = logging.getLogger(__name__)

def is_working_time(user_id: int, mongo, timezone, is_auto_check: bool = False):
    """Проверка на рабочее время"""
    try:
        if not is_auto_check:
            return True
        settings = mongo.get_user_settings(user_id)
        if not settings:
            logger.error(f"No settings found for user {user_id} in is_working_time")
            return False
        now = datetime.now(timezone)
        current_time = now.time()
        working_hours = settings.get('working_hours', {})
        working_hours_start = working_hours.get('start', 9)
        working_hours_end = working_hours.get('end', 22)
        if working_hours_start == 0 and working_hours_end == 0:
            logger.info(f"No working hours restrictions for user {user_id}")
            return True
        working_hours_start = time(hour=working_hours_start)
        working_hours_end = time(hour=working_hours_end)
        logger.info(f"Checking working hours for user {user_id}:")
        logger.info(f"Current time: {current_time}")
        logger.info(f"Working hours start: {working_hours_start}")
        logger.info(f"Working hours end: {working_hours_end}")
        logger.info(f"Settings: {settings}")
        is_working = working_hours_start <= current_time < working_hours_end
        logger.info(f"Is working time: {is_working}")
        return is_working
    except Exception as e:
        logger.error(f"Error checking working hours for user {user_id}: {str(e)}", exc_info=True)
        return False

def format_coefficients_message(coefficients_response, tariffs_data, settings):
    from datetime import datetime
    warehouses = settings.get('warehouses', {})
    target_warehouses = warehouses.get('target', [])
    excluded_warehouses = warehouses.get('excluded', [])
    paused_warehouses = warehouses.get('paused', [])
    target_names = set()
    excluded_names = set()
    filtered_data = {}
    for item in coefficients_response:
        warehouse_id = None
        try:
            warehouse_id = item.get('warehouseID')
            if warehouse_id is None:
                continue
            warehouse_id = int(warehouse_id)
            warehouse_name = item.get('warehouseName', 'N/A')
            if str(warehouse_id) in paused_warehouses:
                continue
            if warehouse_id in target_warehouses:
                target_names.add(warehouse_name)
            if str(warehouse_id) in excluded_warehouses:
                excluded_names.add(warehouse_name)
                continue
            if target_warehouses and warehouse_id not in target_warehouses:
                continue
            thresholds = settings.get('thresholds', {})
            if (item.get('boxTypeName') == "Короба" and 
                item.get('allowUnload', False) and
                item.get('coefficient') >= thresholds.get('min_coefficient', 0) and 
                item.get('coefficient') <= thresholds.get('max_coefficient', 6)):
                date = item.get('date', 'N/A')
                coefficient = item.get('coefficient', 'N/A')
                try:
                    date = date.replace('Z', '')
                    date_obj = datetime.fromisoformat(date)
                    formatted_date = date_obj.strftime('%d.%m.%Y')
                except:
                    formatted_date = date
                if warehouse_name not in filtered_data:
                    filtered_data[warehouse_name] = {
                        'dates': [],
                        'tariff': None,
                        'base_cost': None,
                        'liter_cost': None
                    }
                filtered_data[warehouse_name]['dates'].append({
                    'date': formatted_date,
                    'coefficient': coefficient
                })
        except (ValueError, TypeError):
            continue
    # Добавляем информацию о тарифах
    if tariffs_data and 'warehouseList' in tariffs_data:
        for warehouse in tariffs_data['warehouseList']:
            warehouse_name = warehouse.get('warehouseName')
            base_cost = warehouse.get('boxDeliveryBase', 0)
            liter_cost = warehouse.get('boxDeliveryLiter', 0)
            if warehouse_name == "Самара (Новосемейкино)":
                if "Новосемейкино" in filtered_data:
                    filtered_data["Новосемейкино"]['tariff'] = warehouse.get('boxDeliveryAndStorageExpr')
                    filtered_data["Новосемейкино"]['base_cost'] = base_cost
                    filtered_data["Новосемейкино"]['liter_cost'] = liter_cost
            elif warehouse_name == "Краснодар":
                if "Краснодар (Тихорецкая)" in filtered_data:
                    filtered_data["Краснодар (Тихорецкая)"]['tariff'] = warehouse.get('boxDeliveryAndStorageExpr')
                    filtered_data["Краснодар (Тихорецкая)"]['base_cost'] = base_cost
                    filtered_data["Краснодар (Тихорецкая)"]['liter_cost'] = liter_cost
            elif warehouse_name in filtered_data:
                filtered_data[warehouse_name]['tariff'] = warehouse.get('boxDeliveryAndStorageExpr')
                filtered_data[warehouse_name]['base_cost'] = base_cost
                filtered_data[warehouse_name]['liter_cost'] = liter_cost
    for warehouse in filtered_data:
        filtered_data[warehouse]['dates'].sort(key=lambda x: datetime.strptime(x['date'], '%d.%m.%Y'))
    MAX_MESSAGE_LENGTH = 3500
    current_message = "📊 Коэффициенты складов (Короба):\n\n"
    if target_names:
        current_message += f"*Целевые склады:* {', '.join(sorted(target_names))}\n"
    if excluded_names:
        current_message += f"*Исключенные склады:* {', '.join(sorted(excluded_names))}\n"
    current_message += "\n"
    messages = []
    has_data = False
    for warehouse_name, data in filtered_data.items():
        if not data['dates']:
            continue
        has_data = True
        new_line = f"*{warehouse_name}*:\n"
        if data['tariff']:
            tariff = int(data['tariff'])
            base_cost = data.get('base_cost', 0)
            liter_cost = data.get('liter_cost', 0)
            if 0 <= tariff <= 130:
                new_line += f"Кф. склада: `{data['tariff']}%` ✅\n"
                new_line += f"Логистика: `{base_cost} руб.+ {liter_cost} доп.л`\n"
            elif 131 <= tariff <= 150:
                new_line += f"Кф. склада: `{data['tariff']}%` ⚠️\n"
                new_line += f"Логистика: `{base_cost} руб.+ {liter_cost} доп.л`\n"
            else:
                new_line += f"Кф. склада: `{data['tariff']}%` ❌\n"
                new_line += f"Логистика: `{base_cost} руб.+ {liter_cost} доп.л`\n"
        for item in data['dates']:
            new_line += f"--- {item['date']} = {item['coefficient']}\n"
        new_line += "\n"
        if len(current_message) + len(new_line) > MAX_MESSAGE_LENGTH:
            messages.append(current_message)
            current_message = new_line
        else:
            current_message += new_line
    if current_message:
        messages.append(current_message)
    return messages, has_data, target_warehouses, target_names

def format_stock_message(formatted_data, low_stock_data):
    messages = []
    if formatted_data:
        messages.append("📦 Остатки на складах:\n" + "\n".join(formatted_data))
    if low_stock_data:
        messages.append("⚠️ ТОВАРЫ ЗАКАНЧИВАЮТСЯ! ⚠️\n" + "\n".join(low_stock_data))
    return messages

def format_sales_message(sales_data, period_type, timezone):
    from datetime import datetime, timedelta
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

__all__ = [
    'is_working_time',
]
