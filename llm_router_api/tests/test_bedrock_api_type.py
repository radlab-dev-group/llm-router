"""
Unit tests for the Amazon Bedrock API type.

Covers the request adapter (paths, headers, signing), the payload and
response converters, the Converse stream translation and the Amazon
event‑stream frame decoder.

No AWS SDK is required to run this file.  The two places where an SDK is the
only honest oracle are asserted directly against it and skipped when it is
absent (``pip install boto3`` in a scratch venv to run them):

* the pinned SigV4 signatures, reproduced by
  ``botocore.auth.SigV4Auth`` for the same method, URL, headers, body,
  credentials and timestamp (``test_signature_matches_botocore_reference``,
  which asserts them live when botocore is installed, and
  ``test_signature_matches_botocore_vector``, which pins them for CI);
* the event‑stream frame format, checked against
  ``botocore.eventstream.EventStreamBuffer`` — the parser boto3 uses for every
  Bedrock stream (``test_frames_match_botocore_reference_parser``).
"""

from __future__ import annotations

import datetime
import json
import os
import struct
import zlib

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
from unittest import mock  # noqa: E402

from llm_router_api.core.api_types.auth import aws as aws_auth  # noqa: E402
from llm_router_api.core.api_types.auth.aws import (  # noqa: E402
    AwsCredentialProvider,
    AwsCredentials,
    AwsSigV4Signer,
)
from llm_router_api.core.api_types.bedrock import (  # noqa: E402
    BedrockConverters,
    BedrockType,
)
from llm_router_api.core.api_types.dispatcher import (  # noqa: E402
    ApiTypesDispatcher,
)
from llm_router_api.core.api_types.eventstream import (  # noqa: E402
    AwsEventStreamError,
    iter_events,
)

MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"
API_HOST = "https://bedrock-runtime.eu-central-1.amazonaws.com"


def _provider(**overrides):
    """Build a Bedrock provider descriptor."""
    fields = {
        "id": "bedrock-sonnet",
        "name": "aws/claude-sonnet-4",
        "api_host": API_HOST,
        "api_type": "bedrock",
        "api_token": "",
        "input_size": 200000,
        "model_path": MODEL_ID,
        "provider_options": {"region": "eu-central-1"},
    }
    fields.update(overrides)
    return type("Provider", (), fields)()


# ----------------------------------------------------------------------
# Event-stream frame builder (mirrors the AWS wire framing)
# ----------------------------------------------------------------------
def _frame(event_type, payload, message_type=1, flags=0):
    """
    Encode one ``application/vnd.amazon.eventstream`` frame.

    The trailing CRC is ``crc32(frame[0:payload_end])`` — the one range
    ``botocore.eventstream.EventStreamBuffer`` accepts (see
    :func:`_frame_with_crc`, which asserts that parser agrees with every frame
    this builder produces).
    """
    return _frame_with_crc(event_type, payload, message_type=message_type, flags=flags)


def _frame_with_crc(event_type, payload, message_type=1, flags=0, crc_of=None):
    """
    Encode one frame whose trailing CRC is computed by ``crc_of``.

    ``crc_of(frame_without_crc, payload_end) -> int`` defaults to the real wire
    convention; passing another function builds a deliberately mis-signed frame
    for the negative tests.
    """
    headers = b""
    for name, value in (
        (":event-type", event_type),
        (":content-type", "application/json"),
        (":message-type", "event"),
    ):
        name_bytes, value_bytes = name.encode(), value.encode()
        headers += (
            bytes([len(name_bytes)])
            + name_bytes
            + b"\x07"
            + struct.pack("!H", len(value_bytes))
            + value_bytes
        )
    body = json.dumps(payload).encode("utf-8")
    total = 12 + 1 + 4 + len(headers) + len(body) + 4
    lengths = struct.pack("!II", total, len(headers))
    prelude_crc = zlib.crc32(lengths) & 0xFFFFFFFF
    rest = lengths + struct.pack("!I", prelude_crc)
    rest += struct.pack("!BI", message_type, flags) + headers + body
    end = total - 4
    if crc_of is None:
        crc = zlib.crc32(rest[:end]) & 0xFFFFFFFF
    else:
        crc = crc_of(rest, end) & 0xFFFFFFFF
    return rest + struct.pack("!I", crc)


def _blob(events, crc_of=None):
    return b"".join(
        _frame_with_crc(name, body, crc_of=crc_of) for name, body in events
    )


