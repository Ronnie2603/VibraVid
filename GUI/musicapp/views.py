# musicapp/views.py
# All views for the Music section: search, track detail, playlist, artist, download queue.

from __future__ import annotations

import os
import json
import threading
import concurrent.futures
import time
import logging
from typing import Dict, Any, List

from django.shortcuts import render, redirect
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages

from VibraVid.utils import config_manager
from VibraVid.services._base.site_costant import site_constants
from .models import DownloadedTrack
from VibraVid.services.ytmusic.client import (
    MusicTrack,
    MusicPlaylist,
    ArtistDetails,
    search_tracks,
    search_albums,
    get_ytmusic_playlist,
    get_audio_formats,
    get_artist_details,
    get_album_tracks,
    resolve_spotify_track,
    resolve_spotify_playlist,
    resolve_youtube_track,
    detect_input_type,
    download_track,
)

logger = logging.getLogger(__name__)

# ─── Download queue ───────────────────────────────────────────────────────────

_music_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="MusicDownload"
)
_music_downloads: Dict[str, Dict[str, Any]] = {}
_music_lock = threading.Lock()


def _music_output_dir() -> str:
    """Return the configured Music output directory (same root as Video/Serie/Movie)."""
    try:
        folder = site_constants.MUSIC_FOLDER
        if not os.path.isabs(folder):
            import pathlib
            project_root = pathlib.Path(__file__).resolve().parents[3]
            folder = str(project_root / folder)
        return folder
    except Exception as e:
        logger.error(f"[_music_output_dir] Failed to resolve music folder: {e}", exc_info=True)
        return os.path.join(os.path.expanduser("~"), "Music", "VibraVid")


def _add_music_download(dl_id: str, title: str, artist: str, url: str, format_id: str) -> None:
    with _music_lock:
        _music_downloads[dl_id] = {
            "id": dl_id,
            "title": title,
            "artist": artist,
            "url": url,
            "format_id": format_id,
            "status": "queued",
            "started_at": time.time(),
            "error": None,
        }


def _update_music_download(dl_id: str, status: str, error: str = None) -> None:
    with _music_lock:
        if dl_id in _music_downloads:
            _music_downloads[dl_id]["status"] = status
            if error:
                _music_downloads[dl_id]["error"] = error


def _get_music_downloads() -> List[Dict[str, Any]]:
    with _music_lock:
        return sorted(_music_downloads.values(), key=lambda x: x.get("started_at", 0))


def _enqueue_download(video_id: str, title: str, artist: str, format_id: str, url: str = "", playlist_name: str = "") -> str:
    """Submit one track download to the executor. Returns the download ID."""
    dl_id = f"music_{int(time.time() * 1000)}_{hash(video_id) % 100000}"
    track_url = url or f"https://music.youtube.com/watch?v={video_id}"
    output_dir = _music_output_dir()
    
    # Pre-check database for duplicates (instant skip)
    if video_id and DownloadedTrack.objects.filter(video_id=video_id).exists():
        _add_music_download(dl_id, title, artist, track_url, format_id)
        _update_music_download(dl_id, "completed")
        _handle_playlist_symlink(output_dir, playlist_name, DownloadedTrack.objects.filter(video_id=video_id).first().file_path)
        return dl_id
        
    if DownloadedTrack.objects.filter(artist__iexact=artist, title__iexact=title).exists():
        _add_music_download(dl_id, title, artist, track_url, format_id)
        _update_music_download(dl_id, "completed")
        _handle_playlist_symlink(output_dir, playlist_name, DownloadedTrack.objects.filter(artist__iexact=artist, title__iexact=title).first().file_path)
        return dl_id

    _add_music_download(dl_id, title, artist, track_url, format_id)

    def _task(dl_id=dl_id, track_url=track_url, output_dir=output_dir, format_id=format_id, video_id=video_id, title=title, artist=artist, playlist_name=playlist_name):
        try:
            _update_music_download(dl_id, "downloading")
            success = download_track(track_url, output_dir, format_id)
            if success:
                _update_music_download(dl_id, "completed")
                # Find the downloaded file to save in DB and create symlink
                final_file = _find_downloaded_file(output_dir, artist, title)
                if final_file:
                    rel_path = os.path.relpath(final_file, output_dir)
                    # Extract album from path if possible (Artist/Album/File)
                    parts = rel_path.split(os.sep)
                    album = parts[1] if len(parts) >= 3 else ""
                    DownloadedTrack.objects.update_or_create(
                        file_path=rel_path,
                        defaults={
                            "video_id": video_id,
                            "title": title,
                            "artist": artist,
                            "album": album
                        }
                    )
                    _handle_playlist_symlink(output_dir, playlist_name, rel_path)
            else:
                _update_music_download(dl_id, "failed")
        except Exception as e:
            _update_music_download(dl_id, "failed", error=str(e))

    _music_executor.submit(_task)
    return dl_id


