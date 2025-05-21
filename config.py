import os
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Конфигурация бота
CONFIG = {
    'TG_API_KEY': os.getenv('TG_API_KEY'),
    'API_URLS': {
        'first': "https://seller-analytics-api.wildberries.ru/api/v1/warehouse_remains?groupBySa=true",
        'second': "https://seller-analytics-api.wildberries.ru/api/v1/warehouse_remains/tasks/{task_id}/download",
        'coefficients': "https://supplies-api.wildberries.ru/api/v1/acceptance/coefficients"
    },
    'LOW_STOCK_THRESHOLD': 20,  # нижний порог остатков
    'WORKING_HOURS': "08-22",   # Часы работы (МСК)
    'CHECK_STOCK_INTERVAL': 120,      # Интервал проверки остатков в минутах
    'CHECK_COEFFICIENTS_INTERVAL': 5,      # Интервал проверки коэффициентов в минутах
    'DELAY_BETWEEN_REQUESTS': 20,  # задержка между запросами
    'MIN_COEFFICIENT': 0,       # минимальный коэффициент склада
    'MAX_COEFFICIENT': 6,       # максимальный коэффициент склада
    'TARGET_WAREHOUSE_ID': [],   # ID склада для автоматической проверки
    'EX_WAREHOUSE_ID': ['204939', '324108', '218987'],     # ID складов для исключения из проверки
    'LOG_FILE': 'wb_bot_critical.log'
}

# Проверка наличия необходимых переменных окружения
if not CONFIG['TG_API_KEY']:
    raise ValueError("Не найдена необходимая переменная окружения TG_API_KEY") 