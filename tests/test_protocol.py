# SPDX-License-Identifier: MIT
"""Tests for native messaging protocol framing."""

from __future__ import annotations

import io
import struct

import pytest

from host.protocol import read_message, write_message


def _make_message(data: bytes) -> bytes:
    return struct.pack("<I", len(data)) + data


def test_roundtrip() -> None:
    msg = {"action": "sync", "data": [1, 2, 3]}
    buf = io.BytesIO()
    write_message(msg, buf)
    buf.seek(0)
    assert read_message(buf) == msg


def test_empty_object() -> None:
    buf = io.BytesIO()
    write_message({}, buf)
    buf.seek(0)
    assert read_message(buf) == {}


def test_eof_raises() -> None:
    buf = io.BytesIO(b"")
    with pytest.raises(EOFError):
        read_message(buf)


def test_truncated_length() -> None:
    buf = io.BytesIO(b"\x01\x00")
    with pytest.raises(EOFError):
        read_message(buf)


def test_truncated_body() -> None:
    buf = io.BytesIO(struct.pack("<I", 100) + b"short")
    with pytest.raises(EOFError):
        read_message(buf)


def test_message_too_large() -> None:
    buf = io.BytesIO(struct.pack("<I", 2 * 1024 * 1024))
    with pytest.raises(ValueError, match="too large"):
        read_message(buf)


def test_multiple_messages() -> None:
    buf = io.BytesIO()
    write_message({"a": 1}, buf)
    write_message({"b": 2}, buf)
    buf.seek(0)
    assert read_message(buf) == {"a": 1}
    assert read_message(buf) == {"b": 2}
