"""Docs hygiene: no long dashes, and every rate quoted in the docs exists in the generated RESULTS.md."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TEXT = [p for p in ROOT.rglob("*") if p.is_file() and p.suffix in {".py", ".md", ".html", ".yaml", ".yml", ".toml", ".sh"}
        and not any(part in {".venv", ".cache", "out", ".git", ".pytest_cache", ".ruff_cache"} for part in p.parts)]


@pytest.mark.parametrize("path", TEXT, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_em_or_en_dashes(path):
    bad = chr(0x2014), chr(0x2013)
    assert not any(b in path.read_text(errors="ignore") for b in bad)


RATE = re.compile(r"\d+% \[\d+-\d+\] \(\d+/\d+\)")


@pytest.mark.parametrize("doc", ["README.md", "docs/BEST_PRACTICES.md"])
def test_quoted_rates_come_from_results(doc):
    p = ROOT / doc
    res = ROOT / "docs" / "RESULTS.md"
    if not p.exists() or not res.exists():
        pytest.skip("doc or RESULTS.md not generated yet")
    results = res.read_text()
    missing = [m for m in RATE.findall(p.read_text()) if m not in results]
    assert not missing, missing
