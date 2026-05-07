# SPDX-License-Identifier: MIT
"""Chrome native messaging protocol: length-prefixed JSON over stdin/stdout."""

from __future__ import annotations

import json
import struct
import sys
from typing import IO


def read_message(stream: IO[bytes] | None = None) -> dict:
    """Read a single native message from stdin (or the given binary stream)."""
    inp = stream if stream is not None else sys.stdin.buffer
    raw_length = inp.read(4)
    if len(raw_length) < 4:
        raise EOFError("no message (stdin closed)")
    length = struct.unpack("<I", raw_length)[0]
    if length > 1024 * 1024:
        raise ValueError(f"message too large: {length} bytes")
    data = inp.read(length)
    if len(data) < length:
        raise EOFError(f"truncated message: expected {length}, got {len(data)}")
    return json.loads(data)


def write_message(msg: dict, stream: IO[bytes] | None = None) -> None:
    """Write a single native message to stdout (or the given binary stream)."""
    out = stream if stream is not None else sys.stdout.buffer
    data = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    out.write(struct.pack("<I", len(data)))
    out.write(data)
    out.flush()
