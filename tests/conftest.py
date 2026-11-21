import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point cards, tape and runs at a temp folder so tests never touch real data."""
    from wordless import config, gemini
    monkeypatch.setattr(config, "CARDS", tmp_path / "cards")
    monkeypatch.setattr(config, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(config, "TAPE", tmp_path / "tape")
    monkeypatch.setattr(config, "VIDEO_DIRS", [tmp_path / "videos"])
    monkeypatch.setattr(config, "DECISIONS_MIN_GAP_S", 0.0)
    monkeypatch.setattr(gemini, "tape", gemini.Tape(tmp_path / "tape"))
    (tmp_path / "videos").mkdir()
    return tmp_path


@pytest.fixture
def fake_api(sandbox, monkeypatch):
    import fake_gemini
    srv, url = fake_gemini.start()
    monkeypatch.setenv("GEMINI_BASE_URL", url)
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("WORDLESS_TAPE", "live")
    fake_gemini.calls.update(decisions=0, generate=0, bad=[])
    fake_gemini.faults.update(decisions_503=0, image_no_image=0)
    yield fake_gemini
    srv.shutdown()
