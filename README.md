# sync-safari-bookmarks

A Chrome extension for a two-way bookmark sync between Chrome and Safari on macOS.

The extension uses a Python native-messaging host, to reads and writes
`~/Library/Safari/Bookmarks.plist`, as well as perform the actual merge.

The merge keeps the latest of conflicting bookmarks (by URL), unions everything new on either side,
and surfaces deletions in a `Recently Deleted Bookmarks` folder.

## Requirements

- macOS (Safari path is hard-coded to `~/Library/Safari/Bookmarks.plist`)
- Google Chrome
- Python ≥ 3.12, [`uv`](https://docs.astral.sh/uv/)

## Install

1. Clone this repository to you machine.
2. Initialize a Python venv:
   ```sh
   uv sync
   ```
3. Load the unpacked extension at [chrome://extensions](chrome://extensions) (enable Developer mode → Load unpacked →
   select the `extension/` directory from this repository).
4. Note the extension ID Chrome assigns, and use it to install  the native messaging host manifest:
   ```sh
   ./install.sh <chrome-extension-id>
   ```
5. In Chrome, click the extension's toolbar icon to trigger a sync.

## License

This software is made available under the terms of the [MIT license](LICENSE).
