# arr.py — Webhook and status views for Sonarr/Radarr/Seerr (ARR) integration.

import json
import time
import threading
import logging

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .core import _is_recent_webhook, _mark_native_webhook_seen

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def seerr_webhook(request: HttpRequest) -> JsonResponse:
    """Seerr/Overseerr webhook endpoint. POST /api/arr/webhook/seerr/"""
    try:
        from ..arr.arr_service import _load_arr_config, trigger_webhook_sync
        from ..models import ArrWebhookEvent

        logger.info("=" * 60)
        logger.info("[SEERR WEBHOOK] Received request")
        logger.info(f"[SEERR WEBHOOK] Headers: {dict(request.headers)}")
        logger.info(f"[SEERR WEBHOOK] Body (raw): {request.body[:2000]}")
        logger.info("=" * 60)

        cfg = _load_arr_config()

        if not cfg.get("enabled"):
            return JsonResponse({"status": "disabled", "message": "ARR services are disabled"}, status=200)

        if not cfg.get("enable_seerr_webhook"):
            return JsonResponse({"status": "disabled", "message": "Seerr webhook is disabled"}, status=200)

        expected_secret = cfg.get("seerr", {}).get("webhook_secret", "")
        if expected_secret:
            token = request.headers.get("X-Webhook-Token", "")
            if token != expected_secret:
                logger.warning("[SEERR WEBHOOK] Invalid webhook token")
                return JsonResponse({"status": "error", "message": "Invalid webhook token"}, status=403)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

        notification_type = payload.get("notification_type", "").upper()

        if notification_type in ("MEDIA_APPROVED", "MEDIA_AUTO_APPROVED", "MEDIA_PENDING", "TEST_NOTIFICATION"):
            event_type = notification_type
        else:
            event_type = "UNKNOWN"
            logger.warning(f"[SEERR WEBHOOK] Unknown notification_type: {notification_type}")

        media = payload.get("media", {}) or {}
        media_type = str(media.get("media_type", "")).lower() or None
        tmdb_id = media.get("tmdbId")
        tmdb_id_str = str(tmdb_id) if tmdb_id is not None else None

        webhook_event = ArrWebhookEvent.objects.create(
            event_type=event_type,
            source="seerr",
            media_type=media_type,
            tmdb_id=tmdb_id_str,
            raw_payload=payload,
            processed=False,
        )

        if event_type == "TEST_NOTIFICATION":
            webhook_event.processed = True
            webhook_event.save(update_fields=["processed"])
            webhook_event.event_type = "TEST"
            webhook_event.save(update_fields=["event_type"])
            return JsonResponse({"status": "ok", "message": "Test notification received"})

        if event_type in ("MEDIA_APPROVED", "MEDIA_AUTO_APPROVED", "MEDIA_PENDING"):
            webhook_priority_enabled = cfg.get("webhook_priority_enabled", True)
            native_window = int(cfg.get("native_webhook_priority_window_seconds", 120))
            fallback_delay = int(cfg.get("seerr_fallback_delay_seconds", 20))

            def _async_sync():
                try:
                    from django.db import close_old_connections
                    close_old_connections()

                    if webhook_priority_enabled and tmdb_id_str and media_type in {"tv", "movie"}:
                        preferred_source = "sonarr" if media_type == "tv" else "radarr"
                        if _is_recent_webhook(tmdb_id_str, source=preferred_source, window_seconds=native_window, touch=False):
                            webhook_event.processed = True
                            webhook_event.ignored_by_priority = True
                            webhook_event.save(update_fields=["processed", "ignored_by_priority"])
                            return

                        if fallback_delay > 0:
                            time.sleep(fallback_delay)
                            if _is_recent_webhook(tmdb_id_str, source=preferred_source, window_seconds=native_window, touch=False):
                                webhook_event.processed = True
                                webhook_event.ignored_by_priority = True
                                webhook_event.save(update_fields=["processed", "ignored_by_priority"])
                                return

                    count = trigger_webhook_sync(payload)
                    webhook_event.processed = True
                    webhook_event.save(update_fields=["processed"])
                    logger.info(f"[SEERR WEBHOOK ASYNC] Sync complete: {count} items enqueued")
                except Exception as exc:
                    webhook_event.error = str(exc)
                    webhook_event.save(update_fields=["error"])
                    logger.error(f"[SEERR WEBHOOK ASYNC] Sync error: {exc}", exc_info=True)

            threading.Thread(target=_async_sync, daemon=True).start()
            return JsonResponse({"status": "ok", "message": f"Processing {event_type}"})

        return JsonResponse({"status": "ok", "message": f"Event {event_type} acknowledged"})

    except Exception as exc:
        logger.error(f"[SEERR WEBHOOK] Unexpected error: {exc}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def sonarr_webhook(request: HttpRequest) -> JsonResponse:
    """Sonarr native webhook endpoint. POST /api/arr/webhook/sonarr/"""
    try:
        from ..arr.arr_service import _load_arr_config, trigger_sonarr_webhook_sync
        from ..models import ArrWebhookEvent

        logger.info("=" * 60)
        logger.info("[SONARR WEBHOOK] Received request")
        logger.info(f"[SONARR WEBHOOK] Body (raw): {request.body[:2000]}")
        logger.info("=" * 60)

        cfg = _load_arr_config()

        if not cfg.get("enabled"):
            return JsonResponse({"status": "disabled", "message": "ARR services are disabled"}, status=200)

        if not cfg.get("enable_sonarr_webhook"):
            return JsonResponse({"status": "disabled", "message": "Sonarr webhook is disabled"}, status=200)

        expected_secret = cfg.get("sonarr_webhook", {}).get("webhook_secret", "")
        if expected_secret:
            token = request.headers.get("X-Webhook-Token", "")
            if token != expected_secret:
                return JsonResponse({"status": "error", "message": "Invalid webhook token"}, status=403)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

        event_type = payload.get("eventType", "UNKNOWN").upper()

        series_data = payload.get("series", {}) or {}
        tmdb_id = series_data.get("tmdbId") or series_data.get("tvdbId")
        tmdb_id_str = str(tmdb_id) if tmdb_id is not None else None
        _mark_native_webhook_seen(tmdb_id_str, "sonarr")

        webhook_event = ArrWebhookEvent.objects.create(
            event_type=event_type,
            source="sonarr",
            media_type="tv",
            tmdb_id=tmdb_id_str,
            arr_item_id=series_data.get("id"),
            raw_payload=payload,
            processed=False,
        )

        if event_type == "TEST":
            webhook_event.processed = True
            webhook_event.save(update_fields=["processed"])
            return JsonResponse({"status": "ok", "message": "Test notification received", "payload_preview": payload})

        if event_type in ("DOWNLOAD", "GRAB", "SERIESADD"):
            def _async_sync():
                try:
                    from django.db import close_old_connections
                    close_old_connections()
                    count = trigger_sonarr_webhook_sync(payload)
                    webhook_event.processed = True
                    webhook_event.save(update_fields=["processed"])
                    logger.info(f"[SONARR WEBHOOK ASYNC] Sync complete: {count} items enqueued")
                except Exception as exc:
                    webhook_event.error = str(exc)
                    webhook_event.save(update_fields=["error"])
                    logger.error(f"[SONARR WEBHOOK ASYNC] Sync error: {exc}", exc_info=True)

            threading.Thread(target=_async_sync, daemon=True).start()
            return JsonResponse({"status": "ok", "message": f"Processing Sonarr event {event_type}"})

        elif event_type == "SERIESDELETE":
            webhook_event.processed = True
            webhook_event.save(update_fields=["processed"])
            return JsonResponse({"status": "ok", "message": "SeriesDelete acknowledged, no action needed"})

        return JsonResponse({"status": "ok", "message": f"Event {event_type} acknowledged"})

    except Exception as exc:
        logger.error(f"[SONARR WEBHOOK] Unexpected error: {exc}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def radarr_webhook(request: HttpRequest) -> JsonResponse:
    """Radarr native webhook endpoint. POST /api/arr/webhook/radarr/"""
    try:
        from ..arr.arr_service import _load_arr_config, trigger_radarr_webhook_sync
        from ..models import ArrWebhookEvent

        logger.info("=" * 60)
        logger.info("[RADARR WEBHOOK] Received request")
        logger.info(f"[RADARR WEBHOOK] Body (raw): {request.body[:2000]}")
        logger.info("=" * 60)

        cfg = _load_arr_config()

        if not cfg.get("enabled"):
            return JsonResponse({"status": "disabled", "message": "ARR services are disabled"}, status=200)

        if not cfg.get("enable_radarr_webhook"):
            return JsonResponse({"status": "disabled", "message": "Radarr webhook is disabled"}, status=200)

        expected_secret = cfg.get("radarr_webhook", {}).get("webhook_secret", "")
        if expected_secret:
            token = request.headers.get("X-Webhook-Token", "")
            if token != expected_secret:
                return JsonResponse({"status": "error", "message": "Invalid webhook token"}, status=403)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

        event_type = payload.get("eventType", "UNKNOWN").upper()

        movie_data = payload.get("movie", {}) or {}
        tmdb_id = movie_data.get("tmdbId")
        tmdb_id_str = str(tmdb_id) if tmdb_id is not None else None
        _mark_native_webhook_seen(tmdb_id_str, "radarr")

        webhook_event = ArrWebhookEvent.objects.create(
            event_type=event_type,
            source="radarr",
            media_type="movie",
            tmdb_id=tmdb_id_str,
            arr_item_id=movie_data.get("id"),
            raw_payload=payload,
            processed=False,
        )

        if event_type == "TEST":
            webhook_event.processed = True
            webhook_event.save(update_fields=["processed"])
            return JsonResponse({"status": "ok", "message": "Test notification received", "payload_preview": payload})

        def _async_sync():
            try:
                from django.db import close_old_connections
                close_old_connections()
                count = trigger_radarr_webhook_sync(payload)
                webhook_event.processed = True
                webhook_event.save(update_fields=["processed"])
                logger.info(f"[RADARR WEBHOOK ASYNC] Sync complete: {count} items enqueued")
            except Exception as exc:
                webhook_event.error = str(exc)
                webhook_event.save(update_fields=["error"])
                logger.error(f"[RADARR WEBHOOK ASYNC] Sync error: {exc}", exc_info=True)

        threading.Thread(target=_async_sync, daemon=True).start()
        return JsonResponse({"status": "ok", "message": f"Processing Radarr event {event_type}"})

    except Exception as exc:
        logger.error(f"[RADARR WEBHOOK] Unexpected error: {exc}", exc_info=True)
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def arr_status(request: HttpRequest) -> JsonResponse:
    """ARR status endpoint. GET /api/arr/status/"""
    try:
        from ..arr.arr_service import _load_arr_config
        from ..models import ArrMediaRequest, ArrWebhookEvent

        cfg = _load_arr_config()

        pending_count = ArrMediaRequest.objects.filter(status="pending").count()
        downloading_count = ArrMediaRequest.objects.filter(status="downloading").count()
        completed_count = ArrMediaRequest.objects.filter(status="completed").count()
        failed_count = ArrMediaRequest.objects.filter(status="failed").count()
        webhook_count = ArrWebhookEvent.objects.count()

        def _latest_test(source_hint):
            qs = ArrWebhookEvent.objects.filter(event_type__iexact="test").order_by("-id")[:20]
            for ev in qs:
                p = ev.raw_payload or {}
                if source_hint == "sonarr" and "series" in p:
                    return p
                if source_hint == "radarr" and "movie" in p:
                    return p
                if source_hint == "seerr" and "notification_type" in p:
                    return p
            return None

        return JsonResponse({
            "enabled": cfg.get("enabled", False),
            "polling_enabled": cfg.get("enable_polling", False),
            "webhook_enabled": cfg.get("enable_seerr_webhook", False),
            "sonarr_webhook_enabled": cfg.get("enable_sonarr_webhook", False),
            "radarr_webhook_enabled": cfg.get("enable_radarr_webhook", False),
            "max_concurrent_downloads": cfg.get("max_concurrent_downloads", 1),
            "webhook_priority_enabled": cfg.get("webhook_priority_enabled", True),
            "native_webhook_priority_window_seconds": cfg.get("native_webhook_priority_window_seconds", 120),
            "seerr_fallback_delay_seconds": cfg.get("seerr_fallback_delay_seconds", 20),
            "polling_interval": cfg.get("polling_interval", 300),
            "full_resync_interval": cfg.get("full_resync_interval", 21600),
            "sonarr_configured": bool(cfg.get("sonarr", {}).get("url")),
            "radarr_configured": bool(cfg.get("radarr", {}).get("url")),
            "last_sonarr_test_payload": _latest_test("sonarr"),
            "last_radarr_test_payload": _latest_test("radarr"),
            "last_seerr_test_payload": _latest_test("seerr"),
            "stats": {
                "pending": pending_count,
                "downloading": downloading_count,
                "completed": completed_count,
                "failed": failed_count,
                "total_webhooks": webhook_count,
            },
        })
    except Exception as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def arr_trigger_sync(request: HttpRequest) -> JsonResponse:
    """Manually trigger ARR sync. POST /api/arr/trigger-sync/"""
    try:
        from ..arr.arr_service import _load_arr_config, trigger_polling_sync

        cfg = _load_arr_config()
        if not cfg.get("enabled"):
            return JsonResponse({"status": "disabled", "message": "ARR services are disabled"})

        def _async_sync():
            try:
                from django.db import close_old_connections
                close_old_connections()
                count = trigger_polling_sync(full_resync=True)
                print(f"[ARR] Manual sync complete: {count} items enqueued")
            except Exception as exc:
                print(f"[ARR] Manual sync error: {exc}")

        threading.Thread(target=_async_sync, daemon=True).start()
        return JsonResponse({"status": "ok", "message": "Sync triggered in background"})

    except Exception as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=500)
