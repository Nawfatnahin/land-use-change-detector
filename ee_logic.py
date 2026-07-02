"""
ee_logic.py — Google Earth Engine Core Logic
=============================================
All GEE authentication, image processing, spectral index computation,
change detection, and statistics functions. Fully isolated from UI code.

Band Reference:
  Sentinel-2 SR Harmonized:  B4=Red, B8=NIR, B11=SWIR1, B12=SWIR2, SCL=Scene Classification
  Landsat 8/9 Collection 2:  SR_B4=Red, SR_B5=NIR, SR_B6=SWIR1, SR_B7=SWIR2, QA_PIXEL=QA
"""

import ee
from google.oauth2 import service_account


# ─── Band Name Lookup ─────────────────────────────────────────────────────────

BAND_MAP = {
    "Sentinel-2": {
        "blue": "B2",
        "green": "B3",
        "red": "B4",
        "nir": "B8",
        "swir1": "B11",
        "swir2": "B12",
        "scale": 10,       # Native resolution in metres
        "collection": "COPERNICUS/S2_SR_HARMONIZED",
    },
    "Landsat 8/9": {
        "blue": "SR_B2",
        "green": "SR_B3",
        "red": "SR_B4",
        "nir": "SR_B5",
        "swir1": "SR_B6",
        "swir2": "SR_B7",
        "scale": 30,
        "collection": "LANDSAT/LC08/C02/T1_L2",  # Works for both L8 & L9
    },
}


# ─── Authentication ───────────────────────────────────────────────────────────

def initialize_ee(secrets: dict) -> None:
    """
    Authenticate and initialize the Earth Engine API using a service account.

    Args:
        secrets: Streamlit secrets dict containing 'gee_service_account' with
                 the full service-account JSON key fields.

    Raises:
        ee.EEException: If authentication or project registration fails.
        KeyError: If required secret fields are missing.
    """
    sa_info = dict(secrets["gee_service_account"])
    project_id = sa_info["project_id"]

    credentials = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/earthengine"],
    )

    # project= is MANDATORY since late 2024 — omitting it will raise an error.
    ee.Initialize(credentials, project=project_id)


# ─── Cloud Masking ────────────────────────────────────────────────────────────

def _cloud_mask_s2(image: ee.Image) -> ee.Image:
    """
    Mask clouds/shadows/cirrus/snow from a Sentinel-2 SR image using the
    Scene Classification Layer (SCL).

    Masked SCL values:
        3  = Cloud Shadow
        8  = Cloud Medium Probability
        9  = Cloud High Probability
        10 = Thin Cirrus
        11 = Snow / Ice
    """
    scl = image.select("SCL")
    mask = (
        scl.neq(3)
        .And(scl.neq(8))
        .And(scl.neq(9))
        .And(scl.neq(10))
        .And(scl.neq(11))
    )
    return image.updateMask(mask)


def _cloud_mask_landsat(image: ee.Image) -> ee.Image:
    """
    Mask clouds/shadows from a Landsat Collection 2 Level-2 image using
    QA_PIXEL bit flags.

    Bit positions:
        3 = Cloud Shadow
        4 = Cloud
        5 = Cirrus (Landsat 9 only, but safe to check on L8 too)
    """
    qa = image.select("QA_PIXEL")
    cloud_shadow_bit = 1 << 3
    cloud_bit = 1 << 4
    cirrus_bit = 1 << 5

    mask = (
        qa.bitwiseAnd(cloud_shadow_bit).eq(0)
        .And(qa.bitwiseAnd(cloud_bit).eq(0))
        .And(qa.bitwiseAnd(cirrus_bit).eq(0))
    )
    return image.updateMask(mask)


# ─── Image Collection Retrieval ───────────────────────────────────────────────

def get_composite(
    roi: ee.Geometry,
    start_date: str,
    end_date: str,
    cloud_pct: int,
    sensor: str = "Sentinel-2",
) -> ee.Image:
    """
    Fetch a cloud-masked median composite for the given sensor, date range, and ROI.

    Args:
        roi:        ee.Geometry defining the region of interest.
        start_date: ISO date string 'YYYY-MM-DD'.
        end_date:   ISO date string 'YYYY-MM-DD'.
        cloud_pct:  Maximum cloud cover percentage filter (0–100).
        sensor:     'Sentinel-2' or 'Landsat 8/9'.

    Returns:
        ee.Image — a single median composite clipped to the ROI.
    """
    bands = BAND_MAP[sensor]
    collection_id = bands["collection"]

    # Start building the collection
    collection = (
        ee.ImageCollection(collection_id)
        .filterBounds(roi)
        .filterDate(start_date, end_date)
    )

    # Apply cloud cover metadata filter
    if sensor == "Sentinel-2":
        collection = collection.filter(
            ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_pct)
        )
        collection = collection.map(_cloud_mask_s2)
    else:
        collection = collection.filter(
            ee.Filter.lte("CLOUD_COVER", cloud_pct)
        )
        collection = collection.map(_cloud_mask_landsat)

    # Median composite — reduces cloud/shadow residuals
    composite = collection.median().clip(roi)

    return composite


