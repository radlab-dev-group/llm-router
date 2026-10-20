"""
Unit tests for the Azure OpenAI API type.

Covers the request adapter (deployment paths, the mandatory ``api-version``
parameter, the two URL styles), the Azure authentication surface (API key in
the ``api-key`` header, Microsoft Entra ID bearer tokens, token caching and
eviction), and the registration of the type in the dispatcher and the
provider lists.

No Azure SDK and no network access is required: the Entra ID flows are
asserted against a mocked ``requests`` layer.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
from unittest import mock  # noqa: E402

from llm_router_api.base.constants_base import (  # noqa: E402
    ALL_PROVIDERS,
    AZURE_OPENAI_PROVIDER,
    OPENAI_COMPATIBLE_PROVIDERS,
)
from llm_router_api.core.api_types.auth import azure as azure_auth  # noqa: E402
from llm_router_api.core.api_types.auth.azure import (  # noqa: E402
    AzureAdTokenProvider,
    DEFAULT_SCOPE,
)
from llm_router_api.core.api_types.azure_openai import (  # noqa: E402
    DEFAULT_API_VERSION,
    AzureOpenAiType,
)
from llm_router_api.core.api_types.dispatcher import (  # noqa: E402
    API_TYPES,
    ApiTypesDispatcher,
)

DEPLOYMENT = "my-gpt4o-deployment"
API_HOST = "https://contoso.openai.azure.com"


def _provider(**overrides):
    """Build an Azure OpenAI provider descriptor."""
    fields = {
        "id": "aoai-1",
        "name": "azure/gpt-4o",
        "api_host": API_HOST,
        "api_type": "azure_openai",
        "api_token": "azure-api-key",
        "input_size": 128000,
        "model_path": DEPLOYMENT,
        "provider_options": {},
    }
    fields.update(overrides)
    return type("Provider", (), fields)()


@pytest.fixture(autouse=True)
def _clean_token_cache():
    """
    Keep the process-wide Entra token cache out of the tests, and keep the
    ambient environment (a developer's own AZURE_* variables) from selecting
    a credential source.
    """
    AzureAdTokenProvider.clear_cache()
    with mock.patch.dict(os.environ, {}, clear=True):
        yield
    AzureAdTokenProvider.clear_cache()


def _token_response(token="entra-token", expires_in=3600, status=200):
    """Fake ``requests`` response of the Entra ID token endpoint."""

    class _Resp:
        status_code = status
        content = b"{}"

        def __init__(self):
            self.content = json.dumps(
                {
                    "access_token": token,
                    "expires_in": expires_in,
                    "token_type": "Bearer",
                }
            ).encode()

        def json(self):
            return json.loads(self.content)

    return _Resp()


# ----------------------------------------------------------------------
# Endpoint paths
# ----------------------------------------------------------------------
class TestAzureEndpoints:
    def test_chat_path_carries_deployment_and_api_version(self):
        path = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai", "v1/chat/completions", provider=_provider()
        )
        assert path == (
            f"/openai/deployments/{DEPLOYMENT}/chat/completions"
            f"?api-version={DEFAULT_API_VERSION}"
        )

    def test_stream_shares_the_chat_path(self):
        # Azure streams the same operation as text/event-stream; the `stream`
        # body flag selects it, so no separate operation exists (unlike
        # Vertex or Bedrock).
        streamed = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai",
            "v1/chat/completions",
            provider=_provider(),
            stream=True,
        )
        plain = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai",
            "v1/chat/completions",
            provider=_provider(),
            stream=False,
        )
        assert streamed == plain

    def test_embeddings_path(self):
        path = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai", "v1/embeddings", provider=_provider()
        )
        assert path == (
            f"/openai/deployments/{DEPLOYMENT}/embeddings"
            f"?api-version={DEFAULT_API_VERSION}"
        )

    def test_responses_path_has_no_deployment_segment(self):
        # The Responses API addresses the model in the body, not in a
        # deployment path segment.
        path = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai", "v1/responses", provider=_provider()
        )
        assert path == f"/openai/v1/responses?api-version={DEFAULT_API_VERSION}"

    def test_api_version_option_pins_the_query(self):
        provider = _provider(provider_options={"api_version": "2025-04-01-preview"})
        path = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai", "v1/chat/completions", provider=provider
        )
        assert path.endswith("/chat/completions?api-version=2025-04-01-preview")

    def test_v1_style_moves_the_operation_to_openai_v1(self):
        provider = _provider(provider_options={"api_style": "v1"})
        path = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai", "v1/chat/completions", provider=provider
        )
        assert (
            path == f"/openai/v1/chat/completions?api-version={DEFAULT_API_VERSION}"
        )

    def test_unknown_api_style_falls_back_to_deployments(self):
        provider = _provider(provider_options={"api_style": "legacy‑unknown"})
        with mock.patch(
            "llm_router_api.core.api_types.azure_openai.logger"
        ) as fake_logger:
            path = ApiTypesDispatcher.get_proper_endpoint(
                "azure_openai", "v1/chat/completions", provider=provider
            )
        assert path == (
            f"/openai/deployments/{DEPLOYMENT}/chat/completions"
            f"?api-version={DEFAULT_API_VERSION}"
        )
        fake_logger.warning.assert_called_once()

    def test_deployment_option_wins_over_model_path(self):
        provider = _provider(provider_options={"deployment": "explicit-dep"})
        path = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai", "v1/chat/completions", provider=provider
        )
        assert "/openai/deployments/explicit-dep/chat/completions" in path

    def test_deployment_falls_back_to_logical_name(self):
        provider = _provider(model_path="")
        path = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai", "v1/chat/completions", provider=provider
        )
        assert "/openai/deployments/azure%2Fgpt-4o/chat/completions" in path

    def test_deployment_name_is_url_encoded(self):
        # A deployment name is a path segment: a reserved character must not
        # be able to add one.
        provider = _provider(model_path="dep/with space")
        path = ApiTypesDispatcher.get_proper_endpoint(
            "azure_openai", "v1/chat/completions", provider=provider
        )
        assert "/openai/deployments/dep%2Fwith%20space/chat/completions" in path

    def test_ping_path_is_the_free_models_probe(self):
        # GET /openai/models authenticates and proves reachability without
        # invoking a model; the generic probe list would only ever get a 404
        # from an Azure resource.
        assert ApiTypesDispatcher.ping_path("azure_openai", _provider()) == (
            f"/openai/models?api-version={DEFAULT_API_VERSION}"
        )

    def test_ping_path_follows_the_api_version_option(self):
        provider = _provider(provider_options={"api_version": "2025-01-01-preview"})
        assert ApiTypesDispatcher.ping_path("azure_openai", provider) == (
            "/openai/models?api-version=2025-01-01-preview"
        )

    def test_registered_in_api_types(self):
        assert AZURE_OPENAI_PROVIDER in ApiTypesDispatcher._REGISTRY
        assert AZURE_OPENAI_PROVIDER in API_TYPES
        assert isinstance(
            ApiTypesDispatcher._get_impl(AZURE_OPENAI_PROVIDER), AzureOpenAiType
        )

    def test_is_openai_compatible_on_the_wire(self):
        # Bodies, responses and the SSE stream are the OpenAI ones, so the
        # OpenAI-shaped endpoints serve it without a conversion layer.
        assert AZURE_OPENAI_PROVIDER in OPENAI_COMPATIBLE_PROVIDERS
        assert AZURE_OPENAI_PROVIDER in ALL_PROVIDERS
        assert (
            ApiTypesDispatcher.owns_message_normalization(AZURE_OPENAI_PROVIDER)
            is False
        )


# ----------------------------------------------------------------------
# Headers / authentication
# ----------------------------------------------------------------------
class TestAzureHeaders:
    def test_api_key_header(self):
        headers = ApiTypesDispatcher.request_headers("azure_openai", _provider())
        assert headers == {
            "Content-Type": "application/json",
            "api-key": "azure-api-key",
        }
        assert "Authorization" not in headers

    def test_provider_option_api_key_is_accepted(self):
        provider = _provider(api_token="", provider_options={"api_key": "opt-key"})
        headers = ApiTypesDispatcher.request_headers("azure_openai", provider)
        assert headers["api-key"] == "opt-key"

    def test_explicit_entra_access_token(self):
        provider = _provider(
            api_token="",
            provider_options={"access_token": "eyJhbGc.test"},
        )
        headers = ApiTypesDispatcher.request_headers("azure_openai", provider)
        assert headers["Authorization"] == "Bearer eyJhbGc.test"
        assert "api-key" not in headers

    def test_client_credentials_flow(self):
        provider = _provider(
            api_token="",
            provider_options={
                "tenant_id": "tenant-1",
                "client_id": "client-1",
                "client_secret": "secret-1",
            },
        )
        with mock.patch.object(
            azure_auth.requests, "post", return_value=_token_response()
        ) as fake_post:
            headers = ApiTypesDispatcher.request_headers("azure_openai", provider)

        assert headers["Authorization"] == "Bearer entra-token"
        url = fake_post.call_args.args[0]
        assert url == (
            "https://login.microsoftonline.com/tenant-1/oauth2/v2.0/token"
        )
        data = fake_post.call_args.kwargs["data"]
        assert data["grant_type"] == "client_credentials"
        assert data["client_id"] == "client-1"
        assert data["client_secret"] == "secret-1"
        assert data["scope"] == DEFAULT_SCOPE

    def test_credentials_are_read_from_the_environment(self):
        provider = _provider(api_token="")
        env = {
            "AZURE_TENANT_ID": "env-tenant",
            "AZURE_CLIENT_ID": "env-client",
            "AZURE_CLIENT_SECRET": "env-secret",
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                azure_auth.requests, "post", return_value=_token_response()
            ) as fake_post,
        ):
            headers = ApiTypesDispatcher.request_headers("azure_openai", provider)
        assert headers["Authorization"] == "Bearer entra-token"
        assert "/env-tenant/oauth2/v2.0/token" in fake_post.call_args.args[0]

    def test_token_is_cached_between_calls(self):
        provider = _provider(
            api_token="",
            provider_options={
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
            },
        )
        with mock.patch.object(
            azure_auth.requests, "post", return_value=_token_response()
        ) as fake_post:
            first = AzureOpenAiType().request_headers(provider)
            second = AzureOpenAiType().request_headers(provider)
        assert first == second
        fake_post.assert_called_once()

    def test_workload_identity_federated_token(self, tmp_path):
        token_file = tmp_path / "azure-token"
        token_file.write_text("federated-assertion", encoding="utf-8")
        provider = _provider(
            api_token="",
            provider_options={
                "tenant_id": "t",
                "client_id": "c",
                "federated_token_file": str(token_file),
            },
        )
        with mock.patch.object(
            azure_auth.requests, "post", return_value=_token_response()
        ) as fake_post:
            headers = AzureOpenAiType().request_headers(provider)
        assert headers["Authorization"] == "Bearer entra-token"
        data = fake_post.call_args.kwargs["data"]
        assert data["client_assertion"] == "federated-assertion"
        assert data["client_assertion_type"].endswith("jwt-bearer")
        assert "client_secret" not in data

    def test_managed_identity_fallback(self):
        provider = _provider(api_token="")
        with (
            mock.patch.object(
                azure_auth.requests,
                "get",
                return_value=_token_response("imds-token"),
            ) as fake_get,
            mock.patch.object(azure_auth.requests, "post") as fake_post,
        ):
            headers = AzureOpenAiType().request_headers(provider)
        assert headers["Authorization"] == "Bearer imds-token"
        fake_post.assert_not_called()
        assert fake_get.call_args.args[0] == azure_auth.IMDS_ENDPOINT
        assert fake_get.call_args.kwargs["headers"]["Metadata"] == "true"

    def test_app_service_identity_endpoint_is_preferred_over_imds(self):
        provider = _provider(api_token="")
        env = {
            "IDENTITY_ENDPOINT": "http://127.0.0.1:8081/_id/token",
            "IDENTITY_HEADER": "identity-secret",
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(
                azure_auth.requests, "get", return_value=_token_response("app-token")
            ) as fake_get,
        ):
            headers = AzureOpenAiType().request_headers(provider)
        assert headers["Authorization"] == "Bearer app-token"
        assert fake_get.call_args.args[0] == env["IDENTITY_ENDPOINT"]
        assert fake_get.call_args.kwargs["headers"]["X-IDENTITY-HEADER"] == (
            "identity-secret"
        )

    def test_missing_credentials_raise_a_readable_error(self):
        provider = _provider(api_token="")
        with (
            mock.patch.object(azure_auth.requests, "post") as fake_post,
            mock.patch.object(
                azure_auth.requests,
                "get",
                side_effect=azure_auth.requests.ConnectionError,
            ),
        ):
            fake_post.return_value = None
            with pytest.raises(RuntimeError, match="Microsoft Entra ID"):
                AzureOpenAiType().request_headers(provider)

    def test_token_endpoint_failure_raises(self):
        provider = _provider(
            api_token="",
            provider_options={"client_id": "c", "client_secret": "s"},
        )
        with (
            mock.patch.object(azure_auth.requests, "post") as fake_post,
            mock.patch.object(
                azure_auth.requests,
                "get",
                side_effect=azure_auth.requests.ConnectionError,
            ),
        ):
            fake_post.return_value.status_code = 401
            fake_post.return_value.text = "AADSTS7000215: invalid secret"
            fake_post.return_value.content = b"{}"
            with pytest.raises(RuntimeError, match="Microsoft Entra ID"):
                AzureOpenAiType().request_headers(provider)

    def test_rejected_status_evicts_the_cached_token(self):
        provider = _provider(
            api_token="",
            provider_options={
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
            },
        )
        with mock.patch.object(
            azure_auth.requests, "post", return_value=_token_response()
        ) as fake_post:
            AzureOpenAiType().request_headers(provider)
            fake_post.return_value = _token_response("fresh-token")
            AzureOpenAiType().on_response_status(provider, 401)
            headers = AzureOpenAiType().request_headers(provider)
        assert headers["Authorization"] == "Bearer fresh-token"
        assert fake_post.call_count == 2

    def test_api_key_providers_have_nothing_to_evict(self):
        # A 401/403 answered with an Azure API key must not be swallowed as a
        # credential eviction: the router caches nothing for this provider.
        provider = _provider()
        with mock.patch.object(
            AzureAdTokenProvider, "invalidate"
        ) as fake_invalidate:
            AzureOpenAiType().on_response_status(provider, 401)
            AzureOpenAiType().on_response_status(provider, 403)
        fake_invalidate.assert_not_called()

    def test_success_status_keeps_the_token(self):
        provider = _provider(
            api_token="",
            provider_options={
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
            },
        )
        with mock.patch.object(
            azure_auth.requests, "post", return_value=_token_response()
        ) as fake_post:
            AzureOpenAiType().request_headers(provider)
            AzureOpenAiType().on_response_status(provider, 200)
            AzureOpenAiType().request_headers(provider)
        fake_post.assert_called_once()


# ----------------------------------------------------------------------
# Request body
# ----------------------------------------------------------------------
class TestAzureRequestBody:
    def test_deployment_name_is_injected_as_model(self):
        body = ApiTypesDispatcher.request_body(
            "azure_openai",
            {"messages": [{"role": "user", "content": "hi"}]},
            _provider(),
            None,
        )
        assert body["model"] == DEPLOYMENT

    def test_system_message_is_prepended(self):
        # The OpenAI-shaped hook is inherited unchanged: Azure takes the
        # system role in ``messages`` (no protocol-specific field).
        body = ApiTypesDispatcher.request_body(
            "azure_openai",
            {"messages": [{"role": "user", "content": "hi"}]},
            _provider(),
            {"role": "system", "content": "be terse"},
        )
        assert [m["role"] for m in body["messages"]] == ["system", "user"]

    def test_untouched_openai_parameters(self):
        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.5,
            "tools": [{"type": "function"}],
            "stream": True,
        }
        body = ApiTypesDispatcher.request_body(
            "azure_openai", dict(payload), _provider(), None
        )
        assert body["temperature"] == 0.5
        assert body["tools"] == [{"type": "function"}]
        # `stream` stays: Azure selects the SSE mode from the body flag.
        assert body["stream"] is True
