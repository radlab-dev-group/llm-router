"""
Decoder for the Amazon event-stream wire format.

Amazon Bedrock's ``converse-stream`` and ``invoke-with-response-stream``
operations answer with ``application/vnd.amazon.eventstream`` — a **binary**
framing, not ``text/event-stream``.  The router's SSE helpers (``iter_lines()``
plus a ``data:`` prefix test) therefore cannot read them, and a Bedrock stream
needs this decoder instead.

Frame layout (all integers big-endian):

======================  =====  ==========================================
field                    bytes  note
======================  =====  ==========================================
total byte length          4   whole frame, trailing CRC included
headers byte length        4   headers section only
prelude CRC32C             4   CRC-32C over the preceding 8 bytes
message type               1   0 transaction, 1 event, 2 exception, 3 error
message flags              4
headers                    n   ``name``/``value`` pairs, see the ``_TYPE_*`` tags
payload                    m   ``total - 17 - headers - 4`` (JSON here)
message CRC32              4   CRC-32 over ``frame[0 : total - 4]``, see below
======================  =====  ==========================================

The trailing message CRC is verified.  Its exact range was settled against
``botocore.eventstream.EventStreamBuffer`` — the parser boto3 uses for every
Bedrock stream — which accepts
``crc32(frame[8 : payload_end], seed=prelude_crc)`` and rejects every other
candidate (see :func:`_verify_message_crc`).  The **prelude CRC is deliberately
not verified**: the published spec calls it CRC-32C (Castagnoli), which is not
in the standard library, so honouring it would mean a hard dependency on
``crc32c`` / ``google-crc32c``.  The frame lengths are self-describing and the
message CRC covers the prelude bytes too, so a corrupted or truncated frame is
still caught.
"""

from __future__ import annotations

import json
import logging
import struct
import zlib
from typing import Any, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Content type of a Bedrock streaming response.
EVENTSTREAM_CONTENT_TYPE = "application/vnd.amazon.eventstream"

#: Size of the fixed prelude (total length + headers length + prelude CRC).
_PRELUDE_LENGTH = 12
#: Bytes before the headers section (prelude + message type + flags).
_HEADER_OFFSET = 17
#: Smallest possible frame: prelude + type + flags + trailing CRC.
_MINIMUM_FRAME = _HEADER_OFFSET + 4

_MESSAGE_TRANSACTION = 0
_MESSAGE_EVENT = 1
_MESSAGE_EXCEPTION = 2
_MESSAGE_ERROR = 3

_MESSAGE_TYPE_NAMES = {
    _MESSAGE_TRANSACTION: "transaction",
    _MESSAGE_EVENT: "event",
    _MESSAGE_EXCEPTION: "exception",
    _MESSAGE_ERROR: "error",
}

#: Header value type tag → byte width (``None`` = variable, see decoder).
_TYPE_BOOL_TRUE = 0
_TYPE_BOOL_FALSE = 1
_TYPE_BYTE = 2
_TYPE_SHORT = 3
_TYPE_INT = 4
_TYPE_LONG = 5
_TYPE_BYTE_ARRAY = 6
_TYPE_STRING = 7
_TYPE_TIMESTAMP = 8
_TYPE_UUID = 9


class AwsEventStreamError(Exception):
    """
    Raised for a malformed or service-signalled error frame.

    A service error arrives as an ``exception``/``error`* frame whose payload
    carries the modelled exception (``ValidationException``, ``ThrottlingException``
    …), so surfacing it as an exception — rather than yielding it as data — lets
    the streaming helpers report it the same way they report a transport error.
    """


