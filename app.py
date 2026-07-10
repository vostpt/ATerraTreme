from flask import Flask, jsonify, render_template
import requests
import json

app = Flask(__name__)

URL = "https://www.ipma.pt/pt/geofisica/sismicidade/"


def obter_sismos():
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(URL, headers=headers, timeout=30)
    response.raise_for_status()

    html = response.text

    marker = "var seismicdata_world ="

    pos = html.find(marker)
    if pos == -1:
        raise Exception("Variável 'seismicdata_world' não encontrada.")

    inicio = html.find("{", pos)

    nivel = 0
    fim = None

    for i in range(inicio, len(html)):
        if html[i] == "{":
            nivel += 1
        elif html[i] == "}":
            nivel -= 1
            if nivel == 0:
                fim = i + 1
                break

    if fim is None:
        raise Exception("Não foi possível extrair o objeto.")

    js_object = html[inicio:fim]
    dados = json.loads(js_object)

    sismos = []

    for s in dados["data"]:

        magnitude = float(s["magnitud"])
        if magnitude == -99.0:
            magnitude = None

        sismos.append({
            "areaID": s["areaID"],
            "obsRegion": s["obsRegion"],
            "magnitude": magnitude,
            "depth": s["depth"],
            "latitude": float(s["lat"]),
            "longitude": float(s["lon"]),
            "time": s["time"],
            "source": s["source"]
        })

    return {
        "owner": dados["owner"],
        "country": dados["country"],
        "total": len(sismos),
        "data": sismos
    }

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/sismos")
def api_sismos():
    return jsonify(obter_sismos())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9076, debug=True)