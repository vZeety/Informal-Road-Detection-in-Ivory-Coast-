"""
road_tiles.py - grid-based satellite image / road mask generator for QGIS
==========================================================================

What it does
------------
Adds a "Road Tiles" toolbar to QGIS with these buttons:

  1 Grid here       Creates 256 m grid cells over the current map view (or over
                    selected polygons in the active layer). Cells snap to
                    multiples of 256 m in EPSG:32630, so every cell has a
                    permanent location-based ID. It also copies the OSM roads
                    for that area into one editable layer: "roads_edit".
  2 Export selected For every selected cell: downloads the basemap image
                    (512 x 512 px at 0.5 m) and makes its road mask from
                    "roads_edit". Images that already exist are not downloaded
                    again.
  3 Rebuild masks   Remakes only the masks of the selected cells. Use it after
                    correcting or adding roads in "roads_edit". No downloading.
  Reviewed / Test / Auto
                    Set the status (and colour) of the selected cells.

Grid colours: red outline = new, yellow = auto-generated, green = reviewed,
blue = test set, grey = failed download.

How to run
----------
QGIS > Plugins > Python Console > "Show Editor" (notepad icon) > Open this
file > Run (green arrow). The toolbar appears. Run it again after editing the
settings below.

Files written (in DATA_DIR)
---------------------------
  images/<site>_<gx>_<gy>.tif   RGB GeoTIFF, EPSG:32630, 0.5 m, 512 x 512
  masks/<site>_<gx>_<gy>.tif    Byte GeoTIFF, 0 = background, 255 = road
  tile_grid.gpkg                grid cells with tile_id, site, status, road_pct, img_date
  roads_edit.gpkg               editable road lines (OSM copy + your corrections)
  tiles_log.csv                 one row per cell (for the paper / reproducibility)

gx = left edge / 256 and gy = bottom edge / 256, in EPSG:32630 metres.
"""

import os
import math
import time
import csv
import datetime
import tempfile
import traceback

from qgis.core import (
    Qgis, NULL, QgsProject, QgsVectorLayer, QgsFields, QgsField, QgsFeature,
    QgsGeometry, QgsRectangle, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsVectorFileWriter, QgsWkbTypes,
    QgsFeatureRequest, QgsMapSettings, QgsMapRendererSequentialJob,
    QgsDefaultValue, QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsFillSymbol, QgsLineSymbol, QgsSingleSymbolRenderer, QgsMapLayer,
)
from qgis.PyQt.QtCore import QVariant, QSize, QEventLoop, QCoreApplication, Qt
from qgis.PyQt.QtGui import QImage, QColor
from qgis.PyQt.QtWidgets import (QAction, QInputDialog, QMessageBox, QProgressDialog,
                                 QToolBar)
from qgis.gui import QgsMapToolExtent
from qgis.utils import iface
from osgeo import gdal, ogr, osr


# --- Qt5 / Qt6 compatibility (newer QGIS builds use scoped enum names) ---
def _enum(obj, old, new_path):
    if hasattr(obj, old):
        return getattr(obj, old)
    value = obj
    for part in new_path.split("."):
        value = getattr(value, part)
    return value


YES = _enum(QMessageBox, "Yes", "StandardButton.Yes")
RGB888 = _enum(QImage, "Format_RGB888", "Format.Format_RGB888")
WINDOW_MODAL = _enum(Qt, "WindowModal", "WindowModality.WindowModal")
POLYGON_GEOM = (QgsWkbTypes.PolygonGeometry if hasattr(QgsWkbTypes, "PolygonGeometry")
                else Qgis.GeometryType.Polygon)

# ===================== SETTINGS (edit these) =====================

# Where images, masks, the grid and the editable roads are stored.
# Keep this OUTSIDE your GitHub repo: raw imagery must not be published.
DATA_DIR = r"D:\Informal Road Detection\dataset"

