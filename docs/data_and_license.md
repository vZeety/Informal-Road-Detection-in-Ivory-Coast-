# Data sources, licences and release

| Data | Source | Licence / terms | Released here |
|---|---|---|---|
| Satellite imagery | Google Satellite basemap (XYZ tiles) loaded in QGIS, exported at 0.5 m/px | Google Maps / Earth terms. The terms do not explicitly grant use for training models; imagery was used only for non-commercial academic research and is **not redistributed** | No |
| Road lines | OpenStreetMap, Geofabrik extract for Côte d'Ivoire (`gis_osm_roads_free_1`) | ODbL | Corrected lines and masks |
| Pretraining data | DeepGlobe Road Extraction (Demir et al., 2018), via Kaggle | Dataset licence (research use) | No |

**Acquisition dates:** the Google basemap does not expose capture dates in QGIS, and they could not be recovered. The export date of each tile is recorded in `tiles_log.csv` (`img_date`); `acquisition_date` is marked `unknown`.

**WARE-Net:** the only published WARE-Net found is an EGU 2026 abstract on Arctic wilderness roads (Wang & Liu, built on Google Satellite Embeddings). Road-prediction GeoTIFFs checked earlier under that name do not cover Yaou or Bonoua, so no regional road product could be compared at these sites. It is therefore removed from the RQ3 comparison.

**Ethics:** the study area includes informal neighbourhoods. Exact coordinates are kept in this repository for reproducibility, but any public map release will generalise the locations of sensitive settlements. Mapping roads can support services and emergency response, but could also attract unwanted attention or support evictions.
