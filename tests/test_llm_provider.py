"""The LLM factory selects the right provider and fails clearly."""
import pytest

from app.config import Settings
from app.services import llm as llm_module


def test_unknown_provider_raises_clear_error(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "get_settings",
        lambda: Settings.model_construct(chat_llm_provider="nope"),
    )
    llm_module.get_chat_model.cache_clear()
    with pytest.raises(RuntimeError, match="Unknown CHAT_LLM_PROVIDER 'nope'"):
        llm_module.get_chat_model()
    llm_module.get_chat_model.cache_clear()


def test_anthropic_without_key_raises(monkeypatch):
    monkeypatch.setattr(
        llm_module, "get_settings",
        lambda: Settings.model_construct(chat_llm_provider="anthropic", anthropic_api_key=None),
    )
    llm_module.get_chat_model.cache_clear()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm_module.get_chat_model()
    llm_module.get_chat_model.cache_clear()


def test_azure_openai_missing_config_raises(monkeypatch):
    # Azure needs key + endpoint + deployment; missing ones are named.
    # (Requires the package, since the import guard runs first.)
    pytest.importorskip("langchain_openai")
    monkeypatch.setattr(
        llm_module, "get_settings",
        lambda: Settings.model_construct(
            chat_llm_provider="azure_openai",
            azure_openai_api_key="k",
        ),
    )
    llm_module.get_chat_model.cache_clear()
    with pytest.raises(RuntimeError) as exc:
        llm_module.get_chat_model()
    assert "AZURE_OPENAI_ENDPOINT" in str(exc.value)
    assert "AZURE_OPENAI_DEPLOYMENT" in str(exc.value)
    llm_module.get_chat_model.cache_clear()


def test_ollama_builds_when_package_present(monkeypatch):
    pytest.importorskip("langchain_ollama")
    monkeypatch.setattr(
        llm_module,
        "get_settings",
        lambda: Settings.model_construct(chat_llm_provider="ollama"),
    )
    llm_module.get_chat_model.cache_clear()
    model = llm_module.get_chat_model()
    assert model.__class__.__name__ == "ChatOllama"
    llm_module.get_chat_model.cache_clear()


def test_extraction_defaults_to_anthropic(monkeypatch):
    monkeypatch.setattr(
        llm_module,
        "get_settings",
        lambda: Settings.model_construct(
            extraction_llm_provider="anthropic",
            anthropic_api_key="k",
        ),
    )
    llm_module.get_extraction_model.cache_clear()
    model = llm_module.get_extraction_model()
    assert model.__class__.__name__ == "ChatAnthropic"
    llm_module.get_extraction_model.cache_clear()
