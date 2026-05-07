# 07.05.26

"""
ARR Service — main orchestrator replacing Core.py from VibraVidArr.

Coordinates:
  - polling sync (incremental + full reconciliation)
  - webhook-triggered immediate sync
  - deduplication via ArrProcessingQueue
  - config loading from config.json
"""

import json
import logging
import os
import threading
from typing import Any, Dict, List, Optional

from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger("ARR")

# Module-level lock for thread-safe enqueue operations
_enqueue_lock = threading.Lock()


def _load_arr_config() -> dict:
    """Load the 'arr' section from Conf/config.json, with env-var overrides."""
    conf_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        "Conf",
    )
    config_path = os.path.join(conf_dir, "config.json")

    arr_cfg = {
        "enabled": False,
        "enable_polling": True,
        "enable_seerr_webhook": False,
        "polling_interval": 300,
        "full_resync_interval": 21600,
        "tags_mode": "BLACKLIST",
        "active_tag_ids": [],
        "sonarr": {"url": "", "api_key": ""},
        "radarr": {"url": "", "api_key": ""},
        "seerr": {"webhook_secret": ""},
    }

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            full_cfg = json.load(f)
        file_arr = full_cfg.get("ARR", {})
        if file_arr:
            arr_cfg.update(file_arr)
    except Exception as exc:
        logger.warning(f"Could not read ARR config from config.json: {exc}")

    # Environment variable overrides (higher priority)
    def _env(key, default=None):
        return os.environ.get(key, default)

    def _env_bool(key, default=False):
        val = _env(key)
        if val is None:
            return default
        return val.strip().lower() in {"1", "true", "yes", "on"}

    def _env_int(key, default=0):
        val = _env(key)
        if val is None:
            return default
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    if _env("USE_ARR_SERVICES") is not None:
        arr_cfg["enabled"] = _env_bool("USE_ARR_SERVICES")
    if _env("ENABLE_ARR_POLLING") is not None:
        arr_cfg["enable_polling"] = _env_bool("ENABLE_ARR_POLLING")
    if _env("ENABLE_SEERR_WEBHOOK") is not None:
        arr_cfg["enable_seerr_webhook"] = _env_bool("ENABLE_SEERR_WEBHOOK")
    if _env("ARR_POLLING_INTERVAL"):
        arr_cfg["polling_interval"] = _env_int("ARR_POLLING_INTERVAL", 300)
    if _env("ARR_FULL_RESYNC_INTERVAL"):
        arr_cfg["full_resync_interval"] = _env_int("ARR_FULL_RESYNC_INTERVAL", 21600)

    sonarr_url = _env("SONARR_URL")
    sonarr_key = _env("SONARR_API_KEY")
    if sonarr_url:
        arr_cfg["sonarr"]["url"] = sonarr_url
    if sonarr_key:
        arr_cfg["sonarr"]["api_key"] = sonarr_key

    radarr_url = _env("RADARR_URL")
    radarr_key = _env("RADARR_API_KEY")
    if radarr_url:
        arr_cfg["radarr"]["url"] = radarr_url
    if radarr_key:
        arr_cfg["radarr"]["api_key"] = radarr_key

    webhook_secret = _env("SEERR_WEBHOOK_SECRET")
    if webhook_secret:
        arr_cfg["seerr"]["webhook_secret"] = webhook_secret

    return arr_cfg


def _build_clients(cfg: dict):
    """Construct SonarrClient and RadarrClient from config."""
    from .clients.sonarr_client import SonarrClient
    from .clients.radarr_client import RadarrClient

    sonarr = None
    radarr = None

    sonarr_cfg = cfg.get("sonarr", {})
    if sonarr_cfg.get("url") and sonarr_cfg.get("api_key"):
        sonarr = SonarrClient(sonarr_cfg["url"], sonarr_cfg["api_key"])

    radarr_cfg = cfg.get("radarr", {})
    if radarr_cfg.get("url") and radarr_cfg.get("api_key"):
        radarr = RadarrClient(radarr_cfg["url"], radarr_cfg["api_key"])

    return sonarr, radarr


def _dedup_key(item: dict, season_num: Optional[int] = None, ep_num: Optional[int] = None) -> str:
    """Build a dedup key for an ARR item."""
    content_type = item.get("content_type", "unknown")
    arr_id = item.get("id", 0)

    if content_type == "movie":
        return f"radarr_{arr_id}"
    else:
        return f"sonarr_{arr_id}_s{season_num}_e{ep_num}"


def _enqueue_if_new(item: dict, sync_source: str, season_num: Optional[int] = None,
                    ep_num: Optional[int] = None, episode_id: Optional[int] = None) -> bool:
    """
    Create ArrMediaRequest + ArrProcessingQueue entries if not already present.
    Returns True if newly enqueued, False if duplicate.
    """
    from searchapp.models import ArrMediaRequest, ArrProcessingQueue

    key = _dedup_key(item, season_num, ep_num)

    with _enqueue_lock:
        # Check for active (non-completed) queue entry
        existing = ArrProcessingQueue.objects.filter(
            dedup_key=key,
            completed_at__isnull=True,
        ).first()

        if existing:
            logger.debug(f"Skipping duplicate enqueue: {key}")
            return False

        # Also skip if recently completed successfully (within last 6 hours)
        recent = ArrProcessingQueue.objects.filter(
            dedup_key=key,
            success=True,
            completed_at__gte=timezone.now() - timezone.timedelta(hours=6),
        ).first()

        if recent:
            logger.debug(f"Skipping recently completed: {key}")
            return False

        content_type = item.get("content_type", "serie")
        arr_source = "radarr" if content_type == "movie" else "sonarr"

        media_req = ArrMediaRequest.objects.create(
            arr_id=item.get("id", 0),
            arr_source=arr_source,
            title=item.get("title", "Unknown"),
            content_type=content_type,
            season_number=season_num,
            episode_number=ep_num,
            episode_id=episode_id,
            year=item.get("year"),
            provider=item.get("provider", "streamingcommunity"),
            status=ArrMediaRequest.Status.PENDING,
            sync_source=sync_source,
            tmdb_id=str(item.get("tmdbId", "")) or None,
            last_synced_at=timezone.now(),
        )

        ArrProcessingQueue.objects.create(
            dedup_key=key,
            media_request=media_req,
        )

        logger.info(f"Enqueued: {key}")
        return True


