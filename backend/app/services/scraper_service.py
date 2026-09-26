"""
Hyperclients — Google Maps Scraper Service

Wraps the google-maps-scraper binary via subprocess.
Handles temp file management, timeout, CSV parsing, and error recovery.
"""

import asyncio
import csv
import json
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_scraper_path() -> str:
    """Resolve the scraper binary path from config."""
    settings = get_settings()
    path = settings.gmaps_scraper_path
    
    # Convert to Path object for easier handling
    path_obj = Path(path)
    
    # Check if path exists as-is first
    if path_obj.exists():
        return str(path_obj.resolve())
    
    # Try relative to current working directory
    cwd_path = Path.cwd() / path_obj
    if cwd_path.exists():
        return str(cwd_path.resolve())
    
    # Try relative to the backend directory
    backend_dir = Path(__file__).parent.parent.parent
    backend_path = backend_dir / path_obj
    if backend_path.exists():
        return str(backend_path.resolve())
    
    # On Windows, try with .exe extension
    if os.name == "nt":
        exe_path = path if str(path).endswith(".exe") else f"{path}.exe"
        exe_path_obj = Path(exe_path)
        if exe_path_obj.exists():
            return str(exe_path_obj.resolve())
        
        # Try with .exe in other locations
        cwd_exe = Path.cwd() / exe_path
        if cwd_exe.exists():
            return str(cwd_exe.resolve())
        
        backend_exe = backend_dir / exe_path
        if backend_exe.exists():
            return str(backend_exe.resolve())
    
    # Return original path and let FileNotFoundError handle it
    return path


class _CsvRowCounter:
    """Incremental row counter for a CSV that is still being written.

    Reads only the bytes appended since the last call (the old full re-read
    every 0.5s per shard blocked the event loop for every other request)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.offset = 0
        self.lines = 0
        self._partial = b""

    def count(self) -> int:
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                chunk = f.read()
        except OSError:
            return max(0, self.lines - 1)
        if chunk:
            self.offset += len(chunk)
            data = self._partial + chunk
            parts = data.split(b"\n")
            self._partial = parts.pop()  # last piece may be an unfinished line
            self.lines += sum(1 for line in parts if line.strip())
        return max(0, self.lines - 1)  # minus the header


def _gmaps_tuning() -> dict:
    """Resolve speed tunables from Settings with env fallback.

    Keeps backwards compat with the legacy GMAPS_CONCURRENCY env var while
    allowing full tuning via typed Settings (which also read env).
    """
    try:
        settings = get_settings()
    except Exception:
        settings = None  # type: ignore[assignment]

    def _int_env(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                pass
        if settings is not None:
            try:
                return max(1, int(getattr(settings, name.lower(), default) or default))
            except (TypeError, ValueError):
                pass
        return default

    concurrency = _int_env("GMAPS_CONCURRENCY", 16)
    workers = _int_env("GMAPS_WORKERS", 4)
    depth = _int_env("GMAPS_DEPTH", 1)
    soft = _int_env("GMAPS_SOFT_DEADLINE_SECONDS", 55)
    timeout = _int_env("GMAPS_TIMEOUT_SECONDS", 70)
    total_concurrency = _int_env("GMAPS_TOTAL_CONCURRENCY", 32)
    try:
        stagger = float((os.environ.get("GMAPS_STAGGER_SECONDS", "").strip()
                         or (getattr(settings, "gmaps_stagger_seconds", 2.0) if settings else 2.0)
                         or 2.0))
    except ValueError:
        stagger = 2.0
    stagger = max(0.0, min(stagger, 10.0))
    exit_inactivity = (os.environ.get("GMAPS_EXIT_INACTIVITY", "").strip()
                       or (getattr(settings, "gmaps_exit_inactivity", "12s") if settings else "12s")
                       or "12s")
    shard_inactivity = (os.environ.get("GMAPS_SHARD_INACTIVITY", "").strip()
                        or (getattr(settings, "gmaps_shard_inactivity", "45s") if settings else "45s")
                        or "45s")
    return {
        "concurrency": concurrency,
        "total_concurrency": total_concurrency,
        "stagger": stagger,
        "shard_inactivity": shard_inactivity,
        "workers": workers,
        "depth": depth,
        "soft_deadline": soft,
        "timeout": timeout,
        "exit_inactivity": exit_inactivity,
    }


def _shard_queries(lines: list[str], workers: int) -> list[list[str]]:
    """Round-robin shard queries across workers for even coverage."""
    workers = max(1, min(workers, len(lines)))
    shards: list[list[str]] = [[] for _ in range(workers)]
    for i, q in enumerate(lines):
        shards[i % workers].append(q)
    return [s for s in shards if s]


def _unique_rows_in(output_file: str) -> int:
    """Unique businesses in a CSV that is still being written (0 on error)."""
    try:
        return len(_parse_csv_results(output_file, 1_000_000, quiet=True))
    except Exception:  # noqa: BLE001 - partial/locked file: check again next tick
        return 0


def _business_key(r: dict) -> str:
    key = (r.get("google_key") or "").strip().lower()
    return key or (r.get("business_name") or "").strip().lower()


def _dedupe_businesses(results: list[dict]) -> list[dict]:
    """Drop duplicates across parallel shards (first wins)."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        key = _business_key(r)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


