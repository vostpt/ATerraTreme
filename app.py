from flask import Flask, jsonify, render_template, send_file
from werkzeug.middleware.proxy_fix import ProxyFix
import requests
import pandas as pd
from PIL import Image, ImageFont, ImageDraw
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import contextily as ctx
import geopandas as gpd
from datetime import datetime, timezone
import os
import threading
import time
import io
import gc
from collections import deque
from dotenv import load_dotenv
from shapely.geometry import box

load_dotenv()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")
# Coolify Dockerfile pack defaults PORT / Ports Exposes to 3000
PORT = int(os.environ.get("PORT", "3000"))

app = Flask(__name__)
# Coolify / Traefik terminate TLS and forward X-Forwarded-* headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# APIs IPMA
API_CONTINENTE = "https://api.ipma.pt/open-data/observation/seismic/7.json"
API_ACORES = "https://api.ipma.pt/open-data/observation/seismic/3.json"

# Limitar tamanho do histórico
MAX_SENT = 5000
sismos_enviados = set()
_sismos_order = deque(maxlen=MAX_SENT)  # para limpeza FIFO

# Session reutilizável
session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; SismoBot/2.0)"})

# Lock para evitar geração simultânea de imagens
image_lock = threading.Lock()


def overlay_text(img, text, position, font, color):
    draw = ImageDraw.Draw(img)
    draw.text(position, text, font=font, fill=color)


