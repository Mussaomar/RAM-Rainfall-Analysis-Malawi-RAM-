"""
Main dialog: tabbed interface for point extraction, AOI zonal stats +
raster export, climate indices, and trend analysis.

Built programmatically (no .ui/Designer file) so the plugin has no
pyuic build step and stays a plain drop-in folder.
"""

import os
import tempfile

from qgis.PyQt.QtWidgets import (
    QDialog, QTabWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QWidget,
    QLabel, QLineEdit, QPushButton, QComboBox, QDateEdit, QDoubleSpinBox,
    QFileDialog, QMessageBox, QPlainTextEdit, QGroupBox, QCheckBox,
)
from qgis.PyQt.QtCore import QDate
from qgis.gui import QgsMapToolEmitPoint
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRasterLayer,
    QgsCoordinateTransform, QgsCoordinateReferenceSystem,
)

from ..gee import authentication, chirps, raster_mask
from ..analysis import indices, trends, graphs


class RamDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.setWindowTitle("RAM - Rainfall Analysis Malawi")
        self.resize(560, 520)

        self._picked_point = None  # (lon, lat) in EPSG:4326
        self._map_tool = None
        self._aoi_layer = None
        self._last_point_df = None
        self._last_aoi_df = None
        self._last_ground_series = None

        self._build_ui()

    # ------------------------------------------------------------ UI ----

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.status_label = QLabel("Earth Engine: not initialized")
        layout.addWidget(self.status_label)

        auth_row = QHBoxLayout()
        self.project_id_edit = QLineEdit()
        self.project_id_edit.setPlaceholderText("GEE-linked Google Cloud project ID")
        auth_row.addWidget(QLabel("Project ID:"))
        auth_row.addWidget(self.project_id_edit)
        auth_btn = QPushButton("Initialize Earth Engine")
        auth_btn.clicked.connect(self._on_initialize_ee)
        auth_row.addWidget(auth_btn)
        layout.addLayout(auth_row)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_point_tab(), "Point")
        self.tabs.addTab(self._build_aoi_tab(), "AOI / District")
        self.tabs.addTab(self._build_indices_tab(), "SPI / RAI / PCI")
        self.tabs.addTab(self._build_trends_tab(), "Trends")

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(90)
        layout.addWidget(self.log)

    def _date_edit(self, years_back=10):
        d = QDateEdit()
        d.setCalendarPopup(True)
        d.setDisplayFormat("yyyy-MM-dd")
        d.setDate(QDate.currentDate().addYears(-years_back))
        return d

    # --- Point tab ---------------------------------------------------

    def _build_point_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        pick_row = QHBoxLayout()
        self.point_lon = QDoubleSpinBox()
        self.point_lon.setRange(-180, 180)
        self.point_lon.setDecimals(6)
        self.point_lon.setValue(35.14)  # Chiradzulu-area default
        self.point_lat = QDoubleSpinBox()
        self.point_lat.setRange(-90, 90)
        self.point_lat.setDecimals(6)
        self.point_lat.setValue(-15.70)
        pick_btn = QPushButton("Pick on map")
        pick_btn.clicked.connect(self._start_point_pick)
        pick_row.addWidget(QLabel("Lon:"))
        pick_row.addWidget(self.point_lon)
        pick_row.addWidget(QLabel("Lat:"))
        pick_row.addWidget(self.point_lat)
        pick_row.addWidget(pick_btn)
        form.addRow(pick_row)

        self.point_start = self._date_edit()
        self.point_end = self._date_edit(years_back=0)
        form.addRow("Start date:", self.point_start)
        form.addRow("End date:", self.point_end)

        self.point_freq = QComboBox()
        self.point_freq.addItems(["daily", "monthly", "annual"])
        self.point_freq.setCurrentText("monthly")
        form.addRow("Frequency:", self.point_freq)

        run_btn = QPushButton("Extract point series")
        run_btn.clicked.connect(self._on_extract_point)
        form.addRow(run_btn)

        export_row = QHBoxLayout()
        export_csv_btn = QPushButton("Export CSV")
        export_csv_btn.clicked.connect(self._on_export_point_csv)
        export_chart_btn = QPushButton("Plot & export chart")
        export_chart_btn.clicked.connect(self._on_plot_point_series)
        export_row.addWidget(export_csv_btn)
        export_row.addWidget(export_chart_btn)
        form.addRow(export_row)

        return w

    # --- AOI tab -------------------------------------------------------

    def _build_aoi_tab(self):
        w = QWidget()
        form = QFormLayout(w)

        aoi_row = QHBoxLayout()
        self.aoi_path_edit = QLineEdit()
        self.aoi_path_edit.setPlaceholderText("Path to district/AOI shapefile or GeoPackage layer")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_aoi)
        aoi_row.addWidget(self.aoi_path_edit)
        aoi_row.addWidget(browse_btn)
        form.addRow("AOI layer:", aoi_row)

        self.aoi_start = self._date_edit()
        self.aoi_end = self._date_edit(years_back=0)
        form.addRow("Start date:", self.aoi_start)
        form.addRow("End date:", self.aoi_end)

        self.aoi_freq = QComboBox()
        self.aoi_freq.addItems(["monthly", "annual"])
        form.addRow("Zonal-stats frequency:", self.aoi_freq)

        zonal_btn = QPushButton("Compute zonal statistics")
        zonal_btn.clicked.connect(self._on_zonal_stats)
        form.addRow(zonal_btn)

        export_csv_btn = QPushButton("Export zonal stats CSV")
        export_csv_btn.clicked.connect(self._on_export_aoi_csv)
        form.addRow(export_csv_btn)

        raster_group = QGroupBox("Rainfall raster")
        raster_form = QFormLayout(raster_group)
        self.raster_resolution = QComboBox()
        self.raster_resolution.addItems(list(chirps.RESOLUTION_PRESETS.keys()))
        self.raster_resolution.setCurrentText("1km")
        raster_form.addRow("Resolution:", self.raster_resolution)
        self.raster_statistic = QComboBox()
        self.raster_statistic.addItems(["sum", "mean"])
        raster_form.addRow("Statistic:", self.raster_statistic)
        self.raster_description = QLineEdit("rainfall_export")
        raster_form.addRow("Layer name:", self.raster_description)
        raster_note = QLabel(
            "Note: resolutions finer than 'native' (~5.5 km) are bicubic-\n"
            "resampled, not truer to the source observation density.\n"
            "State this in any figure/methods text that uses them."
        )
        raster_note.setWordWrap(True)
        raster_form.addRow(raster_note)

        add_to_map_btn = QPushButton("Add rainfall layer to QGIS map")
        add_to_map_btn.clicked.connect(self._on_add_raster_to_qgis)
        raster_form.addRow(add_to_map_btn)

        drive_note = QLabel(
            "If the AOI/resolution/date-range combination is too large for "
            "direct download (roughly >32-50 MB), use the Drive fallback "
            "below instead \u2014 it has no size ceiling but runs as an async "
            "task and lands in your Google Drive rather than QGIS directly."
        )
        drive_note.setWordWrap(True)
        raster_form.addRow(drive_note)
        drive_btn = QPushButton("Fallback: export to Google Drive (large AOIs)")
        drive_btn.clicked.connect(self._on_export_raster_to_drive)
        raster_form.addRow(drive_btn)

        form.addRow(raster_group)

        return w

    # --- Indices tab -----------------------------------------------------

    def _build_indices_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        source_group = QGroupBox("Rainfall source for indices")
        source_form = QFormLayout(source_group)
        self.indices_source = QComboBox()
        self.indices_source.addItems(["Last point extraction", "Last AOI zonal stats", "Ground-station CSV"])
        source_form.addRow("Source:", self.indices_source)

        ground_row = QHBoxLayout()
        self.ground_csv_path = QLineEdit()
        ground_browse = QPushButton("Browse...")
        ground_browse.clicked.connect(self._browse_ground_csv)
        ground_row.addWidget(self.ground_csv_path)
        ground_row.addWidget(ground_browse)
        source_form.addRow("Ground CSV:", ground_row)
        layout.addWidget(source_group)

        spi_group = QGroupBox("SPI")
        spi_form = QFormLayout(spi_group)
        self.spi_scale = QComboBox()
        self.spi_scale.addItems(["1", "3", "6", "12", "24"])
        self.spi_scale.setCurrentText("3")
        spi_form.addRow("Accumulation (months):", self.spi_scale)
        spi_btn = QPushButton("Compute & plot SPI")
        spi_btn.clicked.connect(self._on_compute_spi)
        spi_form.addRow(spi_btn)
        layout.addWidget(spi_group)

        rai_btn = QPushButton("Compute & plot RAI (annual)")
        rai_btn.clicked.connect(self._on_compute_rai)
        layout.addWidget(rai_btn)

        pci_btn = QPushButton("Compute & plot PCI (annual)")
        pci_btn.clicked.connect(self._on_compute_pci)
        layout.addWidget(pci_btn)

        compare_btn = QPushButton("Plot CHIRPS vs ground station")
        compare_btn.clicked.connect(self._on_plot_comparison)
        layout.addWidget(compare_btn)

        layout.addStretch()
        return w

    # --- Trends tab -----------------------------------------------------

    def _build_trends_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        self.trend_source = QComboBox()
        self.trend_source.addItems(["Last point extraction", "Last AOI zonal stats", "Ground-station CSV"])
        form.addRow("Source:", self.trend_source)
        layout.addLayout(form)

        run_btn = QPushButton("Run Mann-Kendall + Sen's slope")
        run_btn.clicked.connect(self._on_run_trend)
        layout.addWidget(run_btn)

        ma_row = QHBoxLayout()
        self.ma_window = QComboBox()
        self.ma_window.addItems(["3", "5", "10"])
        ma_btn = QPushButton("Plot moving average")
        ma_btn.clicked.connect(self._on_plot_moving_average)
        ma_row.addWidget(QLabel("Window (years):"))
        ma_row.addWidget(self.ma_window)
        ma_row.addWidget(ma_btn)
        layout.addLayout(ma_row)

        layout.addStretch()
        return w

    # ------------------------------------------------------------ helpers ----

    def _log(self, msg):
        self.log.appendPlainText(str(msg))

    def _get_save_path(self, name_filter, default_name):
        path, _ = QFileDialog.getSaveFileName(self, "Save file", default_name, name_filter)
        return path or None

    def _series_from_source(self, combo, value_col="rainfall_mm"):
        """Resolve the 'Source' combo choices to a monthly pandas.Series."""
        choice = combo.currentText()
        if choice == "Last point extraction":
            if self._last_point_df is None or self._last_point_df.empty:
                raise ValueError("Run a point extraction first.")
            return indices._to_monthly_series(self._last_point_df, "date", "rainfall_mm")
        elif choice == "Last AOI zonal stats":
            if self._last_aoi_df is None or self._last_aoi_df.empty:
                raise ValueError("Run AOI zonal statistics first.")
            return indices._to_monthly_series(self._last_aoi_df, "date", "mean_mm")
        else:
            path = self.ground_csv_path.text().strip()
            if not path:
                raise ValueError("Choose a ground-station CSV first.")
            series = indices.load_ground_station_csv(path)
            self._last_ground_series = series
            return series

    # ------------------------------------------------------------ slots ----

    def _on_initialize_ee(self):
        try:
            authentication.initialize(project_id=self.project_id_edit.text().strip() or None)
            self.status_label.setText("Earth Engine: initialized")
            self._log("Earth Engine initialized successfully.")
        except authentication.EarthEngineError as exc:
            self.status_label.setText("Earth Engine: not initialized")
            QMessageBox.critical(self, "Earth Engine error", str(exc))

    def _start_point_pick(self):
        canvas = self.iface.mapCanvas()
        self._map_tool = QgsMapToolEmitPoint(canvas)
        self._map_tool.canvasClicked.connect(self._on_canvas_clicked)
        canvas.setMapTool(self._map_tool)
        self._log("Click a point on the map canvas...")

    def _on_canvas_clicked(self, point, button):
        canvas = self.iface.mapCanvas()
        canvas_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(canvas_crs, wgs84, QgsProject.instance())
        point_wgs84 = transform.transform(point)
        self.point_lon.setValue(point_wgs84.x())
        self.point_lat.setValue(point_wgs84.y())
        canvas.unsetMapTool(self._map_tool)
        self._log(f"Picked point: {point_wgs84.x():.5f}, {point_wgs84.y():.5f}")

    def _on_extract_point(self):
        try:
            df = chirps.extract_point_series(
                lon=self.point_lon.value(), lat=self.point_lat.value(),
                start_date=self.point_start.date().toString("yyyy-MM-dd"),
                end_date=self.point_end.date().toString("yyyy-MM-dd"),
                freq=self.point_freq.currentText(),
            )
            self._last_point_df = df
            self._log(f"Extracted {len(df)} rows.")
        except Exception as exc:
            QMessageBox.critical(self, "Extraction failed", str(exc))

    def _on_export_point_csv(self):
        if self._last_point_df is None:
            QMessageBox.warning(self, "Nothing to export", "Run a point extraction first.")
            return
        path = self._get_save_path("CSV (*.csv)", "point_rainfall.csv")
        if path:
            self._last_point_df.to_csv(path, index=False)
            self._log(f"Saved {path}")

    def _on_plot_point_series(self):
        if self._last_point_df is None:
            QMessageBox.warning(self, "Nothing to plot", "Run a point extraction first.")
            return
        path = self._get_save_path("PNG (*.png);;SVG (*.svg);;PDF (*.pdf)", "point_rainfall.png")
        if path:
            s = self._last_point_df.set_index("date")["rainfall_mm"]
            graphs.plot_time_series(s, "Point Rainfall", out_path=path)
            self._log(f"Saved chart to {path}")

    def _browse_aoi(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select AOI vector layer", "", "Vector files (*.shp *.gpkg *.geojson)"
        )
        if path:
            self.aoi_path_edit.setText(path)

    def _load_aoi_geometry(self):
        path = self.aoi_path_edit.text().strip()
        if not path or not os.path.exists(path):
            raise ValueError("Select a valid AOI shapefile/GeoPackage first.")
        layer = QgsVectorLayer(path, "aoi", "ogr")
        if not layer.isValid():
            raise ValueError(f"Could not load AOI layer from {path}")

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(layer.crs(), wgs84, QgsProject.instance())

        import ee
        coords_list = []
        for feature in layer.getFeatures():
            geom = feature.geometry()
            geom.transform(transform)
            geojson = geom.asJson()
            import json
            gj = json.loads(geojson)
            coords_list.append(gj)

        if len(coords_list) == 1:
            return ee.Geometry(coords_list[0])
        # Multiple features (e.g. a multi-part district boundary): dissolve
        # them into one geometry so zonal stats/export treat the AOI as a
        # single region rather than needing a loop per feature.
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry(gj)) for gj in coords_list])
        return fc.geometry().dissolve()

    def _on_zonal_stats(self):
        try:
            aoi_geom = self._load_aoi_geometry()
            df = chirps.extract_aoi_zonal_stats(
                aoi_geom,
                start_date=self.aoi_start.date().toString("yyyy-MM-dd"),
                end_date=self.aoi_end.date().toString("yyyy-MM-dd"),
                freq=self.aoi_freq.currentText(),
            )
            self._last_aoi_df = df
            self._log(f"Computed zonal stats for {len(df)} periods.")
        except Exception as exc:
            QMessageBox.critical(self, "Zonal statistics failed", str(exc))

    def _on_export_aoi_csv(self):
        if self._last_aoi_df is None:
            QMessageBox.warning(self, "Nothing to export", "Compute zonal statistics first.")
            return
        path = self._get_save_path("CSV (*.csv)", "aoi_zonal_rainfall.csv")
        if path:
            self._last_aoi_df.to_csv(path, index=False)
            self._log(f"Saved {path}")

    def _on_add_raster_to_qgis(self):
        """Download the AOI rainfall raster, clip it to the exact AOI
        polygon shape (not just its bounding box), and add it straight
        to the QGIS layers panel."""
        try:
            aoi_path = self.aoi_path_edit.text().strip()
            if not aoi_path or not os.path.exists(aoi_path):
                raise ValueError("Select a valid AOI shapefile/GeoPackage first.")
            aoi_geom = self._load_aoi_geometry()
            layer_name = self.raster_description.text().strip() or "rainfall_export"

            # Persist to a stable temp file rather than a throwaway one --
            # QGIS keeps referencing the file on disk for as long as the
            # layer stays in the project, so it must not be deleted.
            tmp_dir = tempfile.gettempdir()
            raw_path = os.path.join(tmp_dir, f"RAM_{layer_name}_raw.tif")
            masked_path = os.path.join(tmp_dir, f"RAM_{layer_name}.tif")

            chirps.export_aoi_raster_to_qgis(
                aoi_geom,
                start_date=self.aoi_start.date().toString("yyyy-MM-dd"),
                end_date=self.aoi_end.date().toString("yyyy-MM-dd"),
                out_path=raw_path,
                resolution=self.raster_resolution.currentText(),
                statistic=self.raster_statistic.currentText(),
            )

            # Earth Engine's own clip() mask doesn't reliably survive the
            # GeoTIFF download as real NoData, which is why the raw file
            # renders as a rectangular box in QGIS -- clip it locally
            # against the ORIGINAL AOI file so the shape is exact.
            raster_mask.clip_raster_to_vector(raw_path, aoi_path, masked_path)

            raster_layer = QgsRasterLayer(masked_path, layer_name)
            if not raster_layer.isValid():
                raise RuntimeError(f"Clipped file is not a valid raster: {masked_path}")
            QgsProject.instance().addMapLayer(raster_layer)
            self.iface.mapCanvas().setExtent(raster_layer.extent())
            self.iface.mapCanvas().refresh()

            self._log(f"Added '{layer_name}' to the map, clipped to the AOI shape (saved at {masked_path}).")
        except Exception as exc:
            QMessageBox.critical(self, "Add raster to QGIS failed", str(exc))

    def _on_export_raster_to_drive(self):
        try:
            aoi_geom = self._load_aoi_geometry()
            task = chirps.export_aoi_raster_to_drive(
                aoi_geom,
                start_date=self.aoi_start.date().toString("yyyy-MM-dd"),
                end_date=self.aoi_end.date().toString("yyyy-MM-dd"),
                description=self.raster_description.text().strip() or "rainfall_export",
                resolution=self.raster_resolution.currentText(),
                statistic=self.raster_statistic.currentText(),
            )
            self._log(
                f"Drive export task started (id={task.id}). Monitor progress at "
                "https://code.earthengine.google.com/tasks -- the GeoTIFF "
                "will appear in your Google Drive when the task completes, "
                "and you can then drag it into QGIS manually."
            )
        except Exception as exc:
            QMessageBox.critical(self, "Drive export failed", str(exc))

    def _browse_ground_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select ground-station CSV", "", "CSV (*.csv)")
        if path:
            self.ground_csv_path.setText(path)

    def _on_compute_spi(self):
        try:
            series = self._series_from_source(self.indices_source)
            spi = indices.compute_spi(series, scale=int(self.spi_scale.currentText()))
            path = self._get_save_path("PNG (*.png);;SVG (*.svg);;PDF (*.pdf)", "spi.png")
            if path:
                graphs.plot_spi(spi, title=f"SPI-{self.spi_scale.currentText()}", out_path=path)
                self._log(f"Saved SPI chart to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "SPI computation failed", str(exc))

    def _on_compute_rai(self):
        try:
            monthly = self._series_from_source(self.indices_source)
            annual = monthly.groupby(monthly.index.year).sum()
            annual.index.name = "year"
            rai, meta = indices.compute_rai(annual)
            path = self._get_save_path("PNG (*.png);;SVG (*.svg);;PDF (*.pdf)", "rai.png")
            if path:
                graphs.plot_rai(rai, out_path=path)
                self._log(f"Saved RAI chart to {path} (n_years={meta['n_years']}, "
                           f"used_fallback_k={meta['used_fallback_k']})")
        except Exception as exc:
            QMessageBox.critical(self, "RAI computation failed", str(exc))

    def _on_compute_pci(self):
        try:
            monthly = self._series_from_source(self.indices_source)
            pci_series, classes = indices.compute_pci(monthly)
            path = self._get_save_path("PNG (*.png);;SVG (*.svg);;PDF (*.pdf)", "pci.png")
            if path:
                graphs.plot_pci(pci_series, out_path=path)
                self._log(f"Saved PCI chart to {path}. Classes: {classes.to_dict()}")
        except Exception as exc:
            QMessageBox.critical(self, "PCI computation failed", str(exc))

    def _on_plot_comparison(self):
        try:
            # explicit sources for comparison: CHIRPS from point/AOI, ground from CSV
            if self._last_point_df is not None and not self._last_point_df.empty:
                chirps_series = indices._to_monthly_series(self._last_point_df, "date", "rainfall_mm")
            elif self._last_aoi_df is not None and not self._last_aoi_df.empty:
                chirps_series = indices._to_monthly_series(self._last_aoi_df, "date", "mean_mm")
            else:
                raise ValueError("Run a point extraction or AOI zonal stats first (as the CHIRPS side).")

            ground_path = self.ground_csv_path.text().strip()
            if not ground_path:
                raise ValueError("Choose a ground-station CSV first.")
            ground_series = indices.load_ground_station_csv(ground_path)

            path = self._get_save_path("PNG (*.png);;SVG (*.svg);;PDF (*.pdf)", "chirps_vs_ground.png")
            if path:
                graphs.plot_ground_vs_chirps(chirps_series, ground_series, out_path=path)
                self._log(f"Saved comparison chart to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Comparison plot failed", str(exc))

    def _on_run_trend(self):
        try:
            monthly = self._series_from_source(self.trend_source)
            annual = monthly.groupby(monthly.index.year).sum()
            mk = trends.mann_kendall_test(annual)
            slope, intercept = trends.sens_slope(annual)
            self._log(
                f"Mann-Kendall: trend={mk['trend']}, p={mk['p']:.4f}, "
                f"tau={mk['tau']:.3f}, S={mk['s']}"
            )
            self._log(f"Sen's slope: {slope:.3f} mm/year")
            path = self._get_save_path("PNG (*.png);;SVG (*.svg);;PDF (*.pdf)", "trend.png")
            if path:
                graphs.plot_trend(annual, slope, intercept, out_path=path)
                self._log(f"Saved trend chart to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Trend analysis failed", str(exc))

    def _on_plot_moving_average(self):
        try:
            monthly = self._series_from_source(self.trend_source)
            annual = monthly.groupby(monthly.index.year).sum()
            ma = trends.moving_average(annual, window=int(self.ma_window.currentText()))
            path = self._get_save_path("PNG (*.png);;SVG (*.svg);;PDF (*.pdf)", "moving_average.png")
            if path:
                graphs.plot_time_series(ma, f"{self.ma_window.currentText()}-year moving average", out_path=path)
                self._log(f"Saved moving-average chart to {path}")
        except Exception as exc:
            QMessageBox.critical(self, "Moving average failed", str(exc))
