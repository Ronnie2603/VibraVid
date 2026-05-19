# VibraVid/services/ytmusic/client.py
# Core client: search tracks/playlists on YouTube Music using ytmusicapi,
# with a yt-dlp fallback when ytmusicapi is unavailable.
# Also provides Spotify link scraping (no API keys needed) and yt-dlp format listing.

from __future__ import annotations

import os
import re
import sys
import json
import subprocess
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


# ─── yt-dlp helper ───────────────────────────────────────────────────────────
# On Windows, calling "yt-dlp" as a bare string may fail with [WinError 2]
# (executable not found). Using `sys.executable -m yt_dlp` guarantees we run
# the copy installed in the active virtual-environment.

def _ytdlp_cmd() -> List[str]:
    """Return the yt-dlp command that works in any OS/venv."""
    return [sys.executable, "-m", "yt_dlp"]


def _ffmpeg_location() -> Optional[str]:
    """Return the path to an ffmpeg executable.
    Prefers the bundled binary from imageio-ffmpeg (installed in the venv),
    falls back to whatever is on PATH.
    """
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    # Check PATH as fallback
    import shutil
    return shutil.which("ffmpeg")  # may be None if not on PATH


# ─── Data models ──────────────────────────────────────────────────────────────

@dataclass
class MusicArtist:
    """An artist reference (from ytmusicapi results)."""
    name: str
    channel_id: Optional[str] = None  # browseId from ytmusicapi

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "channel_id": self.channel_id}


@dataclass
class MusicTrack:
    """A single music track result."""
    video_id: str
    title: str
    # Now a list of MusicArtist objects (or plain strings for yt-dlp fallback)
    artists: List[Any] = field(default_factory=list)
    album: Optional[str] = None
    album_id: Optional[str] = None  # browseId of the album
    duration_seconds: Optional[int] = None
    thumbnail: Optional[str] = None
    year: Optional[int] = None
    url: str = ""

    @property
    def artist_str(self) -> str:
        if not self.artists:
            return "Unknown"
        parts = []
        for a in self.artists:
            if isinstance(a, MusicArtist):
                parts.append(a.name)
            elif isinstance(a, dict):
                parts.append(a.get("name", ""))
            else:
                parts.append(str(a))
        return ", ".join(p for p in parts if p)

    def artists_list(self) -> List[Dict[str, Any]]:
        """Return artists as list of dicts (safe for JSON / template)."""
        result = []
        for a in self.artists:
            if isinstance(a, MusicArtist):
                result.append(a.to_dict())
            elif isinstance(a, dict):
                result.append({"name": a.get("name", ""), "channel_id": a.get("channel_id") or a.get("id")})
            else:
                result.append({"name": str(a), "channel_id": None})
        return result

    @property
    def yt_url(self) -> str:
        return self.url or f"https://music.youtube.com/watch?v={self.video_id}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "artists": self.artists_list(),
            "artist_str": self.artist_str,
            "album": self.album,
            "album_id": self.album_id,
            "duration_seconds": self.duration_seconds,
            "thumbnail": self.thumbnail,
            "year": self.year,
            "url": self.yt_url,
        }


@dataclass
class MusicAlbum:
    """An album result from ytmusicapi."""
    browse_id: str
    title: str
    artists: List[MusicArtist] = field(default_factory=list)
    year: Optional[int] = None
    thumbnail: Optional[str] = None
    album_type: str = "Album"  # Album | Single | EP

    @property
    def artist_str(self) -> str:
        return ", ".join(a.name for a in self.artists) if self.artists else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "browse_id": self.browse_id,
            "title": self.title,
            "artists": [a.to_dict() for a in self.artists],
            "artist_str": self.artist_str,
            "year": self.year,
            "thumbnail": self.thumbnail,
            "album_type": self.album_type,
        }


@dataclass
class MusicPlaylist:
    """A playlist (YT Music or Spotify)."""
    playlist_id: str
    title: str
    description: Optional[str] = None
    thumbnail: Optional[str] = None
    track_count: Optional[int] = None
    tracks: List[MusicTrack] = field(default_factory=list)
    source: str = "ytmusic"  # 'ytmusic' | 'spotify'

    def to_dict(self) -> Dict[str, Any]:
        return {
            "playlist_id": self.playlist_id,
            "title": self.title,
            "description": self.description,
            "thumbnail": self.thumbnail,
            "track_count": self.track_count or len(self.tracks),
            "tracks": [t.to_dict() for t in self.tracks],
            "source": self.source,
        }


@dataclass
class AudioFormat:
    """An available audio format for a track (from yt-dlp)."""
    format_id: str
    ext: str
    quality: str
    bitrate: Optional[float] = None
    filesize: Optional[int] = None
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format_id": self.format_id,
            "ext": self.ext,
            "quality": self.quality,
            "bitrate": self.bitrate,
            "filesize": self.filesize,
            "note": self.note,
        }


# ─── ytmusicapi wrapper ───────────────────────────────────────────────────────

def _ytmusicapi_available() -> bool:
    try:
        import ytmusicapi  # noqa: F401
        return True
    except ImportError:
        return False


def _parse_artists(raw: Optional[List[Dict]]) -> List[MusicArtist]:
    """Parse the 'artists' field from a ytmusicapi result into MusicArtist objects."""
    if not raw:
        return []
    result = []
    for a in raw:
        name = a.get("name", "")
        channel_id = a.get("id")  # ytmusicapi uses "id" for browseId
        if name:
            result.append(MusicArtist(name=name, channel_id=channel_id))
    return result


def _search_ytmusicapi(query: str, limit: int = 10) -> List[MusicTrack]:
    """Search YouTube Music using ytmusicapi."""
    from ytmusicapi import YTMusic
    yt = YTMusic()
    results = yt.search(query, filter="songs", limit=limit)
    tracks: List[MusicTrack] = []
    for r in results[:limit]:
        video_id = r.get("videoId") or ""
        title = r.get("title") or "Unknown"
        artists = _parse_artists(r.get("artists"))
        album_info = r.get("album") or {}
        album = album_info.get("name") if isinstance(album_info, dict) else None
        album_id = album_info.get("id") if isinstance(album_info, dict) else None
        duration_seconds = r.get("duration_seconds")
        thumbnails = r.get("thumbnails") or []
        thumbnail = thumbnails[-1].get("url") if thumbnails else None
        year = r.get("year")
        tracks.append(MusicTrack(
            video_id=video_id,
            title=title,
            artists=artists,
            album=album,
            album_id=album_id,
            duration_seconds=duration_seconds,
            thumbnail=thumbnail,
            year=year,
        ))
    return tracks