def get_collection_size(
    roi: ee.Geometry,
    start_date: str,
    end_date: str,
    cloud_pct: int,
    sensor: str = "Sentinel-2",
) -> int:
    """
    Return the number of images in the filtered collection (before compositing).
    Useful for warning the user if zero cloud-free images exist in the range.
    """
    bands = BAND_MAP[sensor]
    collection_id = bands["collection"]

    collection = (
        ee.ImageCollection(collection_id)
        .filterBounds(roi)
        .filterDate(start_date, end_date)
    )

    if sensor == "Sentinel-2":
        collection = collection.filter(
            ee.Filter.lte("CLOUDY_PIXEL_PERCENTAGE", cloud_pct)
        )
    else:
        collection = collection.filter(
            ee.Filter.lte("CLOUD_COVER", cloud_pct)
        )

    return collection.size().getInfo()


# ─── Spectral Index Computation ───────────────────────────────────────────────

def compute_ndvi(image: ee.Image, sensor: str = "Sentinel-2") -> ee.Image:
    """
    Compute NDVI = (NIR − Red) / (NIR + Red).

    Returns a single-band ee.Image named 'NDVI'.
    """
    bands = BAND_MAP[sensor]
    nir = image.select(bands["nir"])
    red = image.select(bands["red"])
    ndvi = nir.subtract(red).divide(nir.add(red)).rename("NDVI")
    return ndvi


def compute_ndbi(image: ee.Image, sensor: str = "Sentinel-2") -> ee.Image:
    """
    Compute NDBI = (SWIR1 − NIR) / (SWIR1 + NIR).

    Returns a single-band ee.Image named 'NDBI'.
    """
    bands = BAND_MAP[sensor]
    swir = image.select(bands["swir1"])
    nir = image.select(bands["nir"])
    ndbi = swir.subtract(nir).divide(swir.add(nir)).rename("NDBI")
    return ndbi


def compute_mndwi(image: ee.Image, sensor: str = "Sentinel-2") -> ee.Image:
    """
    Compute MNDWI = (Green − SWIR1) / (Green + SWIR1).

    Returns a single-band ee.Image named 'MNDWI'.
    """
    bands = BAND_MAP[sensor]
    green = image.select(bands["green"])
    swir = image.select(bands["swir1"])
    mndwi = green.subtract(swir).divide(green.add(swir)).rename("MNDWI")
    return mndwi


def compute_ndwi(image: ee.Image, sensor: str = "Sentinel-2") -> ee.Image:
    """
    Compute NDWI = (Green − NIR) / (Green + NIR).

    Returns a single-band ee.Image named 'NDWI'.
    """
    bands = BAND_MAP[sensor]
    green = image.select(bands["green"])
    nir = image.select(bands["nir"])
    ndwi = green.subtract(nir).divide(green.add(nir)).rename("NDWI")
    return ndwi


def compute_evi(image: ee.Image, sensor: str = "Sentinel-2") -> ee.Image:
    """
    Compute EVI = 2.5 × (NIR − Red) / (NIR + 6×Red − 7.5×Blue + 1).

    Returns a single-band ee.Image named 'EVI'.
    """
    bands = BAND_MAP[sensor]
    nir = image.select(bands["nir"])
    red = image.select(bands["red"])
    blue = image.select(bands["blue"])
    evi = (
        nir.subtract(red)
        .multiply(2.5)
        .divide(nir.add(red.multiply(6)).subtract(blue.multiply(7.5)).add(1))
        .rename("EVI")
    )
    return evi


