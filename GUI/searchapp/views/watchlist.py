# watchlist.py — Views for watchlist management and auto-download configuration.

import json
import threading
import logging

from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib import messages
from django.utils import timezone

from ..models import WatchlistItem
from ..watchlist_auto import _get_interval_seconds
from GUI.searchapp.api import get_api
from GUI.searchapp.api.base import Entries
from .core import _run_download_in_thread, _to_bool

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def watchlist(request: HttpRequest) -> HttpResponse:
    """Display the watchlist."""
    items = WatchlistItem.objects.all()
    for item in items:
        item.season_numbers = list(range(1, item.num_seasons + 1))
    poll_interval_seconds = _get_interval_seconds()
    return render(
        request,
        "searchapp/watchlist.html",
        {"items": items, "poll_interval_seconds": poll_interval_seconds},
    )


@require_http_methods(["POST"])
def set_watchlist_polling_interval(request: HttpRequest) -> HttpResponse:
    """Update the watchlist auto-check interval for this process."""
    import os
    raw = request.POST.get("poll_interval", "")
    try:
        value = int(raw)
    except Exception:
        value = None

    allowed = {300, 900, 1800, 3600, 21600, 43200, 86400}
    if value not in allowed:
        messages.error(request, "Intervallo non valido.")
        return redirect("watchlist")

    os.environ["WATCHLIST_AUTO_INTERVAL_SECONDS"] = str(value)
    messages.success(request, "Intervallo di controllo aggiornato.")
    return redirect("watchlist")


@require_http_methods(["POST"])
def add_to_watchlist(request: HttpRequest) -> HttpResponse:
    """Add a media item to the watchlist."""
    source_alias = request.POST.get("source_alias")
    item_payload_raw = request.POST.get("item_payload")
    search_query = request.POST.get("search_query")
    search_site = request.POST.get("search_site")

    if not source_alias or not item_payload_raw:
        messages.error(request, "Parametri mancanti per la watchlist.")
        return redirect("search_home")

    try:
        item_payload = json.loads(item_payload_raw)
        name = item_payload.get("name")
        poster = item_payload.get("poster")
        tmdb_id = item_payload.get("tmdb_id")
        is_movie = _to_bool(item_payload.get("is_movie"))

        existing = WatchlistItem.objects.filter(name=name, source_alias=source_alias).first()

        if existing:
            messages.info(request, f"'{name}' è già nella watchlist.")
        else:
            item = WatchlistItem.objects.create(
                name=name,
                source_alias=source_alias,
                item_payload=item_payload_raw,
                is_movie=is_movie,
                poster_url=poster,
                tmdb_id=tmdb_id,
                num_seasons=0,
                last_season_episodes=0,
            )

            def _bg_update():
                _update_single_item(item)

            threading.Thread(target=_bg_update, daemon=True).start()

    except Exception as e:
        messages.error(request, f"Errore durante l'aggiunta alla watchlist: {e}")

    if search_query and search_site:
        from django.urls import reverse
        return redirect(f"{reverse('search')}?site={search_site}&query={search_query}")

    return redirect(request.META.get("HTTP_REFERER", "search_home"))


@require_http_methods(["POST"])
def remove_from_watchlist(request: HttpRequest, item_id: int) -> HttpResponse:
    """Remove an item from the watchlist."""
    try:
        item = WatchlistItem.objects.get(id=item_id)
        name = item.name
        item.delete()
        messages.success(request, f"'{name}' rimosso dalla watchlist.")
    except WatchlistItem.DoesNotExist:
        messages.error(request, "Elemento non trovato.")

    return redirect("watchlist")


@require_http_methods(["POST"])
def clear_watchlist(request: HttpRequest) -> HttpResponse:
    """Remove all items from the watchlist."""
    WatchlistItem.objects.all().delete()
    messages.success(request, "Watchlist svuotata.")
    return redirect("watchlist")


