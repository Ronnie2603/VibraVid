# 07.05.26

"""
Downloader Service — replaces the standalone Downloader.py from VibraVidArr.

Instead of spawning a subprocess (`VibraVid --search ...`), this service
directly calls the VibraVid internal streaming API (`get_api(site).search()` /
`start_download()`) using the same pipeline that the GUI uses.
"""

import datetime
import logging
import pathlib
import time
from typing import Any, Dict, Optional

from .clients.sonarr_client import SonarrClient
from .clients.radarr_client import RadarrClient

logger = logging.getLogger("ARR")


class ArrDownloaderService:
    """Downloads media by invoking VibraVid's native streaming API pipeline."""

    def __init__(self, sonarr: SonarrClient, radarr: RadarrClient):
        self.sonarr = sonarr
        self.radarr = radarr

    # ── public ───────────────────────────────────────────

    def download(self, item: dict) -> bool:
        """Dispatch a single missing item (serie or movie) to VibraVid's pipeline."""
        content_type = item.get("content_type")
        if content_type == "serie":
            return self._process_serie(item)
        elif content_type == "movie":
            return self._process_movie(item)
        else:
            logger.error(f"Unknown content_type: {content_type}")
            return False

    # ── serie ────────────────────────────────────────────

    def _process_serie(self, serie: dict) -> bool:
        from searchapp.views import _run_download_in_thread

        title = serie["title"]
        provider = serie.get("provider", "streamingcommunity")
        any_success = False

        # Resolve original title from Sonarr
        original_title = self._resolve_sonarr_title(title, serie.get("id"))
        search_title = original_title or title

        year = serie.get("year")
        year_range = self._build_year_range(year)

        for season in serie.get("seasons", []):
            season_num = season["number"]
            for episode in season.get("episodes", []):
                ep_num = episode["episodeNumber"]
                ep_id = episode["id"]

                if self.sonarr.is_episode_in_queue(ep_id):
                    logger.info(f"S{season_num}E{ep_num} of '{title}' already in Sonarr queue, skipping")
                    continue

                logger.info(f"⏳ Downloading '{search_title}' S{season_num}E{ep_num} via {provider}")

                # Build a fake item_payload matching what VibraVid's GUI expects
                item_payload = self._search_and_build_payload(
                    search_title, provider, year_range
                )
                if not item_payload:
                    logger.error(f"✖️ Could not find '{search_title}' on {provider}")
                    continue

                _run_download_in_thread(
                    site=provider,
                    item_payload=item_payload,
                    season=str(season_num),
                    episodes=str(ep_num),
                    media_type="Serie",
                )
                any_success = True

                # Tell Sonarr to scan the target folder
                target_folder = str(pathlib.Path('/app/Video/Serie').joinpath(title, f"S{season_num:02d}"))
                try:
                    time.sleep(2)
                    self.sonarr.command_downloaded_episodes_scan(target_folder)
                except Exception as exc:
                    logger.warning(f"Sonarr scan command failed: {exc}")

                # Mark episode as unmonitored
                self.sonarr.set_episode_unmonitored([ep_id])

        return any_success

    # ── movie ────────────────────────────────────────────

    def _process_movie(self, movie: dict) -> bool:
        from searchapp.views import _run_download_in_thread

        title = movie["title"]
        movie_id = movie["id"]
        tmdb_id = movie.get("tmdbId")
        provider = movie.get("provider", "streamingcommunity")

        if self.radarr.is_movie_in_queue(movie_id):
            logger.info(f"'{title}' already in Radarr queue, skipping")
            return False

        # Resolve original title from Radarr
        original_title = self._resolve_radarr_title(movie_id)
        search_title = original_title or title

        year = movie.get("year")
        year_range = self._build_year_range(year)

        logger.info(f"⏳ Downloading movie '{search_title}' via {provider}")

        item_payload = self._search_and_build_payload(
            search_title, provider, year_range
        )
        if not item_payload:
            logger.error(f"Could not find movie '{search_title}' on {provider}")
            return False

        _run_download_in_thread(
            site=provider,
            item_payload=item_payload,
            season=None,
            episodes=None,
            media_type="Film",
        )

        # Tell Radarr to scan
        target_folder = str(pathlib.Path('/app/Video/Movie').joinpath(title))
        try:
            time.sleep(2)
            self.radarr.command_downloaded_movies_scan(target_folder)
        except Exception as exc:
            logger.warning(f"Radarr scan command failed: {exc}")

        # Mark unmonitored
        self.radarr.set_movie_unmonitored(movie_id)

        return True

    # ── helpers ──────────────────────────────────────────

    def _search_and_build_payload(self, title: str, provider: str, year_range: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Search VibraVid's streaming API for a title and return an item_payload dict."""
        try:
            from searchapp.api import get_api
            from searchapp.api.base import Entries

            api = get_api(provider)
            results = api.search(title)

            if not results:
                return None

            # Pick the best match (first result, optionally filtered by year)
            best = results[0]
            if year_range and len(results) > 1:
                for r in results:
                    if r.year and str(r.year) in year_range:
                        best = r
                        break

            return {**best.__dict__, "is_movie": best.is_movie}

        except Exception as exc:
            logger.error(f"Search failed for '{title}' on {provider}: {exc}")
            return None

    def _resolve_sonarr_title(self, title: str, series_id: Optional[int]) -> Optional[str]:
        """Try to get the original title from Sonarr for better search results."""
        if not series_id:
            return None
        try:
            series = self.sonarr.get_series_by_id(series_id)
            original = series.get("originalTitle")
            if original and original.lower() != title.lower():
                logger.info(f"Using original title from Sonarr: '{original}'")
                return original
        except Exception:
            pass
        return None

    def _resolve_radarr_title(self, movie_id: int) -> Optional[str]:
        """Try to get the original title from Radarr."""
        try:
            movie = self.radarr.get_movie_by_id(movie_id)
            original = movie.get("originalTitle")
            if original:
                logger.info(f"Using original title from Radarr: '{original}'")
                return original
        except Exception:
            pass
        return None

    @staticmethod
    def _build_year_range(year) -> Optional[str]:
        if not year:
            return None
        try:
            y = int(year)
            now = datetime.datetime.now().year
            if y >= (now - 1):
                return f"{y}-9999"
            else:
                return f"{y}-{y + 1}"
        except (ValueError, TypeError):
            return None
