\# Informal Road Detection in Ivory Coast



\## Problem

Roughly 75% of roads worldwide are not mapped, worsening in developing countries. Existing road-detection models (e.g. trained on DeepGlobe) are built almost exclusively on formal, paved roads, so they miss or misclassify informal roads. This project builds a small, hand-labeled ground-truth dataset for informal roads in a test neighborhood and fine-tunes a pretrained DeepLabV3+ model to detect them.



\## Dataset

\- `images/` — satellite image tiles (Google Earth Pro, high-resolution)

\- `masks/` — matching black/white road masks (white = road), same filename as the corresponding image

\- Target: 50-100 labeled image/mask pairs

\- Status: 1 pair complete, in progress



\## Baseline

Comparing stock DeepLabV3+ (pretrained on DeepGlobe) vs. the same model fine-tuned on this dataset, evaluated with IoU, precision, recall, and F1 (recall as the headline metric).



\## Status

Week 1: dataset pipeline established, imagery source switched to Google Earth Pro after resolution issues with browser screenshots. Baseline inference in progress.