def _find_downloaded_file(base_dir: str, artist: str, title: str) -> Optional[str]:
    artist_lower = artist.lower()
    title_lower = title.lower()
    for root, dirs, files in os.walk(base_dir):
        if "Playlists" in root:
            continue
        for f in files:
            f_lower = f.lower()
            if title_lower in f_lower and (artist_lower in f_lower or artist_lower in root.lower()):
                return os.path.join(root, f)
    return None


def _handle_playlist_symlink(output_dir: str, playlist_name: str, rel_path: str):
    if not playlist_name or not rel_path:
        return
        
    playlist_dir = os.path.join(output_dir, "Playlists", "".join(c for c in playlist_name if c.isalnum() or c in " -_").strip())
    os.makedirs(playlist_dir, exist_ok=True)
    
    target_file = os.path.join(output_dir, rel_path)
    link_name = os.path.basename(rel_path)
    link_path = os.path.join(playlist_dir, link_name)
    
    if os.path.exists(link_path):
        return
        
    try:
        os.symlink(target_file, link_path)
    except OSError:
        try:
            os.link(target_file, link_path) # Fallback to hardlink
        except OSError:
            # Fallback to m3u playlist entry if links fail
            m3u_path = os.path.join(playlist_dir, f"{playlist_name}.m3u")
            with open(m3u_path, "a", encoding="utf-8") as f:
                f.write(f"../../{rel_path}\n")

# ─── Library & Sync ─────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def music_library(request: HttpRequest) -> HttpResponse:
    tracks = DownloadedTrack.objects.all().order_by("-downloaded_at")
    return render(request, "musicapp/library.html", {"tracks": tracks})

@csrf_exempt
@require_http_methods(["POST"])
def sync_library(request: HttpRequest) -> JsonResponse:
    output_dir = _music_output_dir()
    added = 0
    valid_exts = {".opus", ".m4a", ".mp3", ".webm"}
    
    try:
        for root, dirs, files in os.walk(output_dir):
            if "Playlists" in root:
                continue
            for f in files:
                if any(f.endswith(ext) for ext in valid_exts):
                    rel_path = os.path.relpath(os.path.join(root, f), output_dir)
                    parts = rel_path.split(os.sep)
                    
                    if len(parts) >= 3:
                        artist = parts[0]
                        album = parts[1]
                        filename = parts[-1]
                        title = os.path.splitext(filename)[0].replace(f"{artist} - ", "", 1)
                    else:
                        artist = "Unknown"
                        album = ""
                        title = os.path.splitext(f)[0]
                        
                    _, created = DownloadedTrack.objects.update_or_create(
                        file_path=rel_path,
                        defaults={
                            "title": title,
                            "artist": artist,
                            "album": album
                        }
                    )
                    if created:
                        added += 1
                        
        return JsonResponse({"status": "ok", "added": added})
    except Exception as e:
        logger.exception("[musicapp] sync_library error")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


