"""
CHIRPS access, point time-series extraction, and AOI raster export,
all run server-side on Google Earth Engine to avoid pulling raw
daily imagery down to the local machine.

Dataset: UCSB-CHG/CHIRPS/DAILY (0.05 deg, ~5.5 km native resolution,
1981-present, daily precipitation in mm).
"""

import ee
import pandas as pd

CHIRPS_DAILY = "UCSB-CHG/CHIRPS/DAILY"
NATIVE_SCALE_M = 5566  # ~0.05 deg at the equator

RESOLUTION_PRESETS = {
    "native": NATIVE_SCALE_M,
    "1km": 1000,
    "500m": 500,
    "250m": 250,
}


def get_collection(start_date, end_date, aoi=None):
    """
    start_date / end_date: 'YYYY-MM-DD' strings.
    aoi: optional ee.Geometry to pre-clip/filterBounds (speeds up
        subsequent reduceRegion/export calls).
    """
    coll = ee.ImageCollection(CHIRPS_DAILY).filterDate(start_date, end_date)
    if aoi is not None:
        coll = coll.filterBounds(aoi)
    return coll


def _add_time_bands(image):
    """Attach a date-string property for easier client-side reassembly."""
    return image.set("date_str", image.date().format("YYYY-MM-dd"))


def extract_point_series(lon, lat, start_date, end_date, freq="daily"):
    """
    Extract a rainfall time series at a single point.

    freq: 'daily', 'monthly', or 'annual'. Monthly/annual are sums of
        the daily CHIRPS values, matching how CHIRPS Monthly is itself
        defined, computed server-side so we only pull back one row per
        period rather than one row per day plus a local groupby.

    Returns a pandas.DataFrame with columns ['date', 'rainfall_mm'].
    """
    point = ee.Geometry.Point([lon, lat])
    coll = get_collection(start_date, end_date, aoi=point)

    if freq == "daily":
        def sample(image):
            value = image.reduceRegion(
                reducer=ee.Reducer.first(), geometry=point, scale=NATIVE_SCALE_M
            ).get("precipitation")
            return ee.Feature(None, {
                "date": image.date().format("YYYY-MM-dd"),
                "rainfall_mm": value,
            })
        features = coll.map(sample)

    elif freq in ("monthly", "annual"):
        start = ee.Date(start_date)
        end = ee.Date(end_date)
        if freq == "monthly":
            n_periods = end.difference(start, "month").round()
            unit = "month"
        else:
            n_periods = end.difference(start, "year").round()
            unit = "year"

        period_list = ee.List.sequence(0, n_periods.subtract(1))

        def period_sum(i):
            period_start = start.advance(ee.Number(i), unit)
            period_end = period_start.advance(1, unit)
            period_img = coll.filterDate(period_start, period_end).sum()
            value = period_img.reduceRegion(
                reducer=ee.Reducer.first(), geometry=point, scale=NATIVE_SCALE_M
            ).get("precipitation")
            label = period_start.format("YYYY-MM" if freq == "monthly" else "YYYY")
            return ee.Feature(None, {"date": label, "rainfall_mm": value})

        features = ee.FeatureCollection(period_list.map(period_sum))
    else:
        raise ValueError("freq must be 'daily', 'monthly', or 'annual'")

    info = features.getInfo()["features"]
    rows = [f["properties"] for f in info]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.dropna(subset=["rainfall_mm"]).sort_values("date").reset_index(drop=True)
        df["rainfall_mm"] = df["rainfall_mm"].astype(float)
    return df


def extract_aoi_zonal_stats(aoi_geom, start_date, end_date, freq="monthly"):
    """
    Zonal statistics (mean/min/max/std/sum) of rainfall over an AOI
    (ee.Geometry, e.g. a district polygon read from a user shapefile
    via QGIS -> GeoJSON -> ee.Geometry), summarized per period.

    Returns a pandas.DataFrame with one row per period and columns
    ['date', 'mean_mm', 'min_mm', 'max_mm', 'std_mm', 'sum_mm'].
    """
    start = ee.Date(start_date)
    end = ee.Date(end_date)
    unit = {"daily": "day", "monthly": "month", "annual": "year"}[freq]
    n_periods = end.difference(start, unit).round()
    period_list = ee.List.sequence(0, n_periods.subtract(1))

    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.minMax(), sharedInputs=True)
        .combine(ee.Reducer.stdDev(), sharedInputs=True)
        .combine(ee.Reducer.sum(), sharedInputs=True)
    )

    def period_stats(i):
        period_start = start.advance(ee.Number(i), unit)
        period_end = period_start.advance(1, unit)
        coll = get_collection(
            period_start.format("YYYY-MM-dd"), period_end.format("YYYY-MM-dd"), aoi=aoi_geom
        )
        period_img = coll.sum() if unit != "day" else coll.first()
        stats = period_img.reduceRegion(
            reducer=reducer, geometry=aoi_geom, scale=NATIVE_SCALE_M, maxPixels=1e9
        )
        fmt = {"day": "YYYY-MM-dd", "month": "YYYY-MM", "year": "YYYY"}[unit]
        return ee.Feature(None, {
            "date": period_start.format(fmt),
            "mean_mm": stats.get("precipitation_mean"),
            "min_mm": stats.get("precipitation_min"),
            "max_mm": stats.get("precipitation_max"),
            "std_mm": stats.get("precipitation_stdDev"),
            "sum_mm": stats.get("precipitation_sum"),
        })

    features = ee.FeatureCollection(period_list.map(period_stats)).getInfo()["features"]
    rows = [f["properties"] for f in features]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.dropna(subset=["mean_mm"]).sort_values("date").reset_index(drop=True)
        for col in ["mean_mm", "min_mm", "max_mm", "std_mm", "sum_mm"]:
            df[col] = df[col].astype(float)
    return df


