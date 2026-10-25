"""Unit tests must not download tokenizer assets or depend on their local cache."""
import pytest


@pytest.fixture(autouse=True)
def offline_tokenizer(monkeypatch):
    monkeypatch.setattr('career_pipeline.providers.model_encoding', lambda model: None)
