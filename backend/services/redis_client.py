"""
Redis Client Dependency

Provides a dependency function to get an initialized redis client from app state.
"""

import redis.asyncio as redis
from fastapi import HTTPException, Request

async def get_redis_client(request: Request) -> redis.Redis:
    """
    Dependency function to get the Redis client stored in app state by server.py's lifespan.
    """
    redis_client = getattr(request.app.state, "redis", None)

    if redis_client is None:
        # This indicates an issue with server.py's lifespan setup or Redis initialization failure
        print("ERROR: Redis client not found in app state. Check server.py lifespan and Redis connection.")
        raise HTTPException(status_code=500, detail="Redis service not available.")

    return redis_client