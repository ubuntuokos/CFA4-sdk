# SPDX-License-Identifier: MIT OR Apache-2.0
"""Protocol version 1: decoding, validation and JSON-lines framing.

Messages are plain dicts shaped as in ``docs/protocol.md``. ``decode`` and
``encode`` accept exactly what ``protocol.schema.json`` accepts, like the Rust
crate ``cfa4-ai-protocol``.
"""

import json
from importlib import resources

from ._schema import Validator

PROTOCOL_VERSION = 1
SOCKET_ENV = "CFA4_AI_SOCKET"
SHM_PREFIX = "/cfa4-ai-"
MAX_LINE_BYTES = 1 << 20
MAX_SAFE_INTEGER = (1 << 53) - 1

ERROR_CODES = (
    "oom", "invalid_input", "model_error", "model_missing", "unsupported",
    "limit_reached", "cancelled", "protocol", "crash",
)

_validator = Validator(
    json.loads(resources.files(__package__).joinpath("protocol.schema.json").read_text("utf-8"))
)


class ProtocolError(Exception):
    """A line that is not a valid protocol message.

    ``code`` is ``"line_too_long"``, ``"truncated"``, ``"json"`` or
    ``"invalid"``; ``field`` names the offending field for ``"invalid"``.
    After ``line_too_long`` the connection must be closed.
    """

    def __init__(self, code, message, field=None):
        super().__init__(message)
        self.code = code
        self.field = field


def _no_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ProtocolError("json", f"duplicate key {key!r}")
        obj[key] = value
    return obj


def _no_constant(name):
    raise ProtocolError("json", f"{name} is not JSON")


def _check_text(value, path="$"):
    """Rejects unpaired surrogates (``"\\ud800"``), which are not Unicode text."""
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ProtocolError("json", f"{path}: unpaired surrogate in a string") from None
    elif isinstance(value, list):
        for item in value:
            _check_text(item, path)
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_text(key, path)
            _check_text(item, path)


_FREE_FORM = {"params", "metrics"}


def _integral(value, key=None):
    """Turns schema-valid integral floats (``0.0``) into ints, outside free-form objects."""
    if key in _FREE_FORM:
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_integral(v) for v in value]
    if isinstance(value, dict):
        return {k: _integral(v, k) for k, v in value.items()}
    return value


def validate(message):
    """Raises ``ProtocolError`` unless ``message`` matches the schema."""
    for path, reason in _validator.errors(message):
        raise ProtocolError("invalid", f"{path}: {reason}", field=path)


def decode(line):
    """Parses and validates one line (bytes, with or without its newline)."""
    if isinstance(line, str):
        line = line.encode("utf-8")
    if line.endswith(b"\n"):
        line = line[:-1]
    if len(line) >= MAX_LINE_BYTES:
        raise ProtocolError("line_too_long", f"line longer than {MAX_LINE_BYTES} bytes")
    try:
        message = json.loads(
            line.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant
        )
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise ProtocolError("json", f"malformed message: {e}") from None
    _check_text(message)
    validate(message)
    return _integral(message)


def encode(message):
    """Validates and serializes one message as a line ending in ``\\n``."""
    _check_text(message)
    validate(message)
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    data = line.encode("utf-8") + b"\n"
    if len(data) > MAX_LINE_BYTES:
        raise ProtocolError("line_too_long", f"line longer than {MAX_LINE_BYTES} bytes")
    return data


class MessageReader:
    """Reads messages from a binary stream, never buffering more than one line."""

    def __init__(self, stream):
        self._stream = stream

    def next_message(self):
        """The next message, or ``None`` at a clean end of stream."""
        while True:
            line = self._stream.readline(MAX_LINE_BYTES)
            if not line:
                return None
            if not line.endswith(b"\n"):
                if len(line) >= MAX_LINE_BYTES:
                    raise ProtocolError("line_too_long", f"line longer than {MAX_LINE_BYTES} bytes")
                raise ProtocolError("truncated", "stream ended inside a line")
            if line.strip():
                return decode(line)

    def __iter__(self):
        while (message := self.next_message()) is not None:
            yield message


def negotiate(host_min, host_max, worker_min=PROTOCOL_VERSION, worker_max=PROTOCOL_VERSION):
    """The highest version both sides speak, or ``None``."""
    low = max(host_min, worker_min, 1)
    high = min(host_max, worker_max)
    return high if low <= high else None


def accepts(host_min, host_max, chosen):
    """Whether the version a worker chose is one the host offered."""
    return chosen >= 1 and host_min <= chosen <= host_max


def buffer_fits(buffer, segment_len):
    """Whether ``buffer`` lies inside a segment of ``segment_len`` bytes."""
    return buffer["offset"] + buffer["len"] <= segment_len