# ─── API ──────────────────────────────────────────────────────────────────────

# ─── Home ─────────────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def music_home(request: HttpRequest) -> HttpResponse:
    return render(request, "musicapp/home.html", {})


# ─── Search ───────────────────────────────────────────────────────────────────

@require_http_methods(["GET", "POST"])
def music_search(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        raw_input = request.POST.get("query", "").strip()
    else:
        raw_input = request.GET.get("query", "").strip()

    if not raw_input:
        return redirect("music_home")

    search_filter = request.GET.get("filter", "tracks")  # tracks | albums | all
    input_type = detect_input_type(raw_input)
    context: Dict[str, Any] = {"query": raw_input, "input_type": input_type, "search_filter": search_filter}

    try:
        if input_type == "spotify_track":
            results = resolve_spotify_track(raw_input) or []
            context["results"] = [t.to_dict() for t in results]
            context["mode"] = "track_results"
            context["subtitle"] = "Risultati da Spotify → YouTube Music"

        elif input_type == "spotify_playlist":
            playlist = resolve_spotify_playlist(raw_input)
            if playlist:
                context["playlist"] = playlist.to_dict()
                context["mode"] = "spotify_playlist"
                context["subtitle"] = f"Playlist Spotify: {playlist.title}"
            else:
                messages.error(request, "Impossibile caricare la playlist Spotify.")
                return redirect("music_home")

        elif input_type == "ytmusic_playlist":
            playlist = get_ytmusic_playlist(raw_input)
            context["playlist"] = playlist.to_dict()
            context["mode"] = "ytmusic_playlist"
            context["subtitle"] = f"Playlist YouTube Music: {playlist.title}"

        elif input_type == "youtube_url":
            results = resolve_youtube_track(raw_input) or []
            context["results"] = [t.to_dict() for t in results]
            context["mode"] = "track_results"
            context["subtitle"] = "Risultati da link YouTube → YouTube Music"

        elif input_type == "ytmusic_url":
            import re as _re
            m = _re.search(r"[?&]v=([^&]+)", raw_input)
            video_id = m.group(1) if m else raw_input
            track = MusicTrack(video_id=video_id, title="Brano selezionato", artists=[], url=raw_input)
            context["track"] = track.to_dict()
            context["mode"] = "track_detail_direct"
            context["subtitle"] = "Link YouTube Music diretto"

        else:
            # Plain text search — support filter param
            track_results = []
            album_results = []

            if search_filter in ("tracks", "all"):
                track_results = search_tracks(raw_input, limit=10)
            if search_filter in ("albums", "all"):
                album_results = search_albums(raw_input, limit=10)

            context["results"] = [t.to_dict() for t in track_results]
            context["album_results"] = [a.to_dict() for a in album_results]
            context["mode"] = "track_results"
            context["subtitle"] = f'Risultati per "{raw_input}"'

    except Exception as e:
        logger.exception(f"[musicapp] Search error: {e}")
        messages.error(request, f"Errore nella ricerca: {e}")
        return redirect("music_home")

    context["filter_choices"] = [
        ("tracks", "Brani"),
        ("albums", "Album"),
        ("all", "Tutti"),
    ]
    return render(request, "musicapp/results.html", context)


# ─── Track detail (formats) ───────────────────────────────────────────────────

@require_http_methods(["GET"])
def track_detail(request: HttpRequest) -> HttpResponse:
    video_id = request.GET.get("video_id", "").strip()
    title = request.GET.get("title", "Brano")
    artist = request.GET.get("artist", "")
    thumbnail = request.GET.get("thumbnail", "")

    if not video_id:
        messages.error(request, "ID brano mancante.")
        return redirect("music_home")

    try:
        formats = get_audio_formats(video_id)
    except Exception as e:
        logger.warning(f"[musicapp] Format fetch failed: {e}")
        formats = []

    return render(request, "musicapp/track_detail.html", {
        "video_id": video_id,
        "title": title,
        "artist": artist,
        "thumbnail": thumbnail,
        "formats": [f.to_dict() for f in formats],
        "url": f"https://music.youtube.com/watch?v={video_id}",
    })


# ─── Artist detail ────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def artist_detail(request: HttpRequest, channel_id: str) -> HttpResponse:
    """Artist page: top tracks, albums, singles."""
    artist = get_artist_details(channel_id)
    if not artist:
        messages.error(request, "Impossibile caricare i dettagli dell'artista.")
        return redirect("music_home")

    return render(request, "musicapp/artist_detail.html", {
        "artist": artist.to_dict(),
    })


@require_http_methods(["GET"])
def artist_all_tracks_json(request: HttpRequest, channel_id: str) -> JsonResponse:
    """
    Lazy-load API: returns ALL tracks for an artist by iterating every
    album and single and fetching their tracklists concurrently.
    Called via AJAX from the artist_detail page.
    """
    import concurrent.futures as _cf

    artist = get_artist_details(channel_id)
    if not artist:
        return JsonResponse({"error": "Artista non trovato"}, status=404)

    # Collect all album browse_ids (albums + singles/EPs)
    album_dicts = artist.to_dict()
    all_albums = album_dicts.get("albums", []) + album_dicts.get("singles", [])
    browse_ids = [a["browse_id"] for a in all_albums if a.get("browse_id")]

    all_tracks: List[Dict[str, Any]] = []
    seen_ids: set = set()

    def _fetch(browse_id: str):
        try:
            pl = get_album_tracks(browse_id)
            return pl.to_dict()["tracks"] if pl else []
        except Exception:
            return []

    # Fetch all albums concurrently (max 8 workers)
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_fetch, bid): bid for bid in browse_ids}
        for fut in _cf.as_completed(futures):
            for t in fut.result():
                vid = t.get("video_id", "")
                if vid and vid not in seen_ids:
                    seen_ids.add(vid)
                    all_tracks.append(t)

    # Sort by album title then track order (stable enough without track_number)
    all_tracks.sort(key=lambda t: (t.get("album") or "", t.get("title") or ""))

    return JsonResponse({
        "artist": artist.to_dict()["name"],
        "total": len(all_tracks),
        "tracks": all_tracks,
    })