def create_map_image(df) -> Image.Image:
    """
    Gera o mapa local do sismo.

    Características:
      - Sem OpenStreetMap
      - Sem Contextily
      - Sem APIs de mapas
      - Sem API keys
      - Sem pedidos HTTP
      - Natural Earth distribuído localmente
      - Zoom automático centrado no epicentro
      - Proteção individual contra camadas em falta
      - Compatível com versões de GeoPandas sem GeoSeries.from_bbox()
    """

    from pathlib import Path

    import io
    import math

    import geopandas as gpd
    import matplotlib.pyplot as plt

    from shapely.geometry import box

    # --------------------------------------------------------
    # Último sismo
    # --------------------------------------------------------

    latest = df.iloc[-1]

    latitude = float(latest["latitude"])
    longitude = float(latest["longitude"])
    magnitude = float(latest["scale"])

    MAPDATA = Path("assets/mapdata")

    # --------------------------------------------------------
    # Ficheiros Natural Earth
    # --------------------------------------------------------

    countries_file = (
        MAPDATA / "ne_10m_admin_0_countries.shp"
    )

    coastline_file = (
        MAPDATA / "ne_10m_coastline.shp"
    )

    places_file = (
        MAPDATA / "ne_10m_populated_places.shp"
    )

    rivers_file = (
        MAPDATA / "ne_10m_rivers_lake_centerlines.shp"
    )

    lakes_file = (
        MAPDATA / "ne_10m_lakes.shp"
    )

    # --------------------------------------------------------
    # Zoom automático
    # --------------------------------------------------------
    #
    # Define o raio aproximado do mapa em km.
    #
    # Sismos pequenos:
    #   zoom mais próximo
    #
    # Sismos grandes:
    #   zoom progressivamente maior
    #
    # Mantemos sempre algum contexto geográfico.
    #

    if magnitude < 3.0:

        radius_km = 180

    elif magnitude < 4.0:

        radius_km = 250

    elif magnitude < 5.0:

        radius_km = 400

    elif magnitude < 6.0:

        radius_km = 600

    else:

        radius_km = 900

    # --------------------------------------------------------
    # Converter km para graus
    # --------------------------------------------------------
    #
    # 1 grau de latitude ≈ 111 km.
    #
    # Para longitude usamos o cos(latitude), porque a
    # distância entre meridianos diminui com a latitude.
    #

    lat_radius = radius_km / 111.0

    cos_lat = math.cos(
        math.radians(latitude)
    )

    # Evitar divisão por zero perto dos polos.

    cos_lat = max(
        abs(cos_lat),
        0.15
    )

    lon_radius = (
        radius_km /
        (111.0 * cos_lat)
    )

    WEST = longitude - lon_radius
    EAST = longitude + lon_radius

    SOUTH = latitude - lat_radius
    NORTH = latitude + lat_radius

    # --------------------------------------------------------
    # Limites geográficos razoáveis
    # --------------------------------------------------------

    WEST = max(WEST, -180)
    EAST = min(EAST, 180)

    SOUTH = max(SOUTH, -90)
    NORTH = min(NORTH, 90)

    # --------------------------------------------------------
    # Ler dados cartográficos individualmente
    # --------------------------------------------------------
    #
    # Uma camada em falta NÃO deve impedir as outras
    # de aparecerem.
    #

    countries = None
    coastline = None
    places = None
    rivers = None
    lakes = None

    def load_layer(path, name):
        """
        Carrega uma camada sem interromper o mapa caso
        o ficheiro esteja ausente ou inválido.
        """

        if not path.exists():

            print(
                f"Aviso: camada não encontrada: {path}"
            )

            return None

        try:

            layer = gpd.read_file(path)

            if layer.empty:

                print(
                    f"Aviso: camada vazia: {name}"
                )

                return None

            # ------------------------------------------------
            # CRS
            # ------------------------------------------------

            if layer.crs is None:

                print(
                    f"Aviso: {name} não possui CRS. "
                    f"A assumir EPSG:4326."
                )

                layer = layer.set_crs(
                    "EPSG:4326"
                )

            else:

                layer = layer.to_crs(
                    "EPSG:4326"
                )

            return layer

        except Exception as e:

            print(
                f"Aviso: erro ao carregar "
                f"{name}: {e}"
            )

            return None

    countries = load_layer(
        countries_file,
        "countries"
    )

    coastline = load_layer(
        coastline_file,
        "coastline"
    )

    places = load_layer(
        places_file,
        "places"
    )

    rivers = load_layer(
        rivers_file,
        "rivers"
    )

    lakes = load_layer(
        lakes_file,
        "lakes"
    )

    # --------------------------------------------------------
    # Criar bounding box
    # --------------------------------------------------------
    #
    # NÃO utilizar:
    #
    # gpd.GeoSeries.from_bbox(...)
    #
    # porque essa API não existe em algumas versões
    # do GeoPandas.
    #
    # shapely.geometry.box() é compatível.
    #

    bbox_geometry = box(
        WEST,
        SOUTH,
        EAST,
        NORTH
    )

    # --------------------------------------------------------
    # Cortar uma camada
    # --------------------------------------------------------

    def clip_layer(layer, name):

        if layer is None:
            return None

        try:

            # ------------------------------------------------
            # Usamos clip diretamente com a geometria.
            #
            # Isto evita depender de funcionalidades
            # específicas de versões do GeoPandas.
            # ------------------------------------------------

            clipped = gpd.clip(
                layer,
                bbox_geometry
            )

            if clipped.empty:

                print(
                    f"Aviso: {name} não possui "
                    f"dados dentro do mapa."
                )

                return None

            return clipped

        except Exception as e:

            print(
                f"Aviso: erro ao cortar "
                f"{name}: {e}"
            )

            return layer

    countries = clip_layer(
        countries,
        "countries"
    )

    coastline = clip_layer(
        coastline,
        "coastline"
    )

    places = clip_layer(
        places,
        "places"
    )

    rivers = clip_layer(
        rivers,
        "rivers"
    )

    lakes = clip_layer(
        lakes,
        "lakes"
    )

    # --------------------------------------------------------
    # Figura
    # --------------------------------------------------------

    fig = plt.figure(
        figsize=(6, 6),
        dpi=180
    )

    ax = fig.add_axes(
        [0, 0, 1, 1]
    )

    ax.set_facecolor(
        "#dcecf4"
    )

    # --------------------------------------------------------
    # Países
    # --------------------------------------------------------

    if (
        countries is not None
        and not countries.empty
    ):

        try:

            countries.plot(
                ax=ax,

                color="#eeeeea",

                edgecolor="#b6b6b2",

                linewidth=0.45,

                zorder=1
            )

        except Exception as e:

            print(
                f"Aviso ao desenhar países: {e}"
            )

    # --------------------------------------------------------
    # Lagos
    # --------------------------------------------------------

    if (
        lakes is not None
        and not lakes.empty
    ):

        try:

            lakes.plot(
                ax=ax,

                color="#dcecf4",

                edgecolor="#a9cddc",

                linewidth=0.35,

                zorder=2
            )

        except Exception as e:

            print(
                f"Aviso ao desenhar lagos: {e}"
            )

    # --------------------------------------------------------
    # Rios
    # --------------------------------------------------------

    if (
        rivers is not None
        and not rivers.empty
    ):

        try:

            important_rivers = rivers

            # Natural Earth normalmente possui
            # SCALERANK/scalerank dependendo da versão.

            scalerank_column = None

            if "scalerank" in rivers.columns:

                scalerank_column = "scalerank"

            elif "SCALERANK" in rivers.columns:

                scalerank_column = "SCALERANK"

            if scalerank_column:

                important_rivers = rivers[
                    rivers[
                        scalerank_column
                    ].fillna(99) <= 6
                ]

            if not important_rivers.empty:

                important_rivers.plot(
                    ax=ax,

                    color="#8ebfd3",

                    linewidth=0.45,

                    alpha=0.85,

                    zorder=3
                )

        except Exception as e:

            print(
                f"Aviso ao desenhar rios: {e}"
            )

    # --------------------------------------------------------
    # Costa
    # --------------------------------------------------------

    if (
        coastline is not None
        and not coastline.empty
    ):

        try:

            coastline.plot(
                ax=ax,

                color="#777777",

                linewidth=0.75,

                zorder=4
            )

        except Exception as e:

            print(
                f"Aviso ao desenhar costa: {e}"
            )

    # --------------------------------------------------------
    # Cidades
    # --------------------------------------------------------

    if (
        places is not None
        and not places.empty
    ):

        try:

            major_places = places

            # ------------------------------------------------
            # Selecionar cidades por população
            # ------------------------------------------------

            if "POP_MAX" in places.columns:

                pop = (
                    places["POP_MAX"]
                    .fillna(0)
                )

                major_places = places[
                    pop >= 100000
                ]

            elif "pop_max" in places.columns:

                pop = (
                    places["pop_max"]
                    .fillna(0)
                )

                major_places = places[
                    pop >= 100000
                ]

            # ------------------------------------------------
            # Alternativa usando SCALERANK
            # ------------------------------------------------

            elif "SCALERANK" in places.columns:

                major_places = places[
                    places["SCALERANK"]
                    .fillna(99)
                    <= 7
                ]

            elif "scalerank" in places.columns:

                major_places = places[
                    places["scalerank"]
                    .fillna(99)
                    <= 7
                ]

            # ------------------------------------------------
            # Limitar número de cidades
            # ------------------------------------------------

            if len(major_places) > 35:

                if "POP_MAX" in major_places.columns:

                    major_places = (
                        major_places
                        .sort_values(
                            "POP_MAX",
                            ascending=False
                        )
                        .head(35)
                    )

                elif "pop_max" in major_places.columns:

                    major_places = (
                        major_places
                        .sort_values(
                            "pop_max",
                            ascending=False
                        )
                        .head(35)
                    )

                else:

                    major_places = (
                        major_places
                        .head(35)
                    )

            # ------------------------------------------------
            # Desenhar pontos
            # ------------------------------------------------

            if not major_places.empty:

                major_places.plot(
                    ax=ax,

                    color="#555555",

                    markersize=8,

                    alpha=0.9,

                    zorder=6
                )

                # --------------------------------------------
                # Encontrar nome da cidade
                # --------------------------------------------

                name_column = None

                for candidate in (
                    "NAMEASCII",
                    "nameascii",
                    "NAME",
                    "name",
                    "NAMEPAR",
                    "NAMEARAB"
                ):

                    if (
                        candidate
                        in major_places.columns
                    ):

                        name_column = candidate

                        break

                # --------------------------------------------
                # Labels
                # --------------------------------------------

                if name_column:

                    for _, city in (
                        major_places.iterrows()
                    ):

                        try:

                            if city.geometry is None:
                                continue

                            if city.geometry.is_empty:
                                continue

                            x = city.geometry.x
                            y = city.geometry.y

                            name = str(
                                city[name_column]
                            )

                            if not name:
                                continue

                            ax.annotate(
                                name,

                                xy=(x, y),

                                xytext=(4, 4),

                                textcoords=(
                                    "offset points"
                                ),

                                fontsize=6.2,

                                color="#444444",

                                fontweight="bold",

                                zorder=7
                            )

                        except Exception:

                            continue

        except Exception as e:

            print(
                f"Aviso ao desenhar cidades: {e}"
            )

    # --------------------------------------------------------
    # Epicentro
    # --------------------------------------------------------

    ax.scatter(
        longitude,
        latitude,

        s=7000,

        color="red",

        alpha=0.10,

        zorder=10
    )

    ax.scatter(
        longitude,
        latitude,

        s=2500,

        color="red",

        alpha=0.25,

        zorder=11
    )

    ax.scatter(
        longitude,
        latitude,

        s=350,

        marker="*",

        color="darkred",

        edgecolors="white",

        linewidth=1.5,

        zorder=12
    )

    # --------------------------------------------------------
    # Magnitude
    # --------------------------------------------------------

    ax.text(
        longitude,

        latitude + (
            lat_radius * 0.08
        ),

        f"M {magnitude:.1f}",

        fontsize=16,

        fontweight="bold",

        ha="center",

        va="bottom",

        color="black",

        bbox=dict(
            facecolor="white",

            edgecolor="black",

            alpha=0.92,

            boxstyle="round,pad=0.3"
        ),

        zorder=13
    )

    # --------------------------------------------------------
    # Limites do mapa
    # --------------------------------------------------------

    ax.set_xlim(
        WEST,
        EAST
    )

    ax.set_ylim(
        SOUTH,
        NORTH
    )

    ax.set_aspect(
        "equal",
        adjustable="box"
    )

    ax.set_axis_off()

    # --------------------------------------------------------
    # Atribuição
    # --------------------------------------------------------

    ax.text(
        0.995,

        0.012,

        "Natural Earth",

        transform=ax.transAxes,

        ha="right",

        va="bottom",

        fontsize=5.5,

        color="#666666",

        alpha=0.8,

        zorder=20
    )

    # --------------------------------------------------------
    # Gerar PNG
    # --------------------------------------------------------

    buf = io.BytesIO()

    fig.savefig(
        buf,

        format="png",

        dpi=180,

        facecolor="white",

        pad_inches=0
    )

    plt.close(fig)

    plt.close("all")

    buf.seek(0)

    img = Image.open(
        buf
    ).convert("RGB")

    buf.close()

    return img

