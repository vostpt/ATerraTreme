//===================================================
// MAPA
//===================================================

const map = L.map("map", {
    zoomControl: false
});

L.control.zoom({
    position: "bottomright"
}).addTo(map);

//===================================================
// BASEMAPS
//===================================================

const dark = L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    {
        attribution: "© OpenStreetMap © CARTO"
    }
);

const osm = L.tileLayer(
    "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
        attribution: "© OpenStreetMap"
    }
);

dark.addTo(map);

//===================================================
// CORES
//===================================================

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

//===================================================
// ENERGIA PARA HEATMAP
//===================================================

const maxMagnitude = Math.max(
    ...dados.data.map(s => s.magnitude ?? 0)
);

const heatPoints = [];

const grupoSismos = L.layerGroup();

const markers = [];

const bounds = [];

//===================================================
// SISMOS
//===================================================

dados.data.forEach((s, i) => {

    const intensidade = maxMagnitude > 0
        ? (s.magnitude ?? 0) / maxMagnitude
        : 0;

    heatPoints.push([
        s.latitude,
        s.longitude,
        intensidade
    ]);

    bounds.push([
        s.latitude,
        s.longitude
    ]);

    const marker = L.circleMarker(
        [s.latitude, s.longitude],
        {

            radius: raioMagnitude(s.magnitude),

            color: "#ffffff",

            weight: 1,

            fillColor: corMagnitude(s.magnitude),

            fillOpacity: .9

        }
    );

    marker.bindPopup(`
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
            <td>${s.depth} km</td>
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
            <td><i class="bi bi-broadcast"></i></td>
            <td>Origem</td>
            <td>${s.source}</td>
        </tr>

    </table>

</div>
`,{
    maxWidth:320,
    className:"earthquake-popup"
});

    marker.addTo(grupoSismos);

    markers.push(marker);

});

//===================================================
// HEATMAP
//===================================================

const heat = L.heatLayer(
    heatPoints,
    {

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

    }
);

//===================================================
// CAMADAS
//===================================================

grupoSismos.addTo(map);

const MapButtons = L.Control.extend({

    options:{
        position:"topleft"
    },

    onAdd:function(){

        const div=L.DomUtil.create("div","map-buttons");

        div.innerHTML=`
            <button id="basemap-btn" title="Mapa">
                <i class="bi bi-moon-stars-fill"></i>
            </button>

            <button id="heat-btn" title="Heatmap">
                <i class="bi bi-fire"></i>
            </button>
        `;

        L.DomEvent.disableClickPropagation(div);

        return div;

    }

});

map.addControl(new MapButtons());

let heatVisible=false;

document.addEventListener("click",(e)=>{

    const btn=e.target.closest("#heat-btn");

    if(!btn) return;

    if(heatVisible){

        map.removeLayer(heat);
        btn.classList.remove("active");

    }else{

        heat.addTo(map);
        btn.classList.add("active");

    }

    heatVisible=!heatVisible;

});

let darkMode=false;

document.addEventListener("click",(e)=>{

    const btn=e.target.closest("#basemap-btn");

    if(!btn) return;

    if(darkMode){

        map.removeLayer(dark);
        osm.addTo(map);

        btn.innerHTML='<i class="bi bi-moon-stars-fill"></i>';
        btn.classList.remove("active");

    }else{

        map.removeLayer(osm);
        dark.addTo(map);

        btn.innerHTML='<i class="bi bi-sun-fill"></i>';
        btn.classList.add("active");

    }

    darkMode=!darkMode;

});

//===================================================
// LEGENDA
//===================================================

const legenda = L.control({
    position: "bottomleft"
});

legenda.onAdd = function () {

    const div = L.DomUtil.create("div", "legend");

    div.innerHTML = `
    <div style="background-color: #000; padding: 5px; border-radius: 5px; color: #fff; font-size: 14px;">
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
    </div>
    `;

    return div;
};

legenda.addTo(map);

//===================================================
// AJUSTAR AO CONJUNTO DE DADOS
//===================================================

if (bounds.length) {

    map.fitBounds(bounds, {
        padding: [30, 30]
    });

}

//===================================================
// TABELA
//===================================================

window.zoom = function (i) {

    const s = dados.data[i];

    map.flyTo(
        [s.latitude, s.longitude],
        9,
        {
            duration: 1.2
        }
    );

    markers[i].openPopup();

}