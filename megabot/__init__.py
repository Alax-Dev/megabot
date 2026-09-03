import asyncio
import types

# Python 3.12 compatibility shim:
# asyncio.coroutine was removed in Python 3.11+, but legacy libraries
# (like tenacity < 6 used by mega.py) still reference it.
if not hasattr(asyncio, 'coroutine'):
    asyncio.coroutine = types.coroutine
