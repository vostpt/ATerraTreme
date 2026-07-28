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

# Install Python deps first
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code + assets
COPY app.py .
COPY assets/ ./assets/
COPY templates/ ./templates/
COPY static/ ./static/


# RUN mkdir -p /app/assets

# Environment
ENV PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PORT=9076

EXPOSE 9076

# Healthcheck
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:9076/api/sismos || exit 1

# Run the app
CMD ["python", "app.py"]