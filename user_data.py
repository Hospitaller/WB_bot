import json
import os
from typing import Dict, Optional

class UserData:
    def __init__(self, file_path: str = 'user_data.json'):
        self.file_path = file_path
        self.data: Dict[int, Dict] = self._load_data()

    def _load_data(self) -> Dict[int, Dict]:
        try:
            if os.path.exists(self.file_path):
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Ошибка при загрузке данных: {str(e)}")
            return {}

    def _save_data(self):
        try:
            # Создаем директорию, если её нет
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            
            # Сохраняем данные
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            print(f"Данные успешно сохранены в {self.file_path}")
        except Exception as e:
            print(f"Ошибка при сохранении данных: {str(e)}")

    def add_user(self, user_id: int, wb_token: str):
        self.data[user_id] = {
            'wb_token': wb_token,
            'auto_check_enabled': False
        }
        self._save_data()

    def get_user_token(self, user_id: int) -> Optional[str]:
        return self.data.get(user_id, {}).get('wb_token')

    def is_user_exists(self, user_id: int) -> bool:
        return user_id in self.data

    def set_auto_check_status(self, user_id: int, status: bool):
        if user_id in self.data:
            self.data[user_id]['auto_check_enabled'] = status
            self._save_data()

    def get_auto_check_status(self, user_id: int) -> bool:
        return self.data.get(user_id, {}).get('auto_check_enabled', False) 