async def run_maps_scraper(
    query: str | list[str],
    max_results: int = 50,
    timeout_seconds: int = 300,
    depth: int = 1,
    soft_deadline_seconds: int | None = None,
    on_progress=None,
    concurrency: int | None = None,
    exit_inactivity: str | None = None,
    stop_event=None,
    should_cancel=None,
) -> list[dict]:
    """
    Run the google-maps-scraper binary and return parsed results.

    The process is stopped as soon as the CSV holds `max_results` UNIQUE
    businesses (the Go binary has no result cap of its own: 5 query variants
    x ~20 places would otherwise scrape 80-100 rows for a 20-lead request),
    or as soon as `should_cancel()` returns True.

    Args:
        query: Search query, or list of queries (one per line in the input
            file — the Go binary schedules them as parallel jobs).
        max_results: Maximum number of results to return
        timeout_seconds: Max time to wait for the scraper process
        depth: Number of pages to scrape (1 = fast, 3 = thorough)
        soft_deadline_seconds: After this many seconds, stop as soon as we
            already have >= max_results rows in the CSV (avoids waiting for
            inactivity timeout when the target is met).
        on_progress: Optional sync callback(count) invoked ~1/s while running.

    Returns:
        List of business dicts parsed from the CSV output.
        Returns partial results if available on timeout.
    """
    scraper_path = _get_scraper_path()
    run_id = str(uuid.uuid4())[:8]

    # Create temp files for input and output
    tmp_dir = tempfile.mkdtemp(prefix="hyperclients_scraper_")
    input_file = os.path.join(tmp_dir, f"input_{run_id}.txt")
    output_file = os.path.join(tmp_dir, f"results_{run_id}.csv")

    try:
        # Write query(s) to input file — one per line
        if isinstance(query, (list, tuple)):
            lines = [str(q).strip() for q in query if str(q).strip()]
        else:
            lines = [query.strip()] if str(query).strip() else []
        if not lines:
            raise ValueError("run_maps_scraper: empty query")
        with open(input_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        tuning = _gmaps_tuning()
        if concurrency is None:
            concurrency = os.environ.get("GMAPS_CONCURRENCY", "").strip() or str(tuning["concurrency"])
        concurrency = str(concurrency)
        # Depth passed explicitly wins; otherwise use tuned fast default.
        # Load-more still passes depth=2 for thorough background fill.
        if exit_inactivity is None:
            exit_inactivity = tuning["exit_inactivity"]
        cmd = [
            scraper_path,
            "-input", input_file,
            "-results", output_file,
            "-exit-on-inactivity", exit_inactivity,
            "-depth", str(depth),
            "-c", str(concurrency),
        ]

        logger.info(f"[Scraper:{run_id}] Binary path: {scraper_path}")
        logger.info(f"[Scraper:{run_id}] Binary exists: {os.path.exists(scraper_path)}")
        logger.info(f"[Scraper:{run_id}] Queries: {len(lines)} | concurrency={concurrency}")
        logger.info(f"[Scraper:{run_id}] Starting: {' '.join(cmd)}")

        import subprocess

        cwd = None
        if os.name == "nt":
            scraper_dir = os.path.dirname(scraper_path)
            if scraper_dir and os.path.isdir(scraper_dir):
                cwd = scraper_dir

        # Output goes to files, not pipes: nobody reads a pipe while the
        # scraper runs, and a full 64KB pipe buffer would hang the process.
        out_log = open(output_file + ".stdout.log", "wb")
        err_log = open(output_file + ".stderr.log", "wb")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=out_log,
                stderr=err_log,
                cwd=cwd,
                env={**os.environ},
            )
        except (FileNotFoundError, PermissionError):
            out_log.close()
            err_log.close()
            raise
        row_counter = _CsvRowCounter(output_file)

        hard_deadline = time.time() + max(1, int(timeout_seconds))
        soft_deadline = (
            time.time() + max(1, int(soft_deadline_seconds))
            if soft_deadline_seconds
            else None
        )
        last_report = 0.0
        last_count = 0
        unique_checked_at = -1
        terminated_early = False

        while True:
            ret = proc.poll()
            if ret is not None:
                break
            now = time.time()
            if now >= hard_deadline:
                logger.warning(f"[Scraper:{run_id}] Hard timeout after {timeout_seconds}s — killing process")
                proc.kill()
                terminated_early = True
                break
            if should_cancel is not None:
                try:
                    _cancel = bool(should_cancel())
                except Exception:
                    _cancel = False
                if _cancel:
                    logger.info(f"[Scraper:{run_id}] Cancelled by user — stopping")
                    proc.terminate()
                    terminated_early = True
                    break
            count = row_counter.count()
            if count != last_count:
                last_count = count
            # Target met? Raw rows include businesses repeated across query
            # variants, so confirm on the de-duplicated set before stopping.
            if count >= max_results and count != unique_checked_at:
                unique_checked_at = count
                unique = await asyncio.to_thread(_unique_rows_in, output_file)
                if unique >= max_results:
                    logger.info(
                        f"[Scraper:{run_id}] Target met: {unique} unique businesses "
                        f"({count} rows) for {max_results} requested — stopping"
                    )
                    if on_progress:
                        try:
                            on_progress(max_results)
                        except Exception:
                            pass
                    proc.terminate()
                    terminated_early = True
                    break
            if on_progress and now - last_report >= 1.0:
                last_report = now
                try:
                    # Never show "Found 85/20": the request caps what is delivered.
                    on_progress(min(count, max_results))
                except Exception as cb_err:
                    logger.debug(f"[Scraper:{run_id}] on_progress error: {cb_err}")
            if soft_deadline and now >= soft_deadline and count >= max_results:
                logger.info(
                    f"[Scraper:{run_id}] Soft deadline hit with {count}/{max_results} rows — stopping early"
                )
                proc.terminate()
                terminated_early = True
                break
            if stop_event is not None:
                try:
                    _stop = stop_event.is_set()
                except Exception:
                    _stop = False
                if _stop:
                    logger.info(
                        f"[Scraper:{run_id}] Global target met by a sibling shard — stopping early"
                    )
                    proc.terminate()
                    terminated_early = True
                    break
            await asyncio.sleep(0.5)

        try:
            await asyncio.to_thread(proc.wait, 10)
        except subprocess.TimeoutExpired:
            proc.kill()
            await asyncio.to_thread(proc.wait)
        finally:
            out_log.close()
            err_log.close()

        def _read_log(path: str) -> str:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                os.remove(path)
                return data.decode(errors="replace")
            except OSError:
                return ""

        stdout = _read_log(output_file + ".stdout.log")
        stderr = _read_log(output_file + ".stderr.log")
        if stdout:
            logger.info(f"[Scraper:{run_id}] stdout: {stdout[:1000]}")
        if stderr:
            logger.warning(f"[Scraper:{run_id}] stderr: {stderr[:1000]}")
        logger.info(
            f"[Scraper:{run_id}] Process returned code: {proc.returncode}"
            + (" (early stop)" if terminated_early else "")
        )

        # Parse results (even on timeout, partial CSV may exist)
        results = _parse_csv_results(output_file, max_results)
        logger.info(f"[Scraper:{run_id}] Parsed {len(results)} results")

        # Quality logging
        if results:
            named = sum(1 for r in results if r.get("business_name"))
            with_website = sum(1 for r in results if r.get("website_url"))
            with_rating = sum(1 for r in results if r.get("rating") is not None)
            sample = results[0]
            logger.info(
                f"[Scraper:{run_id}] Quality: {named} named, {with_website} with website, "
                f"{with_rating} with rating. Sample: name='{sample.get('business_name')}', "
                f"cat='{sample.get('category')}', rating={sample.get('rating')}, "
                f"reviews={sample.get('total_reviews')}, web='{sample.get('website_url', '')[:40]}'"
            )

        return results

    except FileNotFoundError:
        logger.error(f"[Scraper:{run_id}] Binary not found at: {scraper_path}")
        logger.error(f"[Scraper:{run_id}] Absolute path would be: {Path(scraper_path).resolve()}")
        logger.error(f"[Scraper:{run_id}] Current working directory: {os.getcwd()}")
        logger.error(f"[Scraper:{run_id}] OS type: {os.name}")
        raise RuntimeError(f"Scraper binary not found at: {scraper_path}")
    except PermissionError:
        logger.error(f"[Scraper:{run_id}] Permission denied: {scraper_path}")
        logger.error(f"[Scraper:{run_id}] File mode: {oct(os.stat(scraper_path).st_mode) if os.path.exists(scraper_path) else 'N/A'}")
        raise RuntimeError(f"Scraper binary is not executable: {scraper_path}")
    except Exception as e:
        logger.error(f"[Scraper:{run_id}] Error: {type(e).__name__}: {str(e)}")
        # Try to return partial results if output file exists
        if os.path.exists(output_file):
            try:
                partial_results = _parse_csv_results(output_file, max_results)
                logger.warning(f"[Scraper:{run_id}] Returning {len(partial_results)} partial results")
                return partial_results
            except Exception as parse_err:
                logger.warning(f"[Scraper:{run_id}] Failed to parse partial results: {parse_err}")
        raise e
    finally:
        # Cleanup temp files
        _cleanup_temp_files(tmp_dir, input_file, output_file)


