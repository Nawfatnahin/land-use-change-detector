// app.js — Land Use Change Detector

// Tokens matching CSS
const COLORS = {
    bg: "#F8F9FA",
    text: "#1F2937",
    textDim: "#64748B",
    accent: "#F6C90E",
    gain: "#10B981",      // emerald
    loss: "#EF4444",      // red
    unchanged: "#94A3B8", // slate
    indigo: "#6366F1",
    amber: "#F59E0B"
};
const SANS = "'Inter', 'Poppins', system-ui, sans-serif";

// Globals
let map;
let drawnItems;
let currentRoi = null;
let currentStats = null;
let activeLayers = {
    before: null,
    after: null,
    change: null
};

// ─── Initialize ──────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    initUI();
    initMap();
    
    document.getElementById("btn-analyze").addEventListener("click", runAnalysis);
    document.getElementById("btn-clear").addEventListener("click", clearAll);
    document.getElementById("area-unit").addEventListener("change", () => {
        if (currentStats) updateMetricsDisplay();
    });

    // ── Guide Modal ─────────────────────────────────────────────────────────
    const btnInfo  = document.getElementById("btn-info");
    const overlay  = document.getElementById("guide-overlay");
    const modal    = document.getElementById("guide-modal");
    const closeBtn = document.getElementById("guide-modal-close");
    let isOpen = false;

    function positionModal() {
        const btn    = btnInfo.getBoundingClientRect();
        const mw     = modal.offsetWidth  || 380;
        const mh     = modal.offsetHeight || 300;
        const vw     = window.innerWidth;
        const vh     = window.innerHeight;
        const GAP    = 10;

        // Prefer above the button; fall back below if not enough room
        let top = btn.top - mh - GAP;
        if (top < 8) top = btn.bottom + GAP;  // flip below
        top = Math.min(top, vh - mh - 8);

        // Right-align to button, but clamp so modal never leaves screen
        let left = btn.right - mw;
        left = Math.max(8, Math.min(left, vw - mw - 8));

        modal.style.top  = top  + "px";
        modal.style.left = left + "px";
    }

    function openGuide() {
        isOpen = true;
        // 1. Make overlay block (so modal takes up space) but modal stays invisible
        overlay.classList.add("open");
        modal.style.opacity = "0";
        modal.style.transform = "translateY(6px) scale(0.98)";

        // 2. Measure + position after one paint
        requestAnimationFrame(() => {
            positionModal();
            // 3. Animate in
            requestAnimationFrame(() => modal.classList.add("open"));
        });
    }

    function closeGuide() {
        isOpen = false;
        modal.classList.remove("open");
        setTimeout(() => overlay.classList.remove("open"), 180);
    }

    btnInfo.addEventListener("click", (e) => {
        e.stopPropagation();
        isOpen ? closeGuide() : openGuide();
    });
    closeBtn.addEventListener("click", closeGuide);

    // Click outside modal body closes it
    overlay.addEventListener("click", (e) => {
        if (!modal.contains(e.target)) closeGuide();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && isOpen) closeGuide();
    });

    // Reposition live on scroll and resize so it tracks the button
    window.addEventListener("resize", () => { if (isOpen) positionModal(); });
    window.addEventListener("scroll", () => { if (isOpen) positionModal(); }, true);

    // Layer radio buttons
    document.querySelectorAll('input[name="layer"]').forEach(radio => {
        radio.addEventListener("change", (e) => {
            switchLayer(e.target.value);
        });
    });
});

function initUI() {
    // Sync slider values to labels
    const cloudSlider = document.getElementById("cloud-pct");
    const cloudVal = document.getElementById("cloud-val");
    cloudSlider.addEventListener("input", e => cloudVal.textContent = e.target.value);
    
    const threshSlider = document.getElementById("threshold");
    const threshVal = document.getElementById("thresh-val");
    threshSlider.addEventListener("input", e => threshVal.textContent = e.target.value);
}

function initMap() {
    // Base light map layer
    const baseLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://carto.com/">CARTO</a>'
    });

    map = L.map('map', {
        center: [23.8, 90.4],
        zoom: 6,
        layers: [baseLayer],
        zoomControl: false // add custom if needed
    });
    L.control.zoom({ position: 'bottomright' }).addTo(map);

    // Drawing tools
    drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    const drawControl = new L.Control.Draw({
        edit: {
            featureGroup: drawnItems
        },
        draw: {
            polygon: {
                shapeOptions: { color: COLORS.accent, weight: 2, fillOpacity: 0.2 }
            },
            rectangle: {
                shapeOptions: { color: COLORS.accent, weight: 2, fillOpacity: 0.2 }
            },
            polyline: false, circle: false, marker: false, circlemarker: false
        }
    });
    map.addControl(drawControl);

    // Only allow one drawing at a time
    map.on(L.Draw.Event.CREATED, function (event) {
        drawnItems.clearLayers(); // keep only latest
        const layer = event.layer;
        drawnItems.addLayer(layer);
        currentRoi = layer.toGeoJSON();
    });
}

