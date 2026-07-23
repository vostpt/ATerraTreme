from flask import Flask, jsonify, render_template, send_file
import requests
import pandas as pd
from PIL import Image, ImageFont, ImageDraw
import matplotlib.pyplot as plt
import contextily as ctx
import geopandas as gpd
from datetime import datetime
import os
import threading
import time
from dotenv import load_dotenv

load_dotenv()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

app = Flask(__name__)

# APIs IPMA
API_CONTINENTE = "https://api.ipma.pt/open-data/observation/seismic/7.json"
API_ACORES = "https://api.ipma.pt/open-data/observation/seismic/3.json"

sismos_enviados = set()


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

    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df.longitude, df.latitude),
        crs="EPSG:4326"
    ).to_crs(epsg=3857)

    latest_point = gdf.iloc[-1]
    cx = latest_point.geometry.x
    cy = latest_point.geometry.y
    window = 175_000

    fig = plt.figure(figsize=(6, 6), dpi=180)
    ax = fig.add_axes([0, 0, 1, 1])

    ax.set_xlim(cx - window, cx + window)
    ax.set_ylim(cy - window, cy + window)
    ax.set_aspect("equal")

    ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, attribution=False)

    # Halos e epicentro
    ax.scatter(cx, cy, s=7000, color="red", alpha=0.10, zorder=2)
    ax.scatter(cx, cy, s=2500, color="red", alpha=0.25, zorder=3)
    ax.scatter(cx, cy, s=350, marker="*", color="darkred", edgecolors="white", linewidth=1.5, zorder=4)

    ax.text(
        cx, cy + 25000, f"M {latest['scale']:.1f}",
        fontsize=18, fontweight="bold", ha="center", va="bottom",
        color="black",
        bbox=dict(facecolor="white", edgecolor="black", alpha=0.9, boxstyle="round,pad=0.3"),
        zorder=5
    )

    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)

    plt.savefig("assets/MAPA_SISMO.png", dpi=180, facecolor="white", pad_inches=0)
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

    if os.path.exists("assets/SISMO_TWEET.png"):
        os.remove("assets/SISMO_TWEET.png")
    
    img_final.save("assets/SISMO_TWEET.png")
    print("Imagem gerada: assets/SISMO_TWEET.png")


def enviar_discord(sismo, tentativas=5):
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
            with open("assets/SISMO_TWEET.png", "rb") as imagem:
                r = requests.post(
                    DISCORD_WEBHOOK,
                    data={"content": mensagem},
                    files={"file": ("SISMO.png", imagem, "image/png")},
                    timeout=30
                )

            if r.status_code in (200, 204):
                print(f"Discord: enviado à {tentativa}ª tentativa.")
                return True

            print(f"Discord respondeu {r.status_code} (tentativa {tentativa})")
        except Exception as e:
            print(f"Erro ao enviar para o Discord: {e}")

        time.sleep(5)

    return False


def obter_sismos():
    headers = {"User-Agent": "Mozilla/5.0"}
    sismos = []

    for url, regiao in [(API_CONTINENTE, "Continente e Madeira"), (API_ACORES, "Açores")]:
        try:
            response = requests.get(url, headers=headers, timeout=30)
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
        except:
            try:
                s["datetime"] = datetime.fromisoformat(s["time"])
            except:
                try:
                    s["datetime"] = datetime.strptime(s["time"], "%Y-%m-%d %H:%M:%S")
                except:
                    s["datetime"] = datetime.now()

    sismos.sort(key=lambda x: x["datetime"], reverse=True)

    return {
        "owner": "IPMA",
        "country": "PT",
        "total": len(sismos),
        "data": sismos,
    }


def get_latest_sismo():
    data = obter_sismos()
    if not data["data"]:
        return None

    s = data["data"][0]
    data_formatada = s["datetime"].strftime("%d-%m-%Y pelas %H:%M (hora local)")

    return {
        "id": s["time"],
        "location": s.get("obsRegion") or "Portugal",
        "scale": s["magnitude"] or 0.0,
        "date": data_formatada,
        "intensity": "Sem info a esta hora",
        "latitude": s["latitude"],
        "longitude": s["longitude"]
    }


def monitor_sismos():
    global sismos_enviados
    print("Monitor de sismos iniciado.")

    while True:
        try:
            data = obter_sismos()

            if not data["data"]:
                time.sleep(60)
                continue

            novos = [s for s in data["data"] if s["time"] not in sismos_enviados]

            if not novos:
                # print("Sem novos sismos.")
                time.sleep(60)
                continue

            novos.sort(key=lambda x: x["datetime"])

            print(f"Foram encontrados {len(novos)} novos sismos.")

            for s in novos:
                sismo = {
                    "id": s["time"],
                    "location": s.get("obsRegion") or "Portugal",
                    "scale": s["magnitude"] or 0.0,
                    "date": s["datetime"].strftime("%d-%m-%Y pelas %H:%M (hora local)"),
                    "intensity": "Sem info a esta hora",
                    "latitude": s["latitude"],
                    "longitude": s["longitude"]
                }

                print(f"Enviar {sismo['location']} M{sismo['scale']} {sismo['id']}")

                generate_final_image(sismo)

                if enviar_discord(sismo):
                    sismos_enviados.add(s["time"])
                    time.sleep(2)

        except Exception as e:
            print("Erro no monitor:", e)

        time.sleep(60)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/sismos")
def api_sismos():
    return jsonify(obter_sismos())


@app.route("/assets/SISMO_TWEET.png")
def download_image():
    path = "assets/SISMO_TWEET.png"
    if os.path.exists(path):
        return send_file(path, mimetype='image/png')
    return "Imagem ainda não gerada.", 404


if __name__ == "__main__":
    os.makedirs("assets", exist_ok=True)

    data = obter_sismos()
    for s in data["data"]:
        sismos_enviados.add(s["time"])

    print(f"{len(sismos_enviados)} sismos existentes ignorados.")

    threading.Thread(target=monitor_sismos, daemon=True).start()

    app.run(host="0.0.0.0", port=9076, debug=False, use_reloader=False)