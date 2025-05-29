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
            
            # Получаем ссылки на коллекции
            self.settings = self.db.settings
            self.logs = self.db.logs
            self.users = self.db.users  # Новая коллекция users
            
            # Создаем индексы
            self.create_indexes()
            logger.info("Successfully connected to MongoDB")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            raise

    def create_indexes(self):
        """Создание индексов для оптимизации запросов"""
        self.settings.create_index('user_id', unique=True)
        self.logs.create_index([('user_id', 1), ('timestamp', -1)])
        self.users.create_index('user_id', unique=True)  # Индекс для users

    def get_global_settings(self):
        """Получение глобальных настроек"""
        try:
            settings = self.settings.find_one({'_id': 'global'})
            if not settings:
                logger.error("Global settings not found in database")
                raise Exception("Global settings not found in database")
            return settings
        except Exception as e:
            logger.error(f"Failed to get global settings: {str(e)}")
            raise

    def init_user(self, user_id: int, first_name: str = None, username: str = None, last_name: str = None):
        """Инициализация нового пользователя"""
        try:
            # Получаем глобальные настройки
            global_settings = self.settings.find_one({'_id': 'global'})
            if not global_settings:
                logger.error("Global settings not found in database")
                raise Exception("Global settings not found in database")

            # Копируем значения из глобальных настроек
            default_settings = global_settings['default_settings']
            
            # Создаем запись в коллекции settings
            user_data = {
                'user_id': user_id,
                'settings': {
                    'intervals': default_settings.get('intervals', {}),
                    'thresholds': default_settings.get('thresholds', {}),
                    'warehouses': {
                        'target': [],
                        'excluded': default_settings.get('warehouses', {}).get('excluded', []),
                        'paused': [],
                        'disabled': []
                    },
                    'working_hours': default_settings.get('working_hours', {}),
                    'auto_coefficients': False
                },
                'metadata': {
                    'created': datetime.utcnow(),
                    'updated': datetime.utcnow(),
                    'last_notification': None
                }
            }
            
            self.settings.update_one(
                {'user_id': user_id},
                {'$setOnInsert': user_data},
                upsert=True
            )
            logger.info(f"User {user_id} initialized with default settings")

            # Создаем запись в коллекции users
            user_info = {
                'user_id': user_id,
                'first_name': first_name,
                'last_name': last_name,
                'username': username,
                'warehouses': {
                    'target': [],
                    'excluded': default_settings.get('warehouses', {}).get('excluded', []),
                    'paused': [],
                    'disabled': []
                },
                'auto_coefficients': False,
                'subscription': {
                    'level': 0,
                    'start_date': None,
                    'end_date': None
                },
                'last_activity': datetime.utcnow()
            }
            
            self.users.update_one(
                {'user_id': user_id},
                {'$setOnInsert': user_info},
                upsert=True
            )
            logger.info(f"User {user_id} info saved in users collection")
            
        except Exception as e:
            logger.error(f"Failed to initialize user {user_id}: {str(e)}")
            raise

    def update_user_activity(self, user_id: int):
        """Обновление времени последней активности пользователя"""
        try:
            # Обновляем в коллекции settings
            result = self.settings.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'metadata.updated': datetime.utcnow()
                    }
                }
            )
            
            # Обновляем в коллекции users
            self.users.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'last_activity': datetime.utcnow()
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
            # Обновляем в коллекции settings
            self.settings.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'settings.auto_coefficients': status,
                        'metadata.updated': datetime.utcnow()
                    }
                }
            )
            
            # Обновляем в коллекции users
            self.users.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'auto_coefficients': status
                    }
                }
            )
            
            logger.info(f"Updated auto_coefficients status for user {user_id}: {status}")
        except Exception as e:
            logger.error(f"Failed to update auto_coefficients status for {user_id}: {str(e)}")
            raise

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
            
            # Добавляем API настройки из глобальных настроек
            merged_settings['api'] = global_settings['api']
            
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
                    if key == 'warehouses':
                        # Для warehouses обновляем только указанные подполя
                        for subkey, subvalue in value.items():
                            update_data[f'settings.warehouses.{subkey}'] = subvalue
                    else:
                        update_data[f'settings.{key}'] = value
            
            if update_data:
                update_data['metadata.updated'] = datetime.utcnow()
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
            # Обновляем в коллекции settings
            result = self.settings.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'settings.warehouses.target': warehouses,
                        'metadata.updated': datetime.utcnow()
                    }
                }
            )
            
            # Обновляем в коллекции users
            self.users.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'warehouses.target': warehouses
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
                    '$set': {'metadata.updated': datetime.utcnow()}
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
                    '$set': {'metadata.updated': datetime.utcnow()}
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
        self.logs.insert_one(activity)

    def get_user_activities(self, user_id: int, limit: int = 100) -> list:
        """Получение последних активностей пользователя"""
        return list(self.logs.find(
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
                        'metadata.updated': datetime.utcnow()
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