import asyncio
from functools import wraps

def run_sync(fn):
    """
    Decorator: run a (possibly) blocking func in default executor
    so we can 'await' disk writes without blocking the loop.
    """
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn, *args, **kwargs)
    return wrapper
