from __future__ import annotations

from app.nlp.config import get_nlp_settings


def test_nlp_settings_defaults(monkeypatch) -> None:
    monkeypatch.delenv("NLP_ENABLE_EMBEDDINGS", raising=False)
    monkeypatch.delenv("NLP_PROCESS_MIN_TEXT_LEN", raising=False)
    monkeypatch.delenv("NLP_TIMEOUT_MS", raising=False)

    settings = get_nlp_settings()

    assert settings.enable_embeddings is True
    assert settings.process_min_text_len == 3
    assert settings.timeout_ms == 2000


def test_nlp_settings_reads_llm_env(monkeypatch) -> None:
    monkeypatch.setenv("NLP_LLM_MODEL", "claude-test-model")
    monkeypatch.setenv("LLM_API_KEY", "sk-test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1/")

    settings = get_nlp_settings()

    assert settings.llm_model == "claude-test-model"
    assert settings.llm_api_key == "sk-test-key"
    assert settings.llm_base_url == "https://api.example.com/v1/"