BASEMAP_LAYER = "Google Satellite"          # layer name in the Layers panel
SOURCE_ROADS_LAYER = "gis_osm_roads_free_1"  # Geofabrik OSM roads layer name

CELL = 256.0      # cell size in metres
RES = 0.5         # metres per pixel (matches DeepGlobe)
EPSG = 32630      # WGS 84 / UTM zone 30N
PAUSE = 0.4       # seconds between image downloads (be polite to the server)
MAX_CELLS = 300   # asks for confirmation above this many cells

# Half road width in metres (buffer distance) per OSM "fclass".
# A road with an empty / unknown fclass gets DEFAULT_HALF_WIDTH.
HALF_WIDTH = {
    "motorway": 7, "motorway_link": 4, "trunk": 6, "trunk_link": 4,
    "primary": 5, "primary_link": 3.5, "secondary": 4.5, "secondary_link": 3.5,
    "tertiary": 4, "tertiary_link": 3, "unclassified": 3, "residential": 3,
    "living_street": 3, "service": 2.5, "pedestrian": 2,
    "track": 2, "track_grade1": 2.5, "track_grade2": 2, "track_grade3": 2,
    "track_grade4": 1.5, "track_grade5": 1.5,
    "path": 1, "footway": 1, "cycleway": 1, "bridleway": 1, "steps": 1,
}
DEFAULT_HALF_WIDTH = 2.0

# ==================================================================

PX = int(round(CELL / RES))  # 512
CRS = QgsCoordinateReferenceSystem("EPSG:%d" % EPSG)
IMG_DIR = os.path.join(DATA_DIR, "images")
MASK_DIR = os.path.join(DATA_DIR, "masks")
GRID_PATH = os.path.join(DATA_DIR, "tile_grid.gpkg")
ROADS_PATH = os.path.join(DATA_DIR, "roads_edit.gpkg")
LOG_PATH = os.path.join(DATA_DIR, "tiles_log.csv")
LABEL_LOG_PATH = os.path.join(DATA_DIR, "labeling_log.csv")
IMAGERY_SOURCE = "Google Satellite basemap (XYZ tiles, mt1.google.com lyrs=s), exported in QGIS"
_TIMERS = {}   # tile_id -> start time of the labeling timer
GRID_NAME = "tile_grid"
ROADS_NAME = "roads_edit"

STATUS_STYLE = {          # status: (fill colour, fill alpha 0-255, outline colour)
    "new": ("#ffffff", 0, "#ff3333"),
    "auto": ("#ffd400", 90, "#e0a800"),
    "reviewed": ("#33cc33", 90, "#1e8a1e"),
    "test": ("#3388ff", 90, "#1f5fbf"),
    "val": ("#b04fd6", 90, "#7a2a9c"),
    "failed": ("#888888", 110, "#555555"),
}


# ---------------------------------------------------------------- helpers

def _msg(text, level=Qgis.Info, duration=8):
    iface.messageBar().pushMessage("Road Tiles", text, level=level, duration=duration)


def _layer(name):
    found = QgsProject.instance().mapLayersByName(name)
    return found[0] if found else None


def _xf(src, dst):
    return QgsCoordinateTransform(src, dst, QgsProject.instance())


def _txt(value, default=""):
    if value is None or value == NULL:
        return default
    return str(value)


def _cell_rect(gx, gy):
    return QgsRectangle(gx * CELL, gy * CELL, (gx + 1) * CELL, (gy + 1) * CELL)


def _create_gpkg(path, name, fields, geom_type):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = name
    writer = QgsVectorFileWriter.create(
        path, fields, geom_type, CRS,
        QgsProject.instance().transformContext(), opts)
    if writer.hasError() != QgsVectorFileWriter.NoError:
        raise RuntimeError("Could not create %s: %s" % (path, writer.errorMessage()))
    del writer  # flushes the file


