//===================================================
// MAPA E DADOS
//===================================================

const loadingEl = document.getElementById("loading");
const totalEl = document.getElementById("total-sismos");

const map = L.map("map", {
    center: [39.6945, -8.1306],
    zoom: 5,
    minZoom: 2,
    maxZoom: 13,
    zoomControl: false,
    tap: true
});

L.control.zoom({
    position: "bottomright"
}).addTo(map);

const basemaps = {
    dark: L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        {
            attribution: "© OpenStreetMap © CARTO"
        }
    ),
    osm: L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        {
            attribution: "© OpenStreetMap"
        }
    )
};

basemaps.dark.addTo(map);

const markersLayer = L.layerGroup().addTo(map);
const heatLayer = L.heatLayer([], {
    radius: 50,
    blur: 25,
    maxZoom: 13,
    minOpacity: 0.35,
    max: 1,
    gradient: {
        0.00: "transparent",
        0.08: "#FFF3C4",
        0.18: "#FFE082",
        0.30: "#FFD54F",
        0.42: "#FFB300",
        0.54: "#FB8C00",
        0.66: "#F57C00",
        0.78: "#EF6C00",
        0.88: "#F4511E",
        0.94: "#E53935",
        0.98: "#C62828",
        1.00: "#7F0000"
    }
});

const state = {
    markers: [],
    earthquakes: [],
    heatVisible: false,
    darkMode: true,
    refreshTimer: null,
    hasLoaded: false,
    firstLoad: true
};

function corMagnitude(m) {
    if (m == null)
        return "#555";

    if (m < 2)
        return "#4a4a4a";

    if (m < 3)
        return "#7B4B1A";

    if (m < 4)
        return "#A66A2B";

    if (m < 5)
        return "#D46A00";

    if (m < 6)
        return "#E53935";

    return "#8E0000";
}

function raioMagnitude(m) {
    if (m == null)
        return 5;

    return 4 + Math.pow(m, 1.5);
}

function criarPopup(s) {
    return `
<div class="eq-popup">
    <div class="eq-header">
        <div class="eq-mag" style="background:${corMagnitude(s.magnitude)}">
            ${s.magnitude ?? "?"}
        </div>

        <div class="eq-title">
            <h3>${s.obsRegion}</h3>
            <small>${s.source}</small>
        </div>
    </div>

    <table class="eq-table">
        <tr>
            <td><i class="bi bi-calendar-event"></i></td>
            <td>Data</td>
            <td>${new Date(s.time).toLocaleString("pt-PT")}</td>
        </tr>
        <tr>
            <td><i class="bi bi-arrow-down-circle"></i></td>
            <td>Profundidade</td>
            <td>${s.depth}</td>
        </tr>
        <tr>
            <td><i class="bi bi-geo-alt"></i></td>
            <td>Latitude</td>
            <td>${Number(s.latitude).toFixed(4)}°</td>
        </tr>
        <tr>
            <td><i class="bi bi-geo"></i></td>
            <td>Longitude</td>
            <td>${Number(s.longitude).toFixed(4)}°</td>
        </tr>
        <tr>
            <td><i class="bi bi-speedometer2"></i></td>
            <td>Intensidade</td>
            <td>${s.intensity}</td>
        </tr>
        <tr>
            <td><i class="bi bi-broadcast"></i></td>
            <td>Origem</td>
            <td>${s.source}</td>
        </tr>
    </table>
</div>`;
}

function atualizarMarcadores(dados) {
    markersLayer.clearLayers();
    state.markers = [];
    state.earthquakes = [];

    const maxMagnitude = dados.data.reduce((max, s) => {
        const magnitude = s.magnitude ?? 0;
        return magnitude > max ? magnitude : max;
    }, 0);

    const heatPoints = [];
    const bounds = [];

    dados.data.forEach((s) => {
        const intensidade = maxMagnitude > 0
            ? (s.magnitude ?? 0) / maxMagnitude
            : 0;

        heatPoints.push([s.latitude, s.longitude, intensidade]);
        bounds.push([s.latitude, s.longitude]);

        const recente = ultimas24h(s.time);

        const marker = L.circleMarker([s.latitude, s.longitude], {
            radius: raioMagnitude(s.magnitude),

            color: "#ffffff",
            weight: recente ? 3 : 1,

            fillColor: corMagnitude(s.magnitude),
            fillOpacity: recente ? 1 : 0.9,

            className: recente ? "earthquake-recent" : ""
        });

        if (recente) {

            const tamanho = (raioMagnitude(s.magnitude) + 8) * 2;

            const halo = L.marker([s.latitude, s.longitude], {
                interactive: false,
                zIndexOffset: -1000,
                icon: L.divIcon({
                    className: "pulse-marker",
                    html: `<div class="pulse" style="width:${tamanho}px;height:${tamanho}px"></div>`,
                    iconSize: [tamanho, tamanho],
                    iconAnchor: [tamanho / 2, tamanho / 2]
                })
            });

            halo.addTo(markersLayer);

        }

        marker.bindPopup(criarPopup(s), {
            maxWidth: 320,
            className: "earthquake-popup"
        });

        marker.addTo(markersLayer);

        const hitArea = L.circleMarker([s.latitude, s.longitude], {
            radius: Math.max(raioMagnitude(s.magnitude), 18),
            stroke: false,
            fill: true,
            fillColor: "#ffffff",
            fillOpacity: 0.01
        });

        hitArea.on("click", () => {
            marker.openPopup();
        });

        hitArea.addTo(markersLayer);


        state.markers.push(marker);
        state.earthquakes.push({
            marker,
            latlng: L.latLng(s.latitude, s.longitude)
        });
    });

    heatLayer.setLatLngs(heatPoints);
    heatLayer.redraw();

    if (state.heatVisible) {
        if (!map.hasLayer(heatLayer)) {
            heatLayer.addTo(map);
        }
    } else if (map.hasLayer(heatLayer)) {
        map.removeLayer(heatLayer);
    }

    if (state.firstLoad && bounds.length) {
        state.firstLoad = false;
    }
}

