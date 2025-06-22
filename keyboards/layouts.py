from .builder import inline_btn, inline_kb

# Клавиатура для меню продаж

def get_sales_menu_kb():
    return inline_kb([
        [inline_btn("День", 'sales_day')],
        [inline_btn("Неделя", 'sales_week')]
    ])

# Кнопка Premium

def get_premium_kb():
    return inline_kb([[inline_btn("Premium", 'premium_info')]])

# Кнопки для админа

def get_admin_kb():
    return inline_kb([
        [inline_btn("✉️ Сообщение", 'send_messages')],
        [inline_btn("📋 Статистика", 'admin_statistics')]
    ])

# Кнопка для рассылки

def get_broadcast_kb():
    return inline_kb([[inline_btn("Отправить", 'broadcast_message')]])

# Клавиатура для коэффициентов

def get_coefficients_menu_kb():
    return inline_kb([
        [inline_btn("Все склады", 'check_all_coefficients')],
        [inline_btn("Запустить авто лимиты", 'start_auto_coefficients')],
        [inline_btn("Остановить авто лимиты", 'stop_auto_coefficients')]
    ])

# Клавиатура для остатков

def get_stock_menu_kb():
    return inline_kb([
        [inline_btn("Остатки на складах", 'check_all_stock')],
        [inline_btn("Запустить авто остатки", 'start_auto_stock')],
        [inline_btn("Остановить авто остатки", 'stop_auto_stock')]
    ])

# Клавиатура для навигации по складам (страницы, удалить, завершить)
def get_warehouse_nav_kb(available, selected, page, total_pages):
    keyboard = []
    for warehouse_id, warehouse_name in available:
        keyboard.append([inline_btn(f"-- {warehouse_name} --", f"select_warehouse_{warehouse_id}")])
    nav_buttons = []
    if page > 0:
        nav_buttons.append(inline_btn("◀️ Назад", f"warehouse_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(inline_btn("Далее ▶️", f"warehouse_page_{page+1}"))
    if nav_buttons:
        keyboard.append(nav_buttons)
    if selected:
        keyboard.append([inline_btn("🗑 Удалить последний", "remove_last_warehouse")])
    keyboard.append([inline_btn("✅ Завершить", "finish_warehouse_selection")])
    return inline_kb(keyboard)

# Клавиатура для отключения складов до завтра/совсем
def get_disable_warehouses_kb(list_of_id_chunks):
    buttons = []
    for chunk in list_of_id_chunks:
        buttons.append([inline_btn("🔕 Выключить до завтра", f"disable_warehouses:{','.join(str(i) for i in chunk)}")])
    buttons.append([inline_btn("🛑 Выключить совсем", "stop_auto_coefficients")])
    return inline_kb(buttons)
