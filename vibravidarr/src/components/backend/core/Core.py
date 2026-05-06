from . import Constant as ctx
from ..utility import ColoredString as cs
from ..database import Settings, Tags, Table, ConnectionsDB
from ..connection import ConnectionsManager, Sonarr, Radarr, ExternalDB
from .Downloader import Downloader
from .Processor import Processor

import logging, logging.handlers
import sys, threading
import time
from typing import Optional


class Core(threading.Thread):

    def __init__(self, *,
                 settings: Optional[Settings] = None,
                 tags: Optional[Tags] = None,
                 table: Optional[Table] = None,
                 sonarr: Optional[Sonarr] = None,
                 radarr: Optional[Radarr] = None,
                 connections_db: Optional[ConnectionsDB] = None,
                 external: Optional[ExternalDB] = None
                 ):
        """
		Inizializzazione funzionalità di base con supporto Sonarr e Radarr.
		"""

        ### Setup Thread ###
        super().__init__(name=self.__class__.__name__, daemon=True)

        self.semaphore = threading.Condition()
        self.version = ctx.VERSION

        ### Setup logger ###
        self.__setupLog()

        ### Setup database ###
        self.settings = settings if settings else Settings(ctx.DATABASE_FOLDER.joinpath('settings.json'))
        self.tags = tags if tags else Tags(ctx.DATABASE_FOLDER.joinpath('tags.json'))
        self.table = table if table else Table(ctx.DATABASE_FOLDER.joinpath('table.json'))
        self.connections_db = connections_db if connections_db else ConnectionsDB(
            ctx.DATABASE_FOLDER.joinpath('connections.json'), ctx.SCRIPT_FOLDER)
        self.external = external if external else ExternalDB()

        ### Fix log level ###
        self.log.setLevel(self.settings["LogLevel"])

        ### Setup Connection ###
        self.sonarr = sonarr if sonarr else Sonarr(ctx.SONARR_URL, ctx.API_KEY)
        self.radarr = radarr if radarr else Radarr(ctx.RADARR_URL, ctx.RADARR_API_KEY)
        self.connections = ConnectionsManager(self.connections_db)

        ### Setup Logic ###
        # Il Processor ora riceve entrambi i client (Sonarr/Radarr)
        self.processor = Processor(
            sonarr=self.sonarr,
            radarr=self.radarr,
            settings=self.settings,
            table=self.table,
            tags=self.tags,
            external=self.external
        )

        # Il Downloader gestirà il lancio di VibraVid e lo spostamento file
        self.downloader = Downloader(
            settings=self.settings,
            sonarr=self.sonarr,
            radarr=self.radarr,
            connections=self.connections,
            folder=ctx.DOWNLOAD_FOLDER
        )

        self.error = None

        ### Welcome Message ###
        self.log.info(cs.blue(
            f"┌───────────────────────────────────[{time.strftime('%d %b %Y %H:%M:%S')}]───────────────────────────────────┐"))
        self.log.info(
            cs.blue(f"└────────────────────────────────────{ctx.VERSION:─^20}────────────────────────────────────┘"))
        self.log.info("")
        self.log.info("Globals")
        self.log.info(f"  ├── SONARR_URL = {ctx.SONARR_URL}")
        self.log.info(f"  ├── RADARR_URL = {ctx.RADARR_URL}")
        self.log.debug(f"  ├── DOWNLOAD_FOLDER = {ctx.DOWNLOAD_FOLDER}")
        self.log.debug(f"  ├── DATABASE_FOLDER = {ctx.DATABASE_FOLDER}")
        self.log.info(f"  └── VERSION = {ctx.VERSION}")
        self.log.info("")

        self.log.info("Settings")
        for index, setting in reversed(list(enumerate(self.settings))):
            prefix = "  └── " if index == 0 else "  ├── "
            self.log.info(f"{prefix}{setting} = {self.settings[setting]}")
        self.log.info("")

    def __setupLog(self):
        """Configura il logger per output su console e file."""
        logger = ctx.LOGGER

        # Console Handler
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter('%(levelname)-8s %(message)s'))
        logger.addHandler(stream_handler)

        # File Handler
        file_handler = logging.FileHandler(filename='log.log', encoding='utf-8', mode='w')
        file_handler.setFormatter(logging.Formatter('%(levelname)-8s %(message)s'))
        logger.addHandler(file_handler)

        logger.propagate = False
        self.log = logger

    def run(self):
        """Ciclo principale del thread."""
        self.log.info("]────────────────────────────────────────────────────────────────────────────────────────────[")

        self.semaphore.acquire()

        try:
            while True:
                start = time.time()
                self.log.info(
                    f"╭───────────────────────────────────「{time.strftime('%d %b %Y %H:%M:%S')}」───────────────────────────────────╮")

                self.job()

                next_run = self.settings['ScanDelay'] * 60 + start
                wait = next_run - time.time()
                self.log.info(
                    f"╰───────────────────────────────────「{time.strftime('%d %b %Y %H:%M:%S', time.localtime(next_run))}」───────────────────────────────────╯")
                self.log.info("")

                # Attende il prossimo ciclo o il wakeUp
                self.semaphore.wait(timeout=max(1, wait))
        except Exception as e:
            self.log.critical(
                "]─────────────────────────────────────────[CRITICAL]─────────────────────────────────────────[")
            self.log.exception(e)
            self.error = e

    def job(self):
        """
		Esegue la scansione dei mancanti e avvia i download.
		"""
        try:
            # Il Processor ora aggrega dati da Sonarr e Radarr
            missing_items = self.processor.getData()

            if not missing_items:
                self.log.info("Nessun contenuto mancante trovato.")
                return

            for item in missing_items:
                self.log.info(
                    "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ")
                self.downloader.download(item)
                self.log.info(
                    "─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ")
        except Exception as e:
            self.log.error(cs.red(f"ERROR: {e}"))

    def wakeUp(self) -> bool:
        """Risveglia il thread immediatamente."""
        try:
            self.semaphore.acquire()
            self.semaphore.notify()
            self.semaphore.release()
            return True
        except RuntimeError:
            return False