function selecionarSismoMaisProximo(e) {

    let maisProximo = null;
    let menorDistancia = Infinity;

    const pontoClique = map.latLngToContainerPoint(e.latlng);

    state.earthquakes.forEach(eq => {

        const pontoSismo = map.latLngToContainerPoint(eq.latlng);

        const distancia = pontoClique.distanceTo(pontoSismo);

        if (distancia < menorDistancia) {
            menorDistancia = distancia;
            maisProximo = eq;
        }

    });

    // raio de seleção em pixels
    const tolerancia = window.innerWidth < 768 ? 35 : 20;

    if (maisProximo && menorDistancia <= tolerancia) {

        maisProximo.marker.openPopup();

    }

}

function definirLegenda() {
    const legenda = L.control({
        position: "bottomleft"
    });

    legenda.onAdd = function () {
        const div = L.DomUtil.create("div", "legend");
        div.innerHTML = `
        <div style="background-color: #1b1f24; padding: 5px; border-radius: 5px; color: #fff; font-size: 14px;">
            <div class="legend-title">
                <i class="bi bi-activity"></i>
                Magnitude
            </div>
            <table class="legend-table">
                <tr>
                    <td><i class="bi bi-record-circle-fill" style="color:#4a4a4a"></i></td>
                    <td>&lt; 2.0</td>
                </tr>
                <tr>
                    <td><i class="bi bi-record-circle-fill" style="color:#7B4B1A"></i></td>
                    <td>2.0 – 2.9</td>
                </tr>
                <tr>
                    <td><i class="bi bi-record-circle-fill" style="color:#A66A2B"></i></td>
                    <td>3.0 – 3.9</td>
                </tr>
                <tr>
                    <td><i class="bi bi-record-circle-fill" style="color:#D46A00"></i></td>
                    <td>4.0 – 4.9</td>
                </tr>
                <tr>
                    <td><i class="bi bi-record-circle-fill" style="color:#E53935"></i></td>
                    <td>5.0 – 5.9</td>
                </tr>
                <tr>
                    <td><i class="bi bi-record-circle-fill" style="color:#8E0000"></i></td>
                    <td>≥ 6.0</td>
                </tr>
            </table>
        </div>`;
        return div;
    };

    legenda.addTo(map);
}

function configurarControles() {
    const MapButtons = L.Control.extend({
        options: {
            position: "topleft"
        },
        onAdd: function () {
            const div = L.DomUtil.create("div", "map-buttons");
            div.innerHTML = `
                <button id="basemap-btn" title="Mapa">
                    <i class="bi bi-sun-fill"></i>
                </button>
                <button id="heat-btn" title="Heatmap">
                    <i class="bi bi-fire"></i>
                </button>`;
            L.DomEvent.disableClickPropagation(div);
            return div;
        }
    });

    map.addControl(new MapButtons());

    document.addEventListener("click", (e) => {
        const heatBtn = e.target.closest("#heat-btn");
        if (heatBtn) {
            state.heatVisible = !state.heatVisible;
            heatBtn.classList.toggle("active", state.heatVisible);

            if (state.heatVisible) {
                heatLayer.addTo(map);
            } else {
                map.removeLayer(heatLayer);
            }

            return;
        }

        const basemapBtn = e.target.closest("#basemap-btn");
        if (!basemapBtn) {
            return;
        }

        state.darkMode = !state.darkMode;
        if (state.darkMode) {
            map.removeLayer(basemaps.osm);
            basemaps.dark.addTo(map);
            basemapBtn.innerHTML = '<i class="bi bi-sun-fill"></i>';
            basemapBtn.classList.add("active");
        } else {
            map.removeLayer(basemaps.dark);
            basemaps.osm.addTo(map);
            basemapBtn.innerHTML = '<i class="bi bi-moon-stars-fill"></i>';
            basemapBtn.classList.remove("active");
        }
    });
}

async function carregarSismos() {
    try {
        if (!state.hasLoaded) {
            loadingEl.style.display = "flex";
        }

        const response = await fetch("/api/sismos", {
            cache: "no-store"
        });

        if (!response.ok) {
            throw new Error("Erro ao obter dados.");
        }

        const dados = await response.json();
        totalEl.textContent = dados.total;
        atualizarMarcadores(dados);

        state.hasLoaded = true;
    } catch (error) {
        console.error(error);
        if (!state.hasLoaded) {
            alert("Não foi possível carregar os dados.");
        }
    } finally {
        // Always clear overlay so a failed API never leaves a blank screen
        loadingEl.style.display = "none";
    }
}

function iniciarAtualizacoes() {
    if (state.refreshTimer) {
        window.clearInterval(state.refreshTimer);
    }

    state.refreshTimer = window.setInterval(() => {
        carregarSismos();
    }, 60000);
}

window.zoom = function (i) {
    const s = state.markers[i]?.getLatLng ? state.markers[i].getLatLng() : null;

    if (!s) {
        return;
    }

    map.flyTo([s.lat, s.lng], 9, {
        duration: 1.2
    });

    state.markers[i].openPopup();
};

function ultimas24h(dataHora) {

    const agora = Date.now();
    const data = new Date(dataHora).getTime();

    return (agora - data) <= 24 * 60 * 60 * 1000;

}

function inicializarMapa() {
    definirLegenda();
    configurarControles();
    carregarSismos();
    iniciarAtualizacoes();
    map.on("click", selecionarSismoMaisProximo);
}

inicializarMapa();