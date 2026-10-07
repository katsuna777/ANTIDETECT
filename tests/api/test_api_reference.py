"""The reference must describe exactly what the server does."""

from __future__ import annotations

import re

import pytest

from antidetect.api import reference as ref
from antidetect.api.server import _ROUTES


def _routes() -> set[tuple[str, str]]:
    found = set()
    for route in _ROUTES:
        path = route.pattern.pattern.removesuffix("/?$").replace(r"(\d+)", "{id}")
        found.add((route.method, path))
    return found


def test_every_route_is_documented_and_nothing_else_is():
    documented = {(e.method, e.path) for e in ref.all_endpoints()}
    assert documented == _routes()


def test_no_endpoint_is_described_twice():
    keys = [ref.endpoint_key(e.method, e.path) for e in ref.all_endpoints()]
    assert len(keys) == len(set(keys))


def test_all_texts_exist_in_both_languages():
    def texts():
        yield from (ref.INTRO, *ref.QUICKSTART, *ref.AUTH, *ref.CONVENTIONS, ref.TITLE, *(title for title, _ in ref.FLOW))
        for group in ref.GROUPS:
            yield group.title
            for e in group.endpoints:
                yield e.summary
                if e.desc != ("", ""):
                    yield e.desc
                for f in (*e.query, *e.body):
                    yield f.desc
        for model in ref.MODELS:
            yield model.intro
            yield from (f.desc for f in model.fields)
        yield from (meaning for _, _, meaning in ref.ERRORS)
        for tip in ref.TIPS:
            yield tip.title
            yield tip.text
        yield from ref.SECTION_TITLES.values()
        yield from ref.FIELD_HEADERS.values()
        yield from ref.LABELS.values()

    for en, ru in texts():
        assert en.strip() and ru.strip(), (en, ru)


def test_the_russian_text_is_not_a_copy_of_the_english_one():
    same = [en for en, ru in (ref.INTRO, *ref.QUICKSTART, *(t.text for t in ref.TIPS)) if en == ru]
    assert same == []


def test_the_examples_are_valid_json():
    import json

    for e in ref.all_endpoints():
        for sample in (e.request, e.response):
            if sample and "..." not in sample:
                json.loads(sample)


def test_every_documented_error_code_is_one_the_server_can_send():
    from antidetect.api import service

    server_codes = {code for _, _, code in service._ERRORS} | {
        "unauthorized", "forbidden_origin", "forbidden_host", "not_found", "method_not_allowed", "bad_json",
        "too_large", "internal_error", "connection_unavailable", "proxy_unreadable", "bad_request", "not_running",
    }
    assert {code for _, code, _ in ref.ERRORS} <= server_codes


def test_every_model_type_mentioned_is_defined():
    names = {m.name for m in ref.MODELS}
    for model in ref.MODELS:
        for f in model.fields:
            for word in re.findall(r"[A-Z][a-z]+", f.type):
                assert word in names, (model.name, f.name, word)
    for e in ref.all_endpoints():
        for word in re.findall(r"[A-Z][a-z]+", e.returns):
            assert word in names, (e.path, word)


@pytest.mark.parametrize("lang", ["en", "ru"])
def test_markdown_covers_everything(lang):
    text = ref.render_markdown(lang)
    for e in ref.all_endpoints():
        assert f"`{e.method} {e.path}`" in text
    for model in ref.MODELS:
        assert f"### {model.name}" in text
    for _, code, _ in ref.ERRORS:
        assert f"`{code}`" in text
    assert text.startswith("# ") and text.endswith("\n")


def test_the_committed_markdown_is_the_generated_one():
    """docs/API.md is generated (antidetect api docs --lang ru > docs/API.md); keep it in step."""
    from pathlib import Path

    docs = Path(__file__).resolve().parents[2] / "docs"
    for lang, name in (("ru", "API.md"), ("en", "API.en.md")):
        committed = (docs / name).read_text(encoding="utf-8")
        assert committed == ref.render_markdown(lang), f"docs/{name} is stale: run antidetect api docs --lang {lang} > docs/{name}"