def _style_grid(layer):
    cats = []
    for status, (fill, alpha, line) in STATUS_STYLE.items():
        c = QColor(fill)
        props = {
            "color": "%d,%d,%d,%d" % (c.red(), c.green(), c.blue(), alpha),
            "outline_color": line,
            "outline_width": "0.6",
        }
        if alpha == 0:
            props["style"] = "no"
        cats.append(QgsRendererCategory(status, QgsFillSymbol.createSimple(props), status))
    layer.setRenderer(QgsCategorizedSymbolRenderer("status", cats))
    layer.triggerRepaint()


def _grid_layer(create=True):
    layer = _layer(GRID_NAME)
    if layer:
        return layer
    if not os.path.exists(GRID_PATH):
        if not create:
            return None
        fields = QgsFields()
        for name, ftype in [("tile_id", QVariant.String), ("gx", QVariant.Int),
                            ("gy", QVariant.Int), ("site", QVariant.String),
                            ("status", QVariant.String), ("road_pct", QVariant.Double),
                            ("img_date", QVariant.String)]:
            fields.append(QgsField(name, ftype))
        _create_gpkg(GRID_PATH, GRID_NAME, fields, QgsWkbTypes.Polygon)
    layer = QgsVectorLayer("%s|layername=%s" % (GRID_PATH, GRID_NAME), GRID_NAME, "ogr")
    if not layer.isValid():
        raise RuntimeError("Could not open " + GRID_PATH)
    QgsProject.instance().addMapLayer(layer)
    _style_grid(layer)
    return layer


def _roads_layer(create=True):
    layer = _layer(ROADS_NAME)
    if layer:
        return layer
    if not os.path.exists(ROADS_PATH):
        if not create:
            return None
        fields = QgsFields()
        for name in ("osm_id", "fclass", "name", "source"):
            fields.append(QgsField(name, QVariant.String))
        _create_gpkg(ROADS_PATH, ROADS_NAME, fields, QgsWkbTypes.MultiLineString)
    layer = QgsVectorLayer("%s|layername=%s" % (ROADS_PATH, ROADS_NAME), ROADS_NAME, "ogr")
    if not layer.isValid():
        raise RuntimeError("Could not open " + ROADS_PATH)
    idx = layer.fields().indexOf("source")
    if idx >= 0:  # roads you draw yourself are tagged "manual"
        layer.setDefaultValueDefinition(idx, QgsDefaultValue("'manual'"))
    layer.setRenderer(QgsSingleSymbolRenderer(
        QgsLineSymbol.createSimple({"line_color": "#ffff00", "line_width": "0.8"})))
    QgsProject.instance().addMapLayer(layer)
    return layer


def _selected_cells():
    grid = _grid_layer(create=False)
    if grid is None:
        _msg("No tile_grid yet. Use '1 Grid here' first.", Qgis.Warning)
        return None, []
    if grid.isEditable():
        _msg("tile_grid is in edit mode. Save and stop editing it first.", Qgis.Warning)
        return grid, []
    cells = grid.selectedFeatures()
    if not cells:
        iface.setActiveLayer(grid)
        _msg("Select cells on 'tile_grid' with the Select Features tool, then click again.",
             Qgis.Warning)
    return grid, cells


def _set_attrs(grid, updates):
    """updates = {feature_id: {field_name: value}}"""
    names = grid.fields().names()
    changes = {fid: {names.index(k): v for k, v in vals.items()}
               for fid, vals in updates.items()}
    if changes:
        grid.dataProvider().changeAttributeValues(changes)
        grid.triggerRepaint()


