import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cloudpilot.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOUDPILOT_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("CLOUDPILOT_LLM", "off")
    monkeypatch.delenv("NEO4J_URI", raising=False)
    monkeypatch.delenv("OPA_URL", raising=False)
    return Settings()


def has(binary: str) -> bool:
    return bool(shutil.which(binary))
