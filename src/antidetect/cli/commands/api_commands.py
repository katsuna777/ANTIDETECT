from __future__ import annotations

import signal
import threading
from typing import TYPE_CHECKING

from antidetect.api import ApiKey, ApiManager, ApiSettings, ApiStartError
from antidetect.api.examples import example, examples
from antidetect.api.reference import render_markdown
from antidetect.i18n import get_language

if TYPE_CHECKING:
    from argparse import Namespace

    from antidetect.container import Container


def cmd_serve(container: "Container", args: "Namespace") -> None:
    """Run the API without the window and stay here: the fingerprint layer lives in this process."""
    manager = ApiManager(container)
    if args.port is not None:
        manager.settings.set_port(args.port)
    try:
        manager.start()
    except ApiStartError as exc:
        raise ValueError(str(exc)) from exc
    print(f"Antidetect API: {manager.url}", flush=True)
    print(f"Token:          {manager.settings.token}", flush=True)
    print("Profiles started through the API stay protected while this window is open. Ctrl+C stops them and the API.", flush=True)
    stop = threading.Event()
    previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        stop.wait()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        manager.stop()
        for profile in container.profiles.list_profiles():
            if profile.status.value == "RUNNING" and container.profiles.is_protected(profile.id):
                container.profiles.stop_profile(profile.id)
                print(f"Stopped profile id={profile.id}", flush=True)


def cmd_token(container: "Container", args: "Namespace") -> None:
    manager = ApiManager(container)
    if args.rotate:
        print(manager.regenerate_token())
    else:
        print(manager.settings.token)


def cmd_examples(container: "Container", args: "Namespace") -> None:
    manager = ApiManager(container)
    url, token = manager.settings.url, manager.settings.token
    lang = args.lang or get_language()
    chosen = [example(args.kind, url, token, lang)] if args.kind else examples(url, token, lang)
    for index, item in enumerate(chosen):
        if len(chosen) > 1:
            print(f"{'' if index == 0 else chr(10)}# ===== {item.title}  ({item.filename}) =====")
            if item.install:
                print(f"# {item.install}")
        print(item.code, end="" if item.code.endswith("\n") else "\n")


def cmd_docs(container: "Container", args: "Namespace") -> None:
    """The whole reference (methods, types, errors) as Markdown; the same text the app shows."""
    print(render_markdown(args.lang or get_language()), end="")


def _find_key(settings: ApiSettings, ref: str) -> ApiKey:
    keys = settings.keys()
    found = next((k for k in keys if k.id == ref), None) or next((k for k in keys if k.name.casefold() == ref.casefold()), None)
    if found is None:
        raise ValueError(f"No key “{ref}”. See: antidetect api keys")
    return found


def cmd_keys(container: "Container", args: "Namespace") -> None:
    manager = ApiManager(container)
    action = args.keys_action or "list"
    if action == "add":
        key = manager.add_key(args.name)
        print(f"Created key id={key.id} name={key.name!r}")
        print(key.token)
    elif action == "rename":
        key = manager.rename_key(_find_key(manager.settings, args.key).id, args.name)
        print(f"Renamed key id={key.id} to {key.name!r}")
    elif action == "regenerate":
        key = manager.regenerate_key(_find_key(manager.settings, args.key).id)
        print(f"New token for key id={key.id} name={key.name!r}; the old one stopped working")
        print(key.token)
    elif action == "remove":
        key = _find_key(manager.settings, args.key)
        manager.delete_key(key.id)
        print(f"Deleted key id={key.id} name={key.name!r}")
    else:
        rows = [("ID", "NAME", "KEY", "CREATED")]
        for key in manager.settings.keys():
            rows.append((key.id, key.name, key.token if args.show else key.masked(), key.created_at[:10]))
        widths = [max(len(r[i]) for r in rows) for i in range(4)]
        for row in rows:
            print("    ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
