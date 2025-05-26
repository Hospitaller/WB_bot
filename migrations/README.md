# Миграция настроек MongoDB

Этот скрипт выполняет миграцию настроек в MongoDB на новую структуру.

## Новая структура настроек

### Глобальные настройки
```json
{
  "_id": "global",
  "default_settings": {
    "intervals": {
      "check_stock": 120,
      "check_coefficients": 1
    },
    "thresholds": {
      "low_stock": 20,
      "min_coefficient": 0,
      "max_coefficient": 6
    },
    "warehouses": {
      "target": [],
      "excluded": ["204939", "324108", "218987"],
      "paused": []
    },
    "api": {
      "urls": {
        "stock": {
          "request": "https://seller-analytics-api.wildberries.ru/api/v1/warehouse_remains?groupBySa=true",
          "download": "https://seller-analytics-api.wildberries.ru/api/v1/warehouse_remains/tasks/{task_id}/download"
        },
        "coefficients": "https://supplies-api.wildberries.ru/api/v1/acceptance/coefficients"
      },
      "request_delay": 20
    },
    "working_hours": {
      "start": 9,
      "end": 22
    }
  }
}
```

### Пользовательские настройки
```json
{
  "_id": ObjectId("68336079ca1d636aa0277402"),
  "user_id": 7185690136,
  "settings": {
    "intervals": {
      "check_coefficients": 30
    },
    "thresholds": {
      "low_stock": 10
    },
    "warehouses": {
      "disabled": [],
      "target": [],
      "paused": []
    },
    "auto_coefficients": false
  },
  "metadata": {
    "created_at": ISODate("2025-05-25T18:24:57.502Z"),
    "updated_at": ISODate("2025-05-26T11:49:05.859Z"),
    "last_notification": ISODate("2025-05-26T10:23:48.593Z")
  }
}
```

## Запуск миграции

1. Убедитесь, что у вас есть доступ к MongoDB
2. Проверьте настройки подключения в файле `config.py`
3. Запустите миграцию:
```bash
python migrations/run_migration.py
```

## Логи

Логи миграции сохраняются в директории `logs`:
- `migration.log` - логи процесса миграции
- `migration_run.log` - логи запуска миграции

## Откат изменений

Перед запуском миграции рекомендуется сделать резервную копию базы данных:
```bash
mongodump --uri="mongodb://your_connection_string" --db=your_database_name
```

Для восстановления из резервной копии:
```bash
mongorestore --uri="mongodb://your_connection_string" --db=your_database_name dump/your_database_name
``` 