from pymongo import MongoClient
from datetime import datetime
import logging
from config import CONFIG

logger = logging.getLogger(__name__)

class MongoDB:
    def __init__(self):
        try:
            logger.info(f"Connecting to MongoDB: {CONFIG['MONGODB_URI']}")
            self.client = MongoClient(CONFIG['MONGODB_URI'])
            self.db = self.client[CONFIG['MONGODB_DB']]
            
            # Проверяем существование коллекций
            collections = self.db.list_collection_names()
            logger.info(f"Existing collections: {collections}")
            
            # Создаем коллекции, если их нет
            if 'users' not in collections:
                logger.info("Creating 'users' collection")
                self.db.create_collection('users')
            
            if 'logs' not in collections:
                logger.info("Creating 'logs' collection")
                self.db.create_collection('logs')
                
            if 'settings' not in collections:
                logger.info("Creating 'settings' collection")
                self.db.create_collection('settings')
                # Инициализируем настройки по умолчанию
                self.init_default_settings()
            
            self.users = self.db.users
            self.logs = self.db.logs
            self.settings = self.db.settings
            self.activities = self.db.activities
            self.create_indexes()
            logger.info("Successfully connected to MongoDB and initialized collections")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            raise

    def create_indexes(self):
        """Создание индексов для оптимизации запросов"""
        self.users.create_index('user_id', unique=True)
        self.activities.create_index([('user_id', 1), ('timestamp', -1)])
        self.activities.create_index('timestamp', expireAfterSeconds=30*24*60*60)  # TTL 30 дней

    def init_default_settings(self):
        """Инициализация настроек по умолчанию"""
        try:
            default_settings = {
                'WORKING_HOURS_START': CONFIG['WORKING_HOURS_START'],
                'WORKING_HOURS_END': CONFIG['WORKING_HOURS_END'],
                'check_stock_interval': CONFIG['CHECK_STOCK_INTERVAL'],
                'check_coefficients_interval': CONFIG['CHECK_COEFFICIENTS_INTERVAL'],
                'low_stock_threshold': CONFIG['LOW_STOCK_THRESHOLD'],
                'min_coefficient': CONFIG['MIN_COEFFICIENT'],
                'max_coefficient': CONFIG['MAX_COEFFICIENT'],
                'target_warehouse_id': CONFIG['TARGET_WAREHOUSE_ID'],
                'ex_warehouse_id': CONFIG['EX_WAREHOUSE_ID'],
                'api_urls': CONFIG['API_URLS'],
                'delay_between_requests': CONFIG['DELAY_BETWEEN_REQUESTS']
            }
            
            # Проверяем, есть ли уже настройки
            if self.settings.count_documents({}) == 0:
                self.settings.insert_one({
                    '_id': 'global',
                    **default_settings
                })
                logger.info("Default settings initialized in database")
            else:
                logger.info("Settings already exist in database")
        except Exception as e:
            logger.error(f"Failed to initialize default settings: {str(e)}")
            raise

    def get_global_settings(self):
        """Получение глобальных настроек"""
        try:
            settings = self.settings.find_one({'_id': 'global'})
            if not settings:
                logger.warning("Global settings not found, initializing defaults")
                self.init_default_settings()
                settings = self.settings.find_one({'_id': 'global'})
            return settings
        except Exception as e:
            logger.error(f"Failed to get global settings: {str(e)}")
            raise

    def update_global_settings(self, settings: dict):
        """Обновление глобальных настроек"""
        try:
            result = self.settings.update_one(
                {'_id': 'global'},
                {'$set': settings}
            )
            logger.info(f"Global settings updated: {result.modified_count} documents modified")
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to update global settings: {str(e)}")
            return False

    def init_user(self, user_id: int, token: str):
        """Инициализация нового пользователя"""
        user_data = {
            'user_id': user_id,
            'token': token,
            'created_at': datetime.utcnow(),
            'last_activity': datetime.utcnow(),
            'settings': {
                'target_warehouses': [],
                'disabled_warehouses': [],
                'last_notification': None,
                'auto_coefficients': False,
                'check_coefficients_interval': CONFIG['CHECK_COEFFICIENTS_INTERVAL'],
                'working_hours_start': CONFIG['WORKING_HOURS_START'],
                'working_hours_end': CONFIG['WORKING_HOURS_END'],
                'low_stock_threshold': CONFIG['LOW_STOCK_THRESHOLD']
            }
        }
        try:
            self.users.update_one(
                {'user_id': user_id},
                {'$setOnInsert': user_data},
                upsert=True
            )
            logger.info(f"User {user_id} initialized with default settings")
        except Exception as e:
            logger.error(f"Failed to initialize user {user_id}: {str(e)}")
            raise

    def update_user_activity(self, user_id: int):
        """Обновление времени последней активности пользователя"""
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'last_activity': datetime.now()}}
        )

    def update_auto_coefficients(self, user_id: int, status: bool):
        """Обновление статуса автоматического отслеживания коэффициентов"""
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'settings.auto_coefficients': status}}
        )

    def update_auto_stock(self, user_id: int, status: bool):
        """Обновление статуса автоматической проверки остатков"""
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'auto_stock': status}}
        )

    def get_user_settings(self, user_id: int) -> dict:
        """Получение настроек пользователя"""
        user = self.users.find_one({'user_id': user_id})
        if user and 'settings' in user:
            return user['settings']
        return {}

    def update_user_settings(self, user_id: int, settings: dict):
        """Обновление настроек пользователя"""
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'settings': settings}}
        )

    def log_activity(self, user_id: int, action: str):
        """Логирование активности пользователя"""
        activity = {
            'user_id': user_id,
            'action': action,
            'timestamp': datetime.utcnow()
        }
        self.activities.insert_one(activity)

    def get_user_stats(self, user_id: int):
        """Получение статистики пользователя"""
        user = self.users.find_one({'user_id': user_id})
        if not user:
            return None
        
        return {
            'user_id': user['user_id'],
            'auto_coefficients': user.get('auto_coefficients', False),
            'auto_stock': user.get('auto_stock', False),
            'last_activity': user.get('last_activity'),
            'warehouse_count': len(user.get('warehouse_selection', []))
        }

    def get_user_activities(self, user_id: int, limit: int = 100) -> list:
        """Получение последних активностей пользователя"""
        return list(self.activities.find(
            {'user_id': user_id},
            {'_id': 0}
        ).sort('timestamp', -1).limit(limit)) 