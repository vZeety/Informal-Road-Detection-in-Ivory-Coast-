# Informal Road Detection in Côte d'Ivoire

Detecting informal dirt roads from 0.5 m satellite imagery around **Yaou and Bonoua (Côte d'Ivoire)**, and measuring where OpenStreetMap (OSM) is missing or misplacing roads.
CIS631 Machine Learning project, Minnesota State University, Mankato. Author: Thierno Barry.

## Research questions
- **RQ1, Coverage:** How completely does OSM cover the real roads at the study sites? (OSM scored against hand-corrected labels, per town.) WARE-Net was checked and does not cover these sites (see `docs/data_and_license.md`).
- **RQ2, Failure types:** How often are roads missing, misplaced or phantom in OSM, and how well do the pretrained and local models recover them? Includes the precision and recall of the missing-road flags.
- **RQ3, Local model:** How much local correction does a model need to beat the DeepGlobe model and OSM? Includes the corrected-tiles experiment (0, 5, 10, ... corrected tiles, 3 seeds, with labelling time), two training methods for noisy labels, and three ablations (pretraining, training-set size, backbone).

## Repository layout
| Path | Content |
|---|---|
| `scripts/road_tiles.py` | QGIS toolbar: grid, image + mask export, mask rebuild, tile status, labelling timer, town tag |
| `notebooks/Missing_Road_Finder.ipynb` | Two-fold prediction and OSM-gap flags (exploratory version) |
| `notebooks/DeepGlobe_Full_Pretraining.ipynb` | Full DeepGlobe pretraining (DeepLabV3+, ResNet-34) |
| `notebooks/Final_Experiments_FAST.ipynb` | All final results: OSM baseline, failure types, flags, corrected-tiles experiment, methods, ablations, statistics, figures |
| `notebooks/Road_First_Run.ipynb` | First exploratory run (October; superseded, labels were raw OSM) |
| `docs/grid_definition.md` | Grid and tile naming rule |
| `docs/annotation_guidelines.md` | What counts as a road and how labels are drawn |
| `docs/data_and_license.md` | Data sources, licences, imagery dates, what is and is not released |
| `data/tiles_log.csv` | Metadata for every tile: site, town, coordinates, CRS, resolution, imagery source, status |
| `data/splits.csv` | Train / validation / test assignment of every tile |
| `data/labeling_log.csv` | Minutes spent correcting each tile |
| `data/roads_edit.gpkg` | Corrected road lines (labels) |
| `results/` | Result files behind every chart, run configs and training logs (from `Final_Experiments.ipynb`) |

Raw satellite imagery is **not** included (see `docs/data_and_license.md`).

## Reproducing the results
1. **QGIS (3.x, Qt5 or Qt6):** add the Google Satellite XYZ layer and the Geofabrik OSM roads layer (`gis_osm_roads_free_1`), set `DATA_DIR` in `scripts/road_tiles.py`, run it from the Python Console editor.
2. Draw the grid, export the tiles, copy `masks/` to `masks_osm/` before any correction, correct roads in `roads_edit`, mark tiles **Test / Val / Reviewed**, set the **town**, and rebuild masks.
3. Zip `images/`, `masks/`, `masks_osm/`, `tiles_log.csv`, `labeling_log.csv` as `Dataset.zip` in `MyDrive/road_data/`.
4. Google Colab (L4 GPU): run `DeepGlobe_Full_Pretraining.ipynb`, then `Final_Experiments.ipynb`. Library versions used are written to `results/environment.json`.

## Main settings
- Tiles: 512 × 512 px at 0.5 m/px, EPSG:32630, 256 m grid cells.
- Model: DeepLabV3+ (`segmentation_models_pytorch`), ResNet-34 encoder with ImageNet weights, RGB input normalised with ImageNet mean/std; DeepGlobe pretraining uses the same normalisation.
- Training: AdamW, lr 1e-4, batch 4, 20 epochs, BCE + Dice loss, rotation/flip augmentation, 3 seeds.
- Model selection: best epoch and decision threshold chosen on the validation tiles only; test tiles scored once per run.
- Metrics: precision, recall, F1, IoU, relaxed (2 m tolerance) precision/recall/F1, mean ± SD over seeds, 95% bootstrap CI over test tiles, Cohen's d.
- Sites: Bonoua is a test-only town and never appears in training.

## Licence
Code: MIT. Labels and guidelines: CC BY 4.0, derived from OpenStreetMap (ODbL) where applicable.
