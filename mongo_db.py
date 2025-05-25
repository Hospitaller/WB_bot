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
            
            self.users = self.db.users
            self.logs = self.db.logs
            logger.info("Successfully connected to MongoDB and initialized collections")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            raise

    def init_user(self, user_id: int, token: str):
        """Инициализация пользователя с настройками по умолчанию"""
        try:
            logger.info(f"Initializing user {user_id} with token: {token[:10]}...")
            user_data = {
                'user_id': user_id,
                'token': token,
                'auto_coefficients': False,
                'auto_stock': False,
                'last_activity': datetime.now(),
                'warehouse_selection': [],
                'settings': {
                    'working_hours_start': CONFIG['WORKING_HOURS'].split('-')[0],
                    'working_hours_end': CONFIG['WORKING_HOURS'].split('-')[1],
                    'check_stock_interval': CONFIG['CHECK_STOCK_INTERVAL'],
                    'check_coefficients_interval': CONFIG['CHECK_COEFFICIENTS_INTERVAL'],
                    'low_stock_threshold': CONFIG['LOW_STOCK_THRESHOLD'],
                    'min_coefficient': CONFIG['MIN_COEFFICIENT'],
                    'max_coefficient': CONFIG['MAX_COEFFICIENT']
                }
            }
            result = self.users.update_one(
                {'user_id': user_id},
                {'$set': user_data},
                upsert=True
            )
            logger.info(f"User initialization result: {result.raw_result}")
            
            # Проверяем, что пользователь действительно создан
            user = self.users.find_one({'user_id': user_id})
            if user:
                logger.info(f"User {user_id} successfully created/updated in database")
            else:
                logger.error(f"Failed to create/update user {user_id} in database")
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
        """Обновление статуса автоматической проверки коэффициентов"""
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'auto_coefficients': status}}
        )

    def update_auto_stock(self, user_id: int, status: bool):
        """Обновление статуса автоматической проверки остатков"""
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'auto_stock': status}}
        )

    def get_user_settings(self, user_id: int):
        """Получение настроек пользователя"""
        user = self.users.find_one({'user_id': user_id})
        return user.get('settings', {}) if user else {}

    def log_activity(self, user_id: int, action: str, details: dict = None):
        """Логирование активности пользователя"""
        try:
            log_entry = {
                'user_id': user_id,
                'action': action,
                'timestamp': datetime.now(),
                'details': details or {}
            }
            logger.info(f"Logging activity: {log_entry}")
            result = self.logs.insert_one(log_entry)
            logger.info(f"Activity logged successfully: {result.inserted_id}")
        except Exception as e:
            logger.error(f"Failed to log activity: {str(e)}")
            raise

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