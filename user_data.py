import os
from typing import Dict, Optional
from dotenv import load_dotenv, set_key, unset_key

class UserData:
    def __init__(self, env_file: str = '.env'):
        self.env_file = env_file
        load_dotenv(env_file)
        self.data: Dict[int, Dict] = self._load_data()

    def _load_data(self) -> Dict[int, Dict]:
        data = {}
        for key, value in os.environ.items():
            if key.startswith('WB_TOKEN_'):
                user_id = int(key.replace('WB_TOKEN_', ''))
                data[user_id] = {
                    'wb_token': value,
                    'auto_check_enabled': False,
                    'warehouse_token': os.getenv(f'WB_TOKEN_{user_id}_warehouse'),
                    'coefficient': 0  # По умолчанию 0
                }
        return data

    def add_user(self, user_id: int, wb_token: str):
        env_key = f'WB_TOKEN_{user_id}'
        set_key(self.env_file, env_key, wb_token)
        load_dotenv(self.env_file, override=True)
        self.data[user_id] = {
            'wb_token': wb_token,
            'auto_check_enabled': False,
            'warehouse_token': None,
            'coefficient': 0
        }

    def add_warehouse_token(self, user_id: int, token: str):
        env_key = f'WB_TOKEN_{user_id}_warehouse'
        set_key(self.env_file, env_key, token)
        load_dotenv(self.env_file, override=True)
        if user_id in self.data:
            self.data[user_id]['warehouse_token'] = token

    def set_coefficient(self, user_id: int, coefficient: float):
        if user_id in self.data:
            self.data[user_id]['coefficient'] = coefficient

    def get_user_token(self, user_id: int) -> Optional[str]:
        load_dotenv(self.env_file, override=True)
        return os.getenv(f'WB_TOKEN_{user_id}')

    def get_warehouse_token(self, user_id: int) -> Optional[str]:
        load_dotenv(self.env_file, override=True)
        return os.getenv(f'WB_TOKEN_{user_id}_warehouse')

    def get_coefficient(self, user_id: int) -> float:
        return self.data.get(user_id, {}).get('coefficient', 0)

    def is_user_exists(self, user_id: int) -> bool:
        load_dotenv(self.env_file, override=True)
        return f'WB_TOKEN_{user_id}' in os.environ

    def set_auto_check_status(self, user_id: int, status: bool):
        if user_id in self.data:
            self.data[user_id]['auto_check_enabled'] = status

    def get_auto_check_status(self, user_id: int) -> bool:
        return self.data.get(user_id, {}).get('auto_check_enabled', False)

    def remove_user(self, user_id: int):
        env_keys = [
            f'WB_TOKEN_{user_id}',
            f'WB_TOKEN_{user_id}_warehouse'
        ]
        for key in env_keys:
            unset_key(self.env_file, key)
        load_dotenv(self.env_file, override=True)
        if user_id in self.data:
            del self.data[user_id] 