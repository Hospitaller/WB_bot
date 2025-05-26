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
        self.settings.create_index('user_id', unique=True)
        self.activities.create_index([('user_id', 1), ('timestamp', -1)])
        self.activities.create_index('timestamp', expireAfterSeconds=30*24*60*60)  # TTL 30 дней

    def init_default_settings(self):
        """Инициализация настроек по умолчанию"""
        try:
            default_settings = {
                '_id': 'global',
                'default_settings': {
                    'intervals': {
                        'check_stock': CONFIG['CHECK_STOCK_INTERVAL'],
                        'check_coefficients': CONFIG['CHECK_COEFFICIENTS_INTERVAL']
                    },
                    'thresholds': {
                        'low_stock': CONFIG['LOW_STOCK_THRESHOLD'],
                        'min_coefficient': CONFIG['MIN_COEFFICIENT'],
                        'max_coefficient': CONFIG['MAX_COEFFICIENT']
                    },
                    'warehouses': {
                        'target': [],
                        'excluded': CONFIG['EX_WAREHOUSE_ID'].split(',') if CONFIG['EX_WAREHOUSE_ID'] else [],
                        'paused': []
                    },
                    'api': {
                        'urls': {
                            'stock': {
                                'request': CONFIG['API_URLS']['first'],
                                'download': CONFIG['API_URLS']['second']
                            },
                            'coefficients': CONFIG['API_URLS']['coefficients']
                        },
                        'request_delay': CONFIG['DELAY_BETWEEN_REQUESTS']
                    },
                    'working_hours': {
                        'start': CONFIG['WORKING_HOURS_START'],
                        'end': CONFIG['WORKING_HOURS_END']
                    }
                }
            }
            
            # Проверяем, есть ли уже настройки
            if self.settings.count_documents({}) == 0:
                self.settings.insert_one(default_settings)
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

    def init_user(self, user_id: int):
        """Инициализация нового пользователя"""
        try:
            user_data = {
                'user_id': user_id,
                'settings': {
                    'intervals': {},
                    'thresholds': {},
                    'warehouses': {
                        'disabled': [],
                        'target': [],
                        'paused': []
                    },
                    'auto_coefficients': False
                },
                'metadata': {
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow(),
                    'last_notification': None
                }
            }
            
            self.settings.update_one(
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
        try:
            result = self.settings.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'metadata.updated_at': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Время последней активности обновлено для пользователя {user_id}")
                return True
            else:
                logger.warning(f"Не удалось обновить время последней активности для пользователя {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени последней активности для пользователя {user_id}: {str(e)}")
            return False

    def update_auto_coefficients(self, user_id: int, status: bool):
        """Обновление статуса автоматического отслеживания коэффициентов"""
        try:
            self.settings.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'settings.auto_coefficients': status,
                        'metadata.updated_at': datetime.utcnow()
                    }
                }
            )
            logger.info(f"Updated auto_coefficients status for user {user_id}: {status}")
        except Exception as e:
            logger.error(f"Failed to update auto_coefficients status for {user_id}: {str(e)}")
            raise

    def update_auto_stock(self, user_id: int, status: bool):
        """Обновление статуса автоматической проверки остатков"""
        self.users.update_one(
            {'user_id': user_id},
            {'$set': {'auto_stock': status}}
        )

    def get_user_settings(self, user_id: int) -> dict:
        """Получение настроек пользователя с мержем глобальных настроек"""
        try:
            # Получаем глобальные настройки
            global_settings = self.settings.find_one({'_id': 'global'})
            if not global_settings:
                logger.warning("Global settings not found, initializing defaults")
                self.init_default_settings()
                global_settings = self.settings.find_one({'_id': 'global'})
            
            # Получаем пользовательские настройки
            user_settings = self.settings.find_one({'user_id': user_id})
            if not user_settings:
                logger.warning(f"User settings not found for {user_id}, initializing defaults")
                self.init_user(user_id)
                user_settings = self.settings.find_one({'user_id': user_id})
            
            # Мержим настройки
            merged_settings = global_settings['default_settings'].copy()
            
            # Обновляем интервалы
            if 'intervals' in user_settings['settings']:
                merged_settings['intervals'].update(user_settings['settings']['intervals'])
            
            # Обновляем пороговые значения
            if 'thresholds' in user_settings['settings']:
                merged_settings['thresholds'].update(user_settings['settings']['thresholds'])
            
            # Обновляем настройки складов
            if 'warehouses' in user_settings['settings']:
                merged_settings['warehouses'].update(user_settings['settings']['warehouses'])
            
            # Добавляем статус автоотслеживания
            merged_settings['auto_coefficients'] = user_settings['settings'].get('auto_coefficients', False)
            
            return merged_settings
        except Exception as e:
            logger.error(f"Failed to get user settings for {user_id}: {str(e)}")
            return {}

    def update_user_settings(self, user_id: int, settings: dict):
        """Обновление настроек пользователя"""
        try:
            # Обновляем только указанные поля
            update_data = {}
            for key, value in settings.items():
                if key in ['intervals', 'thresholds', 'warehouses', 'auto_coefficients']:
                    update_data[f'settings.{key}'] = value
            
            if update_data:
                update_data['metadata.updated_at'] = datetime.utcnow()
                self.settings.update_one(
                    {'user_id': user_id},
                    {'$set': update_data}
                )
                logger.info(f"Updated settings for user {user_id}: {update_data}")
        except Exception as e:
            logger.error(f"Failed to update user settings for {user_id}: {str(e)}")
            raise

    def save_selected_warehouses(self, user_id: int, warehouses: list):
        """Сохранение выбранных складов пользователя"""
        try:
            result = self.settings.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'settings.warehouses.target': warehouses,
                        'metadata.updated_at': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Склады успешно сохранены для пользователя {user_id}: {warehouses}")
                return True
            else:
                logger.warning(f"Не удалось сохранить склады для пользователя {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при сохранении складов для пользователя {user_id}: {str(e)}")
            return False

    def get_selected_warehouses(self, user_id: int) -> list:
        """Получение выбранных складов пользователя"""
        try:
            settings = self.settings.find_one({'user_id': user_id})
            if settings and 'settings' in settings and 'warehouses' in settings['settings']:
                warehouses = settings['settings']['warehouses'].get('target', [])
                logger.info(f"Получены склады для пользователя {user_id}: {warehouses}")
                return warehouses
            logger.warning(f"Склады не найдены для пользователя {user_id}")
            return []
        except Exception as e:
            logger.error(f"Ошибка при получении складов для пользователя {user_id}: {str(e)}")
            return []

    def update_warehouse_status(self, user_id: int, warehouse_id: str, status: str):
        """Обновление статуса склада (disabled/paused)"""
        try:
            if status not in ['disabled', 'paused']:
                raise ValueError(f"Invalid status: {status}")
                
            result = self.settings.update_one(
                {'user_id': user_id},
                {
                    '$addToSet': {f'settings.warehouses.{status}': warehouse_id},
                    '$set': {'metadata.updated_at': datetime.utcnow()}
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Статус склада {warehouse_id} обновлен для пользователя {user_id}: {status}")
                return True
            else:
                logger.warning(f"Не удалось обновить статус склада {warehouse_id} для пользователя {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при обновлении статуса склада для пользователя {user_id}: {str(e)}")
            return False

    def remove_warehouse_status(self, user_id: int, warehouse_id: str, status: str):
        """Удаление статуса склада (disabled/paused)"""
        try:
            if status not in ['disabled', 'paused']:
                raise ValueError(f"Invalid status: {status}")
                
            result = self.settings.update_one(
                {'user_id': user_id},
                {
                    '$pull': {f'settings.warehouses.{status}': warehouse_id},
                    '$set': {'metadata.updated_at': datetime.utcnow()}
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Статус склада {warehouse_id} удален для пользователя {user_id}: {status}")
                return True
            else:
                logger.warning(f"Не удалось удалить статус склада {warehouse_id} для пользователя {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при удалении статуса склада для пользователя {user_id}: {str(e)}")
            return False

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

    def update_last_notification(self, user_id: int):
        """Обновление времени последнего уведомления"""
        try:
            result = self.settings.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'metadata.last_notification': datetime.utcnow(),
                        'metadata.updated_at': datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                logger.info(f"Время последнего уведомления обновлено для пользователя {user_id}")
                return True
            else:
                logger.warning(f"Не удалось обновить время последнего уведомления для пользователя {user_id}")
                return False
                
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени последнего уведомления для пользователя {user_id}: {str(e)}")
            return False

    def get_last_notification(self, user_id: int) -> datetime:
        """Получение времени последнего уведомления"""
        try:
            settings = self.settings.find_one({'user_id': user_id})
            if settings and 'metadata' in settings and 'last_notification' in settings['metadata']:
                return settings['metadata']['last_notification']
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении времени последнего уведомления для пользователя {user_id}: {str(e)}")
            return None 