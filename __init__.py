"""
RAM - Rainfall Analysis Malawi
QGIS plugin entry point.
"""


def classFactory(iface):
    from .ram_plugin import RAM
    return RAM(iface)
