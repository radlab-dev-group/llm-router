import threading
from flask import current_app

from llm_router_api.base.constants import USE_PROMETHEUS

# ... existing imports and code ...

class MetricsHandler:
    # ----------------------------------------------------------------------
    # Singleton machinery (process‑wide, thread‑safe)
    # ----------------------------------------------------------------------
    _instance = None                # the one shared object
    _instance_lock = threading.Lock()   # protects creation of the object

    def __new__(cls, *args, **kwargs):
        """
        Return the existing instance if it already exists; otherwise create
        it under the protection of ``_instance_lock``.  This is the classic
        double‑checked locking pattern and works safely with CPython's GIL.
        """
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:          # second check
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """
        Initialise the handler only once.  Subsequent ``MetricsHandler()``
        calls (triggered by endpoint constructors) become no‑ops.
        """
        # ``hasattr`` prevents re‑initialisation when the singleton is
        # returned on later calls.
        if getattr(self, "_initialized", False):
            return

        self._lock = threading.Lock()   # protects metric updates
        self._metrics = None            # will be fetched lazily from Flask
        self._initialized = True        # flag that we have finished init

    # ----------------------------------------------------------------------
    # Public helpers – unchanged semantics, now thread‑safe
    # ----------------------------------------------------------------------
    def inc_guardrail_incident(self):
        """
        Increment the ``guardrail_incidents_total`` counter.
        """
        if not USE_PROMETHEUS:
            return

        with self._lock:
            if not self._metrics:
                # ``current_app`` is only valid inside an active Flask request
                self._metrics = current_app.extensions["prometheus_metrics"]
            self._metrics.GUARDRAIL_INCIDENTS.inc()

    def inc_masker_incident(self):
        """
        Increment the ``masker_incidents_total`` counter.
        """
        if not USE_PROMETHEUS:
            return

        with self._lock:
            if not self._metrics:
                self._metrics = current_app.extensions["prometheus_metrics"]
            self._metrics.MASKER_INCIDENTS.inc()