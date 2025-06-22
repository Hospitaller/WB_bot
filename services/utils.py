import logging
from datetime import datetime, time
import pytz

logger = logging.getLogger(__name__)

def is_working_time(user_id: int, mongo, timezone, is_auto_check: bool = False):
    """Проверка на рабочее время"""
    try:
        if not is_auto_check:
            return True
        settings = mongo.get_user_settings(user_id)
        if not settings:
            logger.error(f"No settings found for user {user_id} in is_working_time")
            return False
        now = datetime.now(timezone)
        current_time = now.time()
        working_hours = settings.get('working_hours', {})
        working_hours_start = working_hours.get('start', 9)
        working_hours_end = working_hours.get('end', 22)
        if working_hours_start == 0 and working_hours_end == 0:
            logger.info(f"No working hours restrictions for user {user_id}")
            return True
        working_hours_start = time(hour=working_hours_start)
        working_hours_end = time(hour=working_hours_end)
        logger.info(f"Checking working hours for user {user_id}:")
        logger.info(f"Current time: {current_time}")
        logger.info(f"Working hours start: {working_hours_start}")
        logger.info(f"Working hours end: {working_hours_end}")
        logger.info(f"Settings: {settings}")
        is_working = working_hours_start <= current_time < working_hours_end
        logger.info(f"Is working time: {is_working}")
        return is_working
    except Exception as e:
        logger.error(f"Error checking working hours for user {user_id}: {str(e)}", exc_info=True)
        return False

__all__ = [
    'is_working_time',
]
