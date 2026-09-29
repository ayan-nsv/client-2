from dotenv import load_dotenv
import os
import json
from datetime import datetime
import asyncio
from typing import Optional, Any, List

from shared.logger.log import setup_logger

load_dotenv()
logger = setup_logger("marketing-app")

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.error("❌ Critical Error: 'redis' library not installed. Pip install redis.")

# --- Configuration ---
# Defaults to localhost for the Cloud Run / Docker Compose sidecar
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_TTL = 172800  # 2 days

_redis_client: Optional[redis.Redis] = None
# Async Redis connections are tied to the event loop that created them. Celery uses
# asyncio.run() per task (a new loop each time); reusing the old client breaks deletes/gets.
_redis_client_loop: Optional[asyncio.AbstractEventLoop] = None

class FirestoreJSONEncoder(json.JSONEncoder):
    """Encodes datetimes and Firestore types for Redis storage"""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if hasattr(obj, 'isoformat') and callable(getattr(obj, 'isoformat')):
            return obj.isoformat()
        return str(obj)

def json_dumps_firestore(obj: Any) -> str:
    return json.dumps(obj, cls=FirestoreJSONEncoder)

async def get_redis_client() -> Optional[redis.Redis]:
    """Singleton: Returns the active Redis connection for the *current* event loop."""
    global _redis_client, _redis_client_loop
    if not REDIS_AVAILABLE:
        return None
    current_loop = asyncio.get_running_loop()
    if _redis_client is not None and _redis_client_loop is not current_loop:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None
        _redis_client_loop = None
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=2,
                retry_on_timeout=True,
                health_check_interval=30
            )
            await _redis_client.ping()
            _redis_client_loop = current_loop
            logger.info(f"✅ Sidecar Redis Connected: {REDIS_URL}")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Redis Sidecar: {str(e)}")
            _redis_client = None
            _redis_client_loop = None
    return _redis_client

async def close_redis_client():
    """Call on FastAPI shutdown"""
    global _redis_client, _redis_client_loop
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        _redis_client_loop = None
        logger.info("Redis connection closed.")

# --- Standard Operations ---

async def redis_set(key: str, value: Any, ttl: int = DEFAULT_TTL) -> bool:
    client = await get_redis_client()
    if not client: return False
    try:
        val_str = json_dumps_firestore(value) if isinstance(value, (dict, list)) else str(value)
        await client.set(key, val_str, ex=ttl if ttl > 0 else None)
        return True
    except Exception as e:
        logger.error(f"Redis SET Error [{key}]: {e}")
        return False

async def redis_get(key: str) -> Any:
    client = await get_redis_client()
    if not client: return None
    try:
        data = await client.get(key)
        if data is None: return None
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data
    except Exception as e:
        logger.error(f"Redis GET Error [{key}]: {e}")
        return None

async def redis_delete(key: str) -> bool:
    client = await get_redis_client()
    if not client: return False
    try:
        return await client.delete(key) > 0
    except Exception as e:
        logger.error(f"Redis DELETE Error [{key}]: {e}")
        return False

# --- List Operations (For Celery/Queues) ---

async def redis_list_push(key: str, value: Any) -> bool:
    """RPUSH value to list"""
    client = await get_redis_client()
    if not client: return False
    try:
        await client.rpush(key, json_dumps_firestore(value))
        return True
    except Exception as e:
        logger.error(f"Redis LPUSH Error [{key}]: {e}")
        return False

async def redis_list_get_all(key: str) -> List[Any]:
    """LRANGE 0 -1"""
    client = await get_redis_client()
    if not client: return []
    try:
        items = await client.lrange(key, 0, -1)
        decoded = []
        for i in items:
            try:
                decoded.append(json.loads(i))
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to decode list item from key '{key}'")
        return decoded
    except Exception as e:
        logger.error(f"Redis LRANGE Error [{key}]: {e}")
        return []

async def redis_list_set_all(key: str, items: List[Any], ttl: int = DEFAULT_TTL) -> bool:
    """Replace entire list with new items. Deletes old list and creates new one atomically."""
    client = await get_redis_client()
    if not client: return False
    try:
        pipe = client.pipeline()
        pipe.delete(key)
        if items:
            for item in items:
                pipe.rpush(key, json_dumps_firestore(item))
            if ttl > 0:
                pipe.expire(key, ttl)
        await pipe.execute()
        return True
    except Exception as e:
        logger.error(f"Redis LIST SET ALL Error [{key}]: {e}")
        return False

async def redis_list_remove_by_value(key: str, value: Any) -> int:
    """Remove all occurrences of a value from a Redis list (LREM). Returns count removed."""
    client = await get_redis_client()
    if not client: return 0
    try:
        json_value = json_dumps_firestore(value)
        count = await client.lrem(key, 0, json_value)
        return count
    except Exception as e:
        logger.error(f"Redis LIST REMOVE Error [{key}]: {e}")
        return 0