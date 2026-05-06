# Usa un'immagine Python ufficiale e leggera
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 1. LAYER LENTO (SISTEMA) - Questo verrà messo in cache per sempre
RUN apt-get update && apt-get install -y \
    git \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 2. LAYER DELLE LIBRERIE - Unito in una sola riga per ottimizzare la cache
RUN pip install git+https://github.com/AstraeLabs/VibraVid.git httpx requests tenacity

# 3. LAYER DEL CODICE
# Copiamo il codice (questa operazione ora è superflua per lo sviluppo grazie al docker-compose,
# ma è buona norma lasciarla per quando vorrai rilasciare il container "in produzione")
COPY src/ /app/src/
COPY main.py /app/main.py

RUN mkdir -p /database /downloads /scripts

# Comando corretto per avviare il bridge
CMD ["python", "main.py"]