def _write_log(grid):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_PATH, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tile_id", "site", "town", "gx", "gy", "status", "road_pct", "img_date",
                    "left", "bottom", "right", "top", "crs", "resolution_m", "size_px",
                    "imagery_source", "acquisition_date", "image", "mask"])
        has_town = "town" in grid.fields().names()
        for f in grid.getFeatures():
            gx, gy, site = int(f["gx"]), int(f["gy"]), _txt(f["site"], "site")
            name = "%s_%d_%d.tif" % (site, gx, gy)
            town = _txt(f["town"], site) if has_town else site
            w.writerow([_txt(f["tile_id"]), site, town or site, gx, gy, _txt(f["status"]),
                        _txt(f["road_pct"]), _txt(f["img_date"]),
                        gx * CELL, gy * CELL, (gx + 1) * CELL, (gy + 1) * CELL,
                        "EPSG:%d" % EPSG, RES, PX, IMAGERY_SOURCE, "unknown",
                        "images/" + name, "masks/" + name])


# ---------------------------------------------------------------- core steps

def _area():
    """Area to grid, in EPSG:32630: selected polygons of the active layer if any,
    otherwise the current map view. Returns (rectangle, polygon or None)."""
    active = iface.activeLayer()
    if (active is not None and isinstance(active, QgsVectorLayer)
            and active.name() != GRID_NAME
            and active.geometryType() == POLYGON_GEOM
            and active.selectedFeatureCount() > 0):
        to32 = _xf(active.crs(), CRS)
        geoms = []
        for f in active.selectedFeatures():
            g = QgsGeometry(f.geometry())
            g.transform(to32)
            geoms.append(g)
        zone = QgsGeometry.unaryUnion(geoms)
        return zone.boundingBox(), zone
    canvas = iface.mapCanvas()
    to32 = _xf(canvas.mapSettings().destinationCrs(), CRS)
    return to32.transformBoundingBox(canvas.extent()), None


_drag = {"tool": None, "previous": None}


def start_grid_drag():
    """Button 1: drag a box on the map; the grid is created over that box."""
    canvas = iface.mapCanvas()
    _drag["previous"] = canvas.mapTool()
    tool = QgsMapToolExtent(canvas)
    tool.extentChanged.connect(_on_drag_finished)
    _drag["tool"] = tool          # keep a reference so it is not garbage-collected
    canvas.setMapTool(tool)
    _msg("Click and drag a box on the map over the area you want to grid.", Qgis.Info, 10)


def _on_drag_finished(rect):
    canvas = iface.mapCanvas()
    if _drag["previous"] is not None:
        canvas.setMapTool(_drag["previous"])
    else:
        canvas.unsetMapTool(_drag["tool"])
    if rect is None or rect.isEmpty() or rect.width() <= 0:
        _msg("No box drawn. Click '1 Draw grid area' and drag a box.", Qgis.Warning)
        return
    box = _xf(canvas.mapSettings().destinationCrs(), CRS).transformBoundingBox(rect)
    _safe(lambda: make_grid(box))


