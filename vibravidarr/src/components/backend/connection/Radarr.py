import httpx
from ..core.Constant import LOGGER


class Radarr:
    """
    Collegamento con le API di Radarr.
    Maggiori info: https://radarr.video/docs/api/
    """

    def __init__(self, url: str, api_key: str) -> None:
        self.log = LOGGER
        self.url = url
        self.api_key = api_key
        self.client = httpx.Client(
            base_url=f"{url}/api/v3",
            headers={
                'X-Api-Key': api_key
            },
            timeout=5
        )

        # Controlla che il sito sia raggiungibile e che la api_key sia valida
        self.systemStatus().raise_for_status()

    def systemStatus(self) -> httpx.Response:
        """
        Controlla lo stato del sistema.

        Returns:
          La risposta HTTP
        """
        return self.client.get("/system/status")

    def wantedMissing(self, n: int = 20, page: int = 1) -> httpx.Response:
        """
        Ottiene le informazioni riguardanti i film mancanti.

        Args:
          n: numero di film massimi richiesti
          page: pagina da scaricare

        Returns:
          La risposta HTTP
        """
        # Radarr non usa includeSeries, solo paginazione e ordinamento
        return self.client.get("/wanted/missing", params={
            "pageSize": n,
            "page": page
        })

    def movie(self, movieId: int) -> httpx.Response:
        """
        Ottiene informazioni su un film.

        Args:
          movieId: ID del film

        Returns:
          La risposta HTTP
        """
        return self.client.get(f"/movie/{movieId}")

    def queue(self) -> httpx.Response:
        """
        Ottiene la lista di elementi che sono nella coda di download.

        Returns:
          La risposta HTTP
        """
        return self.client.get("/queue", params={
            "includeUnknownMovieItems": False,
            "includeMovie": False
        })

    def tags(self) -> httpx.Response:
        """
        Ottiene la lista dei tag.

        Returns:
          La risposta HTTP
        """
        return self.client.get("/tag", params='')

    ### COMMAND

    def commandRescanMovie(self, movieId: int) -> httpx.Response:
        """
        Esegue un rescan del film con id `movieId`.

        Args:
          movieId: ID del film

        Returns:
          La risposta HTTP
        """
        return self.client.post("/command", json={
            "name": "RescanMovie",
            "movieId": movieId
        })

    def commandRenameMovie(self, movieIds: list[int]) -> httpx.Response:
        """
        Rinomina i file dei film con id in `movieIds`.

        Args:
          movieIds: ID dei film

        Returns:
          La risposta HTTP
        """
        return self.client.post("/command", json={
            "name": "RenameMovie",
            "movieIds": movieIds
        })

    def commandRenameFiles(self, movieId: int, files: list[int]) -> httpx.Response:
        """
        Rinomina i file appartenenti ad un film.

        Args:
          movieId: ID del film
          files: ID dei file

        Returns:
          La risposta HTTP
        """
        return self.client.post("/command", json={
            "name": "RenameFiles",
            "movieId": movieId,
            "files": files
        })

    def commandDownloadedMoviesScan(self, path: str) -> httpx.Response:
        """
        Ordina a Radarr di scansionare una cartella specifica per importare i film appena scaricati.
        """
        return self.client.post("/command", json={
            "name": "DownloadedMoviesScan",
            "path": path,
            "importMode": "Auto"
        })