# ----------------------------------------------------------------------
# Endpoint paths
# ----------------------------------------------------------------------
class TestBedrockEndpoints:
    def test_converse_path(self):
        path = ApiTypesDispatcher.get_proper_endpoint(
            "bedrock", "v1/chat/completions", provider=_provider()
        )
        assert path == f"/model/{MODEL_ID}/converse"

    def test_stream_path_uses_converse_stream(self):
        path = ApiTypesDispatcher.get_proper_endpoint(
            "bedrock", "v1/chat/completions", provider=_provider(), stream=True
        )
        assert path == f"/model/{MODEL_ID}/converse-stream"

    def test_embeddings_path_uses_invoke(self):
        # Converse has no embeddings operation.
        path = ApiTypesDispatcher.get_proper_endpoint(
            "bedrock", "v1/embeddings", provider=_provider()
        )
        assert path == f"/model/{MODEL_ID}/invoke"

    def test_completions_and_responses_share_converse(self):
        assert ApiTypesDispatcher.get_proper_endpoint(
            "bedrock", "v1/completions", provider=_provider()
        ) == ApiTypesDispatcher.get_proper_endpoint(
            "bedrock", "v1/chat/completions", provider=_provider()
        )
        assert ApiTypesDispatcher.get_proper_endpoint(
            "bedrock", "v1/responses", provider=_provider()
        ) == ApiTypesDispatcher.get_proper_endpoint(
            "bedrock", "v1/chat/completions", provider=_provider()
        )

    def test_model_id_falls_back_to_name(self):
        provider = _provider(model_path="")
        path = ApiTypesDispatcher.get_proper_endpoint(
            "bedrock", "v1/chat/completions", provider=provider
        )
        assert path == "/model/aws/claude-sonnet-4/converse"

    def test_inference_profile_and_arn_kept_verbatim(self):
        for model in (
            "eu.anthropic.claude-3-5-sonnet-20240620-v1:0",
            "arn:aws:bedrock:eu-west-1:123456789012:provisioned-model/abc123",
        ):
            path = ApiTypesDispatcher.get_proper_endpoint(
                "bedrock", "v1/chat/completions", provider=_provider(model_path=model)
            )
            assert path == f"/model/{model}/converse"

    def test_owns_message_normalization(self):
        assert ApiTypesDispatcher.owns_message_normalization("bedrock") is True

    def test_ping_path_is_none(self):
        # The runtime has no cheap GET; the monitor keeps its generic probe.
        assert ApiTypesDispatcher.ping_path("bedrock", _provider()) is None

    def test_registered_in_api_types(self):
        assert "bedrock" in ApiTypesDispatcher._REGISTRY
        assert isinstance(ApiTypesDispatcher._get_impl("bedrock"), BedrockType)


# ----------------------------------------------------------------------
# Headers
# ----------------------------------------------------------------------
class TestBedrockHeaders:
    def test_api_token_is_bearer(self):
        headers = ApiTypesDispatcher.request_headers(
            "bedrock", _provider(api_token="bedrock-api-key")
        )
        assert headers["Authorization"] == "Bearer bedrock-api-key"
        assert headers["Content-Type"] == "application/json"

    def test_iam_path_leaves_authorization_to_the_signer(self):
        headers = ApiTypesDispatcher.request_headers("bedrock", _provider())
        assert "Authorization" not in headers

    def test_type_signs_payload(self):
        assert ApiTypesDispatcher.signs_payload("bedrock") is True
        assert ApiTypesDispatcher.signs_payload("openai") is False
        assert ApiTypesDispatcher.signs_payload("does-not-exist") is False

    def test_sign_request_passes_through_for_api_key(self):
        headers = {"Content-Type": "application/json", "Authorization": "Bearer k"}
        signed = BedrockType().sign_request(
            _provider(api_token="k"), "POST", API_HOST + "/x", headers, b"{}"
        )
        assert signed == headers

    def test_signing_requires_a_region(self, monkeypatch):
        monkeypatch.setattr(
            aws_auth.AwsCredentialProvider,
            "resolve_region",
            staticmethod(lambda options=None: ""),
        )
        with pytest.raises(ValueError, match="region"):
            AwsSigV4Signer.sign(
                method="POST",
                url=API_HOST + "/model/m/converse",
                headers={},
                body=b"{}",
                region="",
                credentials=AwsCredentials("AK", "SK"),
            )


# ----------------------------------------------------------------------
# SigV4 signing
# ----------------------------------------------------------------------
SIGN_TS = datetime.datetime(2026, 1, 15, 10, 30, 0, tzinfo=datetime.timezone.utc)
SIGN_URL = f"{API_HOST}/model/{MODEL_ID}/converse"
SIGN_BODY = b'{"messages":[{"role":"user","content":[{"text":"hi"}]}]}'
ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"