def trigger_polling_sync(full_resync: bool = False) -> int:
    """
    Run a polling sync against Sonarr/Radarr.
    Returns the number of newly enqueued items.
    """
    close_old_connections()

    cfg = _load_arr_config()
    if not cfg.get("enabled"):
        return 0

    sonarr, radarr = _build_clients(cfg)
    if not sonarr and not radarr:
        logger.warning("No Sonarr/Radarr clients configured, skipping polling")
        return 0

    from .processor_service import ArrProcessorService
    from .downloader_service import ArrDownloaderService

    processor = ArrProcessorService(
        sonarr=sonarr,
        radarr=radarr,
        tags_mode=cfg.get("tags_mode", "BLACKLIST"),
        active_tag_ids=cfg.get("active_tag_ids", []),
    )

    missing_items = processor.get_missing_items()
    if not missing_items:
        logger.info("No missing items found during polling")
        return 0

    logger.info(f"Found {len(missing_items)} missing items from ARR")

    enqueued = 0
    for item in missing_items:
        content_type = item.get("content_type")

        if content_type == "movie":
            if _enqueue_if_new(item, "polling"):
                enqueued += 1
                # Immediately start download
                downloader = ArrDownloaderService(sonarr, radarr)
                try:
                    downloader._process_movie(item)
                    _mark_completed(item)
                except Exception as exc:
                    logger.error(f"Download failed for movie '{item.get('title')}': {exc}")
                    _mark_failed(item, str(exc))

        elif content_type == "serie":
            for season in item.get("seasons", []):
                for episode in season.get("episodes", []):
                    ep_item = {**item, "seasons": [{"number": season["number"], "episodes": [episode]}]}
                    if _enqueue_if_new(
                        item, "polling",
                        season_num=season["number"],
                        ep_num=episode["episodeNumber"],
                        episode_id=episode["id"],
                    ):
                        enqueued += 1
                        downloader = ArrDownloaderService(sonarr, radarr)
                        try:
                            downloader._process_serie(ep_item)
                            _mark_completed(item, season["number"], episode["episodeNumber"])
                        except Exception as exc:
                            logger.error(f"Download failed for '{item.get('title')}' S{season['number']}E{episode['episodeNumber']}: {exc}")
                            _mark_failed(item, str(exc), season["number"], episode["episodeNumber"])

    logger.info(f"Polling sync complete: {enqueued} new items enqueued")
    return enqueued


def trigger_webhook_sync(event_data: dict) -> int:
    """
    Handle an incoming Seerr/Overseerr webhook and trigger immediate sync.
    Returns the number of newly enqueued items.
    """
    close_old_connections()

    cfg = _load_arr_config()
    if not cfg.get("enabled"):
        return 0

    sonarr, radarr = _build_clients(cfg)
    if not sonarr and not radarr:
        return 0

    # Parse the webhook payload
    media = event_data.get("media", {})
    media_type = media.get("media_type", "").lower()  # "movie" or "tv"
    tmdb_id = media.get("tmdbId")

    if not tmdb_id:
        logger.warning("Webhook payload missing tmdbId, falling back to full polling sync")
        return trigger_polling_sync()

    # For now, trigger a full polling sync — the deduplication layer
    # ensures we don't re-download anything already processed.
    logger.info(f"Webhook received for {media_type} (tmdbId={tmdb_id}), triggering sync")
    return trigger_polling_sync()


def _mark_completed(item: dict, season_num=None, ep_num=None):
    """Mark queue entry as completed."""
    from searchapp.models import ArrMediaRequest, ArrProcessingQueue

    key = _dedup_key(item, season_num, ep_num)
    try:
        queue_entry = ArrProcessingQueue.objects.filter(dedup_key=key, completed_at__isnull=True).first()
        if queue_entry:
            queue_entry.completed_at = timezone.now()
            queue_entry.success = True
            queue_entry.save(update_fields=["completed_at", "success"])
            queue_entry.media_request.status = ArrMediaRequest.Status.COMPLETED
            queue_entry.media_request.save(update_fields=["status"])
    except Exception as exc:
        logger.error(f"Failed to mark completed {key}: {exc}")


def _mark_failed(item: dict, error: str, season_num=None, ep_num=None):
    """Mark queue entry as failed."""
    from searchapp.models import ArrMediaRequest, ArrProcessingQueue

    key = _dedup_key(item, season_num, ep_num)
    try:
        queue_entry = ArrProcessingQueue.objects.filter(dedup_key=key, completed_at__isnull=True).first()
        if queue_entry:
            queue_entry.completed_at = timezone.now()
            queue_entry.success = False
            queue_entry.save(update_fields=["completed_at", "success"])
            queue_entry.media_request.status = ArrMediaRequest.Status.FAILED
            queue_entry.media_request.save(update_fields=["status"])
    except Exception as exc:
        logger.error(f"Failed to mark failed {key}: {exc}")