def make_grid(box=None):
    """box = rectangle in EPSG:32630 from a drag; None = current view / selected polygons."""
    site, ok = QInputDialog.getText(iface.mainWindow(), "Road Tiles",
                                    "Site / area name for these cells (e.g. yaou):")
    if not ok or not site.strip():
        return
    site = site.strip().lower().replace(" ", "_")

    rect, zone = (box, None) if box is not None else _area()
    gx0, gy0 = int(math.floor(rect.xMinimum() / CELL)), int(math.floor(rect.yMinimum() / CELL))
    gx1, gy1 = int(math.ceil(rect.xMaximum() / CELL)), int(math.ceil(rect.yMaximum() / CELL))
    candidates = [(gx, gy) for gx in range(gx0, gx1) for gy in range(gy0, gy1)
                  if zone is None or zone.intersects(QgsGeometry.fromRect(_cell_rect(gx, gy)))]
    if not candidates:
        _msg("No cells in this area.", Qgis.Warning)
        return
    if len(candidates) > MAX_CELLS:
        answer = QMessageBox.question(
            iface.mainWindow(), "Road Tiles",
            "This creates %d cells (%.1f km2). Zoom in for a smaller area?\n\n"
            "Yes = create them anyway, No = cancel." % (len(candidates),
                                                        len(candidates) * CELL * CELL / 1e6))
        if answer != YES:
            return

    grid = _grid_layer()
    if grid.isEditable():
        _msg("tile_grid is in edit mode. Save and stop editing it first.", Qgis.Warning)
        return
    existing = {_txt(f["tile_id"]) for f in grid.getFeatures()}
    feats = []
    for gx, gy in candidates:
        tile_id = "%d_%d" % (gx, gy)
        if tile_id in existing:
            continue
        f = QgsFeature(grid.fields())
        f.setGeometry(QgsGeometry.fromRect(_cell_rect(gx, gy)))
        f["tile_id"], f["gx"], f["gy"] = tile_id, gx, gy
        f["site"], f["status"] = site, "new"
        feats.append(f)
    if feats:
        grid.dataProvider().addFeatures(feats)
        grid.updateExtents()
        grid.triggerRepaint()

    area = QgsRectangle(gx0 * CELL, gy0 * CELL, gx1 * CELL, gy1 * CELL)
    copied = _copy_roads(area)
    _write_log(grid)
    _msg("%d new cells for '%s' (%d already existed). %s OSM roads copied into roads_edit."
         % (len(feats), site, len(candidates) - len(feats),
            "No" if copied is None else copied), Qgis.Success)


def _copy_roads(rect):
    """Copy OSM roads inside rect (EPSG:32630) into roads_edit, once per osm_id."""
    src = _layer(SOURCE_ROADS_LAYER)
    if src is None:
        _msg("OSM layer '%s' not found; roads_edit not filled." % SOURCE_ROADS_LAYER,
             Qgis.Warning)
        return None
    roads = _roads_layer()
    if roads.isEditable():
        _msg("roads_edit is in edit mode; save it and run '1 Grid here' again "
             "to copy the OSM roads for this area.", Qgis.Warning)
        return None
    have = {_txt(f["osm_id"]) for f in roads.getFeatures()} - {""}
    names = src.fields().names()
    to_src, to32 = _xf(CRS, src.crs()), _xf(src.crs(), CRS)
    area = QgsGeometry.fromRect(rect)
    new = []
    for f in src.getFeatures(QgsFeatureRequest().setFilterRect(to_src.transformBoundingBox(rect))):
        oid = _txt(f["osm_id"]) if "osm_id" in names else ""
        if oid and oid in have:
            continue
        g = QgsGeometry(f.geometry())
        if g.isEmpty():
            continue
        g.transform(to32)
        if not g.intersects(area):
            continue
        g.convertToMultiType()
        nf = QgsFeature(roads.fields())
        nf.setGeometry(g)
        nf["osm_id"] = oid
        nf["fclass"] = _txt(f["fclass"]) if "fclass" in names else ""
        nf["name"] = _txt(f["name"]) if "name" in names else ""
        nf["source"] = "osm"
        new.append(nf)
        if oid:
            have.add(oid)
    if new:
        roads.dataProvider().addFeatures(new)
        roads.updateExtents()
        roads.triggerRepaint()
    return len(new)