def _search_ytdlp_fallback(query: str, limit: int = 10) -> List[MusicTrack]:
    """Fallback: search YouTube Music via yt-dlp ytsearch."""
    try:
        cmd = _ytdlp_cmd() + [
            "--dump-json",
            "--no-playlist",
            "--quiet",
            f"ytsearch{limit}:{query}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        tracks: List[MusicTrack] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                info = json.loads(line)
                video_id = info.get("id") or ""
                title = info.get("title") or "Unknown"
                channel = info.get("channel") or info.get("uploader") or "Unknown"
                duration = info.get("duration")
                thumbnail = info.get("thumbnail")
                year = info.get("upload_date", "")[:4] or None
                year = int(year) if year and year.isdigit() else None
                tracks.append(MusicTrack(
                    video_id=video_id,
                    title=title,
                    artists=[MusicArtist(name=channel)],
                    duration_seconds=duration,
                    thumbnail=thumbnail,
                    year=year,
                ))
            except Exception:
                continue
        return tracks[:limit]
    except Exception as e:
        logger.warning(f"[ytmusic] yt-dlp fallback search failed: {e}")
        return []


def search_tracks(query: str, limit: int = 10) -> List[MusicTrack]:
    """Search YouTube Music. Uses ytmusicapi if available, otherwise falls back to yt-dlp."""
    if _ytmusicapi_available():
        try:
            return _search_ytmusicapi(query, limit)
        except Exception as e:
            logger.warning(f"[ytmusic] ytmusicapi search failed, falling back to yt-dlp: {e}")
    return _search_ytdlp_fallback(query, limit)


def search_artists(query: str, limit: int = 10) -> List["MusicArtist"]:
    """Search YouTube Music for artists by name. Requires ytmusicapi."""
    if not _ytmusicapi_available():
        logger.warning("[ytmusic] ytmusicapi not available — cannot search artists")
        return []
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        results = yt.search(query, filter="artists", limit=limit)
        artists: List[MusicArtist] = []
        for r in results[:limit]:
            name = r.get("artist") or r.get("title") or "Unknown"
            channel_id = r.get("browseId") or r.get("artistId") or ""
            artists.append(MusicArtist(name=name, channel_id=channel_id))
        return artists
    except Exception as e:
        logger.warning(f"[ytmusic] search_artists failed: {e}")
        return []


def search_albums(query: str, limit: int = 10) -> List["MusicAlbum"]:
    """Search YouTube Music for albums by title/artist. Requires ytmusicapi."""
    if not _ytmusicapi_available():
        logger.warning("[ytmusic] ytmusicapi not available — cannot search albums")
        return []
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        results = yt.search(query, filter="albums", limit=limit)
        albums: List[MusicAlbum] = []
        for r in results[:limit]:
            browse_id = r.get("browseId") or ""
            title = r.get("title") or "Unknown"
            raw_artists = r.get("artists") or []
            al_artists = _parse_artists(raw_artists)
            year = r.get("year")
            thumbs = r.get("thumbnails") or []
            thumb = thumbs[-1].get("url") if thumbs else None
            al_type = r.get("type") or "Album"
            albums.append(MusicAlbum(
                browse_id=browse_id,
                title=title,
                artists=al_artists,
                year=year,
                thumbnail=thumb,
                album_type=al_type,
            ))
        return albums
    except Exception as e:
        logger.warning(f"[ytmusic] search_albums failed: {e}")
        return []


def get_album_tracks(browse_id: str) -> Optional["MusicPlaylist"]:
    """
    Fetch full album details and return its tracks as a MusicPlaylist.
    browse_id is the ytmusicapi browseId for the album.
    Requires ytmusicapi.
    """
    if not _ytmusicapi_available():
        logger.warning("[ytmusic] ytmusicapi not available — cannot fetch album tracks")
        return None
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        data = yt.get_album(browse_id)

        title = data.get("title") or "Album"
        thumbs = data.get("thumbnails") or []
        thumbnail = thumbs[-1].get("url") if thumbs else None
        description = data.get("description")
        raw_artists = data.get("artists") or []
        al_artists = _parse_artists(raw_artists)
        year = data.get("year")

        tracks: List[MusicTrack] = []
        for r in (data.get("tracks") or []):
            video_id = r.get("videoId") or ""
            if not video_id:
                continue
            t_title = r.get("title") or "Unknown"
            t_artists = _parse_artists(r.get("artists") or []) or al_artists
            duration_seconds = r.get("duration_seconds")
            t_thumbs = r.get("thumbnails") or thumbs
            t_thumb = t_thumbs[-1].get("url") if t_thumbs else thumbnail
            tracks.append(MusicTrack(
                video_id=video_id,
                title=t_title,
                artists=t_artists,
                album=title,
                thumbnail=t_thumb,
                duration_seconds=duration_seconds,
                year=year,
            ))

        return MusicPlaylist(
            playlist_id=browse_id,
            title=title,
            description=description,
            thumbnail=thumbnail,
            track_count=len(tracks),
            tracks=tracks,
            source="ytmusic",
        )
    except Exception as e:
        logger.error(f"[ytmusic] get_album_tracks failed for {browse_id}: {e}", exc_info=True)
        return None


# ─── Artist details ───────────────────────────────────────────────────────────

@dataclass
class ArtistDetails:
    """Full details of a YouTube Music artist page."""
    channel_id: str
    name: str
    description: Optional[str] = None
    thumbnail: Optional[str] = None
    banner: Optional[str] = None
    views: Optional[str] = None
    top_tracks: List[MusicTrack] = field(default_factory=list)
    albums: List[MusicAlbum] = field(default_factory=list)
    singles: List[MusicAlbum] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "name": self.name,
            "description": self.description,
            "thumbnail": self.thumbnail,
            "banner": self.banner,
            "views": self.views,
            "top_tracks": [t.to_dict() for t in self.top_tracks],
            "albums": [a.to_dict() for a in self.albums],
            "singles": [s.to_dict() for s in self.singles],
        }