def _parse_csv_results(output_file: str, max_results: int, quiet: bool = False) -> list[dict]:
    """
    Parse the CSV output from google-maps-scraper.
    Returns up to `max_results` DISTINCT businesses (a place found by several
    query variants appears once), with normalized field names.
    """
    if not os.path.exists(output_file):
        logger.warning(f"Output file does not exist: {output_file}")
        raise RuntimeError("Scraper returned no data: output CSV missing.")
    
    if os.path.getsize(output_file) == 0:
        logger.warning(f"Output file is completely empty: {output_file}")
        # Try to read file content to see if there's an error message
        try:
            with open(output_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                logger.warning(f"Empty CSV content: '{content}'")
        except Exception as e:
            logger.error(f"Could not read empty CSV: {e}")
        raise RuntimeError("Scraper returned no data: output CSV empty.")

    results = []
    seen: set[str] = set()
    raw_count = 0
    try:
        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_count += 1
                if len(results) >= max_results:
                    continue # keep counting raw lines for logging
                business = _normalize_row(row)
                key = _business_key(business)
                if business.get("business_name") and key not in seen:
                    seen.add(key)
                    results.append(business)
        if not quiet:
            logger.info(f"CSV Parse: {raw_count} raw rows found, {len(results)} distinct businesses returned (max {max_results})")
    except Exception as e:
        logger.error(f"Failed to parse CSV: {e}")
        # Try to read raw content for debugging
        try:
            with open(output_file, "r", encoding="utf-8", errors="replace") as f:
                preview = f.read()[:500]
                logger.warning(f"Raw CSV preview: {preview}")
        except Exception as read_err:
            logger.warning(f"Could not read CSV content for debugging: {read_err}")
        raise RuntimeError(f"Failed to parse CSV output: {e}")

    return results


def _normalize_row(row: dict) -> dict:
    """
    Normalize a CSV row from google-maps-scraper output
    into our internal lead format.
    
    Actual CSV headers from the scraper source (entry.go CsvHeaders()):
      input_id, link, title, category, address, open_hours, popular_times,
      website, phone, plus_code, review_count, review_rating,
      reviews_per_rating, latitude, longitude, cid, status, descriptions,
      reviews_link, thumbnail, timezone, price_range, data_id, place_id,
      images, reservations, order_online, menu, owner, complete_address,
      about, user_reviews, user_reviews_extended, emails
    """
    # Normalize keys: strip whitespace, lowercase, replace spaces with underscores
    row = {k.strip().lower().replace(" ", "_"): v for k, v in row.items()}

    def safe_float(val: str | None, default: float | None = None) -> float | None:
        if not val:
            return default
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def safe_int(val: str | None, default: int = 0) -> int:
        if not val:
            return default
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return default

    def safe_json(val: str | None, default=None):
        if not val:
            return default if default is not None else []
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return default if default is not None else []

    # Map from EXACT scraper CSV headers to our internal schema
    title = (row.get("title") or "").strip()
    
    return {
        "google_key": row.get("place_id") or row.get("cid") or row.get("input_id", ""),
        "business_name": title,
        "category": (row.get("category") or "").strip(),
        "full_address": (row.get("address") or "").strip(),
        "phone": (row.get("phone") or "").strip(),
        "email_found": (row.get("emails") or "").strip(),
        "website_url": (row.get("website") or "").strip(),
        "rating": safe_float(row.get("review_rating")),
        "total_reviews": safe_int(row.get("review_count"), 0),
        "google_maps_link": row.get("link", ""),
        "photos": safe_json(row.get("images"), []),
        "business_hours": safe_json(row.get("open_hours"), {}),
        "description": (row.get("descriptions") or row.get("description") or "").strip(),
    }


async def run_maps_scraper_parallel(
    query: str | list[str],
    max_results: int = 100,
    timeout_seconds: int | None = None,
    depth: int | None = None,
    soft_deadline_seconds: int | None = None,
    workers: int | None = None,
    on_progress=None,
    should_cancel=None,
) -> list[dict]:
    """Run N Go scraper processes in parallel, each with a query shard.

    This is the 10x path for 100-leads-in-~60s: a single Go process fans
    variants via -c, but one slow query still blocks the whole CSV. Sharding
    into 2-4 processes isolates slow queries and multiplies throughput.

    Fast-first: depth=1 in the hot path. Website/email deep analysis is
    on-demand (POST /api/leads/{id}/analyze-website), never blocking here.

    Falls back to single-process run_maps_scraper when only 1 query/worker.
    """
    import math

    if isinstance(query, (list, tuple)):
        lines = [str(q).strip() for q in query if str(q).strip()]
    else:
        lines = [str(query).strip()] if str(query).strip() else []
    if not lines:
        raise ValueError("run_maps_scraper_parallel: empty query")

    tuning = _gmaps_tuning()
    if timeout_seconds is None:
        timeout_seconds = tuning["timeout"]
    if depth is None:
        depth = tuning["depth"]
    if soft_deadline_seconds is None:
        soft_deadline_seconds = tuning["soft_deadline"]
    # Evidence-based default from 5 live VPS runs against Google Maps:
    #   * 4 fleets x -c8..12  -> late starters throttled to 0 rows (30-53 leads)
    #   * 1 fleet  x -c48      -> nearly everything blocked (1 lead / 90s)
    #   * 1 fleet  x -c24      -> sweet spot (86 leads / 90s, no mass blocks)
    # So: ONE browser fleet, -c16 (small) / -c24 (large), plus a serial
    # second pass for stragglers. Sharding stays for explicit workers=N.
    if workers is None:
        workers = 1
    workers = max(1, min(workers, len(lines), 4))

    t0 = time.time()
    if workers <= 1 or len(lines) <= 1:
        single_c = 16 if max_results <= 20 else 24
        first = await run_maps_scraper(
            query=lines,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
            depth=depth,
            soft_deadline_seconds=soft_deadline_seconds,
            on_progress=on_progress,
            concurrency=single_c,
            should_cancel=should_cancel,
        )
        got = _dedupe_businesses(first or [])
        # Serial second pass in the SAME fleet (no new concurrent burst):
        # picks up queries Google slow-rolled the first time around.
        second_budget = int(timeout_seconds + 15 - (time.time() - t0))
        if len(got) < max_results and second_budget >= 20 and not _cancel_requested(should_cancel):
            need = max_results - len(got)
            logger.info(
                f"[Scraper] SECOND-PASS: have {len(got)}/{max_results}, "
                f"retrying all queries for +{need} with {second_budget}s"
            )
            try:
                extra = await run_maps_scraper(
                    query=lines,
                    max_results=need,
                    timeout_seconds=second_budget,
                    depth=depth,
                    soft_deadline_seconds=min(int(soft_deadline_seconds or 65), second_budget),
                    on_progress=on_progress,
                    concurrency=single_c,
                    should_cancel=should_cancel,
                )
                got = _dedupe_businesses(got + (extra or []))[:max_results]
            except Exception as e:
                logger.warning(f"[Scraper] second pass failed: {e}")
        logger.info(
            f"[Scraper] SINGLE done: {len(got)}/{max_results} in {time.time() - t0:.1f}s"
        )
        return got

    shards = _shard_queries(lines, workers)
    per_worker_max = max(10, math.ceil(max_results / len(shards)) + 5)
    # Split the TOTAL tab budget across shards: 4 shards on a 32 budget ->
    # -c 8 each (was -c 24 each = 96 tabs, which OOMs/blocks a 4vCPU box).
    per_worker_c = max(6, min(16, int(tuning["total_concurrency"]) // max(1, len(shards))))
    stagger = float(tuning.get("stagger", 2.0) or 0.0)
    run_id = str(uuid.uuid4())[:8]
    logger.info(
        f"[Scraper:{run_id}] PARALLEL x{len(shards)} | total_queries={len(lines)} "
        f"| max={max_results} (per-worker {per_worker_max}) | depth={depth} "
        f"| per-worker -c {per_worker_c} (total ~{per_worker_c * len(shards)}) "
        f"| stagger={stagger}s | timeout={timeout_seconds}s soft={soft_deadline_seconds}s"
    )

    # Aggregate progress across shards so the UI shows a single x/100 counter.
    # When the GLOBAL target is met, all sibling workers stop immediately
    # instead of each filling its own per-worker quota.
    t0 = time.time()
    counts = [0] * len(shards)
    last_report = [0.0]
    stop_event = asyncio.Event()

    def _make_cb(idx: int):
        def _cb(n: int) -> None:
            counts[idx] = max(0, int(n or 0))
            total = sum(counts)
            if total >= max_results and not stop_event.is_set():
                stop_event.set()
            if on_progress is None:
                return
            now = time.time()
            if now - last_report[0] >= 1.0:
                last_report[0] = now
                try:
                    on_progress(total)
                except Exception as cb_err:
                    logger.debug(f"[Scraper:{run_id}] parallel on_progress error: {cb_err}")
        return _cb

    # Throttled shards must WAIT OUT a Google cooldown (45s inactivity),
    # not suicide after 12s like single runs may.
    shard_inactivity = str(tuning.get("shard_inactivity", "45s"))

    async def _one(shard: list[str], idx: int) -> list[dict]:
        try:
            if stagger > 0 and idx > 0:
                await asyncio.sleep(stagger * idx)
            return await run_maps_scraper(
                query=shard,
                max_results=per_worker_max,
                timeout_seconds=timeout_seconds,
                depth=depth,
                soft_deadline_seconds=soft_deadline_seconds,
                on_progress=_make_cb(idx),
                concurrency=per_worker_c,
                exit_inactivity=shard_inactivity,
                stop_event=stop_event,
                should_cancel=should_cancel,
            )
        except Exception as e:
            logger.warning(f"[Scraper:{run_id}] shard {idx} failed ({len(shard)} queries): {e}")
            return []

    nested = await asyncio.gather(*(_one(s, i) for i, s in enumerate(shards)))
    merged: list[dict] = []
    for part in nested:
        merged.extend(part or [])
    deduped = _dedupe_businesses(merged)[:max_results]

    # Mop-up wave: shards Google throttled to 0 rows get ONE serial retry in a
    # single low-concurrency process. Allowed a small overrun past the main
    # timeout (UI already streams partials live, so users see 50+ in ~60s
    # while the tail completes by ~90s).
    elapsed = time.time() - t0
    failed_queries = [q for i, part in enumerate(nested) if not part for q in shards[i]]
    mop_budget = min(35, max(0, int(timeout_seconds + 15 - elapsed)))
    if (failed_queries and len(deduped) < max_results and mop_budget >= 25
            and not _cancel_requested(should_cancel)):
        need = max_results - len(deduped)
        logger.info(
            f"[Scraper:{run_id}] MOP-UP: {len(failed_queries)} queries from "
            f"{sum(1 for p in nested if not p)} empty shards, need {need}, budget {mop_budget}s"
        )
        try:
            extra = await run_maps_scraper(
                query=failed_queries,
                max_results=need,
                timeout_seconds=mop_budget,
                depth=depth,
                soft_deadline_seconds=min(int(soft_deadline_seconds or 55), mop_budget),
                concurrency=8,
                exit_inactivity=shard_inactivity,
                should_cancel=should_cancel,
            )
            deduped = _dedupe_businesses(deduped + (extra or []))[:max_results]
        except Exception as e:
            logger.warning(f"[Scraper:{run_id}] mop-up failed: {e}")

    logger.info(
        f"[Scraper:{run_id}] PARALLEL done: {sum(len(p) for p in nested)} raw "
        f"-> {len(deduped)} deduped (target {max_results}) in {time.time() - t0:.1f}s"
    )
    return deduped


def _cancel_requested(should_cancel) -> bool:
    try:
        return bool(should_cancel and should_cancel())
    except Exception:  # noqa: BLE001
        return False


def _cleanup_temp_files(tmp_dir: str, *files: str) -> None:
    """Remove temp files and directory."""
    for f in files:
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError as e:
            logger.debug(f"Temp file cleanup warning: {e}")
    try:
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
    except OSError as e:
        logger.debug(f"Temp dir cleanup warning: {e}")