def _render_image(basemap, rect, path):
    """Render the basemap for one cell into a georeferenced 512 x 512 GeoTIFF."""
    ms = QgsMapSettings()
    ms.setLayers([basemap])
    ms.setDestinationCrs(CRS)
    ms.setTransformContext(QgsProject.instance().transformContext())
    ms.setOutputSize(QSize(PX, PX))
    ms.setOutputDpi(96)
    ms.setExtent(rect)
    ms.setBackgroundColor(QColor(0, 0, 0))
    job = QgsMapRendererSequentialJob(ms)
    loop = QEventLoop()
    job.finished.connect(loop.quit)
    job.start()
    (loop.exec_ if hasattr(loop, "exec_") else loop.exec)()
    img = job.renderedImage().convertToFormat(RGB888)
    if img.width() != PX or img.height() != PX:
        return False
    tmp = os.path.join(tempfile.gettempdir(), "road_tiles_tmp.png")
    img.save(tmp, "PNG")
    gdal.Translate(path, tmp, format="GTiff", outputSRS="EPSG:%d" % EPSG,
                   outputBounds=[rect.xMinimum(), rect.yMaximum(),
                                 rect.xMaximum(), rect.yMinimum()],
                   bandList=[1, 2, 3], creationOptions=["COMPRESS=DEFLATE"])
    ds = gdal.Open(path)
    arr = ds.ReadAsArray() if ds is not None else None
    ds = None
    if arr is None or float(arr.std()) < 4.0:   # blank or failed download
        try:
            os.remove(path)
        except OSError:
            pass
        return False
    return True


def _make_mask(roads, rect, path):
    """Buffer road lines by road type and burn them into a Byte mask (0 / 255).
    Returns the percentage of road pixels."""
    to32, to_roads = _xf(roads.crs(), CRS), _xf(CRS, roads.crs())
    cell = QgsGeometry.fromRect(rect)
    names = roads.fields().names()
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(EPSG)
    drv = ogr.GetDriverByName("Memory") or ogr.GetDriverByName("MEM")
    mem = drv.CreateDataSource("mask")
    mlayer = mem.CreateLayer("roads", srs, ogr.wkbUnknown)
    count = 0
    request = QgsFeatureRequest().setFilterRect(to_roads.transformBoundingBox(rect))
    for f in roads.getFeatures(request):   # includes unsaved edits
        g = QgsGeometry(f.geometry())
        if g.isEmpty():
            continue
        g.transform(to32)
        fclass = _txt(f["fclass"]).lower() if "fclass" in names else ""
        buf = g.buffer(HALF_WIDTH.get(fclass, DEFAULT_HALF_WIDTH), 8).intersection(cell)
        if buf.isEmpty():
            continue
        of = ogr.Feature(mlayer.GetLayerDefn())
        of.SetGeometry(ogr.CreateGeometryFromWkb(bytes(buf.asWkb())))
        mlayer.CreateFeature(of)
        count += 1
    ds = gdal.GetDriverByName("GTiff").Create(path, PX, PX, 1, gdal.GDT_Byte,
                                              options=["COMPRESS=DEFLATE"])
    ds.SetGeoTransform((rect.xMinimum(), RES, 0, rect.yMaximum(), 0, -RES))
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.Fill(0)
    if count:
        gdal.RasterizeLayer(ds, [1], mlayer, burn_values=[255])
    pct = float((band.ReadAsArray() > 0).mean() * 100.0)
    ds.FlushCache()
    ds, mem = None, None
    return round(pct, 2)


def _cells_in_view(grid, statuses):
    """Cells of tile_grid visible on screen whose status is in `statuses`."""
    canvas = iface.mapCanvas()
    view = _xf(canvas.mapSettings().destinationCrs(), grid.crs()).transformBoundingBox(
        canvas.extent())
    return [f for f in grid.getFeatures(QgsFeatureRequest().setFilterRect(view))
            if _txt(f["status"]) in statuses]


