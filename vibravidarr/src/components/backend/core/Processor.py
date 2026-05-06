from .Constant import LOGGER
from ..connection import Sonarr, Radarr, ExternalDB
from ..database import Settings, Tags, Table

from typing import Iterable, List
from itertools import count

class Processor:
    """Processa i dati che provengono da Sonarr e Radarr"""

    def __init__(self, sonarr: Sonarr, radarr: Radarr, *, settings: Settings, tags: Tags, table: Table,
                 external: ExternalDB):
        self.sonarr = sonarr
        self.radarr = radarr
        self.settings = settings
        self.tags = tags
        self.table = table
        self.external = external
        self.log = LOGGER

        # Scarichiamo la mappa reale dei Tag da Sonarr e Radarr {ID: "nome-tag"}
        try:
            self.sonarr_tags_map = {tag['id']: tag['label'].lower() for tag in self.sonarr.tags().json()}
            self.radarr_tags_map = {tag['id']: tag['label'].lower() for tag in self.radarr.tags().json()}
        except Exception as e:
            self.log.error(f"Errore nel recupero dei tag da Sonarr/Radarr: {e}")
            self.sonarr_tags_map = {}
            self.radarr_tags_map = {}

    def getData(self) -> list:
        """Restituisce i dati elaborati da Sonarr e Radarr pronti per il download."""

        items_to_download = []
        
        # Svuotiamo la memoria anti-spam ad ogni nuova scansione
        self._logged_skipped_series = set()

        self.log.debug("Recupero episodi mancanti da Sonarr...")
        sonarr_missing = self.__get_sonarr_missing()
        items_to_download.extend(sonarr_missing)

        self.log.debug("Recupero film mancanti da Radarr...")
        radarr_missing = self.__get_radarr_missing()
        items_to_download.extend(radarr_missing)

        return items_to_download

    ### --- SONARR LOGIC --- ###

    def __get_sonarr_missing(self) -> list:
        """Ottiene tutta la lista di episodi mancanti formattati."""
        missing = []

        for page in count(1):
            res = self.sonarr.wantedMissing(page=page)
            res.raise_for_status()
            data = res.json()

            if len(data["records"]) == 0: break
            missing.extend(data['records'])

        # Riduco in "Serie -> Stagione -> Episodi"
        reduced_series = []
        for elem in missing:
            if self.__filter_sonarr(elem):
                self.__reduce_sonarr(reduced_series, elem)

        # Assegno il provider e riordino
        for serie in reduced_series:
            serie["provider"] = self.__extract_provider(serie["tags"], "sonarr")

            serie["seasons"].sort(key=lambda x: x["number"])
            for season in serie["seasons"]:
                season["episodes"].sort(key=lambda x: (x['seasonNumber'], x['episodeNumber']))

        return reduced_series

    def __filter_sonarr(self, elem: dict) -> bool:
        """Filtra le serie in base ai tag, con logica Custom per saltare stagioni e mettere in pausa."""
        series_title = elem["series"]["title"]
        season_num = elem["seasonNumber"]
        tag_ids = elem["series"]["tags"]

        # 1. Controllo base Whitelist/Blacklist
        if not self.__check_tags_validity(series_title, tag_ids):
            return False

        # --- MAGIA CUSTOM: CONTROLLO TAG SPECIFICI ---
        
        # Convertiamo gli ID dei tag nei loro nomi leggibili (tutti in minuscolo)
        tag_names = [self.sonarr_tags_map.get(t_id, "") for t_id in tag_ids]

        # Regola A: Freno a mano (Tag 'hold' o 'pausa')
        if "hold" in tag_names or "pausa" in tag_names:
            log_key = f"{series_title}_hold"
            if log_key not in self._logged_skipped_series:
                self.log.info(f"⏸️ '{series_title}' in PAUSA. In attesa di approvazione (Rimuovi il tag 'hold' da Sonarr per avviare).")
                self._logged_skipped_series.add(log_key)
            return False

        # Regola B: Salta stagioni specifiche (Es. se c'è il tag 'skip-s1')
        target_tag = f"skip-s{season_num}"
        if target_tag in tag_names:
            log_key = f"{series_title}_skip_{season_num}"
            if log_key not in self._logged_skipped_series:
                self.log.info(f"⏭️ Stagione {season_num} di '{series_title}' ignorata (Richiesto dal tag {target_tag}).")
                self._logged_skipped_series.add(log_key)
            return False

        # Regola C: Salta sempre la stagione 0 (Speciali) di default
        if season_num == 0:
            if series_title not in self._logged_skipped_series:
                self.log.debug(f"❌ Stagione 0 (Speciali) di '{series_title}' scartata di default.")
                self._logged_skipped_series.add(series_title)
            return False
            
        # ---------------------------------------------

        return True


    

    def __reduce_sonarr(self, base: list, elem: dict):
        """Impacchetta le chiamate piatte API di Sonarr in oggetti gerarchici."""
        # Cerca la serie
        serie = next((s for s in base if s["id"] == elem["series"]["id"]), None)
        if not serie:
            serie = {
                "content_type": "serie",
                "title": elem["series"]["title"],
                "path": elem["series"]["path"],
                "id": elem["series"]["id"],
                "tags": elem["series"]["tags"],
                "seasons": []
            }
            base.append(serie)

        # Cerca la stagione
        season = next((s for s in serie["seasons"] if s["number"] == elem["seasonNumber"]), None)
        if not season:
            season = {"number": elem["seasonNumber"], "episodes": []}
            serie["seasons"].append(season)

        # Aggiunge l'episodio
        season["episodes"].append({
            "id": elem["id"],
            "title": elem["title"],
            "seasonNumber": elem["seasonNumber"],
            "episodeNumber": elem["episodeNumber"],
            "absoluteEpisodeNumber": elem.get("absoluteEpisodeNumber")
        })

    ### --- RADARR LOGIC --- ###

    def __get_radarr_missing(self) -> list:
        """Ottiene tutta la lista di film mancanti."""
        missing = []

        if not hasattr(self.radarr, 'wantedMissing'): return missing

        for page in count(1):
            res = self.radarr.wantedMissing(page=page)
            if not res: break
            data = res.json()

            if len(data.get("records", [])) == 0: break
            missing.extend(data['records'])

        valid_movies = []
        for elem in missing:
            if self.__filter_radarr(elem):
                valid_movies.append({
                    "content_type": "movie",
                    "id": elem["id"],
                    "title": elem["title"],
                    "year": elem.get("year"),
                    "path": elem["path"],
                    "tags": elem["tags"],
                    "provider": self.__extract_provider(elem["tags"], "radarr")
                })

        return valid_movies

    def __filter_radarr(self, elem: dict) -> bool:
        """Filtra i film in base ai tag di whitelist/blacklist e pause manuali."""
        movie_title = elem["title"]
        tag_ids = elem.get("tags", [])

        # 1. Controllo base Whitelist/Blacklist
        if not self.__check_tags_validity(movie_title, tag_ids):
            return False

        # --- MAGIA CUSTOM PER I FILM ---
        
        # Convertiamo gli ID dei tag nei loro nomi leggibili (tutti in minuscolo)
        tag_names = [self.radarr_tags_map.get(t_id, "") for t_id in tag_ids]

        # Regola A: Freno a mano per Radarr (Tag 'hold' o 'pausa')
        if "hold" in tag_names or "pausa" in tag_names:
            if movie_title not in self._logged_skipped_series:
                self.log.info(f"⏸️ '{movie_title}' in PAUSA. In attesa di approvazione (Rimuovi il tag 'hold' da Radarr per avviare).")
                self._logged_skipped_series.add(movie_title)
            return False
            
        # ---------------------------------------------

        return True

    ### --- GLOBAL UTILITIES --- ###

    def __check_tags_validity(self, title: str, item_tags: list) -> bool:
        """Verifica se l'elemento rispetta Whitelist/Blacklist nelle settings."""
        active_tags: List[int] = [x['id'] for x in self.tags if self.tags.isActive(x['id'])]
        item_has_active_tag = any(t in active_tags for t in item_tags)

        if self.settings["TagsMode"] == "BLACKLIST" and item_has_active_tag:
            if title not in self._logged_skipped_series:
                self.log.debug(f"❌ '{title}' scartato (Ha un tag in BLACKLIST).")
                self._logged_skipped_series.add(title)
            return False
            
        if self.settings["TagsMode"] == "WHITELIST" and not item_has_active_tag:
            if title not in self._logged_skipped_series:
                self.log.debug(f"❌ '{title}' scartato (Nessun tag attivo in WHITELIST).")
                self._logged_skipped_series.add(title)
            return False
            
        return True

    def __extract_provider(self, tag_ids: list[int], source: str) -> str:
        """
        Legge gli ID dei tag, interroga i server e cerca quello del provider.
        """
        # Seleziona la mappa corretta (Sonarr o Radarr)
        tags_map = self.sonarr_tags_map if source == "sonarr" else self.radarr_tags_map
        
        for t_id in tag_ids:
            label = tags_map.get(t_id, "")
            
            # Se trova un tag che inizia per 'provider-', estrae il nome
            if label.startswith("provider-"):
                return label.replace("provider-", "").strip()
                
        # Valore di fallback se l'utente non ha assegnato tag provider
        return "streamingcommunity"