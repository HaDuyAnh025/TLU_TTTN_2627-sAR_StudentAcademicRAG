"""Cache Redis đơn giản cho kết quả tìm kiếm. Redis lỗi/không cấu hình thì bỏ qua cache,
API vẫn chạy bình thường."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class Cache:
    def __init__(self, redis_url: str | None):
        self._client = None
        if redis_url:
            import redis

            self._client = redis.Redis.from_url(
                redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def get_json(self, key: str) -> Any | None:
        if not self._client:
            return None
        try:
            raw = self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:  # noqa: BLE001 - cache không được làm hỏng request
            logger.warning("Redis get lỗi: %s", e)
            return None

    def set_json(self, key: str, value: Any, ttl: int) -> None:
        if not self._client:
            return
        try:
            self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except Exception as e:  # noqa: BLE001
            logger.warning("Redis set lỗi: %s", e)

    def ping(self) -> str:
        if not self._client:
            return "disabled"
        try:
            self._client.ping()
            return "ok"
        except Exception as e:  # noqa: BLE001
            return f"error: {e}"
