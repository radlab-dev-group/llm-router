from typing import List, Dict, Optional, Any

from llm_router_api.core.lb.strategies.first_available import FirstAvailableStrategy


class FirstAvailableOptimStrategy(FirstAvailableStrategy):
    """
    Optimized version of :class:`FirstAvailableStrategy` that tries to reuse
    the previously used host for a model before falling back to the generic
    first‑available logic.

    The algorithm consists of the following steps:

    1. **Last host reuse** – if the model was previously run on a host that is
       currently free (no other model occupies it) and the provider on that host
       is not locked, select it.
    2. **Existing host reuse** – look for other hosts that already have the same
       model loaded (tracked in a Redis set). Choose a free provider on one of
       those hosts.
    3. **Unused host** – pick a host that has never been used for any model.
    4. **Fallback** – if none of the above succeed, delegate to the original
       :class:`FirstAvailableStrategy`.
    5. **Record** – after a provider is selected, store the host as the last
       used host for the model and update the bookkeeping structures.
    """

    # -------------------------------------------------------------------------
    # Helper utilities
    # -------------------------------------------------------------------------

    def _host_from_provider(self, provider: Dict) -> Optional[str]:
        """Extract the host identifier from a provider configuration."""
        # Most providers expose the host under ``api_host`` or ``host``.
        return provider.get("api_host") or provider.get("host")

    def _last_host_key(self, model_name: str) -> str:
        """Redis key that stores the last host used for a given model."""
        return f"{self._get_redis_key(model_name)}:last_host"

    def _model_hosts_set_key(self, model_name: str) -> str:
        """Redis set key that holds all hosts where *model_name* is loaded."""
        return f"{self._get_redis_key(model_name)}:hosts"

    def _host_occupancy_key(self, host_name: str) -> str:
        """
        Redis hash key that stores the model currently occupying *host_name*.
        The hash field used is ``model``.
        """
        return self._host_key(host_name)

    # -------------------------------------------------------------------------
    # Step 1 – reuse last host
    # -------------------------------------------------------------------------

    def _step1_last_host(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Try to acquire a provider on the host that was used the last time this
        model was selected.

        Returns the provider if successful, otherwise ``None``.
        """
        last_host = self.redis_client.get(self._last_host_key(model_name))
        if not last_host:
            return None

        # Verify host is not occupied by a different model.
        occupancy_hash = self._host_occupancy_key(last_host)
        current_model = self.redis_client.hget(occupancy_hash, "model")
        if current_model and current_model != model_name:
            return None  # host busy with another model

        # Find a provider that belongs to this host.
        for provider in providers:
            if self._host_from_provider(provider) != last_host:
                continue
            # Attempt atomic acquisition using the same Lua script as the base class.
            field = self._provider_field(provider)
            try:
                ok = int(
                    self._acquire_script(
                        keys=[self._get_redis_key(model_name)], args=[field]
                    )
                )
                if ok == 1:
                    provider["__chosen_field"] = field
                    return provider
            except Exception:
                # If the script fails we simply treat this provider as unavailable.
                continue
        return None

    # -------------------------------------------------------------------------
    # Step 2 – reuse any host that already runs this model
    # -------------------------------------------------------------------------

    def _step2_existing_hosts(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Look for hosts that already have *model_name* loaded (tracked in a Redis
        set) and try to acquire a free provider on one of those hosts.
        """
        hosts_key = self._model_hosts_set_key(model_name)
        host_bytes = self.redis_client.smembers(hosts_key)
        if not host_bytes:
            return None
        known_hosts = {b.decode() for b in host_bytes}

        for provider in providers:
            host = self._host_from_provider(provider)
            if host not in known_hosts:
                continue
            # Ensure the host is not occupied by a different model.
            occ_key = self._host_occupancy_key(host)
            cur = self.redis_client.hget(occ_key, "model")
            if cur and cur.decode() != model_name:
                continue

            field = self._provider_field(provider)
            try:
                ok = int(
                    self._acquire_script(
                        keys=[self._get_redis_key(model_name)], args=[field]
                    )
                )
                if ok == 1:
                    provider["__chosen_field"] = field
                    return provider
            except Exception:
                continue
        return None

    # -------------------------------------------------------------------------
    # Step 3 – pick an entirely unused host
    # -------------------------------------------------------------------------

    def _step3_unused_host(
        self, model_name: str, providers: List[Dict]
    ) -> Optional[Dict]:
        """
        Find a host that has never been used for any model (no occupancy entry)
        and acquire a provider on it.
        """
        for provider in providers:
            host = self._host_from_provider(provider)
            if not host:
                continue
            occ_key = self._host_occupancy_key(host)
            if self.redis_client.hexists(occ_key, "model"):
                # Host already assigned to some model.
                continue

            field = self._provider_field(provider)
            try:
                ok = int(
                    self._acquire_script(
                        keys=[self._get_redis_key(model_name)], args=[field]
                    )
                )
                if ok == 1:
                    provider["__chosen_field"] = field
                    return provider
            except Exception:
                continue
        return None

    # -------------------------------------------------------------------------
    # Step 5 – bookkeeping after a successful acquisition
    # -------------------------------------------------------------------------

    def _record_selection(self, model_name: str, provider: Dict) -> None:
        """
        Store the chosen host as the *last host* for the model and update the
        host‑occupancy hash as well as the set of hosts known to run the model.
        """
        host = self._host_from_provider(provider)
        if not host:
            return

        # 1. Remember the last host.
        self.redis_client.set(self._last_host_key(model_name), host)

        # 2. Add host to the model‑specific set.
        self.redis_client.sadd(self._model_hosts_set_key(model_name), host)

        # 3. Mark the host as occupied by this model.
        occ_key = self._host_occupancy_key(host)
        self.redis_client.hset(occ_key, "model", model_name)

    # -------------------------------------------------------------------------
    # Overridden public API
    # -------------------------------------------------------------------------

    def get_provider(
        self,
        model_name: str,
        providers: List[Dict],
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict | None:
        """
        Execute the optimisation steps before falling back to the base
        implementation.
        """
        if not providers:
            return None

        # Initialise Redis structures (same as parent).
        redis_key, _ = self.init_provider(
            model_name=model_name, providers=providers, options=options
        )
        if not redis_key:
            return None

        # ---- Step 1 ---------------------------------------------------------
        provider = self._step1_last_host(model_name, providers)
        print("last_host_provider", provider)
        print("last_host_provider", provider)
        print("last_host_provider", provider)
        print("last_host_provider", provider)
        if provider:
            self._record_selection(model_name, provider)
            return provider

        # ---- Step 2 ---------------------------------------------------------
        provider = self._step2_existing_hosts(model_name, providers)
        print("existing_host_provider", provider)
        print("existing_host_provider", provider)
        print("existing_host_provider", provider)
        print("existing_host_provider", provider)
        if provider:
            self._record_selection(model_name, provider)
            return provider

        # ---- Step 3 ---------------------------------------------------------
        provider = self._step3_unused_host(model_name, providers)
        print("unused_host_provider", provider)
        print("unused_host_provider", provider)
        print("unused_host_provider", provider)
        print("unused_host_provider", provider)
        if provider:
            self._record_selection(model_name, provider)
            return provider

        # ---- Step 4 – fallback ---------------------------------------------
        provider = super().get_provider(
            model_name=model_name, providers=providers, options=options
        )
        print("first_available_host_provider", provider)
        print("first_available_host_provider", provider)
        print("first_available_host_provider", provider)
        print("first_available_host_provider", provider)
        if provider:
            self._record_selection(model_name, provider)
        return provider

    # -------------------------------------------------------------------------
    # Ensure buffers are cleared on construction (delegated to parent)
    # -------------------------------------------------------------------------

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Parent already calls ``_clear_buffers`` when ``clear_buffers=True``.
        # No additional initialisation required here.
