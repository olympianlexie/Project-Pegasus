# Boundary source

`laguna_municipalities.geojson` (30 features) and `laguna_barangays.geojson` (681 features) come from
[faeldon/philippines-json-maps](https://github.com/faeldon/philippines-json-maps), `latest/` (PSGC 3Q 2026),
medium resolution (`provdists/medres/municities-provdist-403400000.0.01.json` and
`municities/medres/bgysubmuns-municity-<code>.0.01.json` for each Laguna municipality). Coordinates are
WGS84, rounded to 6 decimals, and properties trimmed to PSGC code and name.

Medium resolution keeps 1% of the vertices, so a few NAPs near the lakeshore and province borders fall just
outside the polygons. Choropleths therefore join NAPs to polygons **by name**, not by location.

`barangay_aliases.csv` maps raw barangay names that PSGC spells differently. Add a row when the validation
report lists an unmatched barangay.
