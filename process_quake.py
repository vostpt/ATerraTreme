#!/usr/bin/env python3
"""
process_quake.py
Recebe um ficheiro JSON temporário com os dados do sismo.
Gera a imagem exactamente como o código original e envia para o Discord.
"""

import sys
import os
import json
import io
import gc
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

import requests
import pandas as pd
from PIL import Image, ImageFont, ImageDraw
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import contextily as ctx
import geopandas as gpd

load_dotenv()
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL")

session = requests.Session()
session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; SismoBot/2.0)"})


def overlay_text(img, text, position, font, color):
    draw = ImageDraw.Draw(img)
    draw.text(position, text, font=font, fill=color)


def create_map_image(df) -> Image.Image:
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

    try:
        ctx.add_basemap(ax, source=ctx.providers.OpenStreetMap.Mapnik, attribution=False)
    except Exception as e:
        print(f"Aviso basemap: {e}")

    ax.scatter(cx, cy, s=7000, color="red", alpha=0.10, zorder=2)
    ax.scatter(cx, cy, s=2500, color="red", alpha=0.25, zorder=3)
    ax.scatter(cx, cy, s=350, marker="*", color="darkred", edgecolors="white", linewidth=1.5, zorder=4)

    ax.text(
        cx, cy + 25000, f"M {latest['scale']:.1f}",
        fontsize=16, fontweight="bold", ha="center", va="bottom",
        color="black",
        bbox=dict(facecolor="white", edgecolor="black", alpha=0.9, boxstyle="round,pad=0.3"),
        zorder=5
    )

    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, bottom=0, top=1)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, facecolor="white", pad_inches=0)
    plt.close(fig)
    plt.close('all')
    buf.seek(0)

    img = Image.open(buf).convert("RGB")
    buf.close()
    return img


def generate_final_image(sismo_data) -> bytes:
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
    overlay_text(template, str(latest['intensity']), (520, 832), font, "#703D25")

    final = Image.new("RGB", (2160, 1080), color="white")
    final.paste(template, (0, 0))
    final.paste(map_img, (1080, 0))

    final.save("assets/SISMO_TWEET.png", optimize=True)

    buf = io.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    data = buf.getvalue()
    buf.close()

    del map_img, template, final, df
    gc.collect()
    return data


def enviar_discord(sismo, image_bytes: bytes, tentativas=4):
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
            files = {"file": ("SISMO.png", image_bytes, "image/png")}
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


def main():
    if len(sys.argv) != 2:
        print("Uso: process_quake.py <ficheiro.json>")
        sys.exit(1)

    json_path = sys.argv[1]

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            sismo = json.load(f)
    except Exception as e:
        print(f"Erro a ler JSON: {e}")
        sys.exit(1)

    print(f"Processar → {sismo['location']} M{sismo['scale']} | {sismo['id']}")

    try:
        image_bytes = generate_final_image(sismo)
        success = enviar_discord(sismo, image_bytes)
        if success:
            print("✓ Imagem gerada e enviada com sucesso")
            sys.exit(0)
        else:
            print("✗ Falha no envio para Discord")
            sys.exit(1)
    except Exception as e:
        print(f"Erro ao processar: {e}")
        sys.exit(1)
    finally:
        # limpar o ficheiro temporário
        try:
            os.remove(json_path)
        except:
            pass


if __name__ == "__main__":
    main()