# Annotation guidelines

**Labeller:** all labels were drawn by one person, Thierno Barry, who has local knowledge of the area.
**Tool:** QGIS, editing the `roads_edit` line layer over the Google Satellite basemap at about 1:1 000–1:2 000, then rebuilding masks with `road_tiles.py`.

## What counts as a road
A road is any track that a **car or a motorcycle** can use.
- **Car-accessible dirt road:** `fclass = track` (mask about 4 m wide).
- **Motorcycle-only path:** `fclass = path` (mask about 2 m wide). Included only if it is clearly worn, continuous, at least about 1.5 m wide (3 pixels), and connects two roads or a road to houses.
- **Not a road:** foot-only paths, faint trails across fields, field boundaries and hedges, open yards and cleared lots, plot outlines, dry stream beds.

## How lines are drawn
- Lines follow the **centre of the visible road surface**. A line that stays on the road surface is accepted; a line that leaves it is moved.
- Width is set by road type (see `grid_definition.md`), not drawn by hand.
- **Wide dirt junctions and open dirt areas:** only the driven track through the area is drawn, as a centre line; the open area itself is not labelled as road.
- **Tree cover:** a road is drawn through cover when it clearly continues on both sides and the hidden gap is about 30 m or less.
- New lines start and end on existing roads so the network stays connected.
- **When in doubt, the track is not drawn.** Consistency matters more than catching every faint path.

## Corrections to OSM
Every OSM line in a corrected tile is checked against the imagery:
1. **Missing:** a visible road with no OSM line is drawn.
2. **Misplaced:** an OSM line off the road surface is moved onto it.
3. **Phantom:** an OSM line with no road under it is deleted (or split and partly deleted).
4. **Wrong type:** `fclass` is changed so the mask width matches the road.

## Guarding against OSM anchoring
Starting from OSM makes roads already in OSM more likely to survive into the labels. To limit this, each corrected tile is first **scanned with the OSM layer hidden**, looking for every road visible in the image, before the OSM lines are compared and fixed.

## Tile roles
- **Test** (blue): fully corrected, Bonoua only, never used for training.
- **Val** (purple): fully corrected, a separate Yaou strip, used only to choose the epoch and threshold.
- **Reviewed** (green): fully corrected training tiles (Yaou).
- **Auto** (yellow): raw OSM labels, training only, never Bonoua.

## Labelling time
The QGIS **Start timer** button and the Test / Val / Reviewed buttons log the minutes per tile in `labeling_log.csv`.

## Agreement check (planned)
A subset of corrected tiles will be relabelled independently (or by the same labeller weeks later) and agreement reported with IoU and Cohen's kappa. This was not completed before November 18.
