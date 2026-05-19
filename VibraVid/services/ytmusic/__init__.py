# VibraVid/services/ytmusic/__init__.py
# YouTube Music CLI service integration.
# Provides interactive CLI search, format selection, playlist/artist/album handling,
# auto-first, retry logic, and Lidarr-style folder structure.

from __future__ import annotations

import os
import re
import logging
from typing import Optional, List, Dict, Any

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from VibraVid.services._base.site_costant import site_constants

from VibraVid.services.ytmusic.client import (
    MusicTrack,
    MusicArtist,
    MusicAlbum,
    MusicPlaylist,
    ArtistDetails,
    search_tracks,
    search_artists,
    search_albums,
    get_album_tracks,
    get_artist_details,
    get_ytmusic_playlist,
    get_audio_formats,
    resolve_spotify_track,
    resolve_spotify_playlist,
    resolve_youtube_track,
    detect_input_type,
    download_track,
    AudioFormat,
)

# ─── Module constants (required by site_loader) ───────────────────────────────
indice = 99
_useFor = "song"

console = Console()
msg = Prompt()
logger = logging.getLogger(__name__)

_INVALID_PATH_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


# ─── Path helpers ─────────────────────────────────────────────────────────────

def _sanitize(name: str, fallback: str = "Unknown") -> str:
    name = name.strip()
    name = _INVALID_PATH_CHARS_RE.sub("_", name)
    name = re.sub(r"_+", "_", name).strip("._")
    return name or fallback


def _music_output_dir() -> str:
    """Return the configured Music output directory (same root as Video/Serie/Movie)."""
    try:
        folder = site_constants.MUSIC_FOLDER
        if not os.path.isabs(folder):
            import pathlib
            project_root = pathlib.Path(__file__).resolve().parents[4]
            folder = str(project_root / folder)
        return folder
    except Exception as e:
        logger.error(f"[_music_output_dir] Failed to resolve music folder: {e}", exc_info=True)
        return os.path.join(os.path.expanduser("~"), "Music", "VibraVid")


def _track_output_dir(track: MusicTrack) -> str:
    """Lidarr-style: <root>/<Artist>/<Album or Singles>"""
    root = _music_output_dir()
    artist = _sanitize(track.artist_str or "Unknown Artist")
    album  = _sanitize(track.album or "", fallback="")
    return os.path.join(root, artist, album or "Singles")


# ─── Rich display helpers ─────────────────────────────────────────────────────

def _print_tracks_table(tracks: List[MusicTrack], title: str = "Results") -> None:
    table = Table(title=title, show_header=True, header_style="bold cyan",
                  box=box.SIMPLE_HEAVY, expand=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="white", min_width=30)
    table.add_column("Artist", style="green", min_width=20)
    table.add_column("Album", style="yellow", min_width=18)
    table.add_column("Dur.", style="dim", width=7)
    for i, t in enumerate(tracks):
        dur = ""
        if t.duration_seconds:
            m, s = divmod(t.duration_seconds, 60)
            dur = f"{m}:{s:02d}"
        table.add_row(str(i), t.title, t.artist_str, t.album or "", dur)
    console.print(table)


