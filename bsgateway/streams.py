"""Redis Streams + pub/sub abstraction.

Streams (XADD/XREADGROUP/XACK) carry durable per-worker task queues.
Pub/sub channels carry ephemeral high-frequency signals — streamed
output chunks (``task:{id}:stream``) and terminal completion
(``task:{id}:done``). Pub/sub is fire-and-forget by design; the
gateway always subscribes before dispatching the task so chunks aren't
missed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis


class RedisStreamManager:
    """Thin wrapper around Redis Streams for publish/consume/acknowledge."""

    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def publish(self, stream: str, data: dict) -> str:
        """Publish a message to a stream. Returns the message ID."""
        flat: dict[str, str] = {
            str(k): json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in data.items()
        }
        msg_id: bytes = await self.redis.xadd(stream, flat)  # type: ignore[arg-type]
        return msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 1,
        block: int = 1000,
    ) -> list[dict]:
        """Consume messages from a consumer group."""
        # Ensure consumer group exists
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception:
            pass  # Group already exists

        messages = await self.redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block,
        )
        results: list[dict] = []
        if messages:
            for _stream_name, stream_messages in messages:
                for message_id, data in stream_messages:
                    parsed: dict = {}
                    for k, v in data.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        val = v.decode() if isinstance(v, bytes) else v
                        try:
                            parsed[key] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            parsed[key] = val
                    mid = message_id.decode() if isinstance(message_id, bytes) else message_id
                    parsed["_message_id"] = mid
                    results.append(parsed)
        return results

    async def acknowledge(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge message processing completion."""
        await self.redis.xack(stream, group, message_id)

    # ─── Pub/sub (chunk streaming + completion signal) ──────────────

    async def publish_pubsub(self, channel: str, data: dict[str, Any]) -> None:
        """PUBLISH a JSON-encoded message to a pub/sub channel."""
        await self.redis.publish(channel, json.dumps(data))

    async def subscribe_pubsub(
        self, channel: str, *, timeout: float
    ) -> AsyncIterator[dict[str, Any]]:
        """SUBSCRIBE to a channel, returning an iterator over decoded messages.

        Subscribe completes before this coroutine returns, so callers can
        safely dispatch the task that will publish on the channel without
        a race. Iteration stops when ``timeout`` elapses with no new
        message. Caller is responsible for draining or closing the
        returned iterator (`aclose()`) when done.
        """
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)
        return _iter_pubsub_messages(pubsub, channel, timeout)


async def _iter_pubsub_messages(
    pubsub: Any, channel: str, timeout: float
) -> AsyncIterator[dict[str, Any]]:
    try:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=min(remaining, 1.0)
            )
            if msg is None:
                continue
            payload = msg.get("data")
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8", errors="replace")
            if not payload:
                continue
            try:
                yield json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                yield {"raw": payload}
    finally:
        try:
            await pubsub.unsubscribe(channel)
            close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if close is not None:
                res = close()
                if hasattr(res, "__await__"):
                    await res
        except Exception:
            pass
