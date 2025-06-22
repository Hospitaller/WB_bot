import logging
import asyncio

logger = logging.getLogger(__name__)

async def make_api_request(session, url, headers, context, chat_id, method='GET', json_data=None, max_retries=3, timeout=30):
    for attempt in range(max_retries):
        try:
            if method == 'POST':
                async with session.post(url, headers=headers, json=json_data, timeout=timeout) as response:
                    if response.status != 200:
                        error_msg = f"Ошибка запроса: {response.status}"
                        logger.critical(f"CRITICAL: {error_msg} для URL: {url}")
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"❌ {error_msg}"
                        )
                        return None
                    return await response.json()
            else:
                async with session.get(url, headers=headers, timeout=timeout) as response:
                    if response.status != 200:
                        error_msg = f"Ошибка запроса: {response.status}"
                        logger.critical(f"CRITICAL: {error_msg} для URL: {url}")
                        await context.bot.send_message(
                            chat_id=chat_id,
                            text=f"❌ {error_msg}"
                        )
                        return None
                    return await response.json()
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                logger.warning(f"Таймаут при попытке {attempt + 1}/{max_retries}, повторная попытка...")
                await asyncio.sleep(5)
                continue
            error_msg = "Превышено время ожидания ответа от сервера"
            logger.critical(f"CRITICAL: {error_msg} для URL: {url}")
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {error_msg}"
            )
            return None
        except Exception as e:
            error_msg = f"Ошибка при выполнении запроса: {str(e)}"
            logger.critical(f"CRITICAL: {error_msg} для URL: {url}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ {error_msg}"
            )
            return None 