def _print_artists_table(artists: List[MusicArtist]) -> None:
    table = Table(title="Artists", show_header=True, header_style="bold cyan",
                  box=box.SIMPLE_HEAVY, expand=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Artist", style="white", min_width=30)
    table.add_column("Channel ID", style="dim", min_width=24)
    for i, a in enumerate(artists):
        table.add_row(str(i), a.name, a.channel_id or "")
    console.print(table)


def _print_albums_table(albums: List[MusicAlbum]) -> None:
    table = Table(title="Albums", show_header=True, header_style="bold cyan",
                  box=box.SIMPLE_HEAVY, expand=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="white", min_width=30)
    table.add_column("Artist", style="green", min_width=20)
    table.add_column("Type", style="yellow", width=10)
    table.add_column("Year", style="dim", width=6)
    for i, a in enumerate(albums):
        table.add_row(str(i), a.title, a.artist_str, a.album_type, str(a.year or ""))
    console.print(table)


def _print_formats_table(formats: List[AudioFormat]) -> None:
    table = Table(title="Audio Formats", show_header=True, header_style="bold cyan",
                  box=box.SIMPLE_HEAVY, expand=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Format ID", style="white", width=14)
    table.add_column("Ext", style="green", width=6)
    table.add_column("Quality", style="yellow", width=14)
    table.add_column("Bitrate", style="magenta", width=10)
    table.add_column("Size", style="dim", width=12)
    for i, f in enumerate(formats):
        bitrate = f"{f.bitrate:.0f} kbps" if f.bitrate else ""
        size = f"{f.filesize / (1024*1024):.1f} MB" if f.filesize else ""
        table.add_row(str(i), f.format_id, f.ext, f.quality, bitrate, size)
    console.print(table)


def _print_failed_table(failed: List[Dict[str, Any]]) -> None:
    table = Table(title="Failed Downloads", show_header=True, header_style="bold red",
                  box=box.SIMPLE_HEAVY, expand=False)
    table.add_column("#", style="dim", width=4)
    table.add_column("Title", style="white", min_width=30)
    table.add_column("Artist", style="green", min_width=20)
    table.add_column("Error", style="red")
    for i, item in enumerate(failed):
        table.add_row(str(i), item["track"].title, item["track"].artist_str, item.get("error", ""))
    console.print(table)


# ─── Format selection ─────────────────────────────────────────────────────────

def _choose_format(track: MusicTrack, forced_audio: Optional[str] = None) -> str:
    if forced_audio:
        return forced_audio
    console.print(f"\n[cyan]Fetching audio formats for[/] [bold]{track.title}[/]…")
    try:
        formats = get_audio_formats(track.video_id)
    except Exception as e:
        logger.warning(f"[ytmusic] Could not fetch formats: {e}")
        formats = []
    if not formats:
        console.print("[yellow]No formats found — using best available audio.[/]")
        return "bestaudio"
    _print_formats_table(formats)
    raw = msg.ask("[cyan]Select format[/] (Enter = best)", choices=[str(i) for i in range(len(formats))],
                  default="0", show_choices=False, show_default=False)
    try:
        return formats[int(raw)].format_id
    except (IndexError, ValueError):
        return "bestaudio"


# ─── Download helpers ─────────────────────────────────────────────────────────

def _download_track_cli(track: MusicTrack, format_id: str) -> bool:
    out_dir = _track_output_dir(track)
    console.print(f"  [dim]→[/] [white]{track.title}[/] [dim]by[/] [green]{track.artist_str}[/] [dim]→ {out_dir}[/]")
    try:
        ok, _ = download_track(track.yt_url, out_dir, format_id)
        return ok
    except Exception as e:
        logger.error(f"[ytmusic] Download exception for {track.title}: {e}")
        return False


def _download_batch_with_retry(tracks: List[MusicTrack], format_id: str) -> None:
    if not tracks:
        console.print("[yellow]No tracks to download.[/]")
        return
    console.print(f"\n[cyan]Downloading {len(tracks)} track(s)…[/]")
    failed: List[Dict[str, Any]] = []
    for track in tracks:
        if not track.video_id:
            console.print(f"  [red]✗[/] [white]{track.title}[/] — no video_id, skipping.")
            failed.append({"track": track, "error": "No video_id"})
            continue
        ok = _download_track_cli(track, format_id)
        if ok:
            console.print(f"  [green]✓[/] [white]{track.title}[/]")
        else:
            console.print(f"  [red]✗[/] [white]{track.title}[/] — download failed.")
            failed.append({"track": track, "error": "Download failed"})

    while failed:
        console.print(f"\n[yellow]{len(failed)} track(s) failed:[/]")
        _print_failed_table(failed)
        retry = msg.ask("[cyan]Retry failed downloads? (y/n)[/]", choices=["y", "n"],
                        default="n", show_choices=False)
        if retry.lower() != "y":
            break
        still_failed: List[Dict[str, Any]] = []
        for item in failed:
            ok = _download_track_cli(item["track"], format_id)
            if ok:
                console.print(f"  [green]✓[/] [white]{item['track'].title}[/]")
            else:
                console.print(f"  [red]✗[/] [white]{item['track'].title}[/] — still failing.")
                still_failed.append(item)
        failed = still_failed

    if not failed:
        console.print("\n[green]All downloads completed successfully.[/]")
    else:
        console.print(f"\n[yellow]{len(failed)} track(s) could not be downloaded.[/]")


# ─── Selection helpers ────────────────────────────────────────────────────────

def _parse_selection(raw: str, max_idx: int) -> List[int]:
    """Parse user selection string into a list of indices."""
    if raw.strip() == "*":
        return list(range(max_idx))
    indices = []
    seen = set()
    for part in raw.split(","):
        part = part.strip()
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                for idx in range(int(a), int(b) + 1):
                    if 0 <= idx < max_idx and idx not in seen:
                        indices.append(idx)
                        seen.add(idx)
            except ValueError:
                pass
        else:
            try:
                idx = int(part)
                if 0 <= idx < max_idx and idx not in seen:
                    indices.append(idx)
                    seen.add(idx)
            except ValueError:
                pass
    return indices


def _select_tracks(tracks: List[MusicTrack]) -> List[MusicTrack]:
    _print_tracks_table(tracks)
    raw = msg.ask("[cyan]Select track(s)[/] [dim](e.g. 0 | 1-3 | 0,2,5 | *)[/]", default="0").strip()
    idxs = _parse_selection(raw, len(tracks))
    return [tracks[i] for i in idxs]


def _resolve_spotify_tracks(tracks: List[MusicTrack]) -> List[MusicTrack]:
    """Resolve video_ids for Spotify-sourced tracks (no video_id yet)."""
    resolved = []
    for i, t in enumerate(tracks, 1):
        if t.video_id:
            resolved.append(t)
            continue
        query = f"{t.artist_str} {t.title}".strip()
        console.print(f"  [dim][{i}/{len(tracks)}][/] Resolving [white]{t.title}[/]…")
        try:
            results = search_tracks(query, limit=1)
            if results:
                r = results[0]
                resolved.append(MusicTrack(
                    video_id=r.video_id, title=t.title,
                    artists=t.artists or r.artists,
                    album=t.album or r.album,
                    thumbnail=t.thumbnail or r.thumbnail,
                    url=r.url,
                ))
            else:
                console.print(f"  [red]✗[/] No match for [white]{t.title}[/] — skipping.")
        except Exception as e:
            console.print(f"  [red]✗[/] Error: {e}")
    return resolved


# ─── Playlist flow ────────────────────────────────────────────────────────────

def _handle_playlist(playlist: MusicPlaylist, forced_audio: Optional[str]) -> None:
    console.print(f"\n[bold cyan]Playlist:[/] [white]{playlist.title}[/] — [dim]{len(playlist.tracks)} tracks[/]")
    if not playlist.tracks:
        console.print("[yellow]Playlist contains no tracks.[/]")
        return
    choice = msg.ask("[cyan]Download all or select manually?[/] (all/select)",
                     choices=["all", "select"], default="all", show_choices=False)
    tracks = playlist.tracks if choice == "all" else _select_tracks(playlist.tracks)
    if not tracks:
        console.print("[yellow]No tracks selected.[/]")
        return
    if playlist.source == "spotify":
        console.print(f"\n[cyan]Resolving {len(tracks)} track(s) on YouTube Music…[/]")
        tracks = _resolve_spotify_tracks(tracks)
    if not tracks:
        console.print("[yellow]No resolvable tracks.[/]")
        return
    first_valid = next((t for t in tracks if t.video_id), None)
    format_id = _choose_format(first_valid, forced_audio) if first_valid else (forced_audio or "bestaudio")
    _download_batch_with_retry(tracks, format_id)


# ─── Artist flow ──────────────────────────────────────────────────────────────

def _handle_artist_detail(artist: ArtistDetails, forced_audio: Optional[str]) -> None:
    """
    Show artist page: top tracks, albums, singles.
    User picks a section → drills into albums/singles or downloads top tracks.
    """
    console.print(f"\n[bold cyan]Artist:[/] [white]{artist.name}[/]")
    if artist.description:
        console.print(f"[dim]{artist.description[:120]}…[/]")

    sections = []
    if artist.top_tracks:
        sections.append("top_tracks")
    if artist.albums:
        sections.append("albums")
    if artist.singles:
        sections.append("singles")

    if not sections:
        console.print("[yellow]No content found for this artist.[/]")
        return

    menu = " / ".join(f"[cyan]{s.replace('_', ' ').title()}[/]" for s in sections)
    choice = msg.ask(f"Browse: {menu}", choices=sections,
                     default=sections[0], show_choices=False).strip()

    if choice == "top_tracks":
        selected = _select_tracks(artist.top_tracks)
        if not selected:
            return
        format_id = _choose_format(selected[0], forced_audio)
        _download_batch_with_retry(selected, format_id)

    elif choice in ("albums", "singles"):
        album_list: List[MusicAlbum] = artist.albums if choice == "albums" else artist.singles
        _print_albums_table(album_list)
        raw = msg.ask("[cyan]Select album(s)[/] [dim](e.g. 0 | 1-3 | *)[/]", default="0").strip()
        idxs = _parse_selection(raw, len(album_list))
        chosen_albums = [album_list[i] for i in idxs]

        all_tracks: List[MusicTrack] = []
        for al in chosen_albums:
            console.print(f"  [cyan]Loading[/] [white]{al.title}[/]…")
            pl = get_album_tracks(al.browse_id)
            if pl and pl.tracks:
                all_tracks.extend(pl.tracks)
            else:
                console.print(f"  [yellow]No tracks found for {al.title}[/]")

        if not all_tracks:
            console.print("[yellow]No tracks loaded.[/]")
            return

        _print_tracks_table(all_tracks, title=f"{len(all_tracks)} tracks from selected album(s)")
        confirm = msg.ask(f"[cyan]Download all {len(all_tracks)} tracks?[/] (y/n)",
                          choices=["y", "n"], default="y", show_choices=False)
        if confirm != "y":
            all_tracks = _select_tracks(all_tracks)

        if not all_tracks:
            return
        format_id = _choose_format(all_tracks[0], forced_audio)
        _download_batch_with_retry(all_tracks, format_id)


def _handle_artist_search(query: str, forced_audio: Optional[str]) -> None:
    console.print(f"[cyan]Searching artists for:[/] [white]{query}[/]")
    artists = search_artists(query, limit=10)
    if not artists:
        console.print("[yellow]No artists found.[/]")
        return
    _print_artists_table(artists)
    raw = msg.ask("[cyan]Select artist[/]", choices=[str(i) for i in range(len(artists))],
                  default="0", show_choices=False)
    try:
        chosen = artists[int(raw)]
    except (ValueError, IndexError):
        return
    if not chosen.channel_id:
        console.print("[red]No channel ID for this artist.[/]")
        return
    console.print(f"[cyan]Loading artist page for[/] [white]{chosen.name}[/]…")
    detail = get_artist_details(chosen.channel_id)
    if not detail:
        console.print("[red]Could not load artist details.[/]")
        return
    _handle_artist_detail(detail, forced_audio)


# ─── Album flow ───────────────────────────────────────────────────────────────

def _handle_album_search(query: str, forced_audio: Optional[str]) -> None:
    console.print(f"[cyan]Searching albums for:[/] [white]{query}[/]")
    albums = search_albums(query, limit=10)
    if not albums:
        console.print("[yellow]No albums found.[/]")
        return
    _print_albums_table(albums)
    raw = msg.ask("[cyan]Select album(s)[/] [dim](e.g. 0 | 1-3 | *)[/]",
                  default="0", show_choices=False)
    idxs = _parse_selection(raw, len(albums))
    chosen_albums = [albums[i] for i in idxs]

    all_tracks: List[MusicTrack] = []
    for al in chosen_albums:
        console.print(f"  [cyan]Loading[/] [white]{al.title}[/]…")
        pl = get_album_tracks(al.browse_id)
        if pl and pl.tracks:
            all_tracks.extend(pl.tracks)
        else:
            console.print(f"  [yellow]No tracks found for {al.title}[/]")

    if not all_tracks:
        console.print("[yellow]No tracks loaded.[/]")
        return

    _print_tracks_table(all_tracks, title=f"{len(all_tracks)} tracks from selected album(s)")
    confirm = msg.ask(f"[cyan]Download all {len(all_tracks)} tracks?[/] (y/n)",
                      choices=["y", "n"], default="y", show_choices=False)
    if confirm != "y":
        all_tracks = _select_tracks(all_tracks)

    if not all_tracks:
        return
    format_id = _choose_format(all_tracks[0], forced_audio)
    _download_batch_with_retry(all_tracks, format_id)


# ─── Mixed search (default text query) ───────────────────────────────────────

def _handle_text_search(query: str, forced_audio: Optional[str], get_onlyDatabase: bool = False):
    """
    Standard text search. Shows tracks by default, offers to also browse
    artist / album pages from the results.
    """
    console.print(f"[cyan]Searching YouTube Music for:[/] [white]{query}[/]")
    tracks = search_tracks(query, limit=10)

    if not tracks:
        console.print("[yellow]No results found.[/]")
        return None

    if get_onlyDatabase:
        class _Stub:
            media_list = tracks
        return _Stub()

    _print_tracks_table(tracks)

    # Offer to jump to artist/album page from results
    console.print(
        "\n[dim]Options:[/] [cyan](d)[/] download selected  "
        "[cyan](a)[/] browse artist page  [cyan](al)[/] browse album"
    )
    action = msg.ask("[cyan]Action[/]", choices=["d", "a", "al"], default="d", show_choices=False)

    if action == "d":
        selected = _select_tracks(tracks)
        if not selected:
            return None
        format_id = _choose_format(selected[0], forced_audio)
        _download_batch_with_retry(selected, format_id)

    elif action == "a":
        # Pick a track and navigate to its first artist
        selected = _select_tracks(tracks)
        if not selected:
            return None
        t = selected[0]
        artist_obj = t.artists[0] if t.artists else None
        if not artist_obj or not getattr(artist_obj, "channel_id", None):
            console.print("[yellow]No artist channel ID available — searching by name.[/]")
            _handle_artist_search(t.artist_str, forced_audio)
            return None
        console.print(f"[cyan]Loading artist page for[/] [white]{artist_obj.name}[/]…")
        detail = get_artist_details(artist_obj.channel_id)
        if detail:
            _handle_artist_detail(detail, forced_audio)
        else:
            console.print("[red]Could not load artist page.[/]")

    elif action == "al":
        # Navigate to the album of the selected track
        selected = _select_tracks(tracks)
        if not selected:
            return None
        t = selected[0]
        if t.album_id:
            console.print(f"[cyan]Loading album[/] [white]{t.album}[/]…")
            pl = get_album_tracks(t.album_id)
            if pl:
                _handle_playlist(pl, forced_audio)
            else:
                console.print("[red]Could not load album.[/]")
        elif t.album:
            _handle_album_search(t.album, forced_audio)
        else:
            console.print("[yellow]No album info for this track.[/]")

    return None


# ─── Public entry point ───────────────────────────────────────────────────────

def search(
    string_to_search: Optional[str] = None,
    get_onlyDatabase: bool = False,
    direct_item: Optional[dict] = None,
    selections: Optional[dict] = None,
    **kwargs,
) -> None:
    """Main CLI entry point for the ytmusic service (called by run.py)."""
    selections = selections or {}

    forced_audio: Optional[str] = None
    try:
        forced_audio = config_manager.config.get("DOWNLOAD", "select_audio") or None
    except Exception:
        pass

    artist_mode: bool = bool(selections.get("artist_mode"))
    album_mode: bool  = bool(selections.get("album_mode"))

    # ── Interactive query prompt if not provided ──────────────────────────────
    if not string_to_search:
        string_to_search = msg.ask(
            "[cyan]Enter search query, Spotify/YouTube URL, or artist/album name[/]"
        ).strip()
    if not string_to_search:
        console.print("[red]No query provided.[/]")
        return

    # ── Direct item (from --auto-first callback) ──────────────────────────────
    if direct_item:
        t = MusicTrack(
            video_id=direct_item.get("video_id", ""),
            title=direct_item.get("title", "Unknown"),
            artists=[],
            album=direct_item.get("album"),
            url=direct_item.get("url", ""),
        )
        format_id = _choose_format(t, forced_audio)
        _download_batch_with_retry([t], format_id)
        return

    # ── --artist mode ─────────────────────────────────────────────────────────
    if artist_mode:
        _handle_artist_search(string_to_search, forced_audio)
        return

    # ── --album mode ──────────────────────────────────────────────────────────
    if album_mode:
        _handle_album_search(string_to_search, forced_audio)
        return

    # ── URL / playlist routing ────────────────────────────────────────────────
    input_type = detect_input_type(string_to_search)
    console.print(f"[dim]Input type: {input_type}[/]")

    if input_type == "spotify_playlist":
        console.print("[cyan]Fetching Spotify playlist…[/]")
        try:
            playlist = resolve_spotify_playlist(string_to_search)
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            return
        if not playlist:
            console.print("[red]Could not load playlist.[/]")
            return
        _handle_playlist(playlist, forced_audio)
        return

    if input_type == "ytmusic_playlist":
        console.print("[cyan]Fetching YouTube Music playlist…[/]")
        try:
            playlist = get_ytmusic_playlist(string_to_search)
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            return
        _handle_playlist(playlist, forced_audio)
        return

    if input_type == "spotify_track":
        console.print("[cyan]Resolving Spotify track…[/]")
        try:
            tracks = resolve_spotify_track(string_to_search) or []
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            return
        if not tracks:
            console.print("[yellow]No results found.[/]")
            return
        selected = _select_tracks(tracks)
        if not selected:
            return
        format_id = _choose_format(selected[0], forced_audio)
        _download_batch_with_retry(selected, format_id)
        return

    if input_type == "youtube_url":
        console.print("[cyan]Resolving YouTube URL…[/]")
        try:
            tracks = resolve_youtube_track(string_to_search) or []
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")
            return
        if not tracks:
            console.print("[yellow]No results.[/]")
            return
        selected = _select_tracks(tracks)
        if not selected:
            return
        format_id = _choose_format(selected[0], forced_audio)
        _download_batch_with_retry(selected, format_id)
        return

    if input_type == "ytmusic_url":
        import re as _re
        m = _re.search(r"[?&]v=([^&]+)", string_to_search)
        video_id = m.group(1) if m else ""
        t = MusicTrack(video_id=video_id, title="Selected track", artists=[], url=string_to_search)
        format_id = _choose_format(t, forced_audio)
        _download_batch_with_retry([t], format_id)
        return

    # ── Default: plain text search with mixed navigation ─────────────────────
    return _handle_text_search(string_to_search, forced_audio, get_onlyDatabase)