def compute_index(
    image: ee.Image,
    index: str,
    sensor: str = "Sentinel-2",
) -> ee.Image:
    """
    Dispatch to the correct index function.

    Args:
        image:  ee.Image composite.
        index:  'NDVI' or 'NDBI'.
        sensor: 'Sentinel-2' or 'Landsat 8/9'.

    Returns:
        Single-band ee.Image named after the index.
    """
    if index == "NDVI":
        return compute_ndvi(image, sensor)
    elif index == "NDBI":
        return compute_ndbi(image, sensor)
    elif index == "MNDWI":
        return compute_mndwi(image, sensor)
    elif index == "NDWI":
        return compute_ndwi(image, sensor)
    elif index == "EVI":
        return compute_evi(image, sensor)
    else:
        raise ValueError(f"Unknown index: {index}. Use NDVI, NDBI, MNDWI, NDWI, or EVI.")


# ─── Change Detection ─────────────────────────────────────────────────────────

def compute_change(index_a: ee.Image, index_b: ee.Image) -> ee.Image:
    """
    Per-pixel difference: Time B − Time A.

    Positive values → index increased (e.g. vegetation gain for NDVI).
    Negative values → index decreased (e.g. vegetation loss for NDVI).

    Returns a single-band ee.Image named 'change'.
    """
    return index_b.subtract(index_a).rename("change")


def classify_change(
    change_img: ee.Image,
    threshold: float,
) -> ee.Image:
    """
    Classify each pixel into:
        1 = Significant Gain   (change >  +threshold)
        0 = No Significant Change (−threshold ≤ change ≤ +threshold)
       -1 = Significant Loss   (change < −threshold)

    Returns a single-band ee.Image named 'classification'.
    """
    gain = change_img.gt(threshold)           # 1 where gain
    loss = change_img.lt(-threshold)          # 1 where loss
    # gain pixels → +1, loss pixels → −1, else → 0
    classified = gain.subtract(loss).rename("classification")
    return classified


# ─── Statistics ───────────────────────────────────────────────────────────────

def compute_stats(
    index_img: ee.Image,
    change_img: ee.Image,
    classified_img: ee.Image,
    roi: ee.Geometry,
    scale: int,
) -> dict:
    """
    Compute summary statistics over the ROI using reduceRegion.

    Returns dict with:
        mean_index:      Mean value of the index image.
        total_pixels:    Total valid pixel count in ROI.
        gain_pixels:     Pixels classified as significant gain.
        loss_pixels:     Pixels classified as significant loss.
        pct_gain:        Percentage of area with significant gain.
        pct_loss:        Percentage of area with significant loss.
        hectares_gain:   Approximate hectares of gain.
        hectares_loss:   Approximate hectares of loss.
        mean_change:     Mean change value across ROI.

    All .getInfo() calls happen here — keeps GEE lazy up to this point.
    """
    # Mean index value for Time B
    mean_result = index_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=scale,
        bestEffort=True,
        maxPixels=1e8,
    ).getInfo()

    # Pixel counts for classification categories
    # Map: gain=1 → 'gain', loss=-1 remapped to 2 → 'loss', no-change=0 → 'nochange'
    # Use frequency histogram
    class_remapped = classified_img.remap([-1, 0, 1], [0, 1, 2]).rename("class_id")

    freq_result = class_remapped.reduceRegion(
        reducer=ee.Reducer.frequencyHistogram(),
        geometry=roi,
        scale=scale,
        bestEffort=True,
        maxPixels=1e8,
    ).getInfo()

    # Mean change
    change_mean_result = change_img.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=roi,
        scale=scale,
        bestEffort=True,
        maxPixels=1e8,
    ).getInfo()

    # Parse frequency histogram
    histogram = freq_result.get("class_id", {})
    loss_pixels = int(histogram.get("0", 0))
    nochange_pixels = int(histogram.get("1", 0))
    gain_pixels = int(histogram.get("2", 0))
    total_pixels = loss_pixels + nochange_pixels + gain_pixels

    # Compute percentages and hectares
    pixel_area_ha = (scale * scale) / 10000.0  # square metres → hectares

    pct_gain = (gain_pixels / total_pixels * 100) if total_pixels > 0 else 0
    pct_loss = (loss_pixels / total_pixels * 100) if total_pixels > 0 else 0
    hectares_gain = gain_pixels * pixel_area_ha
    hectares_loss = loss_pixels * pixel_area_ha

    # Extract the mean index value (band name varies)
    band_name = list(mean_result.keys())[0] if mean_result else "unknown"
    mean_index = mean_result.get(band_name, 0)
    if mean_index is None:
        mean_index = 0

    change_band = list(change_mean_result.keys())[0] if change_mean_result else "change"
    mean_change = change_mean_result.get(change_band, 0)
    if mean_change is None:
        mean_change = 0

    pct_nochange = 100.0 - pct_gain - pct_loss
    hectares_nochange = nochange_pixels * pixel_area_ha

    return {
        "mean_index": round(mean_index, 4),
        "total_pixels": total_pixels,
        "gain_pixels": gain_pixels,
        "loss_pixels": loss_pixels,
        "nochange_pixels": nochange_pixels,
        "pct_gain": round(pct_gain, 2),
        "pct_loss": round(pct_loss, 2),
        "pct_nochange": round(pct_nochange, 2),
        "hectares_gain": round(hectares_gain, 2),
        "hectares_loss": round(hectares_loss, 2),
        "hectares_nochange": round(hectares_nochange, 2),
        "mean_change": round(mean_change, 4),
    }