def generate_final_image(sismo_data) -> bytes:
    """Gera a imagem final completa e devolve os bytes."""
    with image_lock:
        if isinstance(sismo_data, dict):
            df = pd.DataFrame([sismo_data])
        else:
            df = pd.DataFrame(sismo_data)

        map_img = create_map_image(df)

        template = Image.open("assets/SISMO_TEMPLATE_AUTO.png").convert("RGB")
        font = ImageFont.truetype("assets/Lato-Bold.ttf", 38)

        latest = df.iloc[-1]

        overlay_text(template, str(latest['location']).upper(), (390, 559), font, "#703D25")
        overlay_text(template, str(latest['scale']), (455, 629), font, "#703D25")
        overlay_text(template, str(latest['date']), (242, 772), font, "#00A396")
        overlay_text(template, str(latest['intensity']), (520, 832), font, "#00A396")


        # Image with just info (no map)
        info_buf = io.BytesIO()
        template.save("assets/SISMO_INFO.png", optimize=True)
        template.save(info_buf, format="PNG", optimize=True)
        info_buf.seek(0)
        info_data = info_buf.getvalue()
        info_buf.close()

        # Image with the just the map
        map_buf = io.BytesIO()
        map_img.save("assets/MAPA_SISMO.png", optimize=True)
        map_img.save(map_buf, format="PNG", optimize=True)
        map_buf.seek(0)
        map_data = map_buf.getvalue()
        map_buf.close()

        # Image with map (final)
        final = Image.new("RGB", (2160, 1080), color="white")
        final.paste(template, (0, 0))
        final.paste(map_img, (1080, 0))

        final.save("assets/SISMO_TWEET.png", optimize=True)

        # Bytes para envio imediato
        buf = io.BytesIO()
        final.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        data = buf.getvalue()
        buf.close()

        # Limpeza
        del map_img, template, final, df
        gc.collect()

        return data, info_data, map_data