class TestBedrockSigning:
    def _sign(self, session_token="", headers=None):
        return AwsSigV4Signer.sign(
            method="POST",
            url=SIGN_URL,
            headers=(
                headers
                if headers is not None
                else {"Content-Type": "application/json"}
            ),
            body=SIGN_BODY,
            region="eu-central-1",
            credentials=AwsCredentials(ACCESS_KEY, SECRET_KEY, session_token),
            timestamp=SIGN_TS,
        )

    def test_signature_matches_botocore_reference(self):
        """
        Sign the same request with ``botocore.auth.SigV4Auth`` and compare.

        A hand-rolled SigV4 that is internally consistent can still be wrong
        (wrong canonical URI, an extra signed header, the S3-only content-hash
        header), so the golden vectors alone cannot prove the algorithm — only
        the service's own signer can.  Skipped when botocore is not installed.
        """
        pytest.importorskip("botocore")
        from unittest import mock  # noqa: PLC0415

        from botocore.auth import SigV4Auth  # noqa: PLC0415
        from botocore.awsrequest import AWSRequest  # noqa: PLC0415
        from botocore.credentials import Credentials  # noqa: PLC0415

        def botocore_authorization(token: str) -> str:
            request = AWSRequest(
                method="POST",
                url=SIGN_URL,
                data=SIGN_BODY,
                headers={"Content-Type": "application/json"},
            )
            credentials = Credentials(ACCESS_KEY, SECRET_KEY, token or None)
            # botocore reads the signing time from this helper and expects a
            # naive UTC datetime.
            with mock.patch(
                "botocore.auth.get_current_datetime",
                return_value=SIGN_TS.replace(tzinfo=None),
            ):
                SigV4Auth(credentials, "bedrock", "eu-central-1").add_auth(request)
            return request.headers["Authorization"]

        for token in ("", "IQ.ExampleToken"):
            assert (
                self._sign(session_token=token)["Authorization"]
                == botocore_authorization(token)
            )

    def test_signature_matches_botocore_vector(self):
        """
        Golden SigV4 vectors.

        These values were generated by this implementation and compared, byte
        for byte, against ``botocore.auth.SigV4Auth`` for the same method, URL,
        headers, body, credentials and timestamp.  The comparison is what
        pinned two behaviours this test now guards: the canonical URI percent-
        encodes the model ID's colon (``…-v1%3A0``), and Bedrock signs **no**
        ``x-amz-content-sha256`` header (unlike S3).
        """
        signed = self._sign()
        assert (
            signed["Authorization"]
            == "AWS4-HMAC-SHA256 "
            "Credential=AKIAIOSFODNN7EXAMPLE/20260115/eu-central-1/bedrock/aws4_request, "
            "SignedHeaders=content-type;host;x-amz-date, "
            "Signature=31f7bd58c9459a421b99a1d5c8e9da778210b1781121f6c81393331b1748a97b"
        )

    def test_signature_with_session_token_matches_botocore_vector(self):
        signed = self._sign(session_token="IQ.ExampleToken")
        assert (
            signed["Authorization"]
            == "AWS4-HMAC-SHA256 "
            "Credential=AKIAIOSFODNN7EXAMPLE/20260115/eu-central-1/bedrock/aws4_request, "
            "SignedHeaders=content-type;host;x-amz-date;x-amz-security-token, "
            "Signature=becec230100f7f623ab154c1c2f448c6837f705f335470933d9c751dede4660d"
        )
        assert signed["x-amz-security-token"] == "IQ.ExampleToken"

    def test_no_content_sha_header_by_default(self):
        assert "x-amz-content-sha256" not in self._sign()

    def test_content_sha_header_when_requested(self):
        signed = AwsSigV4Signer.sign(
            method="POST",
            url=SIGN_URL,
            headers={},
            body=SIGN_BODY,
            region="eu-central-1",
            credentials=AwsCredentials(ACCESS_KEY, SECRET_KEY),
            timestamp=SIGN_TS,
            include_content_hash=True,
        )
        assert signed["x-amz-content-sha256"] == AwsSigV4Signer.payload_hash(SIGN_BODY)

    def test_amz_date_is_utc_compact(self):
        assert self._sign()["x-amz-date"] == "20260115T103000Z"

    def test_host_is_signed_even_when_absent(self):
        signed = self._sign(headers={"Content-Type": "application/json"})
        assert "host" in signed["Authorization"].split("SignedHeaders=")[1]
        assert signed["host"] == "bedrock-runtime.eu-central-1.amazonaws.com"

    def test_canonical_uri_encodes_colon(self):
        # Verified against botocore's canonical_request().
        assert (
            AwsSigV4Signer._canonical_uri(f"/model/{MODEL_ID}/converse")
            == "/model/anthropic.claude-3-5-sonnet-20240620-v1%3A0/converse"
        )

    def test_canonical_query_string_sorts_without_reencoding(self):
        assert (
            AwsSigV4Signer._canonical_query_string("b=2&a=x%2Fy") == "a=x%2Fy&b=2"
        )

    def test_changing_the_body_changes_the_signature(self):
        first = self._sign()
        second = AwsSigV4Signer.sign(
            method="POST",
            url=SIGN_URL,
            headers={"Content-Type": "application/json"},
            body=SIGN_BODY + b" ",
            region="eu-central-1",
            credentials=AwsCredentials(ACCESS_KEY, SECRET_KEY),
            timestamp=SIGN_TS,
        )
        assert first["Authorization"] != second["Authorization"]

    def test_input_headers_are_not_mutated(self):
        headers = {"Content-Type": "application/json"}
        AwsSigV4Signer.sign(
            method="POST",
            url=SIGN_URL,
            headers=headers,
            body=SIGN_BODY,
            region="eu-central-1",
            credentials=AwsCredentials(ACCESS_KEY, SECRET_KEY),
            timestamp=SIGN_TS,
        )
        assert headers == {"Content-Type": "application/json"}


