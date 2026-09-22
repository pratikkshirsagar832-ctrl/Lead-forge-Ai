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


def _count_csv_rows(output_file: str) -> int:
    """Best-effort count of data rows in a (possibly still-writer) CSV."""
    try:
        if not os.path.exists(output_file):
            return 0
        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            # First line is the header; count non-empty remaining lines.
            n = 0
            for line in f:
                if line.strip():
                    n += 1
            return max(0, n - 1)
    except OSError:
        return 0


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
    return {
        "concurrency": concurrency,
        "total_concurrency": total_concurrency,
        "stagger": stagger,
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


def _dedupe_businesses(results: list[dict]) -> list[dict]:
    """Drop duplicates across parallel shards (first wins)."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        key = (r.get("google_key") or "").strip().lower()
        if not key:
            key = (r.get("business_name") or "").strip().lower()
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
) -> list[dict]:
    """
    Run the google-maps-scraper binary and return parsed results.

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

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env={**os.environ},
            )
        except FileNotFoundError:
            raise
        except PermissionError:
            raise

        hard_deadline = time.time() + max(1, int(timeout_seconds))
        soft_deadline = (
            time.time() + max(1, int(soft_deadline_seconds))
            if soft_deadline_seconds
            else None
        )
        last_report = 0.0
        last_count = 0
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
            count = _count_csv_rows(output_file)
            if count != last_count:
                last_count = count
            if on_progress and now - last_report >= 1.0:
                last_report = now
                try:
                    on_progress(count)
                except Exception as cb_err:
                    logger.debug(f"[Scraper:{run_id}] on_progress error: {cb_err}")
            if soft_deadline and now >= soft_deadline and count >= max_results:
                logger.info(
                    f"[Scraper:{run_id}] Soft deadline hit with {count}/{max_results} rows — stopping early"
                )
                proc.terminate()
                terminated_early = True
                break
            await asyncio.sleep(0.5)

        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()

        stdout = stdout.decode(errors="replace") if stdout else ""
        stderr = stderr.decode(errors="replace") if stderr else ""
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


def _parse_csv_results(output_file: str, max_results: int) -> list[dict]:
    """
    Parse the CSV output from google-maps-scraper.
    Returns a list of business dicts with normalized field names.
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
    raw_count = 0
    try:
        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw_count += 1
                if len(results) >= max_results:
                    continue # keep counting raw lines for logging
                business = _normalize_row(row)
                if business.get("business_name"):
                    results.append(business)
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
    if workers is None:
        if max_results <= 20:
            workers = min(2, tuning["workers"])
        elif max_results <= 50:
            workers = min(3, tuning["workers"])
        else:
            workers = tuning["workers"]
    workers = max(1, min(workers, len(lines), 4))

    if workers <= 1 or len(lines) <= 1:
        return await run_maps_scraper(
            query=lines,
            max_results=max_results,
            timeout_seconds=timeout_seconds,
            depth=depth,
            soft_deadline_seconds=soft_deadline_seconds,
            on_progress=on_progress,
        )

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
    counts = [0] * len(shards)
    last_report = [0.0]

    def _make_cb(idx: int):
        def _cb(n: int) -> None:
            counts[idx] = max(0, int(n or 0))
            if on_progress is None:
                return
            now = time.time()
            if now - last_report[0] >= 1.0:
                last_report[0] = now
                try:
                    on_progress(sum(counts))
                except Exception as cb_err:
                    logger.debug(f"[Scraper:{run_id}] parallel on_progress error: {cb_err}")
        return _cb

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
            )
        except Exception as e:
            logger.warning(f"[Scraper:{run_id}] shard {idx} failed ({len(shard)} queries): {e}")
            return []

    nested = await asyncio.gather(*(_one(s, i) for i, s in enumerate(shards)))
    merged: list[dict] = []
    for part in nested:
        merged.extend(part or [])
    deduped = _dedupe_businesses(merged)[:max_results]
    logger.info(
        f"[Scraper:{run_id}] PARALLEL done: {sum(len(p) for p in nested)} raw "
        f"-> {len(deduped)} deduped (target {max_results})"
    )
    return deduped


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
