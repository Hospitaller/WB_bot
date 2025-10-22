import logging
import asyncio
import random
import time

logger = logging.getLogger(__name__)

def _get_token_key_from_headers(headers: dict) -> str:
    try:
        return headers.get('Authorization') or ''
    except Exception:
        return ''

WB_RATE_LIMIT_STORE: dict = {}

async def _respect_wb_rate_limit(context, token_key: str):
    """WB лимиты: 3 запроса в минуту на аккаунт, интервал 20 сек, всплеск 3.
    Реализуем token bucket: capacity=3, refill=1 на 20 сек."""
    if not token_key:
        return
    # Пытаемся хранить счётчики в bot_data, если он доступен; иначе используем модульное хранилище
    try:
        store = context.bot_data.setdefault('wb_rate_limit', {})
    except Exception:
        store = WB_RATE_LIMIT_STORE
    bucket = store.get(token_key)
    now = time.monotonic()
    capacity = 3
    interval_seconds = 20.0
    if not bucket:
        bucket = {
            'tokens': capacity,
            'last_refill': now
        }
        store[token_key] = bucket
    # Refill tokens
    elapsed = now - bucket['last_refill']
    if elapsed > 0:
        tokens_to_add = int(elapsed // interval_seconds)
        if tokens_to_add > 0:
            bucket['tokens'] = min(capacity, bucket['tokens'] + tokens_to_add)
            bucket['last_refill'] += tokens_to_add * interval_seconds
    # If no tokens, wait until next token is available
    if bucket['tokens'] <= 0:
        wait_seconds = bucket['last_refill'] + interval_seconds - now
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
            # After sleep, add exactly one token
            bucket['tokens'] = min(capacity, bucket['tokens'] + 1)
            bucket['last_refill'] = time.monotonic()
    # Consume one token
    bucket['tokens'] -= 1

async def make_api_request(session, url, headers, context, chat_id, method='GET', json_data=None, max_retries=3, timeout=30):
    token_key = _get_token_key_from_headers(headers or {})
    for attempt in range(max_retries):
        try:
            # Соблюдаем лимиты WB для данного токена
            await _respect_wb_rate_limit(context, token_key)
            if method == 'POST':
                async with session.post(url, headers=headers, json=json_data, timeout=timeout) as response:
                    if 200 <= response.status < 300:
                        return await response.json()
                    # Для 429/5xx пробуем ретраить
                    if response.status == 429 or 500 <= response.status < 600:
                        if attempt < max_retries - 1:
                            try:
                                error_body = await response.text()
                            except Exception:
                                error_body = ''
                            # Экспоненциальный бэкофф с джиттером и верхним пределом
                            backoff_seconds = min(30, 2 * (2 ** attempt)) + random.uniform(0, 0.5)
                            logger.warning(
                                f"HTTP {response.status} при попытке {attempt + 1}/{max_retries} для {url}. "
                                f"Повтор через {backoff_seconds:.1f} c. Тело: {error_body[:500]}"
                            )
                            await asyncio.sleep(backoff_seconds)
                            continue
                    error_msg = f"Ошибка запроса: {response.status}"
                    try:
                        error_body = await response.text()
                    except Exception:
                        error_body = ''
                    logger.critical(f"CRITICAL: {error_msg} для URL: {url}. Тело: {error_body[:1000]}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ {error_msg}"
                    )
                    return None
            else:
                async with session.get(url, headers=headers, timeout=timeout) as response:
                    if 200 <= response.status < 300:
                        return await response.json()
                    if response.status == 429 or 500 <= response.status < 600:
                        if attempt < max_retries - 1:
                            try:
                                error_body = await response.text()
                            except Exception:
                                error_body = ''
                            backoff_seconds = min(30, 2 * (2 ** attempt)) + random.uniform(0, 0.5)
                            logger.warning(
                                f"HTTP {response.status} при попытке {attempt + 1}/{max_retries} для {url}. "
                                f"Повтор через {backoff_seconds:.1f} c. Тело: {error_body[:500]}"
                            )
                            await asyncio.sleep(backoff_seconds)
                            continue
                    error_msg = f"Ошибка запроса: {response.status}"
                    try:
                        error_body = await response.text()
                    except Exception:
                        error_body = ''
                    logger.critical(f"CRITICAL: {error_msg} для URL: {url}. Тело: {error_body[:1000]}")
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ {error_msg}"
                    )
                    return None
        except asyncio.TimeoutError:
            if attempt < max_retries - 1:
                backoff_seconds = min(30, 2 * (2 ** attempt)) + random.uniform(0, 0.5)
                logger.warning(f"Таймаут при попытке {attempt + 1}/{max_retries}, повтор через {backoff_seconds:.1f} c...")
                await asyncio.sleep(backoff_seconds)
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