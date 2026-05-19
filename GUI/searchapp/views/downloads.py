# downloads.py — Views for the download dashboard and download management APIs.

import json
import logging

from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages

from ..forms import DownloadForm
from GUI.searchapp.api.base import Entries
from VibraVid.core.ui.tracker import download_tracker

from .core import (
    _run_download_in_thread,
    _enrich_active_downloads_with_series,
    _prune_scheduled_downloads,
    _get_scheduled_downloads,
    _cancel_scheduled_download,
    _extract_series_base_title,
    _same_series,
    scheduled_downloads,
    scheduled_downloads_lock,
    cancelled_scheduled_downloads,
)

logger = logging.getLogger(__name__)


@require_http_methods(["POST"])
def start_download(request: HttpRequest) -> HttpResponse:
    """Handle download requests for movies or individual series selections."""
    form = DownloadForm(request.POST)
    if not form.is_valid():
        error_msg = f"Dati non validi: {form.errors.as_text()}"
        print(f"[Error] {error_msg}")
        messages.error(request, error_msg)
        return redirect("search_home")

    source_alias = form.cleaned_data["source_alias"]
    item_payload_raw = form.cleaned_data["item_payload"]
    season = form.cleaned_data.get("season") or None
    episode = form.cleaned_data.get("episode") or None
    audio_format = form.cleaned_data.get("audio_format") or None

    if season:
        season = str(season).strip() or None
    if episode:
        episode = str(episode).strip() or None
    if audio_format:
        audio_format = str(audio_format).strip().lower() or None

    try:
        item_payload = json.loads(item_payload_raw)
    except Exception:
        messages.error(request, "Payload non valido")
        return redirect("search_home")

    item_type = str(item_payload.get("type") or "").lower()
    if item_type in ("song", "track", "music"):
        media_type = "Musica"
    elif item_type == "album":
        media_type = "Album"
    elif item_payload.get("is_movie"):
        media_type = "Film"
    else:
        media_type = "Serie"

    if media_type == "Serie" and season and not episode:
        messages.error(request, "Seleziona almeno un episodio prima di scaricare!")

    _run_download_in_thread(source_alias, item_payload, season, episode, media_type, audio_format=audio_format)
    return redirect("download_dashboard")


def download_dashboard(request: HttpRequest) -> HttpResponse:
    """Dashboard to view all active and completed downloads."""
    active_downloads = _enrich_active_downloads_with_series(download_tracker.get_active_downloads())
    history = download_tracker.get_history()
    _prune_scheduled_downloads(active_downloads, history)
    scheduled = _get_scheduled_downloads()

    return render(
        request,
        "searchapp/downloads.html",
        {
            "active_downloads": active_downloads,
            "scheduled_downloads": scheduled,
            "history": history,
            "active_count": len(active_downloads),
            "scheduled_count": len(scheduled),
        },
    )


def get_downloads_json(request: HttpRequest) -> JsonResponse:
    """API endpoint to get real-time download progress."""
    active_downloads = _enrich_active_downloads_with_series(download_tracker.get_active_downloads())
    history = download_tracker.get_history()
    _prune_scheduled_downloads(active_downloads, history)
    scheduled = _get_scheduled_downloads()

    return JsonResponse({"active": active_downloads, "scheduled": scheduled, "history": history})


@csrf_exempt
def kill_download(request: HttpRequest) -> JsonResponse:
    """API view to cancel a download."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            download_id = data.get("download_id")
            if download_id:
                download_tracker.request_stop(download_id)
                return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    return JsonResponse({"status": "error", "message": "Method not allowed", "status_code": 405}, status=405)


@csrf_exempt
def kill_and_clear_queue(request: HttpRequest) -> JsonResponse:
    """API view to cancel a specific download and empty the entire scheduled queue."""
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            download_id = data.get("download_id")
            series_name = data.get("series_name")
            target_site = ""
            target_series = _extract_series_base_title(series_name)

            if download_id:
                with scheduled_downloads_lock:
                    info = scheduled_downloads.get(download_id)
                if info:
                    target_site = str(info.get("site") or "").strip()
                    if not target_series:
                        target_series = _extract_series_base_title(info.get("title", ""))

                if not info:
                    active_items = download_tracker.get_active_downloads()
                    active_info = next((d for d in active_items if d.get("id") == download_id), None)
                    if active_info:
                        target_site = str(active_info.get("site") or "").strip()
                        if not target_series:
                            target_series = _extract_series_base_title(active_info.get("title", ""))

                _cancel_scheduled_download(download_id)
                download_tracker.request_stop(download_id)

            if target_series:
                active_to_stop = []
                for item in download_tracker.get_active_downloads():
                    current_id = item.get("id")
                    if not current_id:
                        continue
                    if target_site and str(item.get("site") or "").strip() != target_site:
                        continue
                    if _same_series(item.get("title", ""), target_series):
                        active_to_stop.append(current_id)

                for current_id in active_to_stop:
                    _cancel_scheduled_download(current_id)
                    download_tracker.request_stop(current_id)

            with scheduled_downloads_lock:
                to_remove = []
                for d_id, d_info in scheduled_downloads.items():
                    if not target_series:
                        continue
                    if target_site and str(d_info.get("site") or "").strip() != target_site:
                        continue
                    if _same_series(d_info.get("title", ""), target_series):
                        cancelled_scheduled_downloads.add(d_id)
                        to_remove.append(d_id)
                for d_id in to_remove:
                    scheduled_downloads.pop(d_id, None)

            return JsonResponse({"status": "success"})

        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=400)

    return JsonResponse({"status": "error", "message": "Method not allowed", "status_code": 405}, status=405)


@csrf_exempt
def clear_download_history(request: HttpRequest) -> JsonResponse:
    """API view to clear the download history."""
    if request.method == "POST":
        try:
            download_tracker.clear_history()
            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)}, status=500)
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)
