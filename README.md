RAM - Rainfall Analysis Malawi (QGIS plugin)

Rainfall extraction, SPI/RAI/PCI indices, and trend analysis for
Malawi, using CHIRPS Daily precipitation via the Google Earth Engine
Python API.

 What it does

Point extraction,pick a point on the map (or type lon/lat),
get a daily/monthly/annual CHIRPS rainfall time series, export to CSV.
AOI / district analysis,load your own boundary (shapefile or
GeoPackage: a district, a watershed, a hand-drawn polygon the
 plugin does not bundle a boundary layer, so bring your own), get
zonal statistics (mean/min/max/std/sum) per period, export CSV.
Rainfall raster, straight into QGIS,total or mean rainfall
over the AOI, downloaded synchronously from Earth Engine and added
directly as a layer in the QGIS map canvas  no Google Drive step,
no waiting on an export task. Choose native (~5.5 km), 1 km, 500 m,
 or 250 m (the last three bicubic-resampled from the native grid,
 not a truer observation). A Google Drive export is kept as a
fallback button for AOIs/date-ranges too large for direct download
(roughly >32-50 MB), since that path has no size ceiling.
Climate indices ,SPI (1/3/6/12/24-month), RAI (annual), PCI
(annual), computed from either a CHIRPS extraction or an imported
 ground-station monthly CSV, so the two can also be plotted together.
Trend analysis, Mann-Kendall test, Sen's slope, OLS regression,
  moving averages, on the annual series.

 Install

1. Copy this folder into your QGIS plugins directory:
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
2. Install dependencies into QGIS's own Python (see `requirements.txt`
   for the exact commands per OS  QGIS plugins run inside QGIS's
   bundled interpreter, not your regular system Python).
3. In QGIS: Plugins -> Manage and Install Plugins -> Installed, enable
   "RAM - Rainfall Analysis Malawi".
4. You need a Google Earth Engine account with a linked Google Cloud
   project (register at https://earthengine.google.com if you don't
   have one). Enter that project ID in the plugin dialog and click
   "Initialize Earth Engine" — the first run opens a browser window
   for one-time OAuth sign-in and then caches the token.

 Raster workflow: direct to QGIS vs Drive fallback

`gee/chirps.py` has two export functions:

- `export_aoi_raster_to_qgis()` : the default. Uses
  `ee.Image.getDownloadURL` to fetch a GeoTIFF synchronously and save
  it to a temp file; the UI then loads that file with `QgsRasterLayer`
  and adds it to `QgsProject.instance()`. Fast, no Drive account
  friction, but capped at roughly 32-50 MB per request (Earth Engine's
  own limit on that endpoint) — fine for a single Malawi district at
  1 km over a multi-year period, but will fail for e.g. the whole
  country at 250 m over many years.
 `export_aoi_raster_to_drive()` :kept as a fallback for AOI/
  resolution/date-range combinations that exceed that ceiling. Runs
  as an asynchronous GEE batch task and lands in the user's Google
  Drive; the plugin reports the task ID and a link to
  https://code.earthengine.google.com/tasks rather than blocking on
  it, since these commonly take minutes.

If you hit the size ceiling on the direct path, either reduce the
resolution, shorten the date range, or use the Drive fallback and
then drag the resulting file into QGIS once it lands.

 Why the raster is clipped to the exact AOI shape, not just its box

Earth Engine's `Image.clip()` masks pixels outside the AOI *on the
server*, but that mask doesn't reliably survive the `getDownloadURL`
GeoTIFF round-trip as a real GDAL NoData value ,the file that comes
back is a plain rectangular grid covering the AOI's bounding box, and
QGIS has no way to know which pixels are "outside" your district or
basin, so it draws the whole rectangle (this is exactly what you'd see
if you added the raw download straight to the map).

`gee/raster_mask.py` fixes this with a second, local step: after
download, it runs a GDAL cutline warp (`gdal.Warp` with
`cutlineDSName` set to your original AOI file) that clips the raster
to the exact polygon boundary and burns in a real NoData value
(-9999 by default). This is what `_on_add_raster_to_qgis` in the UI
actually loads into the map the raw rectangular download is kept
alongside it as `RAM_<name>_raw.tif` in case you want to compare or
debug. The Drive-export fallback does **not** get this treatment
automatically (it's an async file you retrieve from Drive yourself);
if you go that route, use QGIS's own **Raster → Extraction → Clip
Raster by Mask Layer** tool against the same AOI file to get the same
exact-shape result.



 limitations / next steps

No bundled Malawi boundary layer by design you supply the AOI
  file each session; consider a "recent files" list if this gets
  repetitive.
Direct raster download has the ~32-50 MB ceiling described above;
  the Drive fallback does not poll for completion  check
  https://code.earthengine.google.com/tasks or extend
  `chirps.export_aoi_raster_to_drive` with a polling loop if you want
  in-app status.
SPI is fit per calendar month across the full record; very short
  records (a handful of years) will produce statistically shaky fits 
  the code skips fitting when fewer than 4 observations are available
  for a given month, which for CHIRPS's 1981–present record should
  rarely bind unless your date range is deliberately narrow.
- No automated test suite yet recommended before relying on this for
  a submitted dissertation figure: unit-test `analysis/indices.py` and
  `analysis/trends.py` against a small hand-computed example.