def enviar_discord(sismo, image_bytes: bytes, info_image: bytes, map_image: bytes, tentativas=4):
    if not DISCORD_WEBHOOK:
        print("Webhook não configurado.")
        return False

    mensagem = (
        f"🌍 **Novo sismo registado**\n\n"
        f"📍 Local: {sismo['location']}\n"
        f"📈 Magnitude: {sismo['scale']}\n"
        f"🕒 {sismo['date']}"
    )

    for tentativa in range(1, tentativas + 1):
        try:
            files = {"file1": ("SISMO.png", image_bytes, "image/png"), "file2": ("SISMO_INFO.png", info_image, "image/png"), "file3": ("SISMO_MAP.png", map_image, "image/png")}
            r = session.post(
                DISCORD_WEBHOOK,
                data={"content": mensagem},
                files=files,
                timeout=25
            )

            if r.status_code in (200, 204):
                print(f"Discord: enviado à {tentativa}ª tentativa.")
                return True

            print(f"Discord respondeu {r.status_code} (tentativa {tentativa})")
        except Exception as e:
            print(f"Erro ao enviar para o Discord: {e}")

        time.sleep(3 + tentativa)

    return False


def obter_sismos():
    sismos = []

    for url, regiao in [(API_CONTINENTE, "Continente e Madeira"), (API_ACORES, "Açores")]:
        try:
            response = session.get(url, timeout=20)
            response.raise_for_status()
            dados = response.json()

            for s in dados.get("data", []):
                mag_str = s.get("magnitud", "-99.0")
                try:
                    mag = float(mag_str)
                    if mag == -99.0 or mag < 0:
                        mag = None
                except (ValueError, TypeError):
                    mag = None

                sismos.append({
                    "areaID": dados.get("idArea"),
                    "obsRegion": s.get("obsRegion") or s.get("regionName"),
                    "magnitude": mag,
                    "depth": s.get("depth"),
                    "intensity": s.get("degree") if s.get("degree") not in (None, "", "0") else "Sem info",
                    "latitude": float(s.get("lat") or s.get("latitude") or 0),
                    "longitude": float(s.get("lon") or s.get("longitude") or 0),
                    "time": s.get("time"),
                    "source": s.get("source", "IPMA"),
                })
        except Exception as e:
            print(f"Erro ao buscar API {regiao}: {e}")

    # Converter time para datetime
    for s in sismos:
        try:
            time_str = s["time"].replace("Z", "+00:00")
            s["datetime"] = datetime.fromisoformat(time_str)
        except Exception:
            try:
                s["datetime"] = datetime.fromisoformat(s["time"])
            except Exception:
                try:
                    s["datetime"] = datetime.strptime(s["time"], "%Y-%m-%d %H:%M:%S")
                except Exception:
                    s["datetime"] = datetime.now(timezone.utc)

    sismos.sort(key=lambda x: x["datetime"], reverse=True)
    return {
        "owner": "IPMA",
        "country": "PT",
        "total": len(sismos),
        "data": sismos,
    }


