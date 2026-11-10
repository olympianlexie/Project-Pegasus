# Local patches to vendored libraries

- `leaflet-heat.js` (0.2.0): reads an `intensityZoom` option before `maxZoom` when scaling point intensity.
  Leaflet's layer list disables any layer whose `maxZoom` is below the current zoom, so passing `maxZoom`
  made the heat maps unselectable at street level. Search for `intensityZoom` to see the change.
- `leaflet-heat.js` (0.2.0): `_redraw` returns early when the layer has already been removed from the map.
  Turning a heat map off right after turning it on otherwise threw "Cannot read properties of null (reading 'getSize')".
