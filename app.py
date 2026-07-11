from flask import Flask, jsonify, render_template, send_file
import requests
import json
import pandas as pd
from PIL import Image, ImageFont, ImageDraw
import matplotlib.pyplot as plt
import contextily as ctx
from shapely.geometry import Point
import geopandas as gpd
from datetime import datetime
import os
import threading
import time
from dotenv import load_dotenv

load_dotenv()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

app = Flask(__name__)

URL = "https://www.ipma.pt/pt/geofisica/sismicidade/"

ultimo_sismo = None


def overlay_text(img, text, position, font, color):
    draw = ImageDraw.Draw(img)
    draw.text(position, text, font=font, fill=color)


def parse_intensity(intensity_list):
    roman = {'I':1,'II':2,'III':3,'IV':4,'V':5,'VI':6,'VII':7,'VIII':8,'IX':9,'X':10}
    result = []
    for intensity in intensity_list:
        if '/' in intensity:
            parts = intensity.split('/')
            values = [roman.get(p.strip().upper(), 1) for p in parts]
            result.append(sum(values) / 2)
        else:
            result.append(roman.get(intensity.strip().upper(), 1))
    return result


def create_map_image(df):

    latest = df.iloc[-1]

    # ----------------------------
    # Criar GeoDataFrame
    # ----------------------------
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(
            df.longitude,
            df.latitude
        ),
        crs="EPSG:4326"
    ).to_crs(epsg=3857)

    latest_point = gdf.iloc[-1]

    # Centro do mapa (epicentro)
    cx = latest_point.geometry.x
    cy = latest_point.geometry.y

    # Janela visível (175 km para cada lado)
    window = 175_000

    fig = plt.figure(figsize=(6, 6), dpi=180)
    ax = fig.add_axes([0, 0, 1, 1])

    # Centrar exatamente no epicentro
    ax.set_xlim(cx - window, cx + window)
    ax.set_ylim(cy - window, cy + window)
    ax.set_aspect("equal")

    # Mapa de fundo
    ctx.add_basemap(
        ax,
        source=ctx.providers.OpenStreetMap.Mapnik,
        attribution=False
    )

    # Halo exterior
    ax.scatter(
        cx,
        cy,
        s=7000,
        color="red",
        alpha=0.10,
        zorder=2
    )

    # Halo interior
    ax.scatter(
        cx,
        cy,
        s=2500,
        color="red",
        alpha=0.25,
        zorder=3
    )

    # Epicentro
    ax.scatter(
        cx,
        cy,
        s=350,
        marker="*",
        color="darkred",
        edgecolors="white",
        linewidth=1.5,
        zorder=4
    )

    # Magnitude
    ax.text(
        cx,
        cy + 25000,
        f"M {latest['scale']:.1f}",
        fontsize=18,
        fontweight="bold",
        ha="center",
        va="bottom",
        color="black",
        bbox=dict(
            facecolor="white",
            edgecolor="black",
            alpha=0.9,
            boxstyle="round,pad=0.3"
        ),
        zorder=5
    )

    ax.set_axis_off()

    # Remover margens
    fig.subplots_adjust(
        left=0,
        right=1,
        bottom=0,
        top=1
    )

    plt.savefig(
        "assets/MAPA_SISMO.png",
        dpi=180,
        facecolor="white",
        pad_inches=0
    )

    plt.close(fig)

def generate_final_image(sismo_data):
    if isinstance(sismo_data, dict):
        df = pd.DataFrame([sismo_data])
    else:
        df = pd.DataFrame(sismo_data)

    create_map_image(df)

    img = Image.open("assets/SISMO_TEMPLATE_AUTO.png")
    font = ImageFont.truetype("assets/Lato-Bold.ttf", 38)

    latest = df.iloc[-1]

    overlay_text(img, str(latest['location']).upper(), (390, 559), font, "#703D25")
    overlay_text(img, str(latest['scale']), (455, 629), font, "#703D25")
    overlay_text(img, str(latest['date']), (242, 772), font, "#00A396")
    overlay_text(img, str(latest['intensity']), (520, 832), font, "#703D25")

    img_final = Image.new("RGB", (2160, 1080), color="white")
    img_map = Image.open("assets/MAPA_SISMO.png")

    img_final.paste(img, (0, 0))
    img_final.paste(img_map, (1080, 0))
    img_final.save("assets/SISMO_TWEET.png")

    print("Imagem gerada: assets/SISMO_TWEET.png")


