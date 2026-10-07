"""``antidetect browser``: which Chrome runs the profiles, and downloading one."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace

    from antidetect.container import Container

_SOURCE_TEXT = {
    "configured": "the browser you chose",
    "managed": "Chrome downloaded by the app",
    "auto": "Chrome installed on this computer",
    "none": "none found",
}


def _megabytes(count: int) -> str:
    return f"{count / 2 ** 20:.0f}"


def cmd_status(container: "Container", args: "Namespace") -> None:
    status = container.browsers.status()
    print(f"BROWSER  {_SOURCE_TEXT[status.source]}")
    print(f"  PATH:     {status.path or '-'}")
    print(f"  VERSION:  {status.version or '-'}")
    if status.downloaded:
        print("DOWNLOADED")
        for index, item in enumerate(status.downloaded):
            print(f"  {item.version}  {item.folder}{'  (in use)' if index == 0 and status.source == 'managed' else ''}")
    if status.source == "none":
        print("No Chrome was found. Get one with: antidetect browser download")
    elif status.source == "configured" and os.environ.get("ANTIDETECT_CHROMIUM_PATH"):
        print("ANTIDETECT_CHROMIUM_PATH is set and takes precedence over a downloaded Chrome.")


def cmd_check_update(container: "Container", args: "Namespace") -> None:
    release = container.browsers.update_available(args.channel)
    if release is None:
        print("The downloaded Chrome is up to date.")
        return
    print(f"Chrome {release.version} ({args.channel}) is available. Download it with: antidetect browser download")


def cmd_download(container: "Container", args: "Namespace") -> None:
    shown = {"last": -1}
    interactive = sys.stderr.isatty()

    def progress(done: int, total: int) -> None:
        percent = int(done * 100 / total) if total else 0
        step = percent if interactive else percent // 10 * 10
        if step == shown["last"]:
            return
        shown["last"] = step
        text = f"Downloading Chrome: {percent}%  ({_megabytes(done)} of {_megabytes(total)} MB)"
        print("\r" + text if interactive else text, end="" if interactive else "\n", file=sys.stderr, flush=True)

    release, installed = container.browsers.install_latest(args.channel, on_progress=progress)
    if interactive and shown["last"] >= 0:
        print(file=sys.stderr)
    if installed is None:
        print(f"Chrome {release.version} is already downloaded.")
    else:
        print(f"Chrome {installed.version} installed in {installed.folder}")
    if container.use_downloaded_browser():         # the user asked for the app's Chrome: it is used from now on
        print("Profiles now run on it (the browser path you had chosen was cleared).")
    status = container.browsers.status()
    print(f"Running profiles use: {_SOURCE_TEXT[status.source]} {status.version or ''}".rstrip())
    if status.source != "managed" and release is not None:
        print("A path set in ANTIDETECT_CHROMIUM_PATH takes precedence over the downloaded Chrome.")


def cmd_path(container: "Container", args: "Namespace") -> None:
    """Print only the path of the browser that runs the profiles (for scripts); exit 1 when there is none."""
    path = container.browsers.status().path
    if path is None:
        raise ValueError("No Chrome was found. Get one with: antidetect browser download")
    print(path)
