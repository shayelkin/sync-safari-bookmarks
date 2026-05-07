"""Tests for the native messaging entry point."""

from __future__ import annotations

import io
import json
import plistlib
import struct
import sys
from pathlib import Path

import pytest

from host import main as host_main
from host import safari_bookmarks


def _make_plist(
    bookmark_bar: list[dict] | None = None,
    other: list[dict] | None = None,
) -> bytes:
    children: list[dict] = [
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "Title": "BookmarksBar",
            "WebBookmarkUUID": "BAR-UUID",
            "Children": bookmark_bar or [],
        },
        *(other or []),
    ]
    plist = {
        "WebBookmarkFileVersion": 1,
        "WebBookmarkType": "WebBookmarkTypeList",
        "Children": children,
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_BINARY)


def _encode_message(msg: dict) -> bytes:
    data = json.dumps(msg).encode("utf-8")
    return struct.pack("<I", len(data)) + data


def _decode_message(data: bytes) -> dict:
    length = struct.unpack("<I", data[:4])[0]
    return json.loads(data[4:4 + length])


class _FakeStdio:
    def __init__(self, data: bytes = b"") -> None:
        self.buffer = io.BytesIO(data)


@pytest.fixture
def host_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    """Redirect main's state file and Safari plist to tmp paths."""
    state_file = tmp_path / "state" / "state.json"
    plist_path = tmp_path / "Bookmarks.plist"
    plist_path.write_bytes(_make_plist())

    monkeypatch.setattr(host_main, "STATE_FILE", state_file)
    monkeypatch.setattr(
        host_main, "read_safari",
        lambda: safari_bookmarks.read(plist_path),
    )
    monkeypatch.setattr(
        host_main, "write_safari",
        lambda roots: safari_bookmarks.write(roots, plist_path),
    )
    return {"state_file": state_file, "plist": plist_path}


def _bookmark_dict(
    title: str, url: str, date: str = "2025-01-01T00:00:00+00:00"
) -> dict:
    return {"type": "bookmark", "title": title, "url": url, "date": date}


def test_handle_sync_merges_chrome_and_safari(host_env: dict[str, Path]) -> None:
    safari_bar = [{
        "WebBookmarkType": "WebBookmarkTypeLeaf",
        "WebBookmarkUUID": "S1",
        "URLString": "https://safari.example",
        "URIDictionary": {"title": "Safari Bm"},
    }]
    host_env["plist"].write_bytes(_make_plist(bookmark_bar=safari_bar))

    chrome = {
        "bookmark_bar": [_bookmark_dict("Chrome Bm", "https://chrome.example")],
        "other": [],
    }
    response = host_main._handle_sync(chrome)

    assert response["status"] == "ok"
    urls = {b["url"] for b in response["merged"]["bookmark_bar"]}
    assert urls == {"https://safari.example", "https://chrome.example"}
    assert host_env["state_file"].exists()


def test_handle_sync_records_deletion(host_env: dict[str, Path]) -> None:
    bm = _bookmark_dict("Old", "https://old.example")
    host_env["state_file"].parent.mkdir(parents=True, exist_ok=True)
    host_env["state_file"].write_text(
        json.dumps({"bookmark_bar": [bm], "other": []})
    )
    safari_bar = [{
        "WebBookmarkType": "WebBookmarkTypeLeaf",
        "WebBookmarkUUID": "S1",
        "URLString": "https://old.example",
        "URIDictionary": {"title": "Old"},
    }]
    host_env["plist"].write_bytes(_make_plist(bookmark_bar=safari_bar))
    chrome = {"bookmark_bar": [], "other": []}

    response = host_main._handle_sync(chrome)

    assert response["status"] == "ok"
    assert response["stats"]["deleted"] == 1
    other = response["merged"]["other"]
    rdb = [
        item for item in other
        if item["type"] == "folder"
        and item["title"] == "Recently Deleted Bookmarks"
    ]
    assert len(rdb) == 1
    assert {c["url"] for c in rdb[0]["children"]} == {"https://old.example"}


def test_handle_sync_replaces_existing_recently_deleted(
    host_env: dict[str, Path],
) -> None:
    bm_a = _bookmark_dict("A", "https://a.example")
    bm_b = _bookmark_dict("B", "https://b.example")
    host_env["state_file"].parent.mkdir(parents=True, exist_ok=True)
    host_env["state_file"].write_text(json.dumps({
        "bookmark_bar": [],
        "other": [bm_a, bm_b],
    }))
    other_entries = [
        {
            "WebBookmarkType": "WebBookmarkTypeLeaf",
            "WebBookmarkUUID": "U1",
            "URLString": "https://a.example",
            "URIDictionary": {"title": "A"},
        },
        {
            "WebBookmarkType": "WebBookmarkTypeLeaf",
            "WebBookmarkUUID": "U2",
            "URLString": "https://b.example",
            "URIDictionary": {"title": "B"},
        },
        {
            "WebBookmarkType": "WebBookmarkTypeList",
            "WebBookmarkUUID": "U3",
            "Title": "Recently Deleted Bookmarks",
            "Children": [{
                "WebBookmarkType": "WebBookmarkTypeLeaf",
                "WebBookmarkUUID": "U4",
                "URLString": "https://stale.example",
                "URIDictionary": {"title": "Stale"},
            }],
        },
    ]
    host_env["plist"].write_bytes(_make_plist(other=other_entries))
    # Chrome has dropped bm_b; Safari still has it → deletion is detected,
    # which should replace the stale Recently Deleted folder from Safari.
    chrome = {"bookmark_bar": [], "other": [bm_a]}

    response = host_main._handle_sync(chrome)

    rdb = [
        item for item in response["merged"]["other"]
        if item["type"] == "folder"
        and item["title"] == "Recently Deleted Bookmarks"
    ]
    assert len(rdb) == 1
    assert {c["url"] for c in rdb[0]["children"]} == {"https://b.example"}


def test_main_eof_exits_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", _FakeStdio(b""))
    monkeypatch.setattr(sys, "stdout", _FakeStdio())

    with pytest.raises(SystemExit) as exc:
        host_main.main()
    assert exc.value.code == 0


def test_main_unknown_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys, "stdin", _FakeStdio(_encode_message({"action": "nonsense"}))
    )
    fake_out = _FakeStdio()
    monkeypatch.setattr(sys, "stdout", fake_out)

    host_main.main()

    response = _decode_message(fake_out.buffer.getvalue())
    assert response["status"] == "error"
    assert "unknown action" in response["error"]


def test_main_sync_round_trip(
    host_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    msg = _encode_message({
        "action": "sync",
        "chrome_bookmarks": {
            "bookmark_bar": [_bookmark_dict("X", "https://x.example")],
            "other": [],
        },
    })
    monkeypatch.setattr(sys, "stdin", _FakeStdio(msg))
    fake_out = _FakeStdio()
    monkeypatch.setattr(sys, "stdout", fake_out)

    host_main.main()

    response = _decode_message(fake_out.buffer.getvalue())
    assert response["status"] == "ok"
    assert host_env["state_file"].exists()


def test_main_sync_failure_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> dict:
        raise RuntimeError("plist read failed")
    monkeypatch.setattr(host_main, "read_safari", boom)

    monkeypatch.setattr(
        sys, "stdin",
        _FakeStdio(_encode_message({"action": "sync", "chrome_bookmarks": {}})),
    )
    fake_out = _FakeStdio()
    monkeypatch.setattr(sys, "stdout", fake_out)

    host_main.main()

    response = _decode_message(fake_out.buffer.getvalue())
    assert response["status"] == "error"
    assert "plist read failed" in response["error"]