# ─── Map Tile URLs ────────────────────────────────────────────────────────────

def get_map_tiles(image: ee.Image, vis_params: dict) -> str:
    """
    Get a XYZ tile URL for displaying an ee.Image on a folium map.

    Args:
        image:      ee.Image to visualize.
        vis_params: Visualization parameters dict (min, max, palette, etc.).

    Returns:
        str — the tile URL template with {x}, {y}, {z} placeholders.
    """
    map_id_dict = image.getMapId(vis_params)
    return map_id_dict["tile_fetcher"].url_format


# ─── Visualization Parameters ────────────────────────────────────────────────

# NDVI: red (bare/urban) → yellow → green (dense vegetation)
NDVI_VIS = {
    "min": -0.2,
    "max": 0.8,
    "palette": ["#d73027", "#fc8d59", "#fee08b", "#d9ef8b", "#66bd63", "#1a9850"],
}

# NDBI: green (non-built) → yellow → red (dense built-up)
NDBI_VIS = {
    "min": -0.3,
    "max": 0.3,
    "palette": ["#1a9850", "#66bd63", "#fee08b", "#fc8d59", "#d73027", "#a50026"],
}

# Change: red (loss) → white (no change) → green (gain)
CHANGE_VIS = {
    "min": -0.5,
    "max": 0.5,
    "palette": ["#d73027", "#fc8d59", "#ffffbf", "#d9ef8b", "#1a9850"],
}

# Classification: loss=-1 (red), no-change=0 (grey), gain=1 (green)
CLASS_VIS = {
    "min": -1,
    "max": 1,
    "palette": ["#FF4B4B", "#555555", "#00FF87"],
}


def get_vis_params(layer_type: str) -> dict:
    """Return the appropriate visualization params for a layer type."""
    return {
        "NDVI": NDVI_VIS,
        "NDBI": NDBI_VIS,
        "change": CHANGE_VIS,
        "classification": CLASS_VIS,
    }.get(layer_type, NDVI_VIS)


# ─── ROI Validation ──────────────────────────────────────────────────────────

def validate_roi_size(roi: ee.Geometry, max_hectares: float = 50000) -> dict:
    """
    Check that the ROI is within the allowed size to stay inside free quota.

    Args:
        roi:           ee.Geometry defining the analysis area.
        max_hectares:  Maximum allowed area in hectares (default 50,000 ≈ 500 km²).

    Returns:
        dict with 'valid' (bool), 'area_ha' (float), 'max_ha' (float).
    """
    area_m2 = roi.area(maxError=1000).getInfo()
    area_ha = area_m2 / 10000.0

    return {
        "valid": area_ha <= max_hectares,
        "area_ha": round(area_ha, 2),
        "max_ha": max_hectares,
    }


def geojson_to_ee_geometry(geojson: dict) -> ee.Geometry:
    """
    Convert a GeoJSON Feature or FeatureCollection (from st_folium Draw)
    to an ee.Geometry.
    """
    if geojson is None:
        return None

    # st_folium returns the drawn features under different keys
    features = None

    if "features" in geojson and len(geojson["features"]) > 0:
        # FeatureCollection from Draw plugin
        features = geojson["features"]
    elif "geometry" in geojson:
        # Single Feature
        features = [geojson]

    if not features:
        return None

    # Use the last drawn feature
    last_feature = features[-1]
    geometry = last_feature.get("geometry", {})
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates", [])

    if geom_type == "Polygon":
        return ee.Geometry.Polygon(coords)
    elif geom_type == "Rectangle":
        return ee.Geometry.Rectangle(coords)
    elif geom_type == "Point":
        return ee.Geometry.Point(coords)
    else:
        # Fallback: try as generic GeoJSON
        return ee.Geometry(geometry)
