import os
from redis import Redis

redis_password = os.getenv("LLM_ROUTER_REDIS_PASSWORD")
redis_host = os.getenv("LLM_ROUTER_REDIS_HOST")
redis_protocol = int(os.getenv("LLM_ROUTER_REDIS_PROTOCOL", "3"))

r = Redis(
    host=redis_host,
    password=redis_password,
    socket_connect_timeout=1,
    decode_responses=True,
    protocol=redis_protocol,
)

r.ping()
print(f'Connected to Redis "{redis_host}" with password from env')
