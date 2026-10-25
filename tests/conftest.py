"""Unit tests must not download tokenizer assets or depend on their local cache."""
import pytest


@pytest.fixture(autouse=True)
def offline_tokenizer(monkeypatch):
    monkeypatch.setattr('career_pipeline.providers.model_encoding', lambda model: None)


@pytest.fixture(autouse=True)
def block_paid_network(monkeypatch):
    """A regression test must never fall through to a real model request.

    SDK MockTransport tests still work; actual HTTP transports fail immediately.
    """
    def blocked(*args, **kwargs):
        raise AssertionError('Network disabled in tests; use a recorded or synthetic transport')
    monkeypatch.setattr('httpx.HTTPTransport.handle_request', blocked)
    monkeypatch.setattr('httpx.AsyncHTTPTransport.handle_async_request', blocked)