@require_http_methods(["POST"])
def update_watchlist_auto(request: HttpRequest, item_id: int) -> HttpResponse:
    """Update auto-download settings for a watchlist item."""
    try:
        item = WatchlistItem.objects.get(id=item_id)
    except WatchlistItem.DoesNotExist:
        messages.error(request, "Elemento non trovato.")
        return redirect("watchlist")

    if item.is_movie:
        if item.auto_enabled or item.auto_season:
            item.auto_enabled = False
            item.auto_season = None
            item.auto_last_episode_count = 0
            item.auto_last_downloaded_at = None
            item.save(update_fields=["auto_enabled", "auto_season", "auto_last_episode_count", "auto_last_downloaded_at"])
        messages.error(request, "Auto-download non disponibile per i film.")
        return redirect("watchlist")

    auto_enabled = request.POST.get("auto_enabled") == "on"
    auto_season_raw = request.POST.get("auto_season")
    auto_season = None
    if auto_season_raw:
        try:
            auto_season = int(auto_season_raw)
        except Exception:
            auto_season = None

    if auto_enabled and not auto_season:
        messages.error(request, "Seleziona una stagione per l'auto-download.")
        return redirect("watchlist")

    if item.auto_season != auto_season:
        item.auto_last_episode_count = 0
        item.auto_last_downloaded_at = None

    item.auto_enabled = auto_enabled
    item.auto_season = auto_season if auto_enabled else None

    if not auto_enabled:
        item.auto_last_episode_count = 0

    item.save()
    messages.success(request, "Impostazioni auto-download aggiornate.")
    return redirect("watchlist")


def _update_single_item(item: WatchlistItem) -> bool:
    """Internal helper to update a single watchlist item."""
    try:
        if item.is_movie:
            item.last_checked_at = timezone.now()
            item.has_new_seasons = False
            item.has_new_episodes = False
            item.save(update_fields=["last_checked_at", "has_new_seasons", "has_new_episodes"])
            return False

        api = get_api(item.source_alias)
        item_payload = json.loads(item.item_payload)
        entries_fields = {k: v for k, v in item_payload.items() if k in Entries.__dataclass_fields__}
        media_item = Entries(**entries_fields)

        if media_item.is_movie:
            item.is_movie = True
            item.last_checked_at = timezone.now()
            item.has_new_seasons = False
            item.has_new_episodes = False
            item.save(update_fields=["is_movie", "last_checked_at", "has_new_seasons", "has_new_episodes"])
            return False

        seasons = api.get_series_metadata(media_item)

        if not seasons:
            return False

        current_num_seasons = len(seasons)
        last_season = seasons[-1]
        current_last_season_episodes = last_season.episode_count

        changed = False

        if item.num_seasons == 0:
            item.num_seasons = current_num_seasons
            item.last_season_episodes = current_last_season_episodes
            changed = True
        else:
            if current_num_seasons > item.num_seasons:
                item.has_new_seasons = True
                item.num_seasons = current_num_seasons
                changed = True

            if current_last_season_episodes > item.last_season_episodes:
                item.has_new_episodes = True
                item.last_season_episodes = current_last_season_episodes
                changed = True

        item.last_checked_at = timezone.now()
        item.save()
        return changed
    except Exception as e:
        print(f"Error updating {item.name}: {e}")
        return False


@require_http_methods(["POST"])
def update_watchlist_item(request: HttpRequest, item_id: int) -> HttpResponse:
    """Update a specific watchlist item."""
    try:
        item = WatchlistItem.objects.get(id=item_id)
        threading.Thread(target=_update_single_item, args=(item,), daemon=True).start()
        messages.info(request, f"Aggiornamento per '{item.name}' avviato in background.")
    except WatchlistItem.DoesNotExist:
        messages.error(request, "Elemento non trovato.")

    return redirect("watchlist")


@require_http_methods(["POST"])
def update_all_watchlist(request: HttpRequest) -> HttpResponse:
    """Update all items in the watchlist."""
    items = WatchlistItem.objects.all()

    def _update_all():
        for item in items:
            _update_single_item(item)

    threading.Thread(target=_update_all, daemon=True).start()
    messages.info(request, "Aggiornamento globale avviato in background. Ricarica tra qualche istante.")
    return redirect("watchlist")


@require_http_methods(["POST"])
def run_watchlist_auto_now(request: HttpRequest) -> HttpResponse:
    """Trigger the auto-download scan immediately."""
    from ..watchlist_auto import run_watchlist_auto_once
    threading.Thread(target=run_watchlist_auto_once, daemon=True).start()
    messages.info(request, "Auto-download avviato subito in background.")
    return redirect("watchlist")


def watchlist_status(request: HttpRequest) -> JsonResponse:
    """API endpoint to check if any watchlist item was updated recently."""
    last_update = WatchlistItem.objects.order_by("-last_checked_at").first()
    if last_update:
        return JsonResponse({
            "last_checked": last_update.last_checked_at.timestamp(),
            "items_count": WatchlistItem.objects.count(),
        })
    return JsonResponse({"last_checked": 0, "items_count": 0})