// ─── Clear All ────────────────────────────────────────────────────────────────
function clearAll() {
    // Remove drawn shapes
    drawnItems.clearLayers();
    currentRoi = null;

    // Remove EE tile layers
    clearEELayers();
    document.getElementById("layer-control").style.display = "none";

    // Hide results section
    document.getElementById("results-section").style.display = "none";
    document.getElementById("btn-clear").style.display = "none";

    // Reset metrics
    ["metric-total","metric-changed","metric-rate","metric-pixels"].forEach(
        id => document.getElementById(id).textContent = "0"
    );

    // Scroll back to map
    document.getElementById("map-card").scrollIntoView({ behavior: "smooth" });
}

// ─── Analysis ────────────────────────────────────────────────────────────────
async function runAnalysis() {
    if (!currentRoi) {
        alert("Please draw a region of interest on the map first.");
        return;
    }

    const btn = document.getElementById("btn-analyze");
    btn.disabled = true;
    btn.textContent = "ANALYZING...";

    const payload = {
        sensor: document.getElementById("sensor").value,
        start_date: document.getElementById("start-date").value,
        end_date: document.getElementById("end-date").value,
        cloud_pct: parseInt(document.getElementById("cloud-pct").value),
        index_name: document.getElementById("index-name").value,
        threshold: parseInt(document.getElementById("threshold").value) / 100.0,
        roi_geojson: currentRoi
    };

    try {
        const res = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        if (!res.ok) {
            const err = await res.text();
            throw new Error(err);
        }

        const data = await res.json();
        handleResults(data);

    } catch (err) {
        alert("Analysis failed: " + err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = "RUN ANALYSIS";
    }
}

function updateMetricsDisplay() {
    if (!currentStats) return;
    
    const unit = document.getElementById("area-unit").value;
    let multiplier = 1;
    let unitLabel = "ha";
    
    if (unit === "km2") {
        multiplier = 0.01;
        unitLabel = "km²";
    } else if (unit === "acres") {
        multiplier = 2.47105;
        unitLabel = "ac";
    } else if (unit === "m2") {
        multiplier = 10000;
        unitLabel = "m²";
    }

    // Convert and round (for large numbers) or format properly
    const rawTotal = currentStats.total_area * multiplier;
    const rawChanged = currentStats.changed_area * multiplier;
    
    // Formatting: 1 decimal place if < 100, otherwise round
    const formatArea = (val) => {
        if (val < 100 && unit !== "m2") {
            return val.toFixed(1);
        }
        return Math.round(val).toLocaleString();
    };

    const totalArea = formatArea(rawTotal);
    const changedArea = formatArea(rawChanged);
    const changeRate = parseFloat(currentStats.change_pct).toFixed(1);
    const totalPixels = Math.round(currentStats.pixels);

    document.getElementById("metric-total").textContent   = totalArea;
    document.getElementById("unit-total").textContent     = unitLabel;
    
    document.getElementById("metric-changed").textContent = changedArea;
    document.getElementById("unit-changed").textContent   = unitLabel;
    
    document.getElementById("metric-rate").textContent    = changeRate;
    document.getElementById("metric-pixels").textContent  = totalPixels.toLocaleString();
}

function handleResults(data) {
    document.getElementById("results-section").style.display = "block";
    
    currentStats = data.stats;
    updateMetricsDisplay();

    // 2. Load Map Tiles
    clearEELayers();
    activeLayers.before = L.tileLayer(data.tiles.before, { attribution: 'Google Earth Engine' });
    activeLayers.after  = L.tileLayer(data.tiles.after,  { attribution: 'Google Earth Engine' });
    activeLayers.change = L.tileLayer(data.tiles.change, { attribution: 'Google Earth Engine' });

    // Show change by default
    activeLayers.change.addTo(map);
    document.getElementById("layer-control").style.display = "flex";
    document.querySelector('input[value="change"]').checked = true;

    // 3. Render Charts
    renderPieChart(data.histogram);
    renderHistChart(data.histogram);

    // Show clear button
    document.getElementById("btn-clear").style.display = "inline-flex";

    // Scroll down to results
    document.getElementById("results-section").scrollIntoView({ behavior: 'smooth' });
}

function clearEELayers() {
    if (activeLayers.before) map.removeLayer(activeLayers.before);
    if (activeLayers.after) map.removeLayer(activeLayers.after);
    if (activeLayers.change) map.removeLayer(activeLayers.change);
}

function switchLayer(layerName) {
    clearEELayers();
    if (activeLayers[layerName]) {
        activeLayers[layerName].addTo(map);
    }
}

// ─── Plotly Charts ───────────────────────────────────────────────────────────
const baseLayout = {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: SANS, color: COLORS.text, size: 12 },
    margin: { l: 48, r: 24, t: 44, b: 48 }
};

