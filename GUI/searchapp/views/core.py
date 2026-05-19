# core.py — Shared state, concurrency helpers and download task runner.
# All other view modules import from here so there is a single source of truth
# for the executor, scheduler dict, slot semaphore, etc.

import os
import re
import sys
import time
import json
import threading
import atexit
import signal
import logging
import concurrent.futures
from typing import Any, Dict, List

from django.http import HttpRequest
from django.contrib import messages

from GUI.searchapp.api import get_api
from GUI.searchapp.api.base import Entries

from VibraVid.core.ui.tracker import download_tracker, context_tracker
from VibraVid.cli.run import execute_hooks


logger = logging.getLogger(__name__)


# ─── Webhook dedup ────────────────────────────────────────────────────────────

# Track recently processed webhooks to avoid duplicates (source, tmdbId) -> timestamp
_recent_webhooks: Dict[tuple, float] = {}
_recent_webhooks_lock = threading.Lock()
_WEBHOOK_DEDUP_WINDOW = 300  # 5 minutes


def _is_recent_webhook(tmdb_id, source=None, window_seconds=None, touch=True):
    """Return True if (source, tmdb_id) was processed in the last window_seconds."""
    if not tmdb_id:
        return False
    if window_seconds is None:
        window_seconds = _WEBHOOK_DEDUP_WINDOW
    now = time.time()
    key = (source, str(tmdb_id))
    with _recent_webhooks_lock:
        last_time = _recent_webhooks.get(key)
        if last_time and (now - last_time) < window_seconds:
            return True
        if touch:
            _recent_webhooks[key] = now
        # Clean old entries
        old_keys = [k for k, v in _recent_webhooks.items() if now - v > window_seconds]
        for k in old_keys:
            del _recent_webhooks[k]
        return False


def _mark_native_webhook_seen(tmdb_id, source: str):
    if not tmdb_id:
        return
    _is_recent_webhook(tmdb_id, source=source, window_seconds=_WEBHOOK_DEDUP_WINDOW, touch=True)


# ─── Download executor and scheduler ─────────────────────────────────────────

download_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=10, thread_name_prefix="DownloadWorker"
)
scheduled_downloads: Dict[str, Dict[str, Any]] = {}
scheduled_downloads_lock = threading.Lock()
cancelled_scheduled_downloads: set = set()

# Concurrency limiter
_download_slot_cond = threading.Condition()
_active_downloads = 0
_max_download_slots = 1


def set_max_download_slots(n: int) -> None:
    global _max_download_slots
    _max_download_slots = max(1, n)
    with _download_slot_cond:
        _download_slot_cond.notify_all()


def _acquire_download_slot() -> None:
    global _active_downloads
    with _download_slot_cond:
        while _active_downloads >= _max_download_slots:
            _download_slot_cond.wait()
        _active_downloads += 1


def _release_download_slot() -> None:
    global _active_downloads
    with _download_slot_cond:
        _active_downloads -= 1
        _download_slot_cond.notify()


# ─── Scheduler helpers ────────────────────────────────────────────────────────

def _add_scheduled_download(
    download_id: str,
    title: str,
    site: str,
    media_type: str = "Film",
    season: str = None,
    episodes: str = None,
) -> None:
    with scheduled_downloads_lock:
        scheduled_downloads[download_id] = {
            "id": download_id,
            "title": title,
            "site": site,
            "type": media_type,
            "season": season,
            "episodes": episodes,
            "scheduled_at": time.time(),
        }
        cancelled_scheduled_downloads.discard(download_id)


def _remove_scheduled_download(download_id: str) -> None:
    with scheduled_downloads_lock:
        scheduled_downloads.pop(download_id, None)
        cancelled_scheduled_downloads.discard(download_id)


def _cancel_scheduled_download(download_id: str) -> None:
    with scheduled_downloads_lock:
        cancelled_scheduled_downloads.add(download_id)
        scheduled_downloads.pop(download_id, None)


def _is_scheduled_cancelled(download_id: str) -> bool:
    with scheduled_downloads_lock:
        return download_id in cancelled_scheduled_downloads


def _get_scheduled_downloads() -> List[Dict[str, Any]]:
    with scheduled_downloads_lock:
        return sorted(
            list(scheduled_downloads.values()),
            key=lambda item: item.get("scheduled_at", 0),
        )


