"""
LeadForge AI — Google Maps Scraper Service

Wraps the google-maps-scraper binary via subprocess.
Handles temp file management, timeout, CSV parsing, and error recovery.
"""

import asyncio
import csv
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_scraper_path() -> str:
    """Resolve the scraper binary path from config."""
    settings = get_settings()
    path = settings.scraper_binary_path
    
    # Check if path exists as-is first
    if os.path.exists(path):
        return path
    
    # On Windows, try with .exe extension
    if os.name == "nt":
        exe_path = path if str(path).endswith(".exe") else f"{path}.exe"
        if os.path.exists(exe_path):
            return exe_path
    
    # Return original path and let FileNotFoundError handle it
    return path


async def run_maps_scraper(
    query: str,
    max_results: int = 50,
    timeout_seconds: int = 300,
) -> list[dict]:
    """
    Run the google-maps-scraper binary and return parsed results.

    Args:
        query: Search query (e.g., "plumbers in New York")
        max_results: Maximum number of results to return
        timeout_seconds: Max time to wait for the scraper process

    Returns:
        List of business dicts parsed from the CSV output.
        Returns partial results if available on timeout.
    """
    scraper_path = _get_scraper_path()
    run_id = str(uuid.uuid4())[:8]

    # Create temp files for input and output
    tmp_dir = tempfile.mkdtemp(prefix="leadforge_scraper_")
    input_file = os.path.join(tmp_dir, f"input_{run_id}.txt")
    output_file = os.path.join(tmp_dir, f"results_{run_id}.csv")

    try:
        # Write query to input file
        with open(input_file, "w", encoding="utf-8") as f:
            f.write(query + "\n")

        cmd = [
            scraper_path,
            "-input", input_file,
            "-results", output_file,
            "-exit-on-inactivity", "3m",
            "-depth", "3",
            "-c", "4",
            "-email"
        ]

        logger.info(f"[Scraper:{run_id}] Binary path: {scraper_path}")
        logger.info(f"[Scraper:{run_id}] Binary exists: {os.path.exists(scraper_path)}")
        logger.info(f"[Scraper:{run_id}] Starting: {' '.join(cmd)}")

        import subprocess
        
        def run_in_thread():
            # Don't set cwd in containerized environments - causes permission issues
            cwd = None
            if os.name == "nt":
                # Only set cwd on Windows if directory exists
                scraper_dir = os.path.dirname(scraper_path)
                if scraper_dir and os.path.isdir(scraper_dir):
                    cwd = scraper_dir
            
            return subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_seconds,
                cwd=cwd,
                env={**os.environ},
            )

        try:
            process = await asyncio.to_thread(run_in_thread)
            stdout = process.stdout.decode(errors='replace') if process.stdout else ""
            stderr = process.stderr.decode(errors='replace') if process.stderr else ""
            
            if stdout:
                logger.info(f"[Scraper:{run_id}] stdout: {stdout[:1000]}")
            if stderr:
                logger.warning(f"[Scraper:{run_id}] stderr: {stderr[:1000]}")
                
            # Log return code
            logger.info(f"[Scraper:{run_id}] Process returned code: {process.returncode}")
        except subprocess.TimeoutExpired as e:
            logger.warning(f"[Scraper:{run_id}] Timeout after {timeout_seconds}s")
            # Try to decode partial output
            stdout = e.stdout.decode(errors='replace') if e.stdout else ""
            stderr = e.stderr.decode(errors='replace') if e.stderr else ""
            if stdout:
                logger.info(f"[Scraper:{run_id}] Partial stdout: {stdout[:500]}")
            if stderr:
                logger.warning(f"[Scraper:{run_id}] Partial stderr: {stderr[:500]}")

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

    except FileNotFoundError as e:
        logger.error(f"[Scraper:{run_id}] Binary not found at: {scraper_path}")
        logger.error(f"[Scraper:{run_id}] Absolute path would be: {Path(scraper_path).resolve()}")
        logger.error(f"[Scraper:{run_id}] Current working directory: {os.getcwd()}")
        logger.error(f"[Scraper:{run_id}] OS type: {os.name}")
        raise RuntimeError(f"Scraper binary not found at: {scraper_path}")
    except PermissionError as e:
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
            except Exception:
                pass
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
        raise RuntimeError(f"Scraper returned no data: output CSV missing.")
    
    if os.path.getsize(output_file) == 0:
        logger.warning(f"Output file is completely empty: {output_file}")
        # Try to read file content to see if there's an error message
        try:
            with open(output_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
                logger.warning(f"Empty CSV content: '{content}'")
        except Exception as e:
            logger.error(f"Could not read empty CSV: {e}")
        raise RuntimeError(f"Scraper returned no data: output CSV empty.")

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
        except Exception:
            pass
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


def _cleanup_temp_files(tmp_dir: str, *files: str) -> None:
    """Remove temp files and directory."""
    for f in files:
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError:
            pass
    try:
        if os.path.exists(tmp_dir):
            os.rmdir(tmp_dir)
    except OSError:
        pass