def export_selected(images=True):
    grid = _grid_layer(create=False)
    if grid is not None and not grid.isEditable() and grid.selectedFeatureCount() == 0:
        statuses = ("new", "failed") if images else ("auto", "reviewed", "test")
        visible = _cells_in_view(grid, statuses)
        if not visible:
            _msg("No cells selected and no %s cells on screen." % "/".join(statuses),
                 Qgis.Warning)
            return
        answer = QMessageBox.question(
            iface.mainWindow(), "Road Tiles",
            "No cells selected.\nUse all %d %s cells visible on screen?"
            % (len(visible), "/".join(statuses)))
        if answer != YES:
            return
        grid.selectByIds([f.id() for f in visible])
    grid, cells = _selected_cells()
    if not cells:
        return
    roads = _roads_layer(create=False)
    if roads is None:
        _msg("No roads_edit layer. Use '1 Grid here' first.", Qgis.Warning)
        return
    basemap = _layer(BASEMAP_LAYER) if images else None
    if images and basemap is None:
        _msg("Basemap layer '%s' not found in the Layers panel." % BASEMAP_LAYER,
             Qgis.Critical)
        return
    os.makedirs(IMG_DIR, exist_ok=True)
    os.makedirs(MASK_DIR, exist_ok=True)

    def name_of(f):
        return "%s_%d_%d.tif" % (_txt(f["site"], "site"), int(f["gx"]), int(f["gy"]))

    to_download = [f for f in cells if not os.path.exists(os.path.join(IMG_DIR, name_of(f)))] \
        if images else []
    if images:
        answer = QMessageBox.question(
            iface.mainWindow(), "Road Tiles",
            "%d cells selected: %d images to download, %d already on disk.\n"
            "Masks will be (re)made for all %d. Continue?"
            % (len(cells), len(to_download), len(cells) - len(to_download), len(cells)))
        if answer != YES:
            return

    progress = QProgressDialog("Making tiles...", "Cancel", 0, len(cells), iface.mainWindow())
    progress.setWindowModality(WINDOW_MODAL)
    progress.setMinimumDuration(0)
    today = datetime.date.today().isoformat()
    updates, done, failed = {}, 0, 0
    for i, f in enumerate(cells):
        if progress.wasCanceled():
            break
        progress.setValue(i)
        progress.setLabelText("Cell %d / %d  (%s)" % (i + 1, len(cells), name_of(f)))
        QCoreApplication.processEvents()

        rect = _cell_rect(int(f["gx"]), int(f["gy"]))
        name = name_of(f)
        img_path = os.path.join(IMG_DIR, name)
        vals = {}
        if images and not os.path.exists(img_path):
            ok = _render_image(basemap, rect, img_path)
            if not ok:                      # one retry after a short wait
                time.sleep(2)
                ok = _render_image(basemap, rect, img_path)
            time.sleep(PAUSE)
            if not ok:
                updates[f.id()] = {"status": "failed"}
                failed += 1
                continue
            vals["img_date"] = today
        vals["road_pct"] = _make_mask(roads, rect, os.path.join(MASK_DIR, name))
        if _txt(f["status"]) not in ("reviewed", "test", "val"):
            vals["status"] = "auto"
        updates[f.id()] = vals
        done += 1
    progress.setValue(len(cells))

    _set_attrs(grid, updates)
    _write_log(grid)
    what = "image + mask" if images else "mask"
    level = Qgis.Success if failed == 0 else Qgis.Warning
    _msg("%d cells done (%s). %d failed (grey) - select them and try again later."
         % (done, what, failed), level, 12)


def mark_selected(status):
    grid, cells = _selected_cells()
    if not cells:
        return
    _set_attrs(grid, {f.id(): {"status": status} for f in cells})
    _write_log(grid)
    timed = _log_label_time(cells, status) if status in ("reviewed", "test", "val") else []
    extra = " Labeling time logged: %s." % ", ".join(timed) if timed else ""
    _msg("%d cells marked '%s'.%s" % (len(cells), status, extra), Qgis.Success)


def start_timer():
    """Start the labeling timer for the selected cells."""
    grid, cells = _selected_cells()
    if not cells:
        return
    now = datetime.datetime.now()
    for f in cells:
        _TIMERS[_txt(f["tile_id"])] = now
    _msg("Timer started for %d cell(s) at %s. Correct the roads, then mark them "
         "Test / Val / Reviewed to log the time." % (len(cells), now.strftime("%H:%M")),
         Qgis.Info, 10)


