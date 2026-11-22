"""Guard the adapter methods used by invoke, stream and tool-bound chat models."""
import asyncio
from contextlib import aclosing
from functools import partial

from anyio.from_thread import start_blocking_portal

from .provider_queue import guarded_stream


def _sync_iterator(make_stream):
    # Use the native synchronous SDK client in its own worker. Its connection
    # pool never crosses asyncio loops. Keep the lease until a pending read exits.
    async def source():
        iterator = make_stream()
        end = object()
        try:
            while True:
                read = asyncio.create_task(asyncio.to_thread(next, iterator, end))
                try:
                    item = await asyncio.shield(read)
                except asyncio.CancelledError:
                    await read
                    raise
                if item is end:
                    return
                yield item
        finally:
            iterator.close()
    return source


def _blocking(stream):
    with start_blocking_portal() as portal:
        try:
            while True:
                try:
                    yield portal.call(anext, stream)
                except StopAsyncIteration:
                    return
        finally:
            portal.call(stream.aclose)


def install_queue(model, queue, name, *, retry_after_cooldown):
    guard = partial(guarded_stream, queue, name, retry_after_cooldown=retry_after_cooldown)
    stream_async = model._astream
    generate_async = model._agenerate
    stream_sync = model._stream
    generate_sync = model._generate

    def astream(*args, **kwargs):
        return guard(partial(stream_async, *args, **kwargs))

    async def agenerate(*args, **kwargs):
        async def result():
            yield await generate_async(*args, **kwargs)
        async with aclosing(guard(result)) as stream:
            return [item async for item in stream][0]

    def stream(*args, **kwargs):
        source = _sync_iterator(partial(stream_sync, *args, **kwargs))
        yield from _blocking(guard(source))

    def generate(*args, **kwargs):
        def result():
            yield generate_sync(*args, **kwargs)
        return list(_blocking(guard(_sync_iterator(result))))[0]

    for method, guarded in (("_astream", astream), ("_agenerate", agenerate),
                            ("_stream", stream), ("_generate", generate)):
        object.__setattr__(model, method, guarded)
    object.__setattr__(model, "provider_queue", queue)