function renderPieChart(hist) {
    const unchanged = hist["0"] || 0;
    const loss      = hist["1"] || 0;
    const gain      = hist["2"] || 0;
    const total     = unchanged + loss + gain;

    const data = [{
        type: "pie",
        labels: ["Unchanged", "Loss", "Gain"],
        values: [unchanged, loss, gain],
        hole: 0.60,
        marker: {
            colors: [COLORS.unchanged, COLORS.loss, COLORS.gain],
            line: { width: 3, color: '#FFFFFF' }
        },
        // Only show percent inside — avoids label collision on small slices
        textinfo: "percent",
        textposition: "inside",
        textfont: { family: SANS, size: 12, color: '#FFF' },
        hovertemplate: '<b>%{label}</b><br>%{value:,} pixels<br>%{percent}<extra></extra>',
        insidetextorientation: "horizontal"
    }];

    const layout = {
        ...baseLayout,
        title: {
            text: '<b>Distribution</b>',
            font: { family: SANS, size: 18, color: COLORS.text },
            x: 0.04, xanchor: 'left', y: 0.97, yanchor: 'top'
        },
        margin: { l: 20, r: 20, t: 52, b: 80 },
        height: 440,
        showlegend: true,
        legend: {
            orientation: 'h',
            y: -0.04, x: 0.5, xanchor: 'center',
            font: { family: SANS, size: 13, color: COLORS.textDim },
            traceorder: 'normal'
        },
        annotations: [{
            text: `<b>${total.toLocaleString()}</b><br><span style="color:${COLORS.textDim};font-size:10px">TOTAL PX</span>`,
            x: 0.5, y: 0.5,
            font: { family: SANS, size: 15, color: COLORS.text },
            showarrow: false,
            align: 'center'
        }]
    };

    Plotly.newPlot("chart-pie", data, layout, { displayModeBar: false, responsive: true });
}

function renderHistChart(hist) {
    const unchanged = hist["0"] || 0;
    const loss      = hist["1"] || 0;
    const gain      = hist["2"] || 0;

    const maxVal = Math.max(unchanged, loss, gain, 1);
    // Round up to a clean tick interval
    const magnitude = Math.pow(10, Math.floor(Math.log10(maxVal)));
    const dtick  = Math.ceil(maxVal / magnitude / 5) * magnitude;

    const data = [{
        type: "bar",
        x: ["Unchanged", "Loss", "Gain"],
        y: [unchanged, loss, gain],
        marker: {
            color: [COLORS.unchanged, COLORS.loss, COLORS.gain],
            opacity: 0.88
        },
        text: [unchanged, loss, gain].map(v => v.toLocaleString()),
        textposition: "outside",
        textfont: { family: SANS, size: 12.5, color: COLORS.text },
        hovertemplate: '<b>%{x}</b>: %{y:,} pixels<extra></extra>',
        cliponaxis: false
    }];

    const layout = {
        ...baseLayout,
        title: {
            text: '<b>Pixel Classification</b>',
            font: { family: SANS, size: 18, color: COLORS.text },
            x: 0.04, xanchor: 'left', y: 0.97, yanchor: 'top'
        },
        height: 440,
        xaxis: {
            showgrid: false,
            zeroline: false,
            tickfont: { color: COLORS.textDim, size: 13 },
            color: 'rgba(0,0,0,0.1)'
        },
        yaxis: {
            showgrid: true,
            gridcolor: 'rgba(0,0,0,0.04)',
            zeroline: true,
            zerolinecolor: 'rgba(0,0,0,0.08)',
            tickfont: { color: COLORS.textDim, size: 11 },
            dtick: dtick,
            range: [0, maxVal * 1.15]
        },
        bargap: 0.4,
        margin: { l: 60, r: 20, t: 60, b: 40 }
    };

    Plotly.newPlot("chart-hist", data, layout, { displayModeBar: false, responsive: true });
}

// -- Scroll Reveal Animations ----------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-visible');
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.1, rootMargin: '0px 0px -50px 0px' });

    // Select elements to reveal
    const elementsToReveal = document.querySelectorAll('.app-section, #results-section, .info-section');
    elementsToReveal.forEach(el => {
        el.classList.add('reveal-up');
        observer.observe(el);
    });
});