# ----------------------------------------------------------------------
# Credential resolution
# ----------------------------------------------------------------------
class TestAwsCredentialProvider:
    def setup_method(self):
        AwsCredentialProvider.clear_cache()

    def teardown_method(self):
        AwsCredentialProvider.clear_cache()

    def test_static_credentials_from_options(self):
        credentials = AwsCredentialProvider.get_credentials(
            {
                "access_key_id": "AK",
                "secret_access_key": "SK",
                "session_token": "ST",
            }
        )
        assert (credentials.access_key, credentials.secret_key, credentials.session_token) == ("AK", "SK", "ST")

    def test_static_credentials_from_environment(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ENVAK")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ENVSK")
        monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
        credentials = AwsCredentialProvider.get_credentials({})
        assert credentials.access_key == "ENVAK"
        assert credentials.session_token == ""

    def test_options_win_over_environment(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ENVAK")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ENVSK")
        credentials = AwsCredentialProvider.get_credentials(
            {"access_key_id": "OPTAK", "secret_access_key": "OPTSK"}
        )
        assert credentials.access_key == "OPTAK"

    def test_missing_boto3_raises_install_hint(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        monkeypatch.setattr(aws_auth, "_BOTO3_AVAILABLE", False)
        monkeypatch.setattr(aws_auth, "boto3", None)
        with pytest.raises(RuntimeError, match=r"pip install 'radlab-llm-router\[aws\]'"):
            AwsCredentialProvider.get_credentials({})

    def test_chain_credentials_are_cached(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        calls = []

        def _fake(profile="", region=""):
            calls.append((profile, region))
            return AwsCredentials("AK", "SK", "", expires_at=10**12)

        monkeypatch.setattr(AwsCredentialProvider, "_from_boto3", staticmethod(_fake))
        first = AwsCredentialProvider.get_credentials({"region": "eu-central-1"})
        second = AwsCredentialProvider.get_credentials({"region": "eu-central-1"})
        assert first is second
        assert len(calls) == 1

    def test_expired_chain_credentials_are_resolved_again(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        state = {"n": 0}

        def _fake(profile="", region=""):
            state["n"] += 1
            return AwsCredentials("AK", "SK", "", expires_at=1)

        monkeypatch.setattr(AwsCredentialProvider, "_from_boto3", staticmethod(_fake))
        AwsCredentialProvider.get_credentials({})
        AwsCredentialProvider.get_credentials({})
        assert state["n"] == 2

    def test_invalidate_forces_a_fresh_resolution(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        state = {"n": 0}

        def _fake(profile="", region=""):
            state["n"] += 1
            return AwsCredentials("AK", "SK", "", expires_at=10**12)

        monkeypatch.setattr(AwsCredentialProvider, "_from_boto3", staticmethod(_fake))
        options = {"region": "us-east-1"}
        AwsCredentialProvider.get_credentials(options)
        AwsCredentialProvider.invalidate(options)
        AwsCredentialProvider.get_credentials(options)
        assert state["n"] == 2

    def test_invalidate_only_touches_its_own_key(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

        def _fake(profile="", region=""):
            return AwsCredentials("AK", "SK", "", expires_at=10**12)

        monkeypatch.setattr(AwsCredentialProvider, "_from_boto3", staticmethod(_fake))
        AwsCredentialProvider.get_credentials({"region": "us-east-1"})
        AwsCredentialProvider.invalidate({"region": "eu-west-1"})
        assert AwsCredentialProvider._cached_credentials("profile=|region=us-east-1")

    def test_on_response_status_evicts_chain_credentials(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        dropped = []
        monkeypatch.setattr(
            AwsCredentialProvider,
            "invalidate",
            classmethod(lambda cls, options=None: dropped.append(options)),
        )
        BedrockType().on_response_status(_provider(), 403)
        assert len(dropped) == 1

    def test_on_response_status_ignores_other_statuses(self, monkeypatch):
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
        with mock.patch.object(AwsCredentialProvider, "invalidate") as invalidate:
            BedrockType().on_response_status(_provider(), 429)
            BedrockType().on_response_status(_provider(), 200)
        invalidate.assert_not_called()

    def test_on_response_status_leaves_operator_credentials_alone(self):
        with mock.patch.object(AwsCredentialProvider, "invalidate") as invalidate:
            BedrockType().on_response_status(_provider(api_token="key"), 401)
            BedrockType().on_response_status(
                _provider(provider_options={"region": "x", "access_key_id": "AK"}), 401
            )
        invalidate.assert_not_called()

    def test_resolve_region_order(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "env-region")
        monkeypatch.setenv("AWS_DEFAULT_REGION", "default-region")
        assert AwsCredentialProvider.resolve_region({"region": "opt"}) == "opt"
        assert AwsCredentialProvider.resolve_region({}) == "env-region"
        monkeypatch.delenv("AWS_REGION")
        assert AwsCredentialProvider.resolve_region({}) == "default-region"


# ----------------------------------------------------------------------
# Request payload
# ----------------------------------------------------------------------
class TestBedrockPayloadConverter:
    def _convert(self, params, provider=None):
        return BedrockConverters.Payload.convert_payload(
            params, provider=provider or _provider()
        )

    def test_system_and_user_roles(self):
        body = self._convert(
            {
                "messages": [
                    {"role": "system", "content": "be terse"},
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                    {"role": "user", "content": "again"},
                ]
            }
        )
        assert body["system"] == [{"text": "be terse"}]
        assert [m["role"] for m in body["messages"]] == [
            "user",
            "assistant",
            "user",
        ]

    def test_consecutive_same_role_turns_merged(self):
        body = self._convert(
            {
                "messages": [
                    {"role": "user", "content": "one"},
                    {"role": "user", "content": "two"},
                ]
            }
        )
        assert len(body["messages"]) == 1
        assert [b["text"] for b in body["messages"][0]["content"]] == ["one", "two"]

    def test_model_field_never_sent(self):
        # The model is addressed in the URL.
        body = self._convert({"model": "x", "messages": [{"role": "user", "content": "h"}]})
        assert "model" not in body

    def test_assistant_tool_calls_become_tool_use(self):
        body = self._convert(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "tu_1",
                                "type": "function",
                                "function": {
                                    "name": "get_weather",
                                    "arguments": '{"city":"Warsaw"}',
                                },
                            }
                        ],
                    }
                ]
            }
        )
        blocks = body["messages"][0]["content"]
        assert blocks == [
            {
                "toolUse": {
                    "toolUseId": "tu_1",
                    "name": "get_weather",
                    "input": {"city": "Warsaw"},
                }
            }
        ]

    def test_tool_result_merged_into_user_turn(self):
        body = self._convert(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "tu_1",
                                "type": "function",
                                "function": {"name": "f", "arguments": "{}"},
                            }
                        ],
                    },
                    {"role": "tool", "tool_call_id": "tu_1", "content": "ok"},
                ]
            }
        )
        last = body["messages"][-1]
        assert last["role"] == "user"
        assert last["content"][0]["toolResult"]["toolUseId"] == "tu_1"
        assert last["content"][0]["toolResult"]["content"] == [{"text": "ok"}]

    def test_tool_message_without_id_is_dropped(self):
        body = self._convert(
            {
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "tool", "content": "orphan"},
                ]
            }
        )
        assert all(
            "toolResult" not in block
            for message in body["messages"]
            for block in message["content"]
        )

    def test_unparseable_tool_arguments_degrade_to_empty(self):
        body = self._convert(
            {
                "messages": [
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "tu_1",
                                "function": {"name": "f", "arguments": "not json"},
                            }
                        ],
                    }
                ]
            }
        )
        assert body["messages"][0]["content"][0]["toolUse"]["input"] == {}

    def test_inference_config_mapping(self):
        body = self._convert(
            {
                "messages": [],
                "temperature": 0.4,
                "top_p": 0.9,
                "max_tokens": "64",
                "stop": "END",
            }
        )
        assert body["inferenceConfig"] == {
            "temperature": 0.4,
            "topP": 0.9,
            "maxTokens": 64,
            "stopSequences": ["END"],
        }

    def test_max_completion_tokens_accepted(self):
        body = self._convert({"messages": [], "max_completion_tokens": 12})
        assert body["inferenceConfig"]["maxTokens"] == 12

    def test_zero_and_negative_max_tokens_dropped(self):
        assert "maxTokens" not in self._convert({"messages": [], "max_tokens": 0}).get(
            "inferenceConfig", {}
        )

    def test_tools_and_tool_choice(self):
        body = self._convert(
            {
                "messages": [],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "f",
                            "description": "d",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "tool_choice": "required",
            }
        )
        spec = body["toolConfig"]["tools"][0]["toolSpec"]
        assert spec["name"] == "f"
        assert spec["description"] == "d"
        assert spec["inputSchema"]["json"]["type"] == "object"
        assert body["toolConfig"]["toolChoice"] == {"any": {}}

    def test_named_tool_choice(self):
        body = self._convert(
            {"messages": [], "tool_choice": {"type": "function", "function": {"name": "f"}}}
        )
        assert body["toolConfig"]["toolChoice"] == {"tool": {"name": "f"}}

    def test_response_format_maps_to_output_config(self):
        assert self._convert(
            {"messages": [], "response_format": {"type": "json_object"}}
        )["outputConfig"] == {"textFormat": {"type": "json"}}

    def test_additional_fields_and_guardrail_from_options(self):
        body = self._convert(
            {"messages": []},
            provider=_provider(
                provider_options={
                    "region": "eu-central-1",
                    "additional_model_request_fields": {"top_k": 5},
                    "guardrail_config": {"guardrailIdentifier": "gr"},
                }
            ),
        )
        assert body["additionalModelRequestFields"] == {"top_k": 5}
        assert body["guardrailConfig"] == {"guardrailIdentifier": "gr"}

    def test_data_url_image_becomes_image_block(self):
        body = self._convert(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "what is this"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                            },
                        ],
                    }
                ]
            }
        )
        blocks = body["messages"][0]["content"]
        assert blocks[1] == {"image": {"format": "png", "source": {"bytes": "aGVsbG8="}}}

    def test_remote_image_url_skipped(self):
        body = self._convert(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "t"},
                            {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
                        ],
                    }
                ]
            }
        )
        assert all("image" not in block for block in body["messages"][0]["content"])

    def test_system_message_injected_by_request_body_hook(self):
        body = ApiTypesDispatcher.request_body(
            "bedrock",
            {"messages": [{"role": "user", "content": "hi"}]},
            _provider(),
            {"role": "system", "content": "sys"},
        )
        assert body["system"] == [{"text": "sys"}]