def enviar_discord(sismo):

    if not DISCORD_WEBHOOK:
        print("Webhook do Discord não configurado.")
        return

    mensagem = (
        f"🌍 **Novo sismo registado**\n\n"
        f"📍 **Local:** {sismo['location']}\n"
        f"📈 **Magnitude:** {sismo['scale']}\n"
        f"🕒 **Data:** {sismo['date']}"
    )

    with open("assets/SISMO_TWEET.png", "rb") as imagem:

        requests.post(
            DISCORD_WEBHOOK,
            data={
                "content": mensagem
            },
            files={
                "file": ("SISMO.png", imagem, "image/png")
            },
            timeout=30
        )


def monitor_sismos():

    global ultimo_sismo

    while True:

        try:

            sismo = get_latest_sismo()

            if sismo is None:
                time.sleep(60)
                continue

            identificador = (
                sismo["date"],
                sismo["location"],
                sismo["scale"]
            )

            if identificador != ultimo_sismo:

                print("Novo sismo encontrado!")

                generate_final_image(sismo)

                enviar_discord(sismo)

                ultimo_sismo = identificador

            else:
                print("Sem novos sismos.")

        except Exception as e:
            print("Erro:", e)

        time.sleep(60)

def obter_sismos():
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(URL, headers=headers, timeout=30)
    response.raise_for_status()

    html = response.text
    marker = "var seismicdata_world ="
    pos = html.find(marker)
    if pos == -1:
        raise Exception("Dados sísmicos não encontrados.")

    inicio = html.find("{", pos)
    nivel = 0
    fim = None
    for i in range(inicio, len(html)):
        if html[i] == "{": nivel += 1
        elif html[i] == "}":
            nivel -= 1
            if nivel == 0:
                fim = i + 1
                break

    dados = json.loads(html[inicio:fim])

    sismos = []
    for s in dados["data"]:
        mag = float(s["magnitud"])
        if mag == -99.0:
            mag = None

        sismos.append({
            "areaID": s["areaID"],
            "obsRegion": s["obsRegion"],
            "magnitude": mag,
            "depth": s["depth"],
            "latitude": float(s["lat"]),
            "longitude": float(s["lon"]),
            "time": s["time"],
            "source": s["source"]
        })

    # Ordenar por data (mais recente primeiro)
    sismos.sort(
        key=lambda x: datetime.strptime(x["time"], "%Y-%m-%dT%H:%M:%S"),
        reverse=True
    )

    return {
        "owner": dados["owner"],
        "country": dados["country"],
        "total": len(sismos),
        "data": sismos
    }


def get_latest_sismo():
    data = obter_sismos()
    if not data["data"]:
        return None

    s = data["data"][0]
    try:
        dt = datetime.strptime(s["time"], "%Y-%m-%d %H:%M:%S")
        data_formatada = dt.strftime("%d-%m-%Y pelas %H:%M (hora local)")
    except:
        data_formatada = s["time"]

    return {
        "location": s["obsRegion"] or s["areaID"] or "Portugal",
        "scale": s["magnitude"] or 0.0,
        "date": data_formatada,
        "intensity": "Sem info a esta hora",
        "latitude": s["latitude"],
        "longitude": s["longitude"]
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/sismos")
def api_sismos():
    return jsonify(obter_sismos())


@app.route("/api/gerar_imagem")
def gerar_imagem():
    try:
        sismo = get_latest_sismo()
        if not sismo:
            return jsonify({"error": "Nenhum sismo encontrado"}), 404

        generate_final_image(sismo)

        return jsonify({
            "status": "success",
            "message": "Imagem gerada com sucesso!",
            "url": "/assets/SISMO_TWEET.png"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/assets/SISMO_TWEET.png")
def download_image():
    path = "assets/SISMO_TWEET.png"
    if os.path.exists(path):
        return send_file(path, mimetype='image/png')
    return "Imagem ainda não gerada.", 404


if __name__ == "__main__":
    os.makedirs("assets", exist_ok=True)
    threading.Thread(
        target=monitor_sismos,
        daemon=True
    ).start()
    app.run(host="0.0.0.0", port=9076, debug=True)