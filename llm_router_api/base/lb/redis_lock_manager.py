try:
    import redis

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Helper class – low‑level Redis lock handling
# --------------------------------------------------------------------------- #
class RedisLockManager:
    """
    Encapsulates all Redis‑based locking primitives used by the strategy.

    The manager registers four Lua scripts:

    * ``_acquire_script`` – atomically acquire a provider lock.
    * ``_release_script`` – release a provider lock.
    * ``_acquire_host_script`` – acquire a host‑wide lock (only one provider per
      host may be active at a time).
    * ``_release_host_script`` – release a host lock.

    All scripts work on simple string values (``'true'`` = locked,
    ``'false'`` = free).  Missing fields are treated as free.
    """

    def __init__(self, client: redis.Redis) -> None:
        """
        Parameters
        ----------
        client:
            An instantiated :class:`redis.Redis` connection with
            ``decode_responses=True``.
        """
        self.acquire_script = None
        self.release_script = None
        self.acquire_host_script = None
        self.release_host_script = None

        self.client = client
        self._register_scripts()

    # ------------------------------------------------------------------- #
    # Lua script registration
    # ------------------------------------------------------------------- #
    def _register_scripts(self) -> None:
        """Register the four Lua scripts used for locking."""
        # Provider acquire – treat missing or "false" as free
        self.acquire_script = self.client.register_script(
            """
            local redis_key = KEYS[1]
            local field = ARGV[1]
            local v = redis.call('HGET', redis_key, field)
            if v == false or v == 'false' then
                redis.call('HSET', redis_key, field, 'true')
                return 1
            end
            return 0
            """
        )
        # Provider release – delete the field
        self.release_script = self.client.register_script(
            """
            local redis_key = KEYS[1]
            local field = ARGV[1]
            redis.call('HDEL', redis_key, field)
            return 1
            """
        )
        # Host acquire – a simple key, not a hash
        self.acquire_host_script = self.client.register_script(
            """
            local host_key = KEYS[1]
            local v = redis.call('GET', host_key)
            if v == false or v == 'false' then
                redis.call('SET', host_key, 'true')
                return 1
            end
            return 0
            """
        )
        # Host release – delete the key
        self.release_host_script = self.client.register_script(
            """
            local host_key = KEYS[1]
            redis.call('DEL', host_key)
            return 1
            """
        )

    # ------------------------------------------------------------------- #
    # Public locking helpers
    # ------------------------------------------------------------------- #
    def acquire_provider(self, redis_key: str, field: str) -> bool:
        """
        Try to lock a provider.

        Returns ``True`` if the lock was obtained, ``False`` otherwise.
        """
        result = int(self.acquire_script(keys=[redis_key], args=[field]))
        return result == 1

    def release_provider(self, redis_key: str, field: str) -> None:
        """Release a previously acquired provider lock."""
        self.release_script(keys=[redis_key], args=[field])

    def acquire_host(self, host_key: str) -> bool:
        """
        Acquire a lock that guarantees only one provider on the given host
        is active at a time.
        """
        result = int(self.acquire_host_script(keys=[host_key], args=[]))
        return result == 1

    def release_host(self, host_key: str) -> None:
        """Release a host‑wide lock."""
        self.release_host_script(keys=[host_key], args=[])