# ----------------------------------------------------------------------
# Responses
# ----------------------------------------------------------------------
class TestBedrockResponseConverter:
    def test_text_response(self):
        converted = BedrockConverters.FromBedrock.convert_response(
            {
                "output": {
                    "message": {"role": "assistant", "content": [{"text": "Hello"}]}
                },
                "stopReason": "end_turn",
                "usage": {"inputTokens": 3, "outputTokens": 4, "totalTokens": 7},
            }
        )
        assert converted["object"] == "chat.completion"
        assert converted["choices"][0]["message"]["content"] == "Hello"
        assert converted["choices"][0]["finish_reason"] == "stop"
        assert converted["usage"]["total_tokens"] == 7

    def test_tool_use_response(self):
        converted = BedrockConverters.FromBedrock.convert_response(
            {
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tu_1",
                                    "name": "f",
                                    "input": {"a": 1},
                                }
                            }
                        ],
                    }
                },
                "stopReason": "tool_use",
            }
        )
        message = converted["choices"][0]["message"]
        assert message["tool_calls"][0]["id"] == "tu_1"
        assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"a": 1}
        assert converted["choices"][0]["finish_reason"] == "tool_calls"

    @pytest.mark.parametrize(
        "stop_reason,expected",
        [
            ("end_turn", "stop"),
            ("stop_sequence", "stop"),
            ("max_tokens", "length"),
            ("model_context_window_exceeded", "length"),
            ("tool_use", "tool_calls"),
            ("content_filtered", "content_filter"),
            ("guardrail_intervened", "content_filter"),
            ("something_new", "stop"),
            (None, "stop"),
        ],
    )
    def test_finish_reason_mapping(self, stop_reason, expected):
        assert BedrockConverters.map_finish_reason(stop_reason) == expected

    def test_missing_usage_yields_zeros(self):
        converted = BedrockConverters.FromBedrock.convert_response(
            {"output": {"message": {"content": [{"text": "x"}]}}, "stopReason": "end_turn"}
        )
        assert converted["usage"]["total_tokens"] == 0

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"stopReason": "end_turn"}, True),
            ({"output": {"message": {"content": []}}}, True),
            ({"choices": []}, False),
            ({"message": {"content": "x"}}, False),  # Ollama
            ({"content": "x", "role": "assistant", "id": "1"}, False),  # Anthropic
            ({}, False),
        ],
    )
    def test_response_sniffing(self, payload, expected):
        assert BedrockConverters.is_bedrock_converse_response(payload) is expected