def get_artist_details(channel_id: str) -> Optional[ArtistDetails]:
    """Fetch full artist info from YouTube Music using ytmusicapi."""
    if not _ytmusicapi_available():
        logger.warning("[ytmusic] ytmusicapi not available — cannot fetch artist details")
        return None
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic()
        data = yt.get_artist(channel_id)

        name = data.get("name") or "Unknown Artist"
        description = data.get("description")

        # Thumbnails
        thumbnails = data.get("thumbnails") or []
        thumbnail = thumbnails[-1].get("url") if thumbnails else None

        # Banner (may not always exist)
        banner = None
        banner_list = data.get("banner") or []
        if banner_list:
            banner = banner_list[-1].get("url")

        views = data.get("views")

        # Top tracks ── ytmusicapi returns them under data["songs"]["results"]
        top_tracks: List[MusicTrack] = []
        songs_section = data.get("songs") or {}
        for r in (songs_section.get("results") or []):
            video_id = r.get("videoId") or ""
            if not video_id:
                continue
            t_title = r.get("title") or "Unknown"
            t_artists = _parse_artists(r.get("artists"))
            album_info = r.get("album") or {}
            album = album_info.get("name") if isinstance(album_info, dict) else None
            album_id = album_info.get("id") if isinstance(album_info, dict) else None
            thumbs = r.get("thumbnails") or []
            t_thumb = thumbs[-1].get("url") if thumbs else thumbnail
            top_tracks.append(MusicTrack(
                video_id=video_id,
                title=t_title,
                artists=t_artists,
                album=album,
                album_id=album_id,
                thumbnail=t_thumb,
            ))

        # Albums
        albums: List[MusicAlbum] = []
        albums_section = data.get("albums") or {}
        for r in (albums_section.get("results") or []):
            browse_id = r.get("browseId") or ""
            al_title = r.get("title") or "Unknown"
            al_artists = _parse_artists(r.get("artists"))
            al_year = r.get("year")
            al_thumbs = r.get("thumbnails") or []
            al_thumb = al_thumbs[-1].get("url") if al_thumbs else None
            al_type = r.get("type") or "Album"
            albums.append(MusicAlbum(
                browse_id=browse_id,
                title=al_title,
                artists=al_artists,
                year=al_year,
                thumbnail=al_thumb,
                album_type=al_type,
            ))

        # Singles
        singles: List[MusicAlbum] = []
        singles_section = data.get("singles") or {}
        for r in (singles_section.get("results") or []):
            browse_id = r.get("browseId") or ""
            s_title = r.get("title") or "Unknown"
            s_artists = _parse_artists(r.get("artists"))
            s_year = r.get("year")
            s_thumbs = r.get("thumbnails") or []
            s_thumb = s_thumbs[-1].get("url") if s_thumbs else None
            singles.append(MusicAlbum(
                browse_id=browse_id,
                title=s_title,
                artists=s_artists,
                year=s_year,
                thumbnail=s_thumb,
                album_type="Single",
            ))

        return ArtistDetails(
            channel_id=channel_id,
            name=name,
            description=description,
            thumbnail=thumbnail,
            banner=banner,
            views=views,
            top_tracks=top_tracks,
            albums=albums,
            singles=singles,
        )
    except Exception as e:
        logger.error(f"[ytmusic] get_artist_details failed for {channel_id}: {e}", exc_info=True)
        return None


# ─── Playlist extraction ──────────────────────────────────────────────────────

def get_ytmusic_playlist(playlist_id_or_url: str) -> MusicPlaylist:
    """Fetch a YouTube Music playlist and its tracks."""
    playlist_id = playlist_id_or_url
    match = re.search(r"[?&]list=([^&]+)", playlist_id_or_url)
    if match:
        playlist_id = match.group(1)

    if _ytmusicapi_available():
        try:
            from ytmusicapi import YTMusic
            yt = YTMusic()
            pl = yt.get_playlist(playlist_id, limit=500)
            title = pl.get("title") or "Playlist"
            description = pl.get("description")
            thumbnails = pl.get("thumbnails") or []
            thumbnail = thumbnails[-1].get("url") if thumbnails else None
            track_count = pl.get("trackCount")

            tracks: List[MusicTrack] = []
            for r in (pl.get("tracks") or []):
                video_id = r.get("videoId") or ""
                if not video_id:
                    continue
                t_title = r.get("title") or "Unknown"
                artists = _parse_artists(r.get("artists"))
                album_info = r.get("album") or {}
                album = album_info.get("name") if isinstance(album_info, dict) else None
                album_id = album_info.get("id") if isinstance(album_info, dict) else None
                duration_seconds = r.get("duration_seconds")
                t_thumbnails = r.get("thumbnails") or []
                t_thumbnail = t_thumbnails[-1].get("url") if t_thumbnails else thumbnail
                tracks.append(MusicTrack(
                    video_id=video_id,
                    title=t_title,
                    artists=artists,
                    album=album,
                    album_id=album_id,
                    duration_seconds=duration_seconds,
                    thumbnail=t_thumbnail,
                ))

            return MusicPlaylist(
                playlist_id=playlist_id,
                title=title,
                description=description,
                thumbnail=thumbnail,
                track_count=track_count,
                tracks=tracks,
                source="ytmusic",
            )
        except Exception as e:
            logger.warning(f"[ytmusic] ytmusicapi playlist fetch failed: {e}")

    return _get_playlist_ytdlp(playlist_id_or_url)


