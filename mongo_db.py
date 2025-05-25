from pymongo import MongoClient
from datetime import datetime
import logging
from config import CONFIG

class MongoDB:
    def __init__(self):
        self.client = MongoClient(CONFIG['MONGODB_URI'])
        self.db = self.client[CONFIG['MONGODB_DB']]
        self.users = self.db.users
        self.logs = self.db.logs

    def init_user(self, user_id: int, token: str):
        """Инициализация пользователя с настройками по умолчанию"""
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
        self.users.update_one(
            {'user_id': user_id},
            {'$set': user_data},
            upsert=True
        )

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
        log_entry = {
            'user_id': user_id,
            'action': action,
            'timestamp': datetime.now(),
            'details': details or {}
        }
        self.logs.insert_one(log_entry)

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