def add_enviado(sismo_id: str):
    """Adiciona ao set e remove o mais antigo se ultrapassar o limite."""
    if sismo_id in sismos_enviados:
        return
    if len(sismos_enviados) >= MAX_SENT:
        oldest = _sismos_order.popleft()
        sismos_enviados.discard(oldest)
    sismos_enviados.add(sismo_id)
    _sismos_order.append(sismo_id)


def monitor_sismos():
    print("Monitor de sismos iniciado.")
    consecutive_errors = 0

    while True:
        try:
            data = obter_sismos()

            if not data["data"]:
                time.sleep(45)
                continue

            # novos = [s for s in data["data"] if s["time"] not in sismos_enviados]
            novos = data["data"][:10]  # apenas os 10 mais recentes (for testing purposes)
            
            if not novos:
                consecutive_errors = 0
                time.sleep(45)
                continue

            novos.sort(key=lambda x: x["datetime"])
            print(f"Foram encontrados {len(novos)} novos sismos.")

            for s in novos:
                sismo = {
                    "id": s["time"],
                    "location": s.get("obsRegion") or "Portugal",
                    "scale": s["magnitude"] or 0.0,
                    "date": s["datetime"].strftime("%d-%m-%Y pelas %H:%M UTC"),
                    "intensity": "Sem info a esta hora",
                    "latitude": s["latitude"],
                    "longitude": s["longitude"]
                }

                print(f"Processar → {sismo['location']} M{sismo['scale']} | {sismo['id']}")

                try:
                    image_bytes, info_image, map_image = generate_final_image(sismo)
                    if enviar_discord(sismo, image_bytes, info_image, map_image):
                        add_enviado(s["time"])
                        time.sleep(1.5)
                except Exception as e:
                    print(f"Erro ao processar sismo {s['time']}: {e}")
                    # não marca como enviado → tenta na próxima ronda

            consecutive_errors = 0
            gc.collect()

        except Exception as e:
            consecutive_errors += 1
            print(f"Erro no monitor (#{consecutive_errors}): {e}")
            # Backoff exponencial leve
            sleep_time = min(30 * consecutive_errors, 180)
            time.sleep(sleep_time)
            continue

        time.sleep(45)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    """Lightweight probe for Docker/Coolify — does not call external APIs."""
    return jsonify({"status": "ok"}), 200


@app.route("/api/sismos")
def api_sismos():
    return jsonify(obter_sismos())


@app.route("/assets/SISMO_TWEET.png")
def download_image():
    path = "assets/SISMO_TWEET.png"
    if os.path.exists(path):
        return send_file(path, mimetype="image/png")
    return "Imagem ainda não gerada.", 404


def bootstrap_monitor():
    """Seed known earthquakes then enter the Discord monitor loop."""
    try:
        data = obter_sismos()
        for s in data["data"]:
            add_enviado(s["time"])
        print(f"{len(sismos_enviados)} sismos existentes ignorados.")
    except Exception as e:
        print(f"Aviso: não foi possível pré-carregar sismos: {e}")

    monitor_sismos()


if __name__ == "__main__":
    os.makedirs("assets", exist_ok=True)

    # Start monitor in background so Flask binds immediately (Coolify healthchecks)
    t = threading.Thread(target=bootstrap_monitor, daemon=True, name="SismoMonitor")
    t.start()

    print(f"A servir em 0.0.0.0:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)