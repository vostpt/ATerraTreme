# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG CACHEBUST=1
RUN echo "CACHEBUST=$CACHEBUST"

COPY . .

ENV PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PORT=80

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://127.0.0.1:80/health || exit 1

CMD ["python", "app.py"]