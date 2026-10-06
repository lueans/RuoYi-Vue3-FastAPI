"""Shared, bounded SSE delivery; the database remains the replay authority."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

CHANNEL = 'mindmap:ai:event-wakeup'
RECONCILE_SECONDS = 5.0
MAX_BUFFER_BYTES = 2 * 1024 * 1024
MAX_WAKEUP_JOB_ID_LENGTH = 100


class _Feed:
    def __init__(self, reader: Any, cursor: int, authorize: Any = None) -> None:
        self.reader = reader
        self.authorize = authorize
        self.cursor = cursor
        self.floor = cursor
        self.chunks: deque[tuple[int, str]] = deque()
        self.bytes = 0
        self.terminal = False
        self.ready = False
        self.error: BaseException | None = None
        self.users = 0
        self.revision = 0
        self.changed = asyncio.Condition()
        self.wakeup = asyncio.Event()
        self.task = asyncio.create_task(self._run(), name='mindmap-ai-sse-feed')

    async def _run(self) -> None:
        try:
            while True:
                self.wakeup.clear()
                chunks, terminal = await self.reader(self.cursor)
                # A terminal job can still have additional persisted pages.
                # Only an empty read proves that the terminal cursor is drained.
                terminal = terminal and not chunks
                async with self.changed:
                    changed = bool(chunks) or not self.ready or terminal != self.terminal
                    self.ready = True
                    self.terminal = terminal
                    for sequence, chunk in chunks:
                        if sequence <= self.cursor:
                            continue
                        self.cursor = sequence
                        self.chunks.append((sequence, chunk))
                        self.bytes += len(chunk.encode('utf-8'))
                    while self.bytes > MAX_BUFFER_BYTES and len(self.chunks) > 1:
                        sequence, chunk = self.chunks.popleft()
                        self.floor = sequence
                        self.bytes -= len(chunk.encode('utf-8'))
                    if changed:
                        self.revision += 1
                        self.changed.notify_all()
                if terminal and not chunks:
                    return
                if chunks:
                    # Drain persisted pages without imposing notification delay.
                    await asyncio.sleep(0)
                    continue
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.wakeup.wait(), RECONCILE_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            async with self.changed:
                self.error = error
                self.revision += 1
                self.changed.notify_all()

    async def read(self, cursor: int) -> tuple[list[tuple[int, str]], bool, int]:
        chunks = None
        async with self.changed:
            await self.changed.wait_for(lambda: self.ready or self.error is not None)
            if self.error is not None:
                raise self.error
            revision = self.revision
            if cursor >= self.floor:
                chunks = [item for item in self.chunks if item[0] > cursor]
                terminal = self.terminal
        if chunks is not None:
            # A subscriber may have stalled while access was revoked. SQL
            # validation when filling the ring is not permission to deliver
            # that cached content later. Never hold the condition during I/O.
            if chunks and self.authorize is not None:
                await self.authorize()
            return chunks, terminal, revision
        # A slow/reconnecting reader may have fallen outside the bounded ring.
        # Read its own durable page; never drop events or force its cursor ahead.
        chunks, terminal = await self.reader(cursor)
        return chunks, terminal, revision

    async def wait(self, revision: int, timeout: float = 15.0) -> bool:
        async with self.changed:
            try:
                await asyncio.wait_for(self.changed.wait_for(
                    lambda: self.revision != revision or self.error is not None,
                ), timeout)
                return True
            except asyncio.TimeoutError:
                return False


class MindmapAiEventFeeds:
    def __init__(self) -> None:
        self.redis: Any = None
        self.feeds: dict[tuple[Any, str, int], _Feed] = {}
        self.listener: asyncio.Task[None] | None = None
        self.publish_retry_at = 0.0

    def configure(self, redis: Any) -> None:
        self.redis = redis

    def wake(self, job_id: str) -> None:
        for (_, target, _), feed in tuple(self.feeds.items()):
            if target == job_id:
                feed.wakeup.set()

    async def publish(self, job_id: str) -> None:
        """Call only after the SQL transaction commits; failures are harmless."""
        self.wake(job_id)
        loop = asyncio.get_running_loop()
        if not callable(getattr(self.redis, 'publish', None)) or loop.time() < self.publish_retry_at:
            return
        try:
            await asyncio.wait_for(self.redis.publish(CHANNEL, job_id), 0.25)
        except Exception:
            self.publish_retry_at = loop.time() + 15.0

    async def _listen(self) -> None:
        while self.feeds:
            pubsub = None
            try:
                pubsub = self.redis.pubsub()
                await pubsub.subscribe(CHANNEL)
                async for message in pubsub.listen():
                    if message.get('type') != 'message':
                        continue
                    job_id = message.get('data')
                    if isinstance(job_id, bytes):
                        job_id = job_id.decode('utf-8', errors='ignore')
                    if isinstance(job_id, str) and len(job_id) <= MAX_WAKEUP_JOB_ID_LENGTH:
                        self.wake(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(RECONCILE_SECONDS)
            finally:
                if pubsub is not None:
                    with suppress(Exception):
                        await asyncio.wait_for(pubsub.aclose(), 1.0)

    @asynccontextmanager
    async def subscribe(
        self, job_id: str, user_id: int, cursor: int, reader: Any, *, authorize: Any = None,
    ) -> AsyncIterator[_Feed]:
        key = (asyncio.get_running_loop(), job_id, user_id)
        feed = self.feeds.get(key)
        if feed is None or feed.task.done():
            # A terminal result can later be applied, undone, or saved. A new
            # subscription must check SQL again, even while an old slow client
            # is still draining the previous terminal feed.
            feed = _Feed(reader, cursor, authorize)
            self.feeds[key] = feed
        feed.users += 1
        if callable(getattr(self.redis, 'pubsub', None)) and (self.listener is None or self.listener.done()):
            self.listener = asyncio.create_task(self._listen(), name='mindmap-ai-sse-notifications')
        try:
            yield feed
        finally:
            feed.users -= 1
            if feed.users == 0:
                if self.feeds.get(key) is feed:
                    self.feeds.pop(key, None)
                feed.task.cancel()
                await asyncio.gather(feed.task, return_exceptions=True)
            if not self.feeds and self.listener is not None:
                listener, self.listener = self.listener, None
                listener.cancel()
                await asyncio.gather(listener, return_exceptions=True)

    async def close(self) -> None:
        for feed in self.feeds.values():
            async with feed.changed:
                feed.error = asyncio.CancelledError()
                feed.changed.notify_all()
        tasks = [feed.task for feed in self.feeds.values()]
        if self.listener is not None:
            tasks.append(self.listener)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.feeds.clear()
        self.listener = None
        self.redis = None


mindmap_ai_event_feeds = MindmapAiEventFeeds()