def _log_label_time(cells, status):
    """Append one row per timed cell to labeling_log.csv. Returns 'id: N min' strings."""
    now = datetime.datetime.now()
    rows, out = [], []
    for f in cells:
        tid = _txt(f["tile_id"])
        start = _TIMERS.pop(tid, None)
        if start is None:
            continue
        minutes = round((now - start).total_seconds() / 60.0 / max(1, len(cells)), 1)
        rows.append([tid, _txt(f["site"]), status, start.isoformat(timespec="seconds"),
                     now.isoformat(timespec="seconds"), minutes])
        out.append("%s %.1f min" % (tid, minutes))
    if rows:
        new = not os.path.exists(LABEL_LOG_PATH)
        with open(LABEL_LOG_PATH, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["tile_id", "site", "status", "start", "end", "minutes"])
            w.writerows(rows)
    return out


def set_town():
    """Record the real town of the selected cells (file names stay unchanged)."""
    grid, cells = _selected_cells()
    if not cells:
        return
    town, ok = QInputDialog.getText(iface.mainWindow(), "Town",
                                    "Town for the %d selected cell(s), e.g. bonoua or yaou:"
                                    % len(cells))
    town = town.strip().lower().replace(" ", "_").replace("/", "_")
    if not ok or not town:
        return
    if "town" not in grid.fields().names():
        grid.dataProvider().addAttributes([QgsField("town", QVariant.String)])
        grid.updateFields()
    _set_attrs(grid, {f.id(): {"town": town} for f in cells})
    _write_log(grid)
    _msg("%d cells set to town '%s'." % (len(cells), town), Qgis.Success)


# ---------------------------------------------------------------- toolbar

def _safe(fn):
    try:
        fn()
    except Exception:
        QMessageBox.critical(iface.mainWindow(), "Road Tiles error", traceback.format_exc())


def install_toolbar():
    mw = iface.mainWindow()
    for old in mw.findChildren(QToolBar, "RoadTilesToolbar"):  # remove earlier copies
        mw.removeToolBar(old)
        old.deleteLater()
    tb = QToolBar("Road Tiles", mw)
    tb.setObjectName("RoadTilesToolbar")
    mw.addToolBarBreak()          # put it on its own row so it is always visible
    mw.addToolBar(tb)
    buttons = [
        ("1 Draw grid area", "Drag a box on the map: creates 256 m cells over it "
                             "and copies OSM roads into roads_edit", start_grid_drag),
        ("Grid view", "Create cells over the whole map view (or selected polygons)",
         lambda: make_grid()),
        ("2 Export selected", "Download image + make mask for the selected cells",
         lambda: export_selected(images=True)),
        ("3 Rebuild masks", "Remake masks of selected cells from roads_edit (no download)",
         lambda: export_selected(images=False)),
        ("Reviewed", "Mark selected cells as reviewed (green)",
         lambda: mark_selected("reviewed")),
        ("Test", "Mark selected cells as test set (blue)", lambda: mark_selected("test")),
        ("Val", "Mark selected cells as validation set (purple)", lambda: mark_selected("val")),
        ("Start timer", "Start the labeling timer for the selected cells", start_timer),
        ("Set town", "Record the real town of the selected cells (e.g. bonoua)", set_town),
        ("Auto", "Mark selected cells back to auto (yellow)", lambda: mark_selected("auto")),
    ]
    for text, tip, fn in buttons:
        action = QAction(text, mw)
        action.setToolTip(tip)
        action.triggered.connect(lambda checked=False, fn=fn: _safe(fn))
        tb.addAction(action)
    tb.show()
    # reload existing layers if they are already on disk
    if os.path.exists(GRID_PATH):
        _grid_layer(create=False)
    if os.path.exists(ROADS_PATH):
        _roads_layer(create=False)
    _msg("Toolbar ready. Data folder: %s" % DATA_DIR, Qgis.Success)


install_toolbar()