def _enrich_active_downloads_with_series(
    active_downloads: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach series_name for active TV downloads so GUI can show the parent series."""
    with scheduled_downloads_lock:
        scheduled_by_id = {k: dict(v) for k, v in scheduled_downloads.items()}

    enriched: List[Dict[str, Any]] = []
    for item in active_downloads:
        row = dict(item)
        media_type = str(row.get("type") or "").lower()

        if media_type in {"serie", "tv", "series", "anime"}:
            series_name = ""
            row_id = row.get("id")

            scheduled_info = scheduled_by_id.get(row_id)
            if scheduled_info:
                series_name = _extract_series_base_title(scheduled_info.get("title", ""))

            if not series_name:
                title = str(row.get("title") or "").strip()
                title_base = _extract_series_base_title(title)
                if title_base and title_base != title:
                    series_name = title_base

            if series_name:
                row["series_name"] = series_name

        enriched.append(row)

    return enriched


def _prune_scheduled_downloads(
    _active_downloads: List[Dict[str, Any]], history: List[Dict[str, Any]]
) -> None:
    history_ids = {item.get("id") for item in history if item.get("id")}
    now = time.time()
    max_age_seconds = 6 * 60 * 60

    with scheduled_downloads_lock:
        to_remove = []
        for download_id, item in scheduled_downloads.items():
            if download_id in history_ids:
                to_remove.append(download_id)
                continue
            if now - float(item.get("scheduled_at", now)) > max_age_seconds:
                to_remove.append(download_id)

        for download_id in to_remove:
            scheduled_downloads.pop(download_id, None)
            cancelled_scheduled_downloads.discard(download_id)


# ─── Series title helpers ─────────────────────────────────────────────────────

def _extract_series_base_title(raw_title: str) -> str:
    """Normalize title to a stable series base name (strip season/episode suffixes)."""
    title = str(raw_title or "").strip()
    if not title:
        return ""
    base = re.split(r"\s-\sS\d+(?:\sE[\d\-\*,]+)?", title, maxsplit=1, flags=re.IGNORECASE)[0]
    return base.strip()


def _same_series(title: str, series_base: str) -> bool:
    if not series_base:
        return False
    return _extract_series_base_title(title).casefold() == series_base.casefold()


# ─── Shutdown / signal handling ───────────────────────────────────────────────

def shutdown_downloads():
    """Shutdown downloads and kill processes on exit."""
    print("Shutting down downloads...")
    with scheduled_downloads_lock:
        scheduled_downloads.clear()
        cancelled_scheduled_downloads.clear()
    download_tracker.shutdown()
    download_executor.shutdown(wait=True)


def _submit_download_task(fn):
    """Submit a task to the download executor, recreating it if it was shutdown."""
    global download_executor
    try:
        return download_executor.submit(fn)
    except RuntimeError:
        try:
            download_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=10, thread_name_prefix="DownloadWorker"
            )
            return download_executor.submit(fn)
        except Exception as exc:
            print(f"[Error] Could not recreate download executor: {exc}")
            raise


atexit.register(shutdown_downloads)


def signal_handler(signum, frame):
    shutdown_thread = threading.Thread(target=shutdown_downloads, daemon=True)
    shutdown_thread.start()
    print("Running post-run hooks...")
    execute_hooks("post_run")
    print("Downloads shutdown started, exiting immediately...")
    os._exit(0)


if threading.current_thread() is threading.main_thread():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


# ─── Media helpers ────────────────────────────────────────────────────────────

def _media_item_to_display_dict(item: Entries, source_alias: str) -> Dict[str, Any]:
    """Convert Entries to template-friendly dictionary."""
    poster_url = item.poster if item.poster else "https://via.placeholder.com/300x450?text=Search"

    # Treat songs as 'movie' in the GUI so they show a direct Download button
    display_is_movie = bool(item.is_movie or (str(item.type or "").strip().lower() == "song"))

    result = {
        "display_title": item.name,
        "display_type": item.type.capitalize(),
        "source": source_alias.capitalize(),
        "source_alias": source_alias,
        "bg_image_url": poster_url,
        "is_movie": display_is_movie,
        "year": item.year,
    }

    result["payload_json"] = json.dumps({**item.__dict__, "is_movie": display_is_movie})
    return result


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


# ─── Core download runner ─────────────────────────────────────────────────────

def _run_download_in_thread(
    site: str,
    item_payload: Dict[str, Any],
    season: str = None,
    episodes: str = None,
    media_type: str = "Film",
    output_path: str = None,
    audio_format: str = None,
) -> "concurrent.futures.Future":
    """Run download in background thread. Returns a Future."""
    name = item_payload.get("name", "Unknown")
    if season and episodes:
        title = f"{name} - S{season} E{episodes}"
    elif season:
        title = f"{name} - S{season}"
    else:
        title = name

    download_id = f"{site}_{int(time.time())}_{hash(title) % 10000}"
    _add_scheduled_download(download_id, title, site, media_type, season, episodes)

    def _task():
        _acquire_download_slot()
        try:
            if _is_scheduled_cancelled(download_id):
                print("[_task] Download cancelled before start")
                _remove_scheduled_download(download_id)
                return

            context_tracker.download_id = download_id
            context_tracker.site_name = site
            context_tracker.media_type = media_type
            context_tracker.is_gui = True
            context_tracker.is_cancelled_callback = _is_scheduled_cancelled

            api = get_api(site)

            entries_fields = {k: v for k, v in item_payload.items() if k in Entries.__dataclass_fields__}
            media_item = Entries(**entries_fields)

            if audio_format:
                media_item.audio_format = audio_format

            if output_path:
                context_tracker.output_path = output_path

            print("[_task] Calling api.start_download with:")
            print(f"        season={season}, episodes={episodes}, output_path={output_path}, audio_format={audio_format}")
            try:
                api.start_download(media_item, season=season, episodes=episodes, audio_format=audio_format)
            except TypeError:
                api.start_download(media_item, season=season, episodes=episodes)
            print("[_task] ✓ Download completed successfully")
        except Exception as e:
            error_msg = str(e) or "Errore sconosciuto"
            print(f"[Error] Download task failed: {error_msg}")
            import traceback
            traceback.print_exc()

            try:
                _remove_scheduled_download(download_id)
                if download_id not in download_tracker.downloads:
                    download_tracker.start_download(download_id, title, site, media_type)
                download_tracker.complete_download(download_id, success=False, error=error_msg)
            except Exception as tracker_err:
                print(f"[Error] Failed to update download tracker: {tracker_err}")
            raise
        finally:
            _release_download_slot()

    return download_executor.submit(_task)
