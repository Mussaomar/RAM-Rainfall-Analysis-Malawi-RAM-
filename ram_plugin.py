import os

from qgis.PyQt.QtWidgets import QAction
from qgis.PyQt.QtGui import QIcon


class RAM:
    """RAM - Rainfall Analysis Malawi. QGIS plugin implementation."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu = "&RAM - Rainfall Analysis Malawi"
        self.dialog = None

    def initGui(self):
        icon_path = os.path.join(self.plugin_dir, "resources", "icon.png")
        action = QAction(QIcon(icon_path), "RAM - Rainfall Analysis Malawi", self.iface.mainWindow())
        action.triggered.connect(self.run)
        self.iface.addToolBarIcon(action)
        self.iface.addPluginToMenu(self.menu, action)
        self.actions.append(action)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu, action)
            self.iface.removeToolBarIcon(action)

    def run(self):
        # Imported lazily so a missing earthengine-api / matplotlib
        # install doesn't break QGIS startup (initGui above stays
        # dependency-free); the error surfaces only when the user
        # actually opens the dialog, with a clear message.
        try:
            from .ui.main_dialog import RamDialog
        except ImportError as exc:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(
                self.iface.mainWindow(), "Missing dependency",
                "Could not load the RAM (Rainfall Analysis Malawi) dialog:\n"
                f"{exc}\n\n"
                "Install missing packages into QGIS's Python environment, "
                "e.g. via the OSGeo4W shell:\n"
                "  python -m pip install earthengine-api pandas scipy matplotlib"
            )
            return

        if self.dialog is None:
            self.dialog = RamDialog(self.iface)
        self.dialog.show()
