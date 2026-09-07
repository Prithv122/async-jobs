import sys

from asyncjobs import cli


def test_main_invokes_uvicorn_with_parsed_args(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(sys, "argv", ["async-jobs", "--host", "0.0.0.0", "--port", "9000"])

    cli.main()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("asyncjobs.main:app",)
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 9000
    assert kwargs["reload"] is False


def test_main_uses_defaults_when_no_args_given(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: calls.append((a, kw)))
    monkeypatch.setattr(sys, "argv", ["async-jobs"])

    cli.main()

    _, kwargs = calls[0]
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8000
