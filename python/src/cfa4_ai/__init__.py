# SPDX-License-Identifier: MIT OR Apache-2.0
"""CFA4 AI worker SDK, protocol version 2 (version 1 still accepted). See ``docs/protocol.md``."""

from .protocol import (
    ERROR_CODES, MAX_LINE_BYTES, MAX_SAFE_INTEGER, MIN_PROTOCOL_VERSION, PROTOCOL_VERSION,
    SHM_PREFIX, SOCKET_ENV, MessageReader, ProtocolError, accepts, buffer_fits, decode, encode,
    negotiate, validate,
)
from .shm import MappedBuffer
from .worker import Job, Worker, WorkerError, serve

__all__ = [
    "ERROR_CODES", "MAX_LINE_BYTES", "MAX_SAFE_INTEGER", "MIN_PROTOCOL_VERSION",
    "PROTOCOL_VERSION", "SHM_PREFIX", "SOCKET_ENV", "Job", "MappedBuffer", "MessageReader",
    "ProtocolError", "Worker", "WorkerError", "accepts", "buffer_fits", "decode", "encode",
    "negotiate", "serve", "validate",
]
