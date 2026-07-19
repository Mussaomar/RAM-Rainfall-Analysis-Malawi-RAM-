"""
Google Earth Engine authentication for the plugin.

QGIS ships its own Python interpreter, so `earthengine-authenticate`
run from a normal terminal will not necessarily register credentials
for QGIS's interpreter. This module handles both the one-time
interactive OAuth flow and silent re-use of a cached token, and
gives the calling UI code a plain-English error message instead of
a raw traceback when something goes wrong.
"""

import os
import traceback

try:
    import ee
except ImportError:
    ee = None


class EarthEngineError(Exception):
    pass


def is_ee_available():
    """True if the `earthengine-api` package is importable in this environment."""
    return ee is not None


def initialize(project_id=None, service_account_json=None):
    """
    Initialize an Earth Engine session.

    project_id: your GEE-linked Google Cloud project ID (required for
        newer EE accounts created after the 2022 Cloud migration).
    service_account_json: optional path to a service account key file,
        for headless/unattended use (e.g. batch export jobs). If not
        given, falls back to the interactive user OAuth flow, prompting
        once and caching the token under ~/.config/earthengine.

    Raises EarthEngineError with a readable message on failure.
    """
    if ee is None:
        raise EarthEngineError(
            "The 'earthengine-api' package is not installed in QGIS's Python "
            "environment. Install it with the OSGeo4W/QGIS Python shell:\n"
            "  python -m pip install earthengine-api"
        )

    try:
        if service_account_json:
            if not os.path.isfile(service_account_json):
                raise EarthEngineError(
                    f"Service account key not found at: {service_account_json}"
                )
            with open(service_account_json, "r", encoding="utf-8") as fh:
                import json
                key_data = json.load(fh)
            service_account_email = key_data.get("client_email")
            credentials = ee.ServiceAccountCredentials(
                service_account_email, service_account_json
            )
            ee.Initialize(credentials, project=project_id)
        else:
            try:
                ee.Initialize(project=project_id)
            except Exception:
                # No cached credentials (or they expired) -> run interactive flow.
                ee.Authenticate()
                ee.Initialize(project=project_id)
    except EarthEngineError:
        raise
    except Exception as exc:
        raise EarthEngineError(
            "Earth Engine initialization failed: "
            f"{exc}\n\n{traceback.format_exc(limit=2)}"
        ) from exc

    return True


def is_initialized():
    """Cheap check: does a trivial EE call succeed."""
    if ee is None:
        return False
    try:
        ee.Number(1).getInfo()
        return True
    except Exception:
        return False
