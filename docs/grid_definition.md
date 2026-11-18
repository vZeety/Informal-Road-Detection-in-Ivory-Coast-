# Grid definition

- CRS: **EPSG:32630** (WGS 84 / UTM zone 30N).
- Cell size: **256 m × 256 m**. Image and mask: **512 × 512 px at 0.5 m per pixel** (same as DeepGlobe).
- Cell edges are snapped to multiples of 256 m, so cells from different areas always line up and every location has one fixed cell.
- Tile index: `gx = left / 256`, `gy = bottom / 256` (metres in EPSG:32630).
- File name: `<site>_<gx>_<gy>.tif`. Cell extent: `[gx·256, gy·256, (gx+1)·256, (gy+1)·256]`.
- Example: `yaou_1675_2257` covers x 428 800–429 056 m, y 577 792–578 048 m.
- Note: the `site` in file names is the export batch name. The real town is stored in the `town` column of `tiles_log.csv` (some Bonoua tiles were exported under the name `yaou`).
- Masks: 8-bit, 0 = background, 255 = road. Each road line is buffered by a half-width set by its OSM `fclass` (e.g. primary 5 m, residential 3 m, track 2 m, path 1 m; default 2 m), then rasterised.
