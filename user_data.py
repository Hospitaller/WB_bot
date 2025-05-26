import os
from typing import Dict, Optional
from dotenv import load_dotenv, set_key, unset_key
from mongo_db import MongoDB

class UserData:
    def __init__(self, env_file: str = '.env'):
        self.env_file = env_file
        load_dotenv(env_file)
        self.data: Dict[int, Dict] = self._load_data()
        self.mongo = MongoDB()

    def _load_data(self) -> Dict[int, Dict]:
        data = {}
        for key, value in os.environ.items():
            if key.startswith('AUTH_TOKEN_'):
                user_id = int(key.replace('AUTH_TOKEN_', ''))
                data[user_id] = {
                    'auth_token': value,
                    'auto_check_enabled': False
                }
        return data

    def add_user(self, user_id: int, auth_token: str):
        env_key = f'AUTH_TOKEN_{user_id}'
        set_key(self.env_file, env_key, auth_token)
        load_dotenv(self.env_file, override=True)
        self.data[user_id] = {
            'auth_token': auth_token,
            'auto_check_enabled': False
        }
        # Сохраняем пользователя в MongoDB
        self.mongo.init_user(user_id)

    def get_user_token(self, user_id: int) -> Optional[str]:
        load_dotenv(self.env_file, override=True)
        return os.getenv(f'AUTH_TOKEN_{user_id}')

    def is_user_exists(self, user_id: int) -> bool:
        # Проверяем существование пользователя в MongoDB
        user = self.mongo.settings.find_one({'user_id': user_id})
        return user is not None

    def set_auto_check_status(self, user_id: int, status: bool):
        if user_id in self.data:
            self.data[user_id]['auto_check_enabled'] = status

    def get_auto_check_status(self, user_id: int) -> bool:
        return self.data.get(user_id, {}).get('auto_check_enabled', False)

    def remove_user(self, user_id: int):
        env_key = f'AUTH_TOKEN_{user_id}'
        unset_key(self.env_file, env_key)
        load_dotenv(self.env_file, override=True)
        if user_id in self.data:
            del self.data[user_id] 