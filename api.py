import os
import tomllib
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import ee
import ee_logic

# ─── Load Secrets & Init Earth Engine ─────────────────────────────────────────
try:
    secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
    if not os.path.exists(secrets_path):
        secrets_path = "/etc/secrets/secrets.toml"
        
    with open(secrets_path, "rb") as f:
        secrets = tomllib.load(f)
    ee_logic.initialize_ee(secrets)
except Exception as e:
    print(f"Failed to initialize Earth Engine: {e}")

# ─── API Setup ────────────────────────────────────────────────────────────────
app = FastAPI(title="Land Use Change API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(ee.EEException)
async def ee_exception_handler(request: Request, exc: ee.EEException):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Earth Engine Error: {str(exc)}"}
    )

# ─── Request Models ───────────────────────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    sensor: str
    start_date: str
    end_date: str
    cloud_pct: int
    index_name: str
    threshold: float
    roi_geojson: dict

# ─── Helper Functions ─────────────────────────────────────────────────────────
def get_window(date_str: str, days: int = 45):
    """Returns a (start, end) tuple of dates centered around date_str."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return (dt - timedelta(days=days)).strftime("%Y-%m-%d"), (dt + timedelta(days=days)).strftime("%Y-%m-%d")


# ─── Endpoints ────────────────────────────────────────────────────────────────
@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    print(f"--- Received analysis request for {req.sensor} ---")
    try:
        # 1. Parse ROI
        if "geometry" not in req.roi_geojson:
            raise HTTPException(status_code=400, detail="Invalid GeoJSON format. Missing 'geometry' key.")
        
        roi = ee.Geometry(req.roi_geojson["geometry"])
        print("ROI parsed.")
        
        # 2. Get Images (use a window to build a median composite around the target dates)
        s1_start, s1_end = get_window(req.start_date, days=30)
        e1_start, e1_end = get_window(req.end_date, days=30)
        
        print(f"Fetching {req.sensor} composites: {s1_start} to {s1_end} AND {e1_start} to {e1_end}")
        img1 = ee_logic.get_composite(roi, s1_start, s1_end, req.cloud_pct, req.sensor)
        img2 = ee_logic.get_composite(roi, e1_start, e1_end, req.cloud_pct, req.sensor)
        
        # 3. Compute Indices
        print("Computing indices...")
        idx1 = ee_logic.compute_index(img1, req.index_name, req.sensor)
        idx2 = ee_logic.compute_index(img2, req.index_name, req.sensor)
        
        # 4. Change Detection
        print("Computing change classification...")
        change = ee_logic.compute_change(idx1, idx2)
        classes = ee_logic.classify_change(change, req.threshold)
        
        # 5. Map Tiles
        print("Generating Map IDs...")
        img1_map = idx1.getMapId({'min': -1, 'max': 1, 'palette': ['red', 'white', 'green']})
        img2_map = idx2.getMapId({'min': -1, 'max': 1, 'palette': ['red', 'white', 'green']})
        
        class_palette = ["#EA4335", "#5A5A5C", "#34A853"]
        class_map = classes.getMapId({'min': -1, 'max': 1, 'palette': class_palette})
        
        # 6. Stats & Histogram
        # Calculate dynamic scale to prevent timeouts on huge areas (ponytail style: simple math)
        coords = req.roi_geojson["geometry"]["coordinates"][0]
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        width_deg = max(lons) - min(lons)
        height_deg = max(lats) - min(lats)
        # 1 deg ~ 111km. Aim for ~100k pixels max for blazing fast aggregation.
        area_sq_m = (width_deg * 111000) * (height_deg * 111000)
        ideal_scale = (area_sq_m / 100_000) ** 0.5
        
        base_scale = 10 if "Sentinel" in req.sensor else 30
        scale = max(base_scale, int(ideal_scale))
        
        print(f"Computing statistics at {scale}m scale (Area ~{area_sq_m/1e6:.1f} sq km).")
        raw_stats = ee_logic.compute_stats(idx2, change, classes, roi, scale)
        print("Statistics computed.")
        
        total_ha = raw_stats.get("total_pixels", 0) * (scale * scale) / 10000.0
        
        stats = {
            "total_area": total_ha,
            "changed_area": raw_stats.get("hectares_gain", 0) + raw_stats.get("hectares_loss", 0),
            "change_pct": raw_stats.get("pct_gain", 0) + raw_stats.get("pct_loss", 0),
            "pixels": raw_stats.get("total_pixels", 0)
        }
        
        hist = {
            "0": raw_stats.get("nochange_pixels", 0),
            "1": raw_stats.get("loss_pixels", 0),
            "2": raw_stats.get("gain_pixels", 0)
        }
        
        print("Done. Returning payload.")
        return {
            "status": "success",
            "tiles": {
                "before": img1_map['tile_fetcher'].url_format,
                "after": img2_map['tile_fetcher'].url_format,
                "change": class_map['tile_fetcher'].url_format,
            },
            "stats": stats,
            "histogram": hist
        }

    except ee.EEException as e:
        print(f"Earth Engine Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"Unexpected Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files (Frontend)
app.mount("/", StaticFiles(directory="public", html=True), name="public")
