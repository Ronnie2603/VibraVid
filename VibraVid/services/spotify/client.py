# 14.05.26

import logging
from typing import Any

from VibraVid.utils.os import internet_manager
from VibraVid.utils.http_client import create_client, get_userAgent


logger = logging.getLogger(__name__)
BASE_URL = "https://jumo-dl.pages.dev"
REGION = "FR"
FORMAT_ID = 27   
# 27 = FLAC; 6 = MP3 320


def format_duration(seconds: int) -> str:
    """Convert seconds to M:SS string."""
    try:
        t = internet_manager.format_time(float(seconds))
    except Exception:
        m, s = divmod(int(seconds or 0), 60)
        return f"{m}:{s:02d}"

    if not t:
        return "0:00"
    parts = t.split(":", 1)
    try:
        minutes = str(int(parts[0]))
        return f"{minutes}:{parts[1]}"
    except Exception:
        return t


def _extract_year(album: dict) -> str:
    raw = (
        album.get("release_date_original")
        or album.get("release_date_stream")
        or album.get("release_date_download")
        or ""
    )
    return raw[:4] if raw else ""


def _extract_genre(album: dict) -> str:
    genre = album.get("genre")
    
    if isinstance(genre, dict):
        return genre.get("name", "")
    return ""


class JumoClient:
    def __init__(self) -> None:
        self.client = create_client(headers={
            "accept": "*/*",
            "accept-language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "referer": f"{BASE_URL}/",
            "user-agent": get_userAgent()
        })

    def _get(self, endpoint: str, params: dict | None = None, timeout: int = 20) -> Any:
        url = f"{BASE_URL}/{endpoint.lstrip('/')}"
        resp = self.client.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def search(self, query: str, limit: int = 20) -> list[dict]:
        data = self._get("search", params={"query": query, "offset": 0, "limit": limit, "region": REGION})

        tracks: list[dict] = []
        raw_tracks: list[dict] = []

        if "tracks" in data and "items" in data["tracks"]:
            raw_tracks = data["tracks"]["items"]

        elif "albums" in data and "items" in data["albums"]:
            for album in data["albums"]["items"]:
                raw_tracks.append({"_album_mode": True, "album": album})

        for item in raw_tracks:
            if item.get("_album_mode"):
                album = item["album"]
                tracks.append({
                    "id":        None,
                    "title":     album.get("title", "—"),
                    "artist":    album.get("artist", {}).get("name", "—"),
                    "album":     album.get("title", "—"),
                    "duration":  album.get("duration", 0),
                    "explicit":  album.get("parental_warning", False),
                    "cover":     album.get("image", {}).get("large", ""),
                    "track_num": None,
                    "qobuz_id":  album.get("qobuz_id"),
                    "year":      _extract_year(album),
                    "genre":     _extract_genre(album),
                    "_raw":      album,
                })
            
            else:
                album = item.get("album", {})
                tracks.append({
                    "id":        item.get("id"),
                    "title":     item.get("title", "—"),
                    "artist":    (
                        item.get("performer", {}).get("name")
                        or album.get("artist", {}).get("name", "—")
                    ),
                    "album":     album.get("title", "—"),
                    "duration":  item.get("duration", 0),
                    "explicit":  item.get("parental_warning", False),
                    "cover":     album.get("image", {}).get("large", ""),
                    "track_num": item.get("track_number"),
                    "qobuz_id":  album.get("qobuz_id"),
                    "year":      _extract_year(album),
                    "genre":     _extract_genre(album),
                    "_raw":      item,
                })

        return tracks

    def fetch_stream(self, track_id: int, format_id: int = FORMAT_ID) -> dict:
        return self._get("fetch", params={"track_id": track_id, "format_id": format_id, "region": REGION})