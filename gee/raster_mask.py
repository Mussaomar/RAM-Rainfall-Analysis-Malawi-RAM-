"""
Post-download raster masking.

Why this exists: Earth Engine's Image.clip() masks pixels outside the
AOI on the server side, but that mask does not reliably survive the
getDownloadURL GeoTIFF round-trip as a proper GDAL NoData value --
in practice the downloaded file is a plain rectangular grid covering
the AOI's bounding box, and QGIS has nothing to tell it which pixels
are "outside" the district/basin, so it draws the whole box.

The fix used here is a local GDAL cutline warp against the ORIGINAL
AOI vector file (the shapefile/GeoPackage the user picked in the
dialog) -- this clips to the exact polygon boundary regardless of
what Earth Engine did or didn't encode, and writes a real NoData
value QGIS will render as transparent.

Requires GDAL's Python bindings (osgeo.gdal / osgeo.ogr), which ship
with QGIS itself, so no extra dependency for the plugin's target
environment.
"""

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()

DEFAULT_NODATA = -9999.0


def _first_layer_name(vector_path):
    """
    Cutline sources with a single layer (shapefiles, GeoJSON) don't
    need an explicit layer name, but GeoPackages can hold several --
    read the actual layer name rather than guessing, so multi-layer
    GeoPackages (e.g. one with both a district boundary and a
    settlement layer, as in the screenshot) don't silently clip
    against the wrong layer.
    """
    ds = ogr.Open(vector_path)
    if ds is None:
        raise ValueError(f"GDAL/OGR could not open AOI vector file: {vector_path}")
    layer = ds.GetLayer(0)
    name = layer.GetName()
    ds = None
    return name


def clip_raster_to_vector(raster_path, vector_path, out_path,
                           nodata_value=DEFAULT_NODATA, layer_name=None):
    """
    Clip raster_path to the exact polygon boundary of vector_path
    (a cutline warp, not just an extent crop) and write the result
    to out_path with nodata_value burned in outside the polygon.

    raster_path: the raw GeoTIFF as downloaded from Earth Engine
        (rectangular, covering the AOI's bounding box).
    vector_path: the original AOI file the user selected in the
        dialog -- same file used to build the ee.Geometry, so the
        polygon boundary matches exactly.
    layer_name: OGR layer name within vector_path. Auto-detected from
        the first layer if not given (fine for shapefiles/GeoJSON;
        pass this explicitly for a multi-layer GeoPackage where the
        AOI isn't layer 0).

    Returns out_path. Raises RuntimeError with a readable message if
    the warp fails (e.g. mismatched/unreadable CRS).
    """
    if layer_name is None:
        layer_name = _first_layer_name(vector_path)

    warp_options = gdal.WarpOptions(
        format="GTiff",
        cutlineDSName=vector_path,
        cutlineLayer=layer_name,
        cropToCutline=True,
        dstNodata=nodata_value,
        # Reproject the cutline to match the raster's CRS during the
        # warp rather than assuming they already match -- CHIRPS
        # downloads come back in EPSG:4326, but a user's district
        # shapefile could be in UTM or anything else.
        multithread=True,
    )

    try:
        result_ds = gdal.Warp(out_path, raster_path, options=warp_options)
    except Exception as exc:
        raise RuntimeError(
            "Local GDAL clip-to-AOI failed. This usually means the AOI "
            "vector's CRS couldn't be read, or the layer name didn't "
            f"match (tried layer '{layer_name}'). Original error: {exc}"
        ) from exc

    if result_ds is None:
        raise RuntimeError("GDAL Warp returned no result -- check the AOI file is valid.")

    result_ds = None  # flush/close
    return out_path