# ─── Album detail ──────────────────────────────────────────────────

@require_http_methods(["GET"])
def album_detail(request: HttpRequest) -> HttpResponse:
    """Album detail page: shows all tracks with selection + download."""
    browse_id = request.GET.get("browse_id", "").strip()
    if not browse_id:
        messages.error(request, "ID album mancante.")
        return redirect("music_home")

    try:
        playlist = get_album_tracks(browse_id)
    except Exception as e:
        messages.error(request, f"Errore nel caricamento dell'album: {e}")
        return redirect("music_home")

    if not playlist:
        messages.error(request, "Album non trovato o non caricabile.")
        return redirect("music_home")

    return render(request, "musicapp/album_detail.html", {
        "album": playlist.to_dict(),
        "browse_id": browse_id,
    })


# ─── Playlist detail ──────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def playlist_detail(request: HttpRequest) -> HttpResponse:
    playlist_id = request.GET.get("playlist_id", "").strip()
    source = request.GET.get("source", "ytmusic")

    if not playlist_id:
        messages.error(request, "ID playlist mancante.")
        return redirect("music_home")

    try:
        playlist = get_ytmusic_playlist(playlist_id)
    except Exception as e:
        messages.error(request, f"Errore nel caricamento della playlist: {e}")
        return redirect("music_home")

    return render(request, "musicapp/playlist_detail.html", {
        "playlist": playlist.to_dict(),
    })


