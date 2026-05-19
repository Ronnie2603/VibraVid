# series.py — Views for series metadata and detail page (seasons/episodes).

import json
import logging

from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages

from GUI.searchapp.api import get_api
from GUI.searchapp.api.base import Entries
from VibraVid.utils.tmdb_client import tmdb_client

from .core import _run_download_in_thread, _add_scheduled_download, _is_scheduled_cancelled, _remove_scheduled_download, _submit_download_task
from GUI.searchapp.api import get_api

logger = logging.getLogger(__name__)


@require_http_methods(["POST"])
def series_metadata(request: HttpRequest) -> JsonResponse:
    """API endpoint to get series metadata (seasons/episodes)."""
    try:
        if request.content_type and "application/json" in request.content_type:
            body = json.loads(request.body.decode("utf-8"))
            source_alias = body.get("source_alias") or body.get("site")
            item_payload = body.get("item_payload") or {}
        else:
            source_alias = request.POST.get("source_alias") or request.POST.get("site")
            item_payload_raw = request.POST.get("item_payload")
            item_payload = json.loads(item_payload_raw) if item_payload_raw else {}

        if not source_alias or not item_payload:
            return JsonResponse({"error": "Parametri mancanti"}, status=400)

        api = get_api(source_alias)

        entries_fields = {k: v for k, v in item_payload.items() if k in Entries.__dataclass_fields__}
        media_item = Entries(**entries_fields)

        if media_item.is_movie:
            return JsonResponse({"isSeries": False, "seasonsCount": 0, "episodesPerSeason": {}})

        seasons = api.get_series_metadata(media_item)

        if not seasons:
            return JsonResponse({"isSeries": False, "seasonsCount": 0, "episodesPerSeason": {}})

        episodes_per_season = {season.number: season.episode_count for season in seasons}

        return JsonResponse({
            "isSeries": True,
            "seasonsCount": len(seasons),
            "episodesPerSeason": episodes_per_season,
        })

    except Exception as e:
        return JsonResponse({"Error get metadata": str(e)}, status=500)


@require_http_methods(["GET", "POST"])
def series_detail(request: HttpRequest) -> HttpResponse:
    """Show series detail page with seasons and episodes.
    Handles POST for full series, full season, or episode-specific downloads.
    """
    if request.method == "POST":
        return _handle_series_download(request)

    source_alias = request.GET.get("source_alias")
    item_payload_raw = request.GET.get("item_payload")

    if not source_alias or not item_payload_raw:
        messages.error(request, "Parametri mancanti.")
        return redirect("search_home")

    try:
        item_payload = json.loads(item_payload_raw)
        api = get_api(source_alias)
        entries_fields = {k: v for k, v in item_payload.items() if k in Entries.__dataclass_fields__}
        media_item = Entries(**entries_fields)

        backdrop_url = media_item.poster
        if not media_item.is_movie:
            try:
                if media_item.tmdb_id:
                    backdrop = tmdb_client.get_backdrop_url("tv", int(media_item.tmdb_id), size="w1920")
                    if backdrop:
                        backdrop_url = backdrop
                else:
                    slug = media_item.slug or tmdb_client._slugify(media_item.name)
                    year_str = str(media_item.year) if media_item.year else None
                    tmdb_result = tmdb_client.get_type_and_id_by_slug_year(slug, year_str, "tv")
                    if tmdb_result and tmdb_result.get("type") == "tv":
                        backdrop = tmdb_client.get_backdrop_url("tv", tmdb_result["id"], size="w1920")
                        if backdrop:
                            backdrop_url = backdrop
            except Exception:
                pass

        seasons = api.get_series_metadata(media_item)

        if not seasons:
            messages.warning(
                request,
                "Impossibile caricare i dettagli delle stagioni al momento. "
                "Potrebbe essere dovuto a download attivi. Riprova tra qualche minuto.",
            )
            seasons = []

        series_info = {
            "name": media_item.name,
            "poster": media_item.poster,
            "backdrop": backdrop_url,
            "year": media_item.year,
            "source_alias": source_alias,
            "item_payload": item_payload_raw,
        }

        seasons_data = []
        for season in seasons:
            episodes_data = []
            for ep in season.episodes:
                ep_dict = ep.__dict__.copy()
                lang = ep_dict.get("language") or ""
                ep_dict["language_list"] = (
                    [language.strip() for language in lang.split(",") if language.strip()] if lang else []
                )
                episodes_data.append(ep_dict)

            seasons_data.append({
                "number": season.number,
                "episode_count": season.episode_count,
                "episodes": episodes_data,
            })

        return render(
            request,
            "searchapp/series_detail.html",
            {"series": series_info, "seasons": seasons_data},
        )

    except Exception as e:
        messages.error(request, f"Errore nel caricamento dei dettagli: {e}")
        return redirect("search_home")


