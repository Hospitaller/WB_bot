import os
import sys
import logging
from migrate_settings import migrate_settings

# Добавляем родительскую директорию в PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/migration_run.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def main():
    """Запуск миграции"""
    try:
        logger.info("Starting migration process...")
        
        # Создаем директорию для логов, если её нет
        os.makedirs('logs', exist_ok=True)
        
        # Запускаем миграцию
        if migrate_settings():
            logger.info("Migration completed successfully")
            print("✅ Миграция успешно завершена")
        else:
            logger.error("Migration failed")
            print("❌ Ошибка при выполнении миграции")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Error during migration process: {str(e)}", exc_info=True)
        print(f"❌ Критическая ошибка: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    main() 