from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_study_sources_never_import_live_assistance():
    sources = [
        ROOT / "study_launcher.py",
        ROOT / "pokerlab" / "webapi.py",
        ROOT / "pokerlab" / "webapi_postflop.py",
        *sorted((ROOT / "study_app").rglob("*")),
    ]
    for source in sources:
        if source.is_file():
            text = source.read_text(encoding="utf-8").lower()
            assert "pokerlab.live" not in text, source


def test_live_package_is_not_shipped():
    assert not (ROOT / "pokerlab" / "live").exists()
