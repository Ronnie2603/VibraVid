from ..database import Settings
from ..connection import ConnectionsManager, Sonarr, Radarr
from .Constant import LOGGER
from ..utility import ColoredString as cs

import subprocess
import pathlib
import time
import shutil
import requests
import datetime


class Downloader:
    """Gestisce il corretto download tramite VibraVid e l'importazione in Sonarr/Radarr."""

    def __init__(self, settings: Settings, sonarr: Sonarr, radarr: Radarr, connections: ConnectionsManager,
                 folder: pathlib.Path):
        self.settings = settings
        self.sonarr = sonarr
        self.radarr = radarr
        self.connections = connections
        self.folder = folder
        self.log = LOGGER

    def download(self, item: dict):
        """
        Smista l'elemento da scaricare tra Serie (Sonarr) e Film (Radarr).
        """
        content_type = item.get("content_type")

        if content_type == "serie":
            self._process_serie(item)
        elif content_type == "movie":
            self._process_movie(item)
        else:
            self.log.error(f"❌ Tipo di contenuto sconosciuto: {content_type}")

    ### --- LOGICA SONARR (SERIE E ANIME) --- ###

    def _process_serie(self, serie: dict):
        title = serie["title"]
        provider = serie.get("provider", "streamingcommunity")

        for season in serie["seasons"]:
            season_num = season["number"]
            self.log.info(f"🔎 Ricerca serie '{title}' stagione {season_num} sul provider [{provider.upper()}].")

            # Determinazione della cartella corretta nel container
            target_folder = pathlib.Path('/app/Video/Serie').joinpath(title, f"S{season_num:02d}")

            year_range = None
            year = serie.get("year") # Tentativo di prenderlo dal dizionario iniziale

            # --- Recuperiamo il titolo originale e l'anno di inizio della serie ---
            try:
                api_key = getattr(self.sonarr, 'apikey', None) or getattr(self.sonarr, 'api_key', None)
                sonarr_url = getattr(self.sonarr, 'url', None) or getattr(self.sonarr, 'base_url', 'http://localhost:8989')
                
                url_get = f"{sonarr_url}/api/v3/series"
                headers = {"X-Api-Key": api_key}
                response_get = requests.get(url_get, headers=headers)
                
                if response_get.status_code == 200:
                    series_list = response_get.json()
                    for s in series_list:
                        if s.get("title", "").lower() == title.lower() or s.get("titleSlug", "").lower() == title.lower():
                            original_title = s.get("originalTitle")
                            if original_title:
                                title = original_title
                                self.log.info(f"🌐 Trovato titolo originale da Sonarr/TVDB: '{title}'")
                            
                            # Se non è stato trovato nel dizionario, lo prendiamo dalle API
                            if not year:
                                year = s.get("year")
                                
                            break
            except Exception as e:
                self.log.error(f"⚠️ Impossibile ottenere il titolo originale o l'anno da Sonarr: {e}")
            # -------------------------------------------------------------------------

            # Elaborazione del range dell'anno
            if year:
                try:
                    y = int(year)
                    if y >= (datetime.datetime.now().year - 1):  # Anno attuale - 1
                        year_range = f"{y}-9999"
                    else:
                        year_range = f"{y}-{y + 1}"
                except ValueError:
                    pass

            for episode in season["episodes"]:
                ep_num = episode['episodeNumber']
                ep_id = episode['id']

                self.log.info("")
                self.log.info(f"⚙️ Analisi episodio S{season_num}E{ep_num}...")

                if self.__isInQueueSonarr(ep_id):
                    self.log.info("🔒 L'episodio è già in download su Sonarr.")
                    continue

                self.log.warning(f"⏳ Avvio VibraVid per l'episodio S{season_num}E{ep_num}...")

                comando = [
                    "VibraVid",
                    "--search", title,
                    "--site", provider,
                    "--season", str(season_num),
                    "--episode", str(ep_num),
                ]

                if year_range:
                    comando.extend(["--year", year_range])
                
                comando.append("--auto-first")

                # Log di debug per controllare esattamente il comando
                self.log.debug(f"Comando inviato a VibraVid: {' '.join(comando)}")

                success = self.__run_vibravid(comando)

                if success:
                    self.log.info("✔️ Download Completato da VibraVid.")
                    self.log.info(f"⏳ Avviso Sonarr di importare il file da {target_folder}...")

                    # Richiama l'API di Sonarr per scansionare la cartella finale
                    self.sonarr.commandDownloadedEpisodesScan(str(target_folder))
                    
                    # Attendiamo che il server elabori l'importazione
                    time.sleep(5)

                    # --- IMPOSTAZIONE DELL'EPISODIO SU UNMONITORED PER RIMUOVERLO DAI MANCANTI ---
                    self.log.info(f"🔒 Impostazione dell'episodio S{season_num}E{ep_num} su 'Unmonitored' in Sonarr...")
                    try:
                        api_key = getattr(self.sonarr, 'apikey', None) or getattr(self.sonarr, 'api_key', None)
                        sonarr_url = getattr(self.sonarr, 'url', None) or getattr(self.sonarr, 'base_url', 'http://localhost:8989')
                        
                        if api_key:
                            url = f"{sonarr_url}/api/v3/episode/monitor"
                            headers = {
                                "X-Api-Key": api_key,
                                "Content-Type": "application/json"
                            }
                            payload = {
                                "episodeIds": [ep_id],
                                "monitored": False
                            }
                            
                            response = requests.put(url, json=payload, headers=headers)
                            if response.status_code in [200, 202]:
                                self.log.info("✔️ Episodio impostato su Unmonitored con successo.")
                            else:
                                self.log.error(f"⚠️ Errore durante l'impostazione di Unmonitored. Codice: {response.status_code}")
                        else:
                            self.log.error("⚠️ Chiave API di Sonarr non trovata nell'istanza.")
                    except Exception as e:
                        self.log.error(f"⚠️ Impossibile impostare l'episodio come Unmonitored: {e}")
                    # -----------------------------------------------------------------------------

                    self.log.info('✉️ Inviando il messaggio tramite Connections.')
                    self.connections.send(
                        f"*Nuovo Episodio!*\n{title} - S{season_num}E{ep_num} scaricato tramite {provider.capitalize()}")
                else:
                    self.log.error("✖️ Errore durante il download con VibraVid.")

    ### --- LOGICA RADARR (FILM) --- ###

    def _process_movie(self, movie: dict):
        title = movie["title"]
        movie_id = movie["id"]
        tmdb_id = movie.get("tmdbId")
        provider = movie.get("provider", "streamingcommunity")

        self.log.info(f"🔎 Ricerca film '{title}' sul provider [{provider.upper()}].")

        if self.__isInQueueRadarr(movie_id):
            self.log.info("🔒 Il film è già in download su Radarr.")
            return

        year_range = None
        year = movie.get("year")  # Tentativo di prenderlo dal dizionario iniziale

        # --- Recuperiamo il titolo originale e l'anno da TMDB tramite Radarr ---
        if tmdb_id:
            try:
                api_key = getattr(self.radarr, 'apikey', None) or getattr(self.radarr, 'api_key', None)
                radarr_url = getattr(self.radarr, 'url', None) or getattr(self.radarr, 'base_url', 'http://localhost:7878')
                
                url_get = f"{radarr_url}/api/v3/movie/{movie_id}"
                headers = {"X-Api-Key": api_key}
                response_get = requests.get(url_get, headers=headers)
                
                if response_get.status_code == 200:
                    movie_info = response_get.json()
                    original_title = movie_info.get("originalTitle")
                    if original_title:
                        title = original_title
                        self.log.info(f"🌐 Trovato titolo originale da TMDB/Radarr: '{title}'")
                    
                    # Se non è stato trovato nel dizionario, lo prendiamo dalle API
                    if not year:
                        year = movie_info.get("year")
                        
                    if year:
                        self.log.info(f"🌐 Trovato anno di uscita: {year}")
            except Exception as e:
                self.log.error(f"⚠️ Impossibile ottenere il titolo o l'anno da TMDB/Radarr: {e}")
        # --------------------------------------------------------------

        # Elaborazione del range dell'anno
        if year:
            try:
                y = int(year)
                if y >= (datetime.datetime.now().year - 1):  # Anno attuale - 1
                    year_range = f"{y}-9999"
                else:
                    year_range = f"{y}-{y + 1}"
            except ValueError:
                pass

        # --- Workaround per titoli composti da molte parole ---
        if "Philosopher's Stone" in title:
            query_title = "Harry Potter Philosopher"
        elif "Chamber of Secrets" in title:
            query_title = "Harry Potter Chamber"
        else:
            query_title = title.split(" - ")[0]

        self.log.warning(f"⏳ Avvio VibraVid per il film '{query_title}'...")

        target_folder = pathlib.Path('/app/Video/Movie').joinpath(title)

        comando = [
            "VibraVid",
            "--search", query_title,
            "--site", provider,
        ]

        if year_range:
            comando.extend(["--year", year_range])

        comando.append("--auto-first")

        # Log di debug per controllare esattamente il comando
        self.log.debug(f"Comando inviato a VibraVid: {' '.join(comando)}")

        success = self.__run_vibravid(comando)

        if success:
            self.log.info("✔️ Download Completato da VibraVid.")
            self.log.info(f"⏳ Avviso Radarr di importare il file da {target_folder}...")

            self.radarr.commandDownloadedMoviesScan(str(target_folder))
            time.sleep(5)

            self.log.info(f"🔒 Impostazione del film '{title}' su 'Unmonitored' in Radarr...")
            try:
                api_key = getattr(self.radarr, 'apikey', None) or getattr(self.radarr, 'api_key', None)
                radarr_url = getattr(self.radarr, 'url', None) or getattr(self.radarr, 'base_url', 'http://localhost:7878')
                
                if api_key:
                    url_get = f"{radarr_url}/api/v3/movie/{movie_id}"
                    headers = {"X-Api-Key": api_key}
                    response_get = requests.get(url_get, headers=headers)
                    
                    if response_get.status_code == 200:
                        movie_data = response_get.json()
                        movie_data["monitored"] = False
                        
                        url_put = f"{radarr_url}/api/v3/movie/{movie_id}"
                        headers_put = {
                            "X-Api-Key": api_key,
                            "Content-Type": "application/json"
                        }
                        
                        response_put = requests.put(url_put, json=movie_data, headers=headers_put)
                        
                        if response_put.status_code in [200, 202]:
                            self.log.info("✔️ Film impostato su Unmonitored con successo.")
                        else:
                            self.log.error(f"⚠️ Errore durante l'impostazione di Unmonitored su Radarr. Codice: {response_put.status_code}")
                    else:
                        self.log.error("⚠️ Impossibile recuperare i dati del film da Radarr.")
                else:
                    self.log.error("⚠️ Chiave API di Radarr non trovata nell'istanza.")
            except Exception as e:
                self.log.error(f"⚠️ Impossibile impostare il film come Unmonitored: {e}")

            self.log.info('✉️ Inviando il messaggio tramite Connections.')
            self.connections.send(f"*Nuovo Film!*\n{title} scaricato tramite {provider.capitalize()}")
        else:
            self.log.error("✖️ Errore durante il download del film con VibraVid.")

    ### --- CORE SUBPROCESS --- ###

    def __run_vibravid(self, comando: list) -> bool:
        """Esegue VibraVid e mostra i log in tempo reale."""
        try:
            process = subprocess.Popen(
                comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                if line:
                    clean_line = line.strip()
                    self.log.info(f"VibraVid ➔ {clean_line}")

            rc = process.poll()
            if rc != 0:
                self.log.error(f"⚠️ VibraVid ha terminato con un errore (Codice {rc}).")
                return False

            return True

        except FileNotFoundError:
            self.log.critical(
                "⚠️ Comando 'vibravid' non trovato! Assicurati che sia installato nell'ambiente (es. pip install VibraVid).")
            return False
        except Exception as e:
            self.log.error(f"⚠️ Errore imprevisto durante l'avvio: {e}")
            return False

    ### --- UTILITIES --- ###

    def __isInQueueSonarr(self, episode_id: int) -> bool:
        """Controllo se un episodio è in download su Sonarr."""
        try:
            res = self.sonarr.queue()
            res.raise_for_status()
            records = res.json().get("records", [])

            for record in records:
                if episode_id == record.get("episodeId"): return True
            return False
        except Exception as e:
            self.log.error(f"Errore controllo coda Sonarr: {e}")
            return False

    def __isInQueueRadarr(self, movie_id: int) -> bool:
        """Controllo se un film è in download su Radarr."""
        try:
            res = self.radarr.queue()
            res.raise_for_status()
            records = res.json().get("records", [])

            for record in records:
                if movie_id == record.get("movieId"): return True
            return False
        except Exception as e:
            self.log.error(f"Errore controllo coda Radarr: {e}")
            return False