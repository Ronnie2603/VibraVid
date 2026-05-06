import os
import pathlib
import logging

# Versione del software
VERSION = "2.0.0-VibraVid"

# Percorsi principali
BASE_FOLDER = pathlib.Path(__file__).resolve().parent.parent.parent.parent.parent
DATABASE_FOLDER = pathlib.Path('/database')
DOWNLOAD_FOLDER = pathlib.Path('/downloads')
SCRIPT_FOLDER = pathlib.Path('/scripts')

# Assicurati che le cartelle esistano
DATABASE_FOLDER.mkdir(parents=True, exist_ok=True)
DOWNLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
SCRIPT_FOLDER.mkdir(parents=True, exist_ok=True)

# Configurazioni Sonarr
SONARR_URL = os.environ.get('SONARR_URL', 'http://localhost:8989')
API_KEY = os.environ.get('SONARR_API_KEY', '') # API Key di Sonarr

# Configurazioni Radarr
RADARR_URL = os.environ.get('RADARR_URL', 'http://localhost:7878')
RADARR_API_KEY = os.environ.get('RADARR_API_KEY', '') # API Key di Radarr

# Logger globale
LOGGER = logging.getLogger("SonarrRadarrVibraVid")
LOGGER.setLevel(logging.DEBUG)