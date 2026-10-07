from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Optional
from abc import ABC, abstractmethod


class ApiTypesI(ABC):
    """
    Abstract contract for a concrete external LLM API type.

    The contract splits in two parts:

    * **endpoint descriptors** – ``chat_ep`` / ``completions_ep`` /
      ``responses_ep`` / ``embeddings_ep`` return the canonical paths of the
      backend API;
    * **request adapter hooks** – ``request_path`` / ``request_headers`` /
      ``request_body`` / ``owns_message_normalization`` / ``ping_path`` tell
      the router how to build the actual HTTP call for a given *provider*.
      The default implementations reproduce the historical OpenAI‑style
      behaviour (relative path + ``Bearer <api_token>`` + ``model`` /
      system‑message injection); provider families with a different wire
      protocol (e.g. Google Vertex AI) override the hooks they need.
    """

    @staticmethod
    def tags(models_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert the provided config dict with keys like "google_models",
        "openai_models", etc. into standardized lists per api_type.

        Input schema example:
        {
            "google_models": [
                {
                    "api_host": "...",
                    "api_token": "",
                    "api_type": "vllm",
                    "input_size": 4096,
                    "model_path": "",
                    "name": "google/gemma-3-12b-it"
                }, ...
            ],
            "openai_models": [
                {
                    "api_host": "...",
                    "api_token": "",
                    "api_type": "ollama",
                    "input_size": 256000,
                    "model_path": "",
                    "name": "gpt-oss:20b"
                }
            ]
        }

        Output:
        {
            "<api_type>": [
                {
                    "id": "<name>",
                    "object": "model",
                    "owned_by": "<api_type>",
                     "input_size": <int>,
                     "root": "<name>",
                     "host": "<api_host>",
                     "path": "<model_path>"
                },
                ...
            ]
        }
        """
        out: Dict[str, Any] = {}
        # Flatten all groups in the incoming dict and bucket by api_type
        for _, models_list in (models_config or {}).items():
            if not isinstance(models_list, list):
                continue
            for m in models_list:
                if not isinstance(m, dict):
                    continue
                api_type = str(m.get("api_type", "")).lower()
                if not api_type:
                    continue
                out.setdefault(api_type, []).append(ApiTypesI.get_models_list(m))

        return out

    @staticmethod
    def get_models_list(m: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert a raw model configuration dict into a normalized model descriptor.

        The OpenAI routing layer expects each model to be represented by a
        dictionary containing a fixed set of keys (``id``, ``name``, ``object``,
        ``owned_by`` …).  ``get_models_list`` extracts the relevant fields from
        the source configuration supplied by the user (or a configuration file)
        and populates missing entries with sensible defaults.

        Parameters
        ----------
        m : Dict
            A single model configuration entry.  Expected keys include
            ``name``, ``api_type``, ``input_size``, ``api_host``, and
            ``model_path``.  Any missing keys are replaced with empty strings or
            zero values.

        Returns
        -------
        Dict
            A normalized model description compatible with the internal API.
            Example output::

                {
                    "id": "gpt-oss:20b",
                    "name": "gpt-oss:20b",
                    "model": "gpt-oss:20b",
                    "object": "model",
                    "owned_by": "ollama",
                    "input_size": 256000,
                    "max_context_length": 256000,
                    "root": "gpt-oss:20b",
                    "host": "https://api.example.com",
                    "path": "",
                    "type": "ollama",
                    "publisher": None,
                    "state": None,
                    "arch": None,
                    "compatibility_type": None,
                    "quantization": None,
                }

        Notes
        -----
        * The function does **not** perform any validation beyond basic type
          coercion; callers should ensure the input dictionary follows the
          expected schema.
        * The returned mapping mirrors the structure used by the OpenAI API
          client libraries, facilitating seamless integration downstream.
        """

        _type = m.get("type") or m.get("api_type")
        return {
            "id": str(m.get("name", "")),
            "name": str(m.get("name", "")),
            "model": str(m.get("name", "")),
            "object": "model",
            "owned_by": str(m.get("api_type", "") or ""),
            "input_size": int(m.get("input_size") or 0),
            "max_context_length": int(m.get("input_size") or 0),
            "root": str(m.get("name", "")),
            "host": str(m.get("api_host", "")),
            "path": str(m.get("model_path", "")),
            # Provider-specific metadata: sourced from the real per-provider
            # configuration (e.g. vLLM ``/api/tags``, Ollama ``/api/tags``,
            # OpenAI ``/models``) whenever the operator supplied it; ``None``
            # otherwise — never fabricated constants.
            "type": _type,
            "publisher": m.get("publisher"),
            "state": m.get("state"),
            "arch": m.get("arch"),
            "compatibility_type": m.get("compatibility_type"),
            "quantization": m.get("quantization"),
            "is_embedding": bool(m.get("is_embedding", False)),
        }

    # ------------------------------------------------------------------
    # Provider access helper – the provider descriptor is either an
    # ``ApiModel`` instance (request path) or a plain configuration
    # mapping (monitor / keep‑alive work with raw dicts).
    # ------------------------------------------------------------------
    @staticmethod
    def _provider_field(provider: Any, field_name: str, default: Any = "") -> Any:
        """
        Read ``field_name`` from a provider descriptor of either shape.
        """
        if provider is None:
            return default
        if isinstance(provider, Mapping):
            value = provider.get(field_name)
            return default if value is None else value
        return getattr(provider, field_name, default)

    # ------------------------------------------------------------------
    # Request adapter hooks (provider → router seam)
    # ------------------------------------------------------------------
    def request_path(
        self,
        endpoint_url: str,
        provider: Any = None,
        stream: bool = False,
    ) -> str:
        """
        Resolve a router endpoint fragment to the backend request path.

        The default implementation inspects ``endpoint_url`` (after
        stripping leading/trailing ``/``) for known keywords and forwards
        to the matching endpoint descriptor: ``"completions"`` →
        :meth:`completions_ep`, ``"responses"`` → :meth:`responses_ep`,
        ``"embed"`` → :meth:`embeddings_ep`, ``"messages"`` →
        :meth:`messages_ep`, anything else → :meth:`chat_ep`.

        Parameters
        ----------
        endpoint_url : str
            The router endpoint name (e.g. ``"v1/chat/completions"``).
        provider : Any
            The provider descriptor; unused by the default implementation.
        stream : bool
            Whether the request is a streaming one; unused by the default
            implementation (streaming backends share the chat path).

        Returns
        -------
        str
            The backend path appended to the provider's base URL.
        """
        fragment = (endpoint_url or "").strip("/")
        if "completions" in fragment:
            return self.completions_ep()
        if "responses" in fragment:
            return self.responses_ep()
        if "embed" in fragment:
            return self.embeddings_ep()
        if "messages" in fragment:
            return self.messages_ep()
        return self.chat_ep()

    def request_headers(self, provider: Any) -> Dict[str, str]:
        """
        Build the HTTP headers for a call to ``provider``.

        The default implementation sends a JSON body and, when the
        provider carries an ``api_token``, a ``Bearer`` authorization
        header – the historical behaviour of the router's outbound calls.
        """
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        token = self._provider_field(provider, "api_token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def request_body(
        self,
        payload: Any,
        provider: Any,
        system_message: Optional[Dict[str, str]] = None,
    ) -> Any:
        """
        Finalise the request body right before it is sent to ``provider``.

        The default implementation mirrors the historical executor
        behaviour: it injects the provider's model name (``model_path``
        when set, otherwise the logical model ``name``) and, when a
        resolved system prompt is available, prepends it to ``messages``.

        Parameters
        ----------
        payload : Any
            The payload produced by the endpoint layer.
        provider : Any
            The provider descriptor.
        system_message : Optional[Dict[str, str]]
            A ``{"role": "system", "content": ...}`` message to prepend,
            or ``None``.
        """
        if not isinstance(payload, dict):
            return payload
        model = self._provider_field(
            provider, "model_path", ""
        ) or self._provider_field(provider, "name", "")
        payload["model"] = model
        if system_message:
            payload["messages"] = [system_message] + payload.get("messages", [])
        return payload

    def owns_message_normalization(self) -> bool:
        """
        Whether the provider type normalises ``messages`` by itself.

        When ``True`` the router skips its own role normalisation
        (consecutive same‑role merging / user‑turn guarantees) because the
        type's request‑body hook performs an equivalent, protocol‑aware
        transformation.
        """
        return False

    def ping_path(self, provider: Any) -> Optional[str]:
        """
        Return a provider‑specific health‑check path, or ``None`` to fall
        back to the monitor's generic probe list.

        The returned value is a path appended to the provider's
        ``api_host`` (leading ``/`` included).
        """
        return None

    def on_response_status(self, provider: Any, status_code: int) -> None:
        """
        React to the HTTP status of a completed call to ``provider``.

        Called for **every** outbound non‑streaming response (success and
        failure alike), right after the transport returned and before the
        router decides on a failover.  The default does nothing; types with
        credentials that a upstream can reject use it to drop the rejected
        material — Vertex AI evicts a cached Google access token on
        ``401``/``403`` so the next request mints a fresh one.

        Parameters
        ----------
        provider : Any
            The provider descriptor the call was made to.
        status_code : int
            HTTP status code returned by the provider.
        """
        return None

    # ------------------------------------------------------------------
    # Request signing hooks
    # ------------------------------------------------------------------
    def signs_payload(self) -> bool:
        """
        Whether the type authenticates by signing the request body.

        The default ``False`` keeps every existing provider on the historical
        path (``requests.post(json=payload)``, headers built before the body is
        known).  Types whose signature covers the payload — AWS SigV4 for
        Bedrock — return ``True`` to get the two guarantees signing needs:
        the transport serialises the body **once** and passes those exact bytes
        to :meth:`sign_request`, then transmits them verbatim.  Signing over a
        hash of one serialisation while sending another (what ``requests`` does
        when it re‑serialises a ``json=`` dict) is rejected by the service as a
        signature mismatch.
        """
        return False

    def sign_request(
        self,
        provider: Any,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[bytes] = None,
    ) -> Dict[str, str]:
        """
        Return ``headers`` completed with the authentication of a signed body.

        Called by the transport immediately before the request leaves, with the
        final URL and the exact bytes about to be sent — the only point at
        which a payload signature can be computed correctly.  The default is a
        pass‑through, since header‑only authentication (bearer tokens) is fully
        resolved by :meth:`request_headers`.

        Parameters
        ----------
        provider : Any
            The provider descriptor.
        method : str
            HTTP verb, as it will be sent.
        url : str
            Absolute request URL.
        headers : Dict[str, str]
            Headers produced by :meth:`request_headers`; not mutated.
        body : Optional[bytes]
            The transmitted body, or ``None`` for a bodyless request.
        """
        return headers

    @abstractmethod
    def chat_ep(self) -> str:
        """
        Return the relative URL path for the chat endpoint.

        Returns
        -------
        str
            Endpoint path (e.g., "/v1/chat/completions").
        """
        raise NotImplementedError

    @abstractmethod
    def completions_ep(self) -> str:
        """
        Return the relative URL path for the completion endpoint.

        Returns
        -------
        str
            Endpoint path (e.g., "/v1/completions").
        """
        raise NotImplementedError

    @abstractmethod
    def responses_ep(self) -> str:
        """
        Return the URL path for the responses' endpoint.

        Returns
        -------
        str
            Endpoint path (e.g., "/v1/responses").
        """
        raise NotImplementedError

    @abstractmethod
    def embeddings_ep(self) -> str:
        """
        Return the URL path for the embeddings' endpoint.

        Returns
        -------
        str
            Endpoint path (e.g., "/v1/embeddings").
        """
        raise NotImplementedError

    @staticmethod
    def messages_ep() -> str:
        """
        Return the URL path for the messages's endpoint.

        Returns
        -------
        str:
            Endoint path (e.g. "/v1/messages?").
        """
        return "/v1/messages"
