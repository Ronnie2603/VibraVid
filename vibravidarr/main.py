import logging
import sys
from src.components.backend.core.Core import Core

def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format='%(levelname)-8s %(message)s')
    logging.info("Avvio di VibraVid Bridge per Sonarr/Radarr in corso...")

    try:
        core = Core()
        core.start()
        core.join()
        
    except KeyboardInterrupt:
        logging.info("Chiusura del programma richiesta dall'utente (Ctrl+C).")
    except Exception as e:
        # QUESTA È LA RIGA MODIFICATA (Stamperà tutto l'errore rosso e la riga in cui è avvenuto)
        logging.exception("Chiusura inaspettata per errore critico:")

if __name__ == '__main__':
    main()