def _get_playlist_ytdlp(url: str) -> MusicPlaylist:
    """Fetch playlist tracks via yt-dlp."""
    try:
        cmd = _ytdlp_cmd() + ["--dump-json", "--flat-playlist", "--quiet", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        tracks: List[MusicTrack] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                info = json.loads(line)
                video_id = info.get("id") or ""
                title = info.get("title") or "Unknown"
                channel = info.get("channel") or info.get("uploader") or "Unknown"
                tracks.append(MusicTrack(
                    video_id=video_id,
                    title=title,
                    artists=[MusicArtist(name=channel)],
                ))
            except Exception:
                continue
        return MusicPlaylist(playlist_id=url, title="Playlist", tracks=tracks, source="ytmusic")
    except Exception as e:
        logger.error(f"[ytmusic] yt-dlp playlist fetch failed: {e}")
        return MusicPlaylist(playlist_id=url, title="Playlist", tracks=[], source="ytmusic")


# ─── Spotify metadata extraction ──────────────────────────────────────────────
# Strategy (in order of reliability):
#   1. Spotify oEmbed API  — public, no auth, returns JSON with title+author
#   2. __NEXT_DATA__ blob  — Spotify embeds full JSON in the page <script>
#   3. HTML og:/title tags — last resort, often empty on JS-rendered pages

_SPOTIFY_TRACK_RE    = re.compile(r"spotify\.com/(?:[a-zA-Z-]+/)?track/([A-Za-z0-9]+)")
_SPOTIFY_PLAYLIST_RE = re.compile(r"spotify\.com/(?:[a-zA-Z-]+/)?playlist/([A-Za-z0-9]+)")

_SPOTIFY_OEMBED = "https://open.spotify.com/oembed"
_REQUESTS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Spotify token extraction ──────────────────────────────────────────────────

# Common patterns Spotify uses to embed the access token in page HTML/JS
_TOKEN_PATTERNS = [
    re.compile(r'"accessToken"\s*:\s*"([A-Za-z0-9_\-\.]{50,})"'),
    re.compile(r"'accessToken'\s*:\s*'([A-Za-z0-9_\-\.]{50,})'"),
    re.compile(r'accessToken[":]+\s*["\']([A-Za-z0-9_\-\.]{50,})["\']'),
]


def _extract_token_from_embed(html: str, nd: Optional[Dict] = None) -> Optional[str]:
    """
    Extract a Spotify access token from the embed page HTML.
    Spotify bundles the token inside:
      - __NEXT_DATA__.props.pageProps.config
      - Inline JS bundles (e.g. accessToken:"BQA...")
    This avoids hitting the /get_access_token endpoint which is bot-blocked.
    """
    # 1. Try __NEXT_DATA__ config section
    if nd:
        config = ((nd.get("props") or {}).get("pageProps") or {}).get("config") or {}
        if isinstance(config, dict):
            tok = config.get("accessToken") or config.get("access_token")
            if tok and len(str(tok)) > 50:
                logger.info("[ytmusic] Spotify token found in __NEXT_DATA__.config")
                return str(tok)

    # 2. Scan the raw HTML for known token patterns
    for pat in _TOKEN_PATTERNS:
        m = pat.search(html)
        if m:
            tok = m.group(1)
            if len(tok) > 50:  # real tokens are ~200+ chars
                logger.info("[ytmusic] Spotify token extracted from HTML inline script")
                return tok

    logger.debug("[ytmusic] No access token found in embed HTML")
    return None



def _get_all_spotify_tracks_api(playlist_id: str, token: str) -> List[Dict[str, str]]:
    """
    Page through the Spotify Web API to retrieve ALL tracks from a public playlist.
    Uses the anonymous embed token — works without a user account.
    Fetches 100 tracks per request, waits 0.35 s between requests.
    Returns a list of {title, artist} dicts.
    """
    import time

    tracks: List[Dict[str, str]] = []
    offset = 0
    limit  = 100
    api_base = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    while True:
        params = {
            "offset": offset,
            "limit":  limit,
            "fields": "items(track(name,artists(name))),next,total",
        }
        try:
            text = _http_get(api_base, params=params, timeout=20, headers=auth_headers)
            if not text:
                logger.warning(f"[ytmusic] Spotify API: empty response at offset={offset}")
                break
            data = json.loads(text)
        except Exception as e:
            logger.warning(f"[ytmusic] Spotify API parse error at offset={offset}: {e}")
            break

        # Handle auth errors
        if "error" in data:
            err = data["error"]
            logger.warning(f"[ytmusic] Spotify API error: {err}")
            break

        items = data.get("items", [])
        total = data.get("total", 0)
        logger.info(f"[ytmusic] Spotify API page offset={offset}: {len(items)} items (total={total})")

        for item in items:
            track = item.get("track") if isinstance(item, dict) else None
            if not track or not isinstance(track, dict):
                continue
            t_name   = track.get("name", "") or ""
            artists  = track.get("artists", []) or []
            t_artist = ", ".join(a.get("name", "") for a in artists if isinstance(a, dict) and a.get("name"))
            if t_name:
                tracks.append({"title": t_name, "artist": t_artist})

        offset += limit

        if not data.get("next") or len(items) < limit:
            break  # last page

        time.sleep(0.35)  # gentle rate limiting between pages

    logger.info(f"[ytmusic] Spotify API: fetched {len(tracks)} tracks total from playlist {playlist_id}")
    return tracks



def _http_get(url: str, params: Optional[Dict] = None, timeout: int = 15,
              headers: Optional[Dict] = None) -> Optional[str]:
    """Single HTTP GET with curl_cffi → requests fallback. Returns response text or None."""
    req_headers = {**_REQUESTS_HEADERS, **(headers or {})}
    try:
        from curl_cffi import requests as _cr
        r = _cr.get(url, params=params, headers=req_headers, timeout=timeout, impersonate="chrome120")
        r.raise_for_status()
        return r.text
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[ytmusic] curl_cffi GET failed for {url}: {e}")

    try:
        import requests as _req
        r = _req.get(url, params=params, headers=req_headers, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.warning(f"[ytmusic] HTTP GET failed for {url}: {e}")
        return None


# ── 1. oEmbed (most reliable for single tracks) ───────────────────────────────

def _spotify_oembed(spotify_url: str) -> Optional[Dict[str, str]]:
    """
    Call Spotify's public oEmbed endpoint.
    Returns {"title": <track name>, "artist": <artist name>} or None.
    Response example:
      {"title": "Blinding Lights", "author_name": "The Weeknd", ...}
    """
    # Normalise the URL: strip query-string (si= tokens etc.) to avoid 404s
    clean_url = re.sub(r"\?.*$", "", spotify_url)
    text = _http_get(_SPOTIFY_OEMBED, params={"url": clean_url})
    if not text:
        return None
    try:
        data = json.loads(text)
        title = (data.get("title") or "").strip()
        artist = (data.get("author_name") or "").strip()
        if title:
            logger.info(f"[ytmusic] oEmbed → title='{title}' artist='{artist}'")
            return {"title": title, "artist": artist}
    except Exception as e:
        logger.debug(f"[ytmusic] oEmbed parse error: {e}")
    return None


# ── 2. __NEXT_DATA__ JSON blob ────────────────────────────────────────────────

def _spotify_next_data(spotify_url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch the Spotify page and parse the __NEXT_DATA__ JSON that Next.js injects.
    Works for both tracks and playlists when oEmbed is insufficient.
    """
    html = _http_get(spotify_url)
    if not html:
        return None
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not m:
        # Also try the older format
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
        if not m:
            return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _looks_like_track(obj: Any) -> bool:
    """Return True if obj looks like a single track dict."""
    if not isinstance(obj, dict):
        return False
    # Format 1 — ytmusicapi / ld+json: {"name": "...", "artists": ...}
    if "name" in obj and ("artists" in obj or "byArtist" in obj or "artist" in obj):
        return True
    # Format 2 — Spotify playlist wrapped: {"track": {"name": "...", ...}}
    inner = obj.get("track")
    if isinstance(inner, dict) and "name" in inner:
        return True
    # Format 3 — Spotify embed trackList: {"title": "...", "subtitle": "...", "uri": "spotify:track:..."}
    if "title" in obj and ("subtitle" in obj or "uri" in obj):
        uri = obj.get("uri", "")
        if not uri or "track" in str(uri):   # uri looks like spotify:track:...
            return True
    # Format 4 — Spotify embed with uid/type:  {"uid": "...", "type": "track", "name": "..."}
    if obj.get("type") == "track" and "name" in obj:
        return True
    return False


def _recursive_find_track_list(obj: Any, depth: int = 0, _path: str = "root") -> List[Dict]:
    """
    Recursively walk a JSON tree and return the first list that looks like
    a collection of tracks (has ≥1 items that pass _looks_like_track).
    """
    if depth > 15:
        return []

    if isinstance(obj, list) and len(obj) >= 1 and _looks_like_track(obj[0]):
        logger.debug(f"[ytmusic] _recursive_find_track_list: found {len(obj)} track-like items at path '{_path}'")
        return obj  # type: ignore

    if isinstance(obj, dict):
        # Check priority keys first so we don't accidentally pick up
        # a tiny list of "related tracks" before the main track list.
        for key in ("tracks", "trackList", "items", "results", "contents"):
            val = obj.get(key)
            if val is not None:
                result = _recursive_find_track_list(val, depth + 1, f"{_path}.{key}")
                if result:
                    return result
        # Fallback: check all other keys
        for key, val in obj.items():
            if key in ("tracks", "trackList", "items", "results", "contents"):
                continue
            result = _recursive_find_track_list(val, depth + 1, f"{_path}.{key}")
            if result:
                return result

    if isinstance(obj, list):
        for i, item in enumerate(obj):
            result = _recursive_find_track_list(item, depth + 1, f"{_path}[{i}]")
            if result:
                return result

    return []


def _parse_track_item(item: Dict) -> Optional[Dict[str, str]]:
    """Convert a raw track dict (any Spotify format) to {title, artist}."""
    # Unwrap {"track": {...}} → {...}
    t = item.get("track", item)
    if not isinstance(t, dict):
        return None

    # ── title ──────────────────────────────────────────────────────────────────
    # Standard: "name"  |  Spotify embed: "title"
    t_name = t.get("name") or t.get("title") or ""
    if not t_name:
        return None

    # ── artist ─────────────────────────────────────────────────────────────────
    # Artists can come as:
    #   {"artists": {"items": [{"profile": {"name": "X"}}]}}   ← new Spotify main
    #   {"artists": [{"name": "X"}]}                            ← older / ld+json
    #   {"byArtist": {"name": "X"}}                             ← ld+json schema.org
    #   {"artist": "X"}                                         ← simple flat
    #   {"subtitle": "X · Album · Year"}                        ← Spotify embed flat
    artist_str = ""
    raw_artists = t.get("artists", t.get("byArtist", t.get("artist", None)))

    if isinstance(raw_artists, dict):
        items_list = raw_artists.get("items", [])
        if items_list:
            artist_str = ", ".join(
                (a.get("profile", {}).get("name", "") or a.get("name", ""))
                for a in items_list if isinstance(a, dict)
            )
        else:
            artist_str = raw_artists.get("name", "")
    elif isinstance(raw_artists, list):
        artist_str = ", ".join(
            (a.get("profile", {}).get("name", "") or a.get("name", ""))
            for a in raw_artists if isinstance(a, dict)
        )
    elif isinstance(raw_artists, str):
        artist_str = raw_artists

    # Fallback: Spotify embed "subtitle" field is "Artist · Album · Year"
    if not artist_str:
        subtitle = t.get("subtitle", "")
        if subtitle:
            # Take only the first segment (the artist name)
            artist_str = subtitle.split(" · ")[0].strip()

    return {"title": str(t_name), "artist": artist_str.strip()}


def _playlist_meta_from_next_data(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract playlist name + tracks from any __NEXT_DATA__ / ld+json blob."""
    # ── log the top-level JSON structure ──────────────────────────────────────
    top_keys = list(data.keys()) if isinstance(data, dict) else type(data).__name__
    logger.debug(f"[ytmusic] _playlist_meta_from_next_data: top-level keys = {top_keys}")

    # Dive into props.pageProps.state.data if present and log what's there
    inner = data
    for step in ("props", "pageProps", "state", "data"):
        if isinstance(inner, dict) and step in inner:
            inner = inner[step]
            logger.debug(f"[ytmusic]   → after .{step}: keys = {list(inner.keys()) if isinstance(inner, dict) else type(inner).__name__}")
        else:
            logger.debug(f"[ytmusic]   → key '{step}' not found, stopping early")
            break

    # Log entity sub-keys so we can see where tracks live
    entity = inner.get("entity", {}) if isinstance(inner, dict) else {}
    if isinstance(entity, dict):
        entity_keys = list(entity.keys())
        logger.debug(f"[ytmusic]   → entity keys: {entity_keys}")
        # Log a sample of any list-valued keys (could be track lists)
        for k, v in entity.items():
            if isinstance(v, list) and len(v) > 0:
                logger.debug(f"[ytmusic]   → entity.{k} is a list of {len(v)} items; first item keys: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0]).__name__}")
            elif isinstance(v, dict):
                logger.debug(f"[ytmusic]   → entity.{k} is a dict with keys: {list(v.keys())}")

    # ── find the playlist name ─────────────────────────────────────────────────
    name = ""
    for path in [
        ["props", "pageProps", "state", "data", "entity", "name"],
        ["props", "pageProps", "state", "data", "playlist", "name"],
        ["name"],   # ld+json root
    ]:
        node = data
        for key in path:
            if not isinstance(node, dict):
                break
            node = node.get(key)  # type: ignore
        if isinstance(node, str) and node:
            name = node
            logger.debug(f"[ytmusic]   → playlist name found via path {path}: '{name}'")
            break

    if not name:
        logger.debug("[ytmusic]   → playlist name NOT found in any known path")

    # ── find the track list (recursive, structure-agnostic) ────────────────────
    logger.debug("[ytmusic]   → starting recursive track list search…")
    raw_items = _recursive_find_track_list(data)
    logger.debug(f"[ytmusic]   → recursive finder returned {len(raw_items)} raw items")

    # Log first item's keys to diagnose structure
    if raw_items:
        first_keys = list(raw_items[0].keys()) if isinstance(raw_items[0], dict) else str(raw_items[0])[:100]
        logger.debug(f"[ytmusic]   → first raw item keys: {first_keys}")

    tracks = []
    for item in raw_items:
        parsed = _parse_track_item(item)
        if parsed:
            tracks.append(parsed)

    logger.info(f"[ytmusic] _playlist_meta_from_next_data: name='{name}', tracks={len(tracks)} (raw={len(raw_items)})")

    if name or tracks:
        return {"name": name or "Spotify Playlist", "tracks": tracks}
    return None



# ── 3. Legacy HTML og: fallback ───────────────────────────────────────────────

def _track_meta_from_html(html: str) -> Optional[Dict[str, str]]:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        og_title = soup.find("meta", property="og:title")
        og_desc  = soup.find("meta", property="og:description")
        title = (og_title.get("content", "") if og_title else "").strip()
        desc  = (og_desc.get("content", "")  if og_desc  else "").strip()

        artist = ""
        if " · " in desc:
            parts = desc.split(" · ")
            artist = parts[1] if len(parts) > 1 else ""
        elif not title:
            page_title = soup.find("title")
            if page_title:
                raw = re.sub(r"\s*\|\s*Spotify\s*$", "", page_title.get_text(strip=True), flags=re.IGNORECASE)
                if " - " in raw:
                    title, artist = raw.split(" - ", 1)
                    title, artist = title.strip(), artist.strip()
        if title:
            return {"title": title, "artist": artist}
    except Exception as e:
        logger.debug(f"[ytmusic] HTML og fallback parse error: {e}")
    return None


def _playlist_meta_from_html(html: str) -> Optional[Dict[str, Any]]:
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script", {"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or "")
                if data.get("@type") == "MusicPlaylist":
                    return _playlist_meta_from_next_data(data)
            except Exception:
                continue
        og_title = soup.find("meta", property="og:title")
        name = (og_title.get("content", "Spotify Playlist") if og_title else "Spotify Playlist").strip()
        return {"name": name, "tracks": []}
    except Exception as e:
        logger.debug(f"[ytmusic] HTML playlist fallback parse error: {e}")
        return None


# ── Public resolvers ──────────────────────────────────────────────────────────

def _track_meta_from_next_data(data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Extract single-track title + artist from a __NEXT_DATA__ / ld+json blob."""
    # Try the most common Next.js entity paths first (fast, no recursion)
    for path in [
        ["props", "pageProps", "state", "data", "entity"],
        ["props", "pageProps", "state", "data", "track"],
    ]:
        node: Any = data
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, dict) and node.get("name"):
            parsed = _parse_track_item(node)
            if parsed:
                return parsed

    # ld+json schema.org MusicRecording
    if data.get("@type") == "MusicRecording":
        parsed = _parse_track_item(data)
        if parsed:
            return parsed

    return None


def _get_spotify_track_meta(url: str) -> Optional[Dict[str, str]]:
    """Try oEmbed → __NEXT_DATA__ → HTML og: in order. Return {title, artist} or None."""
    # 1. oEmbed (fastest, most reliable)
    meta = _spotify_oembed(url)
    if meta:
        return meta

    # 2. __NEXT_DATA__ JSON blob
    logger.info("[ytmusic] oEmbed failed, trying __NEXT_DATA__…")
    nd = _spotify_next_data(url)
    if nd:
        meta = _track_meta_from_next_data(nd)
        if meta:
            return meta

    # 3. HTML og: / title tags (last resort)
    logger.info("[ytmusic] __NEXT_DATA__ failed, trying HTML og: tags…")
    html = _http_get(url) or ""
    return _track_meta_from_html(html)


def _fetch_partner_tracks(playlist_id: str, token: str, embed_url: str, session) -> List[Dict[str, str]]:
    """
    Fetch ALL playlist tracks via Spotify's internal GraphQL partner API.
    This is the EXACT endpoint the web embed player uses when scrolling past
    the first 100 tracks:
      POST https://api-partner.spotify.com/pathfinder/v2/query
      operationName: fetchPlaylistContents
    The persisted query hash may rotate with Spotify deploys, but is typically
    stable for weeks/months. We log the raw response on failure so the hash
    can be updated easily.
    """
    import time as _t
    import json as _json

    # The sha256Hash of the persisted GraphQL query for fetchPlaylistContents.
    # Observed from browser DevTools on 2026-05-19. Update if Spotify rotates it.
    GQL_HASH    = "a65e12194ed5fc443a1cdebed5fabe33ca5b07b987185d63c72483867ad13cb4"
    GQL_URL     = "https://api-partner.spotify.com/pathfinder/v2/query"
    LIMIT       = 100  # max observed limit; Spotify default is 50 but 100 works

    req_headers = {
        **_REQUESTS_HEADERS,
        "Authorization":       f"Bearer {token}",
        "Content-Type":        "application/json",
        "Accept":              "application/json",
        "Origin":              "https://open.spotify.com",
        "Referer":             embed_url,
        "app-platform":        "WebPlayer",
        "Spotify-App-Version": "1.0.0.0",
    }

    all_tracks: List[Dict[str, str]] = []
    offset     = 0
    total      = None

    while True:
        payload = {
            "variables": {
                "uri":    f"spotify:playlist:{playlist_id}",
                "offset": offset,
                "limit":  LIMIT,
                "includeEpisodeContentRatingsV2": False,
            },
            "operationName": "fetchPlaylistContents",
            "extensions": {
                "persistedQuery": {
                    "version":    1,
                    "sha256Hash": GQL_HASH,
                }
            },
        }

        try:
            r = session.post(GQL_URL, json=payload, headers=req_headers, timeout=20)
            logger.info(f"[ytmusic] partner-api offset={offset}: HTTP {r.status_code}")

            if r.status_code == 429:
                logger.warning("[ytmusic] partner-api 429 — giving up immediately")
                break
            if r.status_code != 200:
                logger.warning(f"[ytmusic] partner-api non-200 (hash may have rotated): {r.text[:600]}")
                break

            resp = r.json()
        except Exception as e:
            logger.warning(f"[ytmusic] partner-api request failed: {e}")
            break

        # ── Parse GraphQL response ──────────────────────────────────────────
        # Shape: data.playlistV2.content.{items, totalCount}
        # Each item: {uid, item: {__typename, data: {name, artists: {items: [{profile: {name}}]}}}}
        try:
            content = (
                resp.get("data", {})
                    .get("playlistV2", {})
                    .get("content", {})
            )
            if not isinstance(content, dict):
                logger.warning(f"[ytmusic] partner-api unexpected shape, keys: {list(resp.keys())}")
                logger.debug(f"[ytmusic] partner-api raw (first 800): {str(resp)[:800]}")
                break

            if total is None:
                total = content.get("totalCount", 0)

            items = content.get("items", [])
            logger.info(f"[ytmusic] partner-api offset={offset}: {len(items)} items (total={total})")

            # Log the first entry on the first page so we can see the real GQL shape
            if offset == 0 and items:
                first = items[0] if isinstance(items[0], dict) else {}
                logger.debug(f"[ytmusic] partner-api first entry keys: {list(first.keys())}")
                # Also log one level deeper for common wrapper keys
                for k in ("item", "itemV2", "track"):
                    if k in first and isinstance(first[k], dict):
                        inner = first[k]
                        logger.debug(f"[ytmusic] partner-api entry['{k}'] keys: {list(inner.keys())}")
                        if "data" in inner and isinstance(inner["data"], dict):
                            logger.debug(f"[ytmusic] partner-api entry['{k}']['data'] keys: {list(inner['data'].keys())}")

            for entry in items:
                if not isinstance(entry, dict):
                    continue

                # Try all known wrapper key names (Spotify has changed this over time)
                item_obj = (
                    entry.get("item")   or   # older GQL schema
                    entry.get("itemV2") or   # newer GQL schema (2024+)
                    entry.get("track")  or   # fallback
                    {}
                )
                track_data = item_obj.get("data") if isinstance(item_obj, dict) else None

                # If "data" is not present, treat item_obj itself as the track data
                if not isinstance(track_data, dict):
                    track_data = item_obj if isinstance(item_obj, dict) else {}

                t_name = (
                    track_data.get("name") or
                    # Some schemas use "trackName" or "title"
                    track_data.get("trackName") or
                    track_data.get("title") or
                    ""
                )

                # artists shape v1: {"items": [{"profile": {"name": "..."}}]}
                # artists shape v2: [{"name": "..."}]
                artists_obj = track_data.get("artists") or {}
                if isinstance(artists_obj, dict):
                    artist_items = artists_obj.get("items") or []
                    t_artist = ", ".join(
                        a.get("profile", {}).get("name", "") or a.get("name", "")
                        for a in artist_items
                        if isinstance(a, dict)
                        and (a.get("profile", {}).get("name") or a.get("name"))
                    )
                elif isinstance(artists_obj, list):
                    t_artist = ", ".join(
                        a.get("name", "") for a in artists_obj
                        if isinstance(a, dict) and a.get("name")
                    )
                else:
                    t_artist = ""

                if t_name:
                    all_tracks.append({"title": t_name, "artist": t_artist})

        except Exception as e:
            logger.warning(f"[ytmusic] partner-api parse error at offset={offset}: {e}")
            break

        offset += LIMIT
        if not items or len(items) < LIMIT or (total and offset >= total):
            break
        _t.sleep(0.3)

    if all_tracks:
        logger.info(f"[ytmusic] partner-api total: {len(all_tracks)} tracks")
        return all_tracks

    logger.debug("[ytmusic] partner-api returned 0 tracks")
    return []



def _get_spotify_playlist_meta(url: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a Spotify playlist's name + ALL tracks.
    Strategy:
      1. Open a persistent curl_cffi Session (browser-impersonating).
      2. Fetch the embed page → cookies are stored in the session automatically.
      3. Extract the access token from the embed HTML (embedded in inline JS).
      4. Use the SAME session + cookies to call the Spotify Web API with pagination.
         This prevents the 429 that occurs when calling the API without the embed cookies.
      5. Fallback: return the 100 embed tracks if API pagination fails.
    """
    import time as _time

    pid_match = _SPOTIFY_PLAYLIST_RE.search(url)
    playlist_id = pid_match.group(1) if pid_match else None

    embed_url = (
        f"https://open.spotify.com/embed/playlist/{playlist_id}"
        if playlist_id
        else re.sub(r"\?.*$", "", url.strip())
    )

    # ── Step 1: Fetch embed page with a persistent session ────────────────────
    # The session stores cookies (sp_t, sp_dc, etc.) which Spotify checks on API calls.
    html      = ""
    _session  = None  # curl_cffi Session or None

    try:
        from curl_cffi import requests as _cr
        _session = _cr.Session(impersonate="chrome120")
        resp = _session.get(embed_url, headers=_REQUESTS_HEADERS, timeout=20)
        html = resp.text
        logger.info(f"[ytmusic] Embed fetched via curl_cffi session: {len(html)} chars")
    except ImportError:
        html = _http_get(embed_url) or ""
        logger.info(f"[ytmusic] Embed fetched via _http_get fallback: {len(html)} chars")
    except Exception as e:
        logger.warning(f"[ytmusic] Session embed fetch failed: {e}")
        html = _http_get(embed_url) or ""

    if not html:
        return None

    # ── Step 2: Parse __NEXT_DATA__ → name + first 100 tracks ────────────────
    nd: Optional[Dict] = None
    embed_meta: Optional[Dict] = None
    nd_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if nd_match:
        try:
            nd = json.loads(nd_match.group(1))
            embed_meta = _playlist_meta_from_next_data(nd)
        except Exception as e:
            logger.error(f"[ytmusic] __NEXT_DATA__ parse error: {e}")

    name        = embed_meta.get("name", "Spotify Playlist") if embed_meta else "Spotify Playlist"
    init_tracks = embed_meta.get("tracks", [])               if embed_meta else []
    logger.info(f"[ytmusic] Embed: '{name}', {len(init_tracks)} tracks")

    # ── Step 3: Extract token from the same HTML ──────────────────────────────
    token = _extract_token_from_embed(html, nd) if playlist_id else None

    # ── Step 4: Try Spotify's internal spclient API (used by the embed player) ─
    # api.spotify.com/v1 returns 429 with embed tokens server-side.
    # spclient.wg.spotify.com is the ACTUAL endpoint the embed JS calls for tracks.
    if token and playlist_id and _session:
        spc_tracks = _fetch_partner_tracks(playlist_id, token, embed_url, _session)
        if spc_tracks:
            logger.info(f"[ytmusic] spclient: got {len(spc_tracks)} tracks")
            return {"name": name, "tracks": spc_tracks}
        logger.warning("[ytmusic] spclient returned 0 tracks, using embed fallback")

    # ── Step 5: Fallback — return the 100 embed tracks immediately ────────────
    if init_tracks:
        logger.info(f"[ytmusic] Returning embed tracks only: {len(init_tracks)}")
        return {"name": name, "tracks": init_tracks}

    return _playlist_meta_from_html(html)



def resolve_spotify_track(url: str) -> Optional[List[MusicTrack]]:
    meta = _get_spotify_track_meta(url)
    if not meta:
        logger.warning(f"[ytmusic] Could not extract metadata from Spotify URL: {url}")
        return None
    query = f"{meta['artist']} {meta['title']}".strip()
    logger.info(f"[ytmusic] Spotify track resolved → query: '{query}'")
    return search_tracks(query, limit=10)


def resolve_spotify_playlist(url: str) -> Optional[MusicPlaylist]:
    meta = _get_spotify_playlist_meta(url)
    if not meta:
        logger.warning(f"[ytmusic] Could not extract playlist metadata from Spotify URL: {url}")
        return None

    tracks: List[MusicTrack] = []
    for t in (meta.get("tracks") or []):
        tracks.append(MusicTrack(
            video_id="",
            title=t.get("title", "Unknown"),
            artists=[MusicArtist(name=t["artist"])] if t.get("artist") else [],
            url="",
        ))

    return MusicPlaylist(
        playlist_id=url,
        title=meta.get("name", "Spotify Playlist"),
        tracks=tracks,
        source="spotify",
    )


def resolve_youtube_track(url: str) -> Optional[List[MusicTrack]]:
    try:
        cmd = _ytdlp_cmd() + ["--dump-json", "--no-playlist", "--quiet", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        info = json.loads(result.stdout.strip())
        title = info.get("title") or ""
        channel = info.get("channel") or info.get("uploader") or ""
        query = f"{channel} {title}".strip()
        logger.info(f"[ytmusic] YouTube URL resolved to query: '{query}'")
        return search_tracks(query, limit=10)
    except Exception as e:
        logger.warning(f"[ytmusic] YouTube URL resolve failed: {e}")
        return None


# ─── Input type detection ─────────────────────────────────────────────────────

def detect_input_type(text: str) -> str:
    """Classify input as: 'spotify_track' | 'spotify_playlist' | 'ytmusic_playlist'
    | 'youtube_url' | 'ytmusic_url' | 'query'.
    Supports localized Spotify URLs (e.g. /intl-it/track/, /intl-fr/playlist/).
    """
    t = text.strip()
    # Spotify: support optional locale prefix like /intl-it/, /intl-fr/, etc.
    if re.search(r"spotify\.com/(?:[a-zA-Z-]+/)?track/", t):
        return "spotify_track"
    if re.search(r"spotify\.com/(?:[a-zA-Z-]+/)?playlist/", t):
        return "spotify_playlist"
    if re.search(r"music\.youtube\.com/playlist", t):
        return "ytmusic_playlist"
    if re.search(r"music\.youtube\.com/watch", t):
        return "ytmusic_url"
    if re.search(r"youtube\.com/watch|youtu\.be/", t):
        return "youtube_url"
    return "query"


# ─── Audio format discovery ───────────────────────────────────────────────────

def get_audio_formats(video_id_or_url: str) -> List[AudioFormat]:
    """Return available audio formats for a YT Music track using yt-dlp."""
    url = video_id_or_url
    if not url.startswith("http"):
        url = f"https://music.youtube.com/watch?v={video_id_or_url}"

    cmd = _ytdlp_cmd() + ["--dump-json", "--no-playlist", "--quiet"]
    ffmpeg = _ffmpeg_location()
    if ffmpeg:
        cmd += ["--ffmpeg-location", ffmpeg]
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not result.stdout.strip():
            logger.warning(f"[ytmusic] yt-dlp returned no output for {url}. stderr: {result.stderr[:300]}")
            return []
        info = json.loads(result.stdout.strip())
        formats = info.get("formats") or []

        audio_formats: List[AudioFormat] = []
        for f in formats:
            # Only audio-only streams
            if f.get("vcodec", "none") != "none":
                continue
            acodec = f.get("acodec", "")
            if not acodec or acodec == "none":
                continue

            ext = f.get("ext") or acodec.split(".")[0]
            abr = f.get("abr") or f.get("tbr")
            quality_label = f.get("format_note") or f.get("quality") or ""
            if not quality_label and abr:
                quality_label = f"{abr:.0f}kbps"

            audio_formats.append(AudioFormat(
                format_id=f.get("format_id", ""),
                ext=ext,
                quality=str(quality_label),
                bitrate=abr,
                filesize=f.get("filesize") or f.get("filesize_approx"),
                note=f.get("format_note") or "",
            ))

        audio_formats.sort(key=lambda x: (x.bitrate or 0), reverse=True)
        return audio_formats
    except Exception as e:
        logger.warning(f"[ytmusic] Format discovery failed for {url}: {e}")
        return []


# ─── Download ─────────────────────────────────────────────────────────────────

def download_track(video_id_or_url: str, output_dir: str, format_id: str = "bestaudio") -> bool:
    """Download a single track to output_dir using yt-dlp."""
    url = video_id_or_url
    if not url.startswith("http"):
        url = f"https://music.youtube.com/watch?v={video_id_or_url}"

    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, "%(artist)s - %(title)s.%(ext)s")

    ffmpeg = _ffmpeg_location()

    cmd = _ytdlp_cmd() + [
        "--no-playlist",
        "-f", format_id,
        "-o", output_template,
    ]

    if ffmpeg:
        cmd += [
            "--ffmpeg-location", ffmpeg,
            "--extract-audio",
            "--embed-thumbnail",
            "--add-metadata"
        ]
    else:
        # ffmpeg not available — skip postprocessing to avoid the error
        logger.warning("[ytmusic] ffmpeg not found — skipping thumbnail embedding and metadata")

    cmd.append(url)

    try:
        result = subprocess.run(cmd, timeout=300)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"[ytmusic] Download failed for {url}: {e}")
        return False