def _handle_series_download(request: HttpRequest) -> HttpResponse:
    """Handle POST downloads from series_detail: full series, full season, or selected episodes."""
    source_alias = request.POST.get("source_alias")
    item_payload_raw = request.POST.get("item_payload")
    download_type = request.POST.get("download_type")
    season_number = request.POST.get("season_number")
    selected_episodes = request.POST.get("selected_episodes", "")

    if not all([source_alias, item_payload_raw]):
        messages.error(request, "Parametri base mancanti per il download.")
        return redirect("search_home")

    try:
        item_payload = json.loads(item_payload_raw)
    except Exception:
        messages.error(request, "Errore nel parsing dei dati.")
        return redirect("search_home")

    import time
    name = item_payload.get("name")
    media_type = (item_payload.get("type") or "tv").lower()

    # --- FULL SERIES DOWNLOAD ---
    if download_type == "full_series":
        def _download_entire_series_task():
            try:
                api = get_api(source_alias)
                entries_fields = {k: v for k, v in item_payload.items() if k in Entries.__dataclass_fields__}
                media_item = Entries(**entries_fields)
                seasons = api.get_series_metadata(media_item)
                if not seasons:
                    return

                planned_seasons = []
                for season in seasons:
                    season_num = str(season.number)
                    season_title = f"{name} - S{season_num}"
                    planned_id = f"{source_alias}_{int(time.time())}_{hash(season_title + str(season_num)) % 10000}_{season_num}"
                    planned_seasons.append((planned_id, season_num))
                    _add_scheduled_download(planned_id, season_title, source_alias, media_type, season=season_num, episodes="*")

                from VibraVid.core.ui.tracker import download_tracker, context_tracker
                for download_id, season_num in planned_seasons:
                    try:
                        if _is_scheduled_cancelled(download_id):
                            _remove_scheduled_download(download_id)
                            continue
                        context_tracker.download_id = download_id
                        context_tracker.site_name = source_alias
                        context_tracker.media_type = media_type
                        context_tracker.is_gui = True
                        context_tracker.is_cancelled_callback = _is_scheduled_cancelled
                        api.start_download(media_item, season=season_num, episodes="*")
                    except Exception as e:
                        error_msg = str(e) or "Errore sconosciuto"
                        print(f"[Error] Download season {season_num}: {e}")
                        try:
                            _remove_scheduled_download(download_id)
                            if download_id not in download_tracker.downloads:
                                season_title = f"{name} - S{season_num}"
                                download_tracker.start_download(download_id, season_title, source_alias, media_type)
                            download_tracker.complete_download(download_id, success=False, error=error_msg)
                        except Exception as tracker_err:
                            print(f"[Error] Failed to update download tracker: {tracker_err}")
            except Exception as e:
                print(f"[Error] Full series download task: {e}")

        _submit_download_task(_download_entire_series_task)
        return redirect("download_dashboard")

    # --- FULL SEASON DOWNLOAD ---
    elif download_type == "full_season":
        if not season_number:
            messages.error(request, "Numero stagione mancante.")
            return redirect("search_home")
        _run_download_in_thread(site=source_alias, item_payload=item_payload, season=season_number, episodes="*", media_type=media_type)
        return redirect("download_dashboard")

    # --- SELECTED SEASONS DOWNLOAD ---
    elif download_type == "selected_seasons":
        selected_seasons_raw = request.POST.get("selected_seasons", "")
        if not selected_seasons_raw:
            messages.error(request, "Nessuna stagione selezionata.")
            return redirect("search_home")
        selected_seasons = [s.strip() for s in selected_seasons_raw.split(",") if s.strip()]

        def _download_selected_seasons_task():
            try:
                api = get_api(source_alias)
                entries_fields = {k: v for k, v in item_payload.items() if k in Entries.__dataclass_fields__}
                media_item = Entries(**entries_fields)
                planned_seasons = []
                for season_num in selected_seasons:
                    season_title = f"{name} - S{season_num}"
                    planned_id = f"{source_alias}_{int(time.time())}_{hash(season_title + str(season_num)) % 10000}_{season_num}"
                    planned_seasons.append((planned_id, season_num))
                    _add_scheduled_download(planned_id, season_title, source_alias, media_type, season=season_num, episodes="*")

                from VibraVid.core.ui.tracker import download_tracker, context_tracker
                for download_id, season_num in planned_seasons:
                    try:
                        if _is_scheduled_cancelled(download_id):
                            _remove_scheduled_download(download_id)
                            continue
                        context_tracker.download_id = download_id
                        context_tracker.site_name = source_alias
                        context_tracker.media_type = media_type
                        context_tracker.is_gui = True
                        context_tracker.is_cancelled_callback = _is_scheduled_cancelled
                        api.start_download(media_item, season=season_num, episodes="*")
                    except Exception as e:
                        error_msg = str(e) or "Errore sconosciuto"
                        print(f"[Error] Download season {season_num}: {e}")
                        try:
                            _remove_scheduled_download(download_id)
                            if download_id not in download_tracker.downloads:
                                season_title = f"{name} - S{season_num}"
                                download_tracker.start_download(download_id, season_title, source_alias, media_type)
                            download_tracker.complete_download(download_id, success=False, error=error_msg)
                        except Exception as tracker_err:
                            print(f"[Error] Failed to update download tracker: {tracker_err}")
            except Exception as e:
                print(f"[Error] Selected seasons download task: {e}")

        _submit_download_task(_download_selected_seasons_task)
        return redirect("download_dashboard")

    # --- SELECTED EPISODES DOWNLOAD ---
    else:
        if not season_number:
            messages.error(request, "Numero stagione mancante.")
            return redirect("search_home")

        episode_param = selected_episodes.strip() if selected_episodes else None
        print(f"[DEBUG] episode_param after strip: '{episode_param}'")

        if not episode_param:
            print("[ERROR] episode_param is empty/None!")
            messages.error(request, "Nessun episodio selezionato.")
            from django.urls import reverse
            url = reverse("series_detail") + f"?source_alias={source_alias}&item_payload={item_payload_raw}"
            return redirect(url)

        print(f"[DEBUG] ✓ Proceeding with episodes: {episode_param}")
        _run_download_in_thread(
            site=source_alias,
            item_payload=item_payload,
            season=season_number,
            episodes=episode_param,
            media_type=media_type,
        )
        print(f"[DEBUG] ✓ Download thread started for S{season_number} E{episode_param}")
        return redirect("download_dashboard")
