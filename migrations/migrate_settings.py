from pymongo import MongoClient
from datetime import datetime
import logging
from config import CONFIG

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/migration.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def migrate_settings():
    """Миграция настроек в MongoDB на новую структуру"""
    try:
        # Подключение к MongoDB
        client = MongoClient(CONFIG['MONGODB_URI'])
        db = client[CONFIG['MONGODB_DB']]
        settings_collection = db.settings
        users_collection = db.users

        logger.info("Starting settings migration...")

        # 1. Миграция глобальных настроек
        global_settings = settings_collection.find_one({'_id': 'global'})
        if global_settings:
            logger.info("Migrating global settings...")
            
            # Создаем новую структуру глобальных настроек
            new_global_settings = {
                '_id': 'global',
                'default_settings': {
                    'intervals': {
                        'check_stock': global_settings.get('check_stock_interval', CONFIG['CHECK_STOCK_INTERVAL']),
                        'check_coefficients': global_settings.get('check_coefficients_interval', CONFIG['CHECK_COEFFICIENTS_INTERVAL'])
                    },
                    'thresholds': {
                        'low_stock': global_settings.get('low_stock_threshold', CONFIG['LOW_STOCK_THRESHOLD']),
                        'min_coefficient': global_settings.get('min_coefficient', CONFIG['MIN_COEFFICIENT']),
                        'max_coefficient': global_settings.get('max_coefficient', CONFIG['MAX_COEFFICIENT'])
                    },
                    'warehouses': {
                        'target': [],
                        'excluded': global_settings.get('ex_warehouse_id', '').split(',') if global_settings.get('ex_warehouse_id') else [],
                        'paused': global_settings.get('TARGET_WAREHOUSE_ID_PAUSE', [])
                    },
                    'api': {
                        'urls': {
                            'stock': {
                                'request': global_settings.get('api_urls', {}).get('first', CONFIG['API_URLS']['first']),
                                'download': global_settings.get('api_urls', {}).get('second', CONFIG['API_URLS']['second'])
                            },
                            'coefficients': global_settings.get('api_urls', {}).get('coefficients', CONFIG['API_URLS']['coefficients'])
                        },
                        'request_delay': global_settings.get('delay_between_requests', CONFIG['DELAY_BETWEEN_REQUESTS'])
                    },
                    'working_hours': {
                        'start': global_settings.get('WORKING_HOURS_START', CONFIG['WORKING_HOURS_START']),
                        'end': global_settings.get('WORKING_HOURS_END', CONFIG['WORKING_HOURS_END'])
                    }
                }
            }

            # Обновляем глобальные настройки
            settings_collection.replace_one({'_id': 'global'}, new_global_settings)
            logger.info("Global settings migration completed")

        # 2. Миграция пользовательских настроек
        users = users_collection.find({})
        for user in users:
            user_id = user.get('user_id')
            if not user_id:
                continue

            logger.info(f"Migrating settings for user {user_id}...")

            # Получаем текущие настройки пользователя
            user_settings = settings_collection.find_one({'user_id': user_id})
            
            # Создаем новую структуру пользовательских настроек
            new_user_settings = {
                'user_id': user_id,
                'settings': {
                    'intervals': {},
                    'thresholds': {},
                    'warehouses': {
                        'disabled': [],
                        'target': user_settings.get('target_warehouses', []) if user_settings else [],
                        'paused': []
                    },
                    'auto_coefficients': user.get('settings', {}).get('auto_coefficients', False) if user.get('settings') else False
                },
                'metadata': {
                    'created_at': user.get('created_at', datetime.utcnow()),
                    'updated_at': user.get('last_activity', datetime.utcnow()),
                    'last_notification': user_settings.get('last_notification') if user_settings else None
                }
            }

            # Если есть пользовательские настройки, переносим их
            if user_settings:
                # Переносим интервалы
                if 'check_coefficients_interval' in user_settings:
                    new_user_settings['settings']['intervals']['check_coefficients'] = user_settings['check_coefficients_interval']
                
                # Переносим пороговые значения
                if 'low_stock_threshold' in user_settings:
                    new_user_settings['settings']['thresholds']['low_stock'] = user_settings['low_stock_threshold']

            # Обновляем или создаем настройки пользователя
            settings_collection.update_one(
                {'user_id': user_id},
                {'$set': new_user_settings},
                upsert=True
            )
            logger.info(f"User {user_id} settings migration completed")

        logger.info("Settings migration completed successfully")
        return True

    except Exception as e:
        logger.error(f"Error during migration: {str(e)}", exc_info=True)
        return False

if __name__ == '__main__':
    migrate_settings() 