def export_aoi_raster_to_qgis(
    aoi_geom, start_date, end_date, out_path, resolution="1km", statistic="sum",
):
    """
    Download rainfall over the AOI as a local GeoTIFF, synchronously,
    via ee.Image.getDownloadURL -- no Google Drive round-trip, no
    export-task polling. The caller loads out_path straight into QGIS
    with QgsRasterLayer + QgsProject.instance().addMapLayer.

    This uses Earth Engine's direct-download endpoint, which caps
    around 32-50MB per request (varies by EE backend limits). That is
    generous for a single Malawi district at 1km resolution over a
    multi-year period, but WILL fail for very large AOIs (e.g. all of
    Malawi) at fine resolution -- if it does, catch the resulting
    exception, tell the user, and fall back to
    export_aoi_raster_to_drive() below instead, which has no such
    size ceiling because it runs as an async batch task.

    resolution / statistic: see export_aoi_raster_to_drive.

    Returns out_path on success. Raises RuntimeError with a
    size-ceiling-aware message on failure.
    """
    import requests

    if resolution not in RESOLUTION_PRESETS:
        raise ValueError(f"resolution must be one of {list(RESOLUTION_PRESETS)}")
    scale = RESOLUTION_PRESETS[resolution]

    coll = get_collection(start_date, end_date, aoi=aoi_geom)
    image = coll.sum() if statistic == "sum" else coll.mean()
    image = image.clip(aoi_geom).toFloat().rename("rainfall_mm")

    if resolution != "native":
        image = image.resample("bicubic")

    try:
        url = image.getDownloadURL({
            "region": aoi_geom,
            "scale": scale,
            "format": "GEO_TIFF",
            "crs": "EPSG:4326",
        })
        response = requests.get(url, timeout=120)
        response.raise_for_status()
    except Exception as exc:
        raise RuntimeError(
            "Direct download failed -- this usually means the AOI/resolution "
            "combination produced a file over Earth Engine's direct-download "
            "size limit (roughly 32-50 MB). Try a coarser resolution (e.g. "
            "'native' instead of '250m'), a shorter date range, or use the "
            f"Google Drive export instead for large AOIs.\n\nOriginal error: {exc}"
        ) from exc

    with open(out_path, "wb") as fh:
        fh.write(response.content)

    return out_path


def export_aoi_raster_to_drive(
    aoi_geom, start_date, end_date, description, folder="RAM_Rainfall_Exports",
    resolution="1km", statistic="sum",
):
    """
    FALLBACK for AOIs too large for export_aoi_raster_to_qgis's direct
    download (e.g. the whole country at fine resolution, or a very
    long date range). Kicks off an asynchronous GEE export task: total
    (or mean) rainfall over the AOI for the given period, as a GeoTIFF
    in the user's Google Drive. Export is async by design (GEE exports
    commonly run minutes and are not something QGIS should block on)
    -- the caller should surface the returned task id/status to the
    user and let them check progress at
    https://code.earthengine.google.com/tasks, then load the resulting
    file into QGIS manually once it lands in Drive.

    resolution: one of RESOLUTION_PRESETS ('native', '1km', '500m', '250m').
        Anything finer than native (~5.5km) is bicubic-resampled, i.e.
        smoother-looking but NOT truer to the underlying satellite
        observation density -- state this explicitly in any figure
        caption/methods text that uses a resampled resolution.
    statistic: 'sum' (total rainfall for the period) or 'mean' (mean
        daily rainfall over the period).
    """
    if resolution not in RESOLUTION_PRESETS:
        raise ValueError(f"resolution must be one of {list(RESOLUTION_PRESETS)}")
    scale = RESOLUTION_PRESETS[resolution]

    coll = get_collection(start_date, end_date, aoi=aoi_geom)
    image = coll.sum() if statistic == "sum" else coll.mean()
    image = image.clip(aoi_geom).toFloat()

    if resolution != "native":
        image = image.resample("bicubic")

    task = ee.batch.Export.image.toDrive(
        image=image,
        description=description,
        folder=folder,
        fileNamePrefix=description,
        region=aoi_geom,
        scale=scale,
        crs="EPSG:4326",
        maxPixels=1e10,
    )
    task.start()
    return task  # caller can poll task.status()