# ─── Download API ─────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def start_music_download(request: HttpRequest) -> JsonResponse:
    """Start download for one or more tracks. Accepts JSON body."""
    try:
        if request.content_type and "application/json" in request.content_type:
            body = json.loads(request.body.decode("utf-8"))
        else:
            body = request.POST.dict()

        playlist_name = body.get("playlist_name", "")
        tracks_raw = body.get("tracks")
        if not tracks_raw:
            video_id = body.get("video_id", "")
            title = body.get("title", "Unknown")
            artist = body.get("artist", "")
            format_id = body.get("format_id", "bestaudio")
            url = body.get("url", "")
            tracks_raw = [{"video_id": video_id, "title": title, "artist": artist,
                           "format_id": format_id, "url": url}]

        started = []
        for t in tracks_raw:
            video_id = t.get("video_id", "")
            if not video_id:
                continue
            dl_id = _enqueue_download(
                video_id=video_id,
                title=t.get("title", "Unknown"),
                artist=t.get("artist", ""),
                format_id=t.get("format_id", "bestaudio"),
                url=t.get("url", ""),
                playlist_name=playlist_name,
            )
            started.append(dl_id)

        return JsonResponse({
            "status": "ok",
            "started": started,
            "output_dir": _music_output_dir(),
        })

    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@require_http_methods(["GET"])
def music_downloads(request: HttpRequest) -> HttpResponse:
    return render(request, "musicapp/downloads.html", {
        "downloads": _get_music_downloads(),
        "output_dir": _music_output_dir(),
    })


@require_http_methods(["GET"])
def get_music_downloads_json(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"downloads": _get_music_downloads()})


@require_http_methods(["GET"])
def get_track_formats_json(request: HttpRequest) -> JsonResponse:
    video_id = request.GET.get("video_id", "").strip()
    if not video_id:
        return JsonResponse({"error": "video_id mancante"}, status=400)
    try:
        formats = get_audio_formats(video_id)
        return JsonResponse({"formats": [f.to_dict() for f in formats]})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["GET"])
def get_album_tracks_json(request: HttpRequest) -> JsonResponse:
    """Return album tracks as JSON for the album_detail page JS."""
    browse_id = request.GET.get("browse_id", "").strip()
    if not browse_id:
        return JsonResponse({"error": "browse_id mancante"}, status=400)
    try:
        playlist = get_album_tracks(browse_id)
        if not playlist:
            return JsonResponse({"error": "Album non trovato"}, status=404)
        return JsonResponse({"album": playlist.to_dict()})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

@require_http_methods(["GET"])
def resolve_spotify_track_api(request: HttpRequest) -> JsonResponse:
    """
    Lightweight API: given a Spotify track title + artist, return the first
    YouTube Music match (video_id, thumbnail, url, artist_str).

    GET params:
      - title: track title
      - artist: primary artist name

    Returns JSON: { video_id, title, artist_str, thumbnail, url } or { error }
    """
    # Normalize: strip + replace non-breaking spaces (\xa0, %C2%A0) with regular spaces
    # These come from Spotify's subtitle field and cause 404s in Django URL matching
    def _clean(s: str) -> str:
        return s.replace("\xa0", " ").replace("\u00a0", " ").strip()

    title  = _clean(request.GET.get("title",  ""))
    artist = _clean(request.GET.get("artist", ""))

    if not title:
        return JsonResponse({"error": "title mancante"}, status=400)

    query = f"{artist} {title}".strip()
    try:
        results = search_tracks(query, limit=1)
        if not results:
            # Return 200 (not 404) so the JS batch resolver marks it as "not found"
            # rather than treating it as a network/server error
            return JsonResponse({"error": "nessun risultato"})
        track = results[0]
        return JsonResponse({
            "video_id":   track.video_id,
            "title":      track.title,
            "artist_str": track.artist_str,
            "thumbnail":  track.thumbnail or "",
            "url":        track.yt_url,
        })
    except Exception as e:
        logger.exception(f"[musicapp] resolve_spotify_track_api error: {e}")
        return JsonResponse({"error": str(e)}, status=500)
