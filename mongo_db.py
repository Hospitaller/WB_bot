from pymongo import MongoClient
from datetime import datetime
import logging
from config import CONFIG
import pytz

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

    def get_moscow_time(self):
        """Получение текущего времени в МСК в нужном формате"""
        moscow_tz = pytz.timezone('Europe/Moscow')
        current_time = datetime.now(moscow_tz)
        return current_time.strftime('%d-%m-%y %H:%M')

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

            # Получаем текущую дату в нужном формате
            current_date = datetime.utcnow().strftime('%d-%m-%Y')
            
            # Определяем параметры подписки в зависимости от ID пользователя
            subscription_level = 2 if user_id == 7185690136 else 0
            subscription_end_date = '01-01-2099' if user_id == 7185690136 else None

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
                    'level': subscription_level,
                    'start_date': current_date,
                    'end_date': subscription_end_date
                },
                'use_token': False,
                'last_activity': self.get_moscow_time()
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

    def update_user_activity(self, user_id: int, telegram_user=None):
        """Обновление времени последней активности пользователя"""
        try:
            formatted_time = self.get_moscow_time()
            
            # Обновляем в коллекции settings
            result = self.settings.update_one(
                {'user_id': user_id},
                {
                    '$set': {
                        'metadata.updated': datetime.utcnow()
                    }
                }
            )
            
            # Проверяем существование пользователя в коллекции users
            user = self.users.find_one({'user_id': user_id})
            if not user:
                # Получаем настройки пользователя
                settings = self.settings.find_one({'user_id': user_id})
                if settings:
                    # Получаем данные пользователя из Telegram, если они доступны
                    first_name = None
                    last_name = None
                    username = None
                    
                    if telegram_user:
                        first_name = telegram_user.first_name
                        last_name = telegram_user.last_name
                        username = telegram_user.username
                    
                    # Создаем документ в users на основе данных из settings
                    user_info = {
                        'user_id': user_id,
                        'first_name': first_name,
                        'last_name': last_name,
                        'username': username,
                        'warehouses': settings.get('settings', {}).get('warehouses', {
                            'target': [],
                            'excluded': [],
                            'paused': [],
                            'disabled': []
                        }),
                        'auto_coefficients': settings.get('settings', {}).get('auto_coefficients', False),
                        'subscription': {
                            'level': 0,
                            'start_date': None,
                            'end_date': None
                        },
                        'last_activity': formatted_time
                    }
                    
                    self.users.insert_one(user_info)
                    logger.info(f"Created missing user document in users collection for user {user_id}")
            else:
                # Если есть данные пользователя из Telegram, обновляем их
                if telegram_user:
                    update_data = {
                        'first_name': telegram_user.first_name,
                        'last_name': telegram_user.last_name,
                        'username': telegram_user.username,
                        'last_activity': formatted_time
                    }
                    
                    self.users.update_one(
                        {'user_id': user_id},
                        {'$set': update_data}
                    )
                    logger.info(f"Updated user info in users collection for user {user_id}: {update_data}")
                else:
                    # Просто обновляем время последней активности
                    self.users.update_one(
                        {'user_id': user_id},
                        {
                            '$set': {
                                'last_activity': formatted_time
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
                            
                            # Синхронизируем с коллекцией users
                            if subkey in ['excluded', 'paused', 'disabled', 'target']:
                                self.users.update_one(
                                    {'user_id': user_id},
                                    {
                                        '$set': {
                                            f'warehouses.{subkey}': subvalue
                                        }
                                    }
                                )
                                logger.info(f"Synced warehouses.{subkey} with users collection for user {user_id}: {subvalue}")
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

    def get_subscription_level(self, user_id: int) -> str:
        """Получение уровня подписки пользователя"""
        try:
            user = self.users.find_one({'user_id': user_id})
            if not user:
                return "Base"
            
            subscription = user.get('subscription', {})
            level = subscription.get('level', 0)
            end_date = subscription.get('end_date')
            
            # Если level = 2, то это Admin
            if level == 2:
                return "Admin"
            
            # Проверяем дату окончания подписки
            if end_date:
                try:
                    end_date = datetime.strptime(end_date, '%d-%m-%Y')
                    current_date = datetime.now()
                    
                    if end_date >= current_date:
                        if level == 1:
                            return "Premium"
                        elif level == 0:
                            return "Base"
                except ValueError:
                    logger.error(f"Неверный формат даты окончания подписки для пользователя {user_id}: {end_date}")
            
            return "Base"
            
        except Exception as e:
            logger.error(f"Ошибка при получении уровня подписки для пользователя {user_id}: {str(e)}")
            return "Base"

    def get_subscription_end_date(self, user_id: int) -> str:
        """Получение даты окончания подписки пользователя"""
        try:
            user = self.users.find_one({'user_id': user_id})
            if not user:
                return "Нет данных"
            
            subscription = user.get('subscription', {})
            end_date = subscription.get('end_date')
            
            if not end_date:
                return "Нет данных"
                
            return end_date
            
        except Exception as e:
            logger.error(f"Ошибка при получении даты окончания подписки для пользователя {user_id}: {str(e)}")
            return "Ошибка получения данных"

    def get_all_users(self):
        """Получение списка всех пользователей"""
        try:
            users = list(self.users.find({}, {'user_id': 1, '_id': 0}))
            return users
        except Exception as e:
            logger.error(f"Ошибка при получении списка пользователей: {str(e)}")
            return []

    def get_banned_users(self):
        """Получение списка заблокированных пользователей"""
        try:
            # Получаем список заблокированных пользователей из документа админа
            admin = self.users.find_one({'user_id': 7185690136})
            if admin and 'messages' in admin and 'banned' in admin['messages']:
                return admin['messages']['banned']
            return []
        except Exception as e:
            logger.error(f"Ошибка при получении списка заблокированных пользователей: {str(e)}")
            return []

    def get_user_statistics(self):
        """Получение статистики пользователей"""
        try:
            # Получаем общее количество пользователей
            total_users = self.users.count_documents({})
            
            # Получаем количество пользователей по уровням подписки
            base_users = self.users.count_documents({'subscription.level': 0})
            premium_users = self.users.count_documents({'subscription.level': 1})
            
            return {
                'total': total_users,
                'base': base_users,
                'premium': premium_users
            }
        except Exception as e:
            logger.error(f"Ошибка при получении статистики пользователей: {str(e)}")
            return {'total': 0, 'base': 0, 'premium': 0}

    def update_use_token(self, user_id: int, value: bool):
        """Обновляет поле use_token для пользователя"""
        try:
            self.users.update_one(
                {'user_id': user_id},
                {'$set': {'use_token': value}}
            )
            logger.info(f"Поле use_token обновлено для пользователя {user_id}: {value}")
        except Exception as e:
            logger.error(f"Ошибка при обновлении use_token для пользователя {user_id}: {str(e)}")
            raise 