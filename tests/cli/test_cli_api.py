"""``antidetect api ...``: token, examples and the headless server."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from antidetect.cli.main import main
from tests.api.conftest import Client, free_port


def test_token_is_stable_and_can_be_rotated(cli_env, capsys) -> None:
    assert main(["api", "token"]) == 0
    first = capsys.readouterr().out.strip()
    assert first.startswith("ad_") and len(first) >= 40
    main(["api", "token"])
    assert capsys.readouterr().out.strip() == first
    assert main(["api", "token", "--rotate"]) == 0
    rotated = capsys.readouterr().out.strip()
    assert rotated != first and rotated.startswith("ad_")
    main(["api", "token"])
    assert capsys.readouterr().out.strip() == rotated


def test_examples_are_filled_in_with_this_machines_address_and_token(cli_env, capsys) -> None:
    main(["api", "token"])
    token = capsys.readouterr().out.strip()
    assert main(["api", "examples"]) == 0
    out = capsys.readouterr().out
    for title in ("Python · Playwright", "Node.js · Puppeteer", "Python · Selenium", "curl"):
        assert title in out
    assert "http://127.0.0.1:47831/v1" in out and token in out
    assert "pip install requests playwright" in out and "npm install puppeteer-core" in out


def test_one_example_is_printed_bare_so_it_can_be_redirected_into_a_file(cli_env, capsys) -> None:
    assert main(["api", "examples", "playwright"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("import requests") and "=====" not in out
    compile(out, "example.py", "exec")                               # a valid script


def test_every_python_example_is_valid_python(cli_env, capsys) -> None:
    for kind in ("playwright", "selenium"):
        main(["api", "examples", kind])
        compile(capsys.readouterr().out, f"{kind}.py", "exec")


def test_an_unknown_example_is_refused(cli_env) -> None:
    with pytest.raises(SystemExit):
        main(["api", "examples", "cobol"])


def test_serve_says_so_when_the_port_is_taken(cli_env, capsys) -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        assert main(["api", "serve", "--port", str(taken.getsockname()[1])]) == 1
    assert "already in use" in capsys.readouterr().err


def test_serve_refuses_an_unusable_port(cli_env, capsys) -> None:
    assert main(["api", "serve", "--port", "80"]) == 1
    assert "between 1024 and 65535" in capsys.readouterr().err


def test_serve_runs_headless_answers_requests_and_stops_cleanly(cli_env) -> None:
    port = free_port()
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}
    server = subprocess.Popen(
        [sys.executable, "-m", "antidetect", "api", "serve", "--port", str(port)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        header = [server.stdout.readline() for _ in range(2)]
        assert header[0].strip() == f"Antidetect API: http://127.0.0.1:{port}"
        token = header[1].split()[-1]
        client = Client(port, token)
        assert client.get("/v1/status")[0] == 200
        assert client.get("/v1/status", token="ad_wrong")[0] == 401
        status, profile, _ = client.post("/v1/profiles", {"name": "headless", "geo_auto": False})
        assert status == 201
        assert client.post(f"/v1/profiles/{profile['id']}/start")[1]["status"] == "running"
        assert client.post(f"/v1/profiles/{profile['id']}/stop")[1]["status"] == "stopped"
        server.send_signal(signal.SIGTERM)
        assert server.wait(timeout=20) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))                               # the port was released