# ----------------------------------------------------------------------
# Stream conversion
# ----------------------------------------------------------------------
class TestBedrockStreamConverter:
    def _drain(self, events):
        ctx = BedrockConverters.FromBedrock.new_stream_ctx(model="claude-x")
        chunks = []
        for event_type, payload in events:
            converted = BedrockConverters.FromBedrock.convert_event(
                event_type, payload, ctx
            )
            if converted:
                chunks.append(converted)
        return chunks, BedrockConverters.FromBedrock.flush(ctx)

    def test_text_deltas(self):
        chunks, final = self._drain(
            [
                ("messageStart", {"role": "assistant"}),
                ("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "He"}}),
                ("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "llo"}}),
                ("messageStop", {"stopReason": "end_turn"}),
            ]
        )
        assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": "He"}
        assert chunks[1]["choices"][0]["delta"] == {"content": "llo"}
        assert final["choices"][0]["finish_reason"] == "stop"

    def test_tool_use_fragments_accumulate_per_block(self):
        # Bedrock opens the block with the tool's id/name, then streams the
        # input as JSON fragments that must be reassembled per content block.
        start_event = (
            "contentBlockStart",
            {
                "contentBlockIndex": 0,
                "start": {"toolUse": {"toolUseId": "tu_1", "name": "get_weather"}},
            },
        )
        first_fragment = (
            "contentBlockDelta",
            {
                "contentBlockIndex": 0,
                "delta": {"toolUse": {"input": '{"ci'}},
            },
        )
        second_fragment = (
            "contentBlockDelta",
            {
                "contentBlockIndex": 0,
                "delta": {"toolUse": {"input": 'ty":"Waw"}'}},
            },
        )
        chunks, final = self._drain(
            [
                start_event,
                first_fragment,
                second_fragment,
                ("messageStop", {"stopReason": "tool_use"}),
            ]
        )
        start = chunks[0]["choices"][0]["delta"]["tool_calls"][0]
        assert start["id"] == "tu_1"
        assert start["function"]["name"] == "get_weather"
        # Both fragments belong to the same OpenAI tool call index…
        indices = {
            call["index"]
            for chunk in chunks
            for call in chunk["choices"][0]["delta"].get("tool_calls", [])
        }
        assert indices == {0}
        # …and concatenated they rebuild the argument object.
        arguments = "".join(
            call["function"].get("arguments", "")
            for chunk in chunks
            for call in chunk["choices"][0]["delta"].get("tool_calls", [])
        )
        assert json.loads(arguments) == {"city": "Waw"}
        assert final["choices"][0]["finish_reason"] == "tool_calls"

    def test_two_tool_blocks_get_separate_indices(self):
        chunks, _ = self._drain(
            [
                (
                    "contentBlockStart",
                    {
                        "contentBlockIndex": 0,
                        "start": {"toolUse": {"toolUseId": "a", "name": "f1"}},
                    },
                ),
                (
                    "contentBlockStart",
                    {
                        "contentBlockIndex": 1,
                        "start": {"toolUse": {"toolUseId": "b", "name": "f2"}},
                    },
                ),
            ]
        )
        ids = [
            call["id"]
            for chunk in chunks
            for call in chunk["choices"][0]["delta"].get("tool_calls", [])
        ]
        assert ids == ["a", "b"]

    def test_metadata_usage_and_invoked_model(self):
        _, final = self._drain(
            [
                ("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "x"}}),
                (
                    "metadata",
                    {
                        "usage": {"inputTokens": 2, "outputTokens": 3, "totalTokens": 5},
                        "trace": {
                            "promptRouter": {"invokedModelId": "claude-invoked"}
                        },
                    },
                ),
                ("messageStop", {"stopReason": "end_turn"}),
            ]
        )
        assert final["usage"]["total_tokens"] == 5
        assert final["model"] == "claude-invoked"

    def test_message_stop_without_content_still_closes(self):
        chunks, final = self._drain([("messageStop", {"stopReason": "max_tokens"})])
        assert chunks == []
        assert final["choices"][0]["finish_reason"] == "length"

    def test_unknown_event_ignored(self):
        chunks, _ = self._drain([("someFutureEvent", {"x": 1})])
        assert chunks == []


# ----------------------------------------------------------------------
# Embeddings
# ----------------------------------------------------------------------
class TestBedrockEmbeddings:
    def _body(self, model, params=None, options=None):
        provider = _provider(
            model_path=model,
            provider_options={"region": "eu-central-1", **(options or {})},
        )
        return ApiTypesDispatcher.request_body(
            "bedrock", {"input": "hello", **(params or {})}, provider, None
        )

    @pytest.mark.parametrize(
        "model,family",
        [
            ("amazon.titan-embed-text-v1", "titan_v1"),
            ("amazon.titan-embed-text-v2:0", "titan"),
            ("amazon.nova-embed-v1:0", "nova"),
            ("cohere.embed-english-v3", "cohere_v3"),
            ("cohere.eu.embed-english-v3", "cohere_v3"),
            ("cohere.embed-v4:0", "cohere_v4"),
            ("mistral.embed-1", "unknown"),
        ],
    )
    def test_family_detection(self, model, family):
        assert BedrockConverters.Payload.embedding_family(model) == family

    def test_titan_v1_body(self):
        assert self._body("amazon.titan-embed-text-v1") == {"inputText": "hello"}

    def test_titan_v2_body_with_dimensions(self):
        assert self._body(
            "amazon.titan-embed-text-v2:0", params={"dimensions": 512}
        ) == {"inputText": "hello", "dimensions": 512}

    def test_nova_body(self):
        assert self._body("amazon.nova-embed-v1:0") == {"input": {"text": "hello"}}

    def test_cohere_v3_body_batches(self):
        provider = _provider(
            model_path="cohere.embed-english-v3",
            provider_options={"region": "eu-central-1"},
        )
        body = ApiTypesDispatcher.request_body(
            "bedrock", {"input": ["a", "b"]}, provider, None
        )
        assert body == {"texts": ["a", "b"], "input_type": "search_document"}

    def test_cohere_v3_input_type_override(self):
        body = self._body(
            "cohere.embed-english-v3", options={"embedding_input_type": "search_query"}
        )
        assert body["input_type"] == "search_query"

    def test_cohere_v4_declares_float_type(self):
        assert self._body("cohere.embed-v4:0")["embedding_types"] == ["float"]

    def test_batch_rejected_by_single_input_models(self):
        provider = _provider(
            model_path="amazon.titan-embed-text-v1",
            provider_options={"region": "eu-central-1"},
        )
        with pytest.raises(ValueError, match="one input per request"):
            ApiTypesDispatcher.request_body(
                "bedrock", {"input": ["a", "b"]}, provider, None
            )

    def test_unknown_model_raises_with_override_hint(self):
        with pytest.raises(ValueError, match="embedding_body"):
            self._body("someone.unknown-embed-1")

    def test_embedding_body_override(self):
        body = self._body(
            "someone.unknown-embed-1", options={"embedding_body": {"custom": 1}}
        )
        assert body["custom"] == 1

    def test_titan_response_converted(self):
        converted = BedrockConverters.FromBedrock.convert_embedding(
            {"embedding": [0.1, 0.2], "inputTextTokenCount": 7}
        )
        assert converted["object"] == "list"
        assert converted["data"][0]["embedding"] == [0.1, 0.2]
        assert converted["usage"]["total_tokens"] == 7

    def test_cohere_response_converted(self):
        converted = BedrockConverters.FromBedrock.convert_embedding(
            {"embeddings": [[0.1], [0.2]], "response_type": "embeddings"}
        )
        assert [item["index"] for item in converted["data"]] == [0, 1]
        assert converted["data"][1]["embedding"] == [0.2]

    def test_cohere_v4_grouped_response_converted(self):
        converted = BedrockConverters.FromBedrock.convert_embedding(
            {"embeddings": {"float": [[0.5, 0.6]]}}
        )
        assert converted["data"][0]["embedding"] == [0.5, 0.6]

    def test_nova_response_converted(self):
        converted = BedrockConverters.FromBedrock.convert_embedding(
            {"output": {"embedding": [0.3]}, "usage": {"inputTokens": 4}}
        )
        assert converted["data"][0]["embedding"] == [0.3]
        assert converted["usage"]["prompt_tokens"] == 4

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"embedding": [0.1], "inputTextTokenCount": 1}, True),
            ({"embeddings": [[0.1]], "response_type": "embeddings"}, True),
            ({"output": {"embedding": [0.1]}}, True),
            ({"data": [{"embedding": [0.1]}]}, False),  # already OpenAI
            ({"embeddings": [[0.1]]}, False),  # Ollama-shaped
        ],
    )
    def test_embedding_sniffing(self, payload, expected):
        assert BedrockConverters.is_bedrock_embedding_response(payload) is expected