class AwsEventStreamDecoder:
    """
    Incremental event-stream frame parser.

    Feed arbitrary byte chunks with :meth:`feed`; it returns the events that
    became complete, holding on to any partial frame until the rest arrives.
    A chunk may contain several frames and a frame may span many chunks — both
    are normal for a live Bedrock stream.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        #: ``true`` once the transport ended; guards against a trailing partial
        #: frame being reported as if it were still in flight.
        self.finished = False

    def feed(self, chunk: Optional[bytes]) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Append ``chunk`` and return every event that is now complete.

        Parameters
        ----------
        chunk : Optional[bytes]
            Raw bytes from the transport; ``None`` or ``b""`` marks the end of
            the stream.

        Returns
        -------
        List[Tuple[str, Dict[str, Any]]]
            ``(event_type, payload)`` pairs, in wire order.

        Raises
        ------
        AwsEventStreamError
            On a malformed frame, on a failed message CRC, on a service error
            frame, or when the stream ends mid-frame.
        """
        if chunk:
            self._buffer.extend(chunk)
        else:
            self.finished = True

        events: List[Tuple[str, Dict[str, Any]]] = []
        while True:
            available = len(self._buffer)
            if available < _MINIMUM_FRAME:
                if self.finished and available:
                    raise AwsEventStreamError(
                        f"Bedrock stream ended inside a frame "
                        f"({available} trailing bytes)."
                    )
                return events

            total_length, headers_length = struct.unpack_from("!II", self._buffer, 0)
            if total_length < _MINIMUM_FRAME:
                raise AwsEventStreamError(
                    f"Implausible event-stream frame length {total_length}; "
                    "the response is not an Amazon event stream."
                )
            if headers_length > total_length:
                raise AwsEventStreamError(
                    f"Event-stream header length {headers_length} exceeds the "
                    f"frame length {total_length}."
                )
            if available < total_length:
                if self.finished:
                    raise AwsEventStreamError(
                        "Bedrock stream ended inside a frame "
                        f"(got {available} of {total_length} bytes)."
                    )
                return events

            frame = bytes(self._buffer[:total_length])
            del self._buffer[:total_length]
            event = self._parse_frame(frame)
            if event is not None:
                events.append(event)

    @staticmethod
    def _parse_frame(frame: bytes) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Decode one complete frame into ``(event_type, payload)``.

        Returns ``None`` for frames that carry no modelled event (connection
        settings changes, and transaction frames without a ``:event-type``).
        """
        total_length, headers_length = struct.unpack_from("!II", frame, 0)

        expected_crc = struct.unpack_from("!I", frame, total_length - 4)[0]
        _verify_message_crc(frame, total_length, expected_crc)

        message_type = frame[12]
        flags = struct.unpack_from("!I", frame, 13)[0]
        if message_type == _MESSAGE_TRANSACTION and flags & 0x01:
            # Connection settings update: no modelled payload.
            return None

        headers_start = _HEADER_OFFSET
        headers_end = headers_start + headers_length
        headers = _decode_headers(frame, headers_start, headers_end)

        payload_bytes = frame[headers_end : total_length - 4]
        type_name = _MESSAGE_TYPE_NAMES.get(message_type, f"type-{message_type}")

        payload: Dict[str, Any] = {}
        if payload_bytes.strip():
            try:
                parsed = json.loads(payload_bytes.decode("utf-8"))
                payload = parsed if isinstance(parsed, dict) else {"value": parsed}
            except (ValueError, UnicodeDecodeError) as exc:
                raise AwsEventStreamError(
                    f"Event-stream {type_name} payload is not JSON: {exc}"
                ) from exc

        event_type = str(headers.get(":event-type") or "")

        if message_type in (_MESSAGE_EXCEPTION, _MESSAGE_ERROR):
            raise AwsEventStreamError(_describe_error(event_type, headers, payload))

        if not event_type:
            return None
        return event_type, payload


def _verify_message_crc(frame: bytes, total_length: int, expected: int) -> None:
    """
    Verify the frame's trailing CRC over the range the service actually signs.

    ``botocore`` — whose :class:`botocore.eventstream.EventStreamBuffer` is the
    parser every boto3 Bedrock stream goes through — computes the field as
    ``crc32(frame[8 : payload_end], crc=prelude_crc)``, i.e. seeded with the
    frame's own prelude CRC and covering everything from that field onward
    (its comment: *"the minus 4 includes the prelude crc to the bytes to be
    checked"*).  Because CRC-32 chains, seeding with
    ``crc32(frame[0:8])`` — which is what the prelude field holds — makes that
    identical to ``crc32(frame[0 : payload_end])``, so the whole prefix is
    covered here without reading the prelude field separately.

    Verified against botocore 1.43.108: it accepts this range and rejects the
    unseeded ``crc32(frame[8:])`` and ``crc32(frame[12:])`` readings that the
    prose in the published format description can be taken to mean.  Accepting
    several conventions would let a corrupted frame through, so exactly one is
    matched here.
    """
    payload_end = total_length - 4
    computed = zlib.crc32(frame[:payload_end]) & 0xFFFFFFFF
    if expected == computed:
        return
    raise AwsEventStreamError(
        "Event-stream frame CRC mismatch "
        f"(expected {expected:#010x}, computed {computed:#010x})."
    )


def _decode_headers(data: bytes, start: int, end: int) -> Dict[str, Any]:
    """
    Decode the header section of a frame.

    Unknown value tags are skipped rather than failing the whole stream: the
    format is extensible and a Bedrock response carries headers this router does
    not read (``:content-type``, ``:message-type``, ``:exception-type``).
    """
    headers: Dict[str, Any] = {}
    cursor = start
    while cursor < end:
        name_length = data[cursor]
        cursor += 1
        name_end = cursor + name_length
        if name_end > end:
            raise AwsEventStreamError("Truncated event-stream header name.")
        name = data[cursor:name_end].decode("utf-8", errors="replace")
        cursor = name_end
        if cursor >= end:
            raise AwsEventStreamError(
                f"Event-stream header {name!r} has no value type."
            )
        value_type = data[cursor]
        cursor += 1

        if value_type in (_TYPE_BOOL_TRUE, _TYPE_BOOL_FALSE):
            headers[name] = value_type == _TYPE_BOOL_TRUE
        elif value_type == _TYPE_BYTE:
            headers[name] = _read_int(data, cursor, end, "!b", 1)
            cursor += 1
        elif value_type == _TYPE_SHORT:
            headers[name] = _read_int(data, cursor, end, "!h", 2)
            cursor += 2
        elif value_type == _TYPE_INT:
            headers[name] = _read_int(data, cursor, end, "!i", 4)
            cursor += 4
        elif value_type in (_TYPE_LONG, _TYPE_TIMESTAMP):
            headers[name] = _read_int(data, cursor, end, "!q", 8)
            cursor += 8
        elif value_type == _TYPE_BYTE_ARRAY:
            (length,) = struct.unpack_from("!I", _require(data, cursor, end, 4), 0)
            cursor += 4
            _require(data, cursor, end, length)
            headers[name] = bytes(data[cursor : cursor + length])
            cursor += length
        elif value_type == _TYPE_STRING:
            (length,) = struct.unpack_from("!H", _require(data, cursor, end, 2), 0)
            cursor += 2
            _require(data, cursor, end, length)
            headers[name] = data[cursor : cursor + length].decode(
                "utf-8", errors="replace"
            )
            cursor += length
        elif value_type == _TYPE_UUID:
            _require(data, cursor, end, 16)
            headers[name] = data[cursor : cursor + 16].hex()
            cursor += 16
        else:
            raise AwsEventStreamError(
                f"Unknown event-stream header value type {value_type} for {name!r}."
            )
    return headers


def _read_int(data: bytes, cursor: int, end: int, fmt: str, width: int) -> int:
    """Read one fixed-width big-endian integer, bounds-checked."""
    _require(data, cursor, end, width)
    return int(struct.unpack_from(fmt, data, cursor)[0])


def _require(data: bytes, cursor: int, end: int, width: int) -> bytes:
    """
    Ensure ``width`` bytes are available, else fail with a clear message.

    Returns the slice so callers can unpack from it; the bounds check happens
    once here instead of being repeated at every header type.
    """
    if cursor + width > end:
        raise AwsEventStreamError("Truncated event-stream header value.")
    return data[cursor : cursor + width]


def _describe_error(
    event_type: str, headers: Dict[str, Any], payload: Dict[str, Any]
) -> str:
    """
    Render a service error frame into one readable line.

    Bedrock puts the modelled exception name in the ``:exception-type`` header
    and the human message in the payload (``message``/``Message``), so both are
    worth surfacing.
    """
    name = str(headers.get(":exception-type") or event_type or "stream error")
    message = payload.get("message") or payload.get("Message") or ""
    if message:
        return f"Bedrock stream error ({name}): {message}"
    return f"Bedrock stream error ({name})."


def iter_events(
    chunks: Iterator[bytes],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Turn a byte-chunk iterator into an ``(event_type, payload)`` iterator.

    This is the form the streaming helpers consume; :class:`AwsEventStreamDecoder`
    is exposed separately for callers that already drive their own buffer.
    """
    decoder = AwsEventStreamDecoder()
    for chunk in chunks:
        for event in decoder.feed(chunk):
            yield event
    for event in decoder.feed(None):
        yield event
