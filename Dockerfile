# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# System libraries needed by geopandas / matplotlib / contextily
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgeos-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libgdal-dev \
    gdal-bin \
    libspatialindex-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code + assets
COPY app.py .
COPY assets/ ./assets/
COPY templates/ ./templates/
COPY static/ ./static/

ENV PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PORT=80

# Coolify Traefik routes to this port — keep in sync with PORT and Coolify "Ports Exposes"
EXPOSE 80

# Lightweight probe (must not call IPMA). Failing health → Traefik 502/503.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://127.0.0.1:80/health || exit 1

CMD ["python", "app.py"]