# ----------------------------------------------------------------------
# Event-stream decoder
# ----------------------------------------------------------------------
class TestEventStreamDecoder:
    EVENTS = [
        ("messageStart", {"role": "assistant"}),
        ("contentBlockDelta", {"contentBlockIndex": 0, "delta": {"text": "Hi"}}),
        ("messageStop", {"stopReason": "end_turn"}),
    ]

    def test_decodes_wire_crc(self):
        assert list(iter_events([_blob(self.EVENTS)])) == self.EVENTS

    def test_rejects_unseeded_crc_convention(self):
        # The reading the prose of the format description can be taken to mean
        # (CRC over ``frame[8:]`` with no seed).  botocore rejects it, so this
        # decoder must too: accepting several conventions would let a
        # corrupted frame through.
        blob = _blob(
            self.EVENTS, crc_of=lambda frame, end: zlib.crc32(frame[8:end])
        )
        with pytest.raises(AwsEventStreamError, match="CRC mismatch"):
            list(iter_events([blob]))

    def test_rejects_crc_over_type_onward(self):
        # …nor the variant that starts after the prelude CRC field.
        blob = _blob(
            self.EVENTS, crc_of=lambda frame, end: zlib.crc32(frame[12:end])
        )
        with pytest.raises(AwsEventStreamError, match="CRC mismatch"):
            list(iter_events([blob]))

    def test_frames_match_botocore_reference_parser(self):
        """
        Byte-level cross-check of the frame format against ``botocore``.

        ``botocore.eventstream.EventStreamBuffer`` is the parser boto3 runs for
        every Bedrock stream, so it is the reference this decoder has to agree
        with.  Skipped when botocore is not installed (it is an optional
        dependency of the *tests*, not of the router); run
        ``pip install boto3`` in a scratch venv to exercise it.
        """
        pytest.importorskip("botocore")
        from botocore.eventstream import EventStreamBuffer  # noqa: PLC0415

        buffer = EventStreamBuffer()
        buffer.add_data(_blob(self.EVENTS))
        # botocore hands the payload over as raw bytes; the router decodes it.
        parsed = [(m.headers.get(":event-type"), json.loads(m.payload)) for m in buffer]
        assert parsed == self.EVENTS

        mis_signed = _blob(
            self.EVENTS[:1], crc_of=lambda frame, end: zlib.crc32(frame[8:end])
        )
        rejecting = EventStreamBuffer()
        rejecting.add_data(mis_signed)
        with pytest.raises(Exception, match="[Cc]hecksum mismatch"):
            list(rejecting)

    @pytest.mark.parametrize("size", [1, 5, 17, 64])
    def test_frame_split_across_chunks(self, size):
        blob = _blob(self.EVENTS)
        chunks = [blob[i : i + size] for i in range(0, len(blob), size)]
        assert list(iter_events(iter(chunks))) == self.EVENTS

    def test_many_frames_in_one_chunk(self):
        assert list(iter_events([_blob(self.EVENTS)])) == self.EVENTS

    def test_empty_chunks_are_noops(self):
        iterator = iter([b"", None, _blob(self.EVENTS[:1]), b""])
        assert list(iter_events(iterator)) == self.EVENTS[:1]

    def test_corrupted_payload_detected(self):
        blob = bytearray(_blob(self.EVENTS[:1]))
        blob[30] ^= 0xFF
        with pytest.raises(AwsEventStreamError, match="CRC mismatch"):
            list(iter_events([bytes(blob)]))

    def test_truncated_frame_detected_at_end_of_stream(self):
        blob = _blob(self.EVENTS[:1])
        with pytest.raises(AwsEventStreamError, match="ended inside a frame"):
            list(iter_events([blob[:20]]))

    def test_implausible_length_detected(self):
        with pytest.raises(AwsEventStreamError, match="not an Amazon event stream"):
            list(iter_events([struct.pack("!II", 3, 1) + b"\x00" * 40]))

    def test_service_error_frame_raises_with_message(self):
        blob = _frame(
            "throttlingException", {"message": "slow down"}, message_type=2
        )
        with pytest.raises(AwsEventStreamError, match=r"throttlingException.*slow down"):
            list(iter_events([blob]))

    def test_connection_settings_frame_skipped(self):
        # A transaction frame with flag bit 0x01 set is the handshake
        # (initial-request / initial-response); it carries no modelled event.
        blob = _frame("", {}, message_type=0, flags=0x01)
        assert list(iter_events([blob])) == []

    def test_non_json_payload_rejected(self):
        frame = bytearray(_frame("messageStart", {"role": "assistant"}))
        total, headers_len = struct.unpack_from("!II", frame, 0)
        payload_start = 17 + headers_len
        payload_end = total - 4
        # Splice an equal-length run of bytes that is neither UTF-8 nor JSON
        # over the payload — every declared length stays valid — and re-sign the
        # frame, so the only failure left is the payload parse itself.
        frame[payload_start:payload_end] = b"\xff" * (payload_end - payload_start)
        frame[payload_end:] = struct.pack(
            "!I", zlib.crc32(bytes(frame[:payload_end])) & 0xFFFFFFFF
        )
        with pytest.raises(AwsEventStreamError, match="not JSON"):
            list(iter_events([bytes(frame)]))
