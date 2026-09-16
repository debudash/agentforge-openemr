"""Test fixtures. No network, no model key: the model is scripted."""

import json
import os
from datetime import date
from pathlib import Path

# Settings are read at import time by the service; make the test environment explicit
# before any copilot module is imported.
os.environ.setdefault("COPILOT_SHARED_SECRET", "test-secret-do-not-use")
os.environ.setdefault("LANGSMITH_TRACING", "false")
# Pin the provider configuration so the developer's .env (which load_dotenv reads, but never
# overrides) cannot change what the tests assume. The key is never used: the model is scripted.
os.environ.update({
    "COPILOT_PROVIDER": "anthropic", "COPILOT_MODEL": "claude-sonnet-5",
    "COPILOT_ALLOWED_PROVIDERS": "anthropic", "COPILOT_ALLOWED_MODELS": "claude-sonnet-5",
    "COPILOT_ALLOWED_ENDPOINTS": "https://api.anthropic.com", "ANTHROPIC_API_KEY": "test-key-never-used",
})

import pytest  # noqa: E402

from copilot.config import Settings  # noqa: E402
from copilot.schemas import Chart  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "evals" / "stage1" / "fixtures" / "charts"
TODAY = date(2026, 9, 15)


def load_chart(name: str) -> Chart:
    return Chart.model_validate(json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8")))


@pytest.fixture
def chart101() -> Chart:
    return load_chart("pid101_hypertension_diabetes")


@pytest.fixture
def chart202() -> Chart:
    return load_chart("pid202_other_provider")


@pytest.fixture
def chart303() -> Chart:
    return load_chart("pid303_labs_failed")


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def today() -> date:
    return TODAY
