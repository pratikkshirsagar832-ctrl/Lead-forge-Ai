"""Google Maps delivers exactly what was asked for.

The Go scraper has no result cap: 5 query variants x ~20 places made a
20-lead request scrape 80-100 businesses (and wait ~65s for the soft
deadline) before the extra rows were thrown away. The runner must stop the
process the moment it holds N UNIQUE businesses, and stop on a user cancel.
"""
import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import scraper_service  # noqa: E402

_real_sleep = asyncio.sleep


class _FakeScraper:
    """Stands in for the Go binary: every poll() appends a few CSV rows (with
    businesses repeated across query variants) until it is terminated."""

    instances: list["_FakeScraper"] = []

    def __init__(self, cmd, **_kwargs):
        self.results = cmd[cmd.index("-results") + 1]
        self.rows_written = 0
        self.returncode = None
        with open(self.results, "w", encoding="utf-8") as f:
            f.write("title,cid\n")
        _FakeScraper.instances.append(self)

    def poll(self):
        if self.returncode is None and self.rows_written < 200:
            with open(self.results, "a", encoding="utf-8") as f:
                for _ in range(4):
                    # Every 3rd row repeats an earlier business (overlapping variants).
                    n = self.rows_written
                    biz = n - 2 if n % 3 == 2 else n
                    f.write(f"Business {biz},cid-{biz}\n")
                    self.rows_written += 1
        return self.returncode

    def terminate(self):
        self.returncode = -15

    kill = terminate

    def wait(self, timeout=None):
        return self.returncode


def _wire(monkeypatch):
    _FakeScraper.instances.clear()
    monkeypatch.setattr(subprocess, "Popen", _FakeScraper)
    monkeypatch.setattr(scraper_service, "_get_scraper_path", lambda: "fake-gmaps-scraper")
    monkeypatch.setattr(asyncio, "sleep", lambda *_a, **_k: _real_sleep(0))


def test_scraper_stops_at_exactly_n_unique_businesses(monkeypatch):
    _wire(monkeypatch)
    progress: list[int] = []
    results = asyncio.run(scraper_service.run_maps_scraper(
        query=["dentist in Pune", "best dentist in Pune"], max_results=20,
        timeout_seconds=60, on_progress=progress.append,
    ))
    assert len(results) == 20
    assert len({r["google_key"] for r in results}) == 20  # distinct, no repeats
    proc = _FakeScraper.instances[0]
    assert proc.returncode == -15  # stopped early, not run to inactivity/timeout
    assert proc.rows_written < 40  # nowhere near the 80-100 it used to scrape
    assert max(progress, default=0) <= 20  # never "Found 85/20"


def test_scraper_stops_when_the_user_cancels(monkeypatch):
    _wire(monkeypatch)
    results = asyncio.run(scraper_service.run_maps_scraper(
        query=["dentist in Pune"], max_results=100, timeout_seconds=60,
        should_cancel=lambda: _FakeScraper.instances[0].rows_written >= 8,
    ))
    proc = _FakeScraper.instances[0]
    assert proc.returncode == -15
    assert proc.rows_written == 8
    assert len(results) < 100


def test_csv_parse_counts_distinct_businesses(tmp_path):
    csv_file = tmp_path / "out.csv"
    csv_file.write_text("title,cid\nA,1\nB,2\nA,1\nC,3\n", encoding="utf-8")
    names = [r["business_name"] for r in scraper_service._parse_csv_results(str(csv_file), 3)]
    assert names == ["A", "B", "C"]
