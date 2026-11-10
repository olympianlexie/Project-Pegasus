/* Project Pegasus map. Data comes from the JSON block written by pegasus/build_map.py. */
(function () {
  'use strict';

  var D = JSON.parse(document.getElementById('pegasus-data').textContent);
  var M = D.meta, N = D.naps, LV = M.levels, F = M.flags;
  var COL = LV.map(function (l) { return M.colors[l]; });
  var NN = N.id.length;
  var RISK = 3, HIGH = 2;

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmt(n) { return (n || 0).toLocaleString('en-US'); }
  function pct(x) { return (x == null || isNaN(x)) ? '–' : (100 * x).toFixed(1) + '%'; }
  function day(d) { return d < 0 ? '–' : new Date(d * 864e5).toISOString().slice(0, 10); }
  function norm(s) { return String(s || '').toUpperCase().replace(/\s+/g, ' ').trim(); }
  function tag(lv) { return '<span class="tag" style="background:' + COL[lv] + '">' + LV[lv] + '</span>'; }
  function has(i, name) { return (N.f[i] & F[name]) !== 0; }
  function lcpOf(i) { return N.id[i].replace(/\s+NP\d+$/i, ''); }
  function muniOf(i) { return D.munis[D.brgys[N.b[i]][0]][0]; }
  function brgyOf(i) { return D.brgys[N.b[i]][1]; }
  function oltOf(i) { return N.o[i] >= 0 ? D.olts[N.o[i]].id : null; }
  function ponOf(i) { return N.p[i] >= 0 ? D.pons[N.p[i]] : null; }
  function natCmp(a, b) { return String(a).localeCompare(String(b), 'en', { numeric: true }); }
  function oltClass(rate) {
    var b = M.oltBounds;
    if (rate == null || isNaN(rate)) return -1;
    return rate < b[0] ? 0 : rate < b[1] ? 1 : rate <= b[2] ? 2 : 3;
  }
  var PORT = { A: ['ACTIVE', '#3b4252'], V: ['AVAILABLE', '#2ca02c'], L: ['ALLOCATED', '#8e44ad'], R: ['RESERVED', '#b8860b'], '?': ['OTHER', '#999'] };

  // ---------- indexes ----------
  var napIndex = {}, oltIndex = {}, lcpIndex = {};
  for (var i = 0; i < NN; i++) {
    napIndex[norm(N.id[i])] = i;
    var l = norm(lcpOf(i));
    (lcpIndex[l] = lcpIndex[l] || []).push(i);
  }
  D.olts.forEach(function (o, k) { oltIndex[norm(o.id)] = k; });
  var poleIndex = null;
  function poleOf(i) {
    if (!poleIndex) {
      poleIndex = {};
      for (var j = 0; j < NN; j++) { var k = N.lat[j] + ',' + N.lon[j]; (poleIndex[k] = poleIndex[k] || []).push(j); }
    }
    return poleIndex[N.lat[i] + ',' + N.lon[i]];
  }
  var relocBy = {}, relocTo = {};
  var R = D.reloc, RN = R.c ? R.c.length : 0;
  for (var k = 0; k < RN; k++) { relocBy[R.c[k]] = k; (relocTo[R.t[k]] = relocTo[R.t[k]] || []).push(k); }
  var sellBy = {};
  for (k = 0; k < D.sell.i.length; k++) sellBy[D.sell.i[k]] = k;

  // ---------- map and base layers ----------
  var map = L.map('map', { preferCanvas: true, maxZoom: 20, zoomControl: true }).setView(M.center, M.zoom);
  var esriAttr = 'Imagery &copy; Esri, Maxar, Earthstar Geographics';
  var tileNote = false;
  function onTileError() {
    if (tileNote) return;
    tileNote = true;
    var d = document.createElement('div');
    d.className = 'tilenote';
    d.textContent = 'The street and satellite background maps could not load here (no internet, or this viewer blocks them). ' +
      'NAPs, OLTs, boundaries and all layers still work. Open the downloaded HTML file in a browser to see the background maps.';
    document.getElementById('map').appendChild(d);
  }
  var tile = function (url, attr) {
    return L.tileLayer(url, { maxZoom: 20, maxNativeZoom: 19, attribution: attr || '' }).on('tileerror', onTileError);
  };
  var bases = {
    'Street map (OpenStreetMap)': tile('https://tile.openstreetmap.org/{z}/{x}/{y}.png', '&copy; OpenStreetMap contributors'),
    'Satellite (Esri)': tile('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', esriAttr),
    'Satellite + roads & labels (Esri)': L.layerGroup([
      tile('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', esriAttr),
      tile('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}'),
      tile('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}')
    ])
  };
  bases['Street map (OpenStreetMap)'].addTo(map);

  function pane(name, z) { map.createPane(name).style.zIndex = z; return name; }
  pane('choro', 350); pane('outline', 360); pane('hot', 390); pane('reloc', 450);
  var napCanvas = L.canvas({ padding: 0.5 });
  var relocCanvas = L.canvas({ pane: 'reloc', padding: 0.5 });
  var hotCanvas = L.canvas({ pane: 'hot', padding: 0.5 });

  // ---------- NAP markers (clustered) ----------
  var markers = new Array(NN);
  for (i = 0; i < NN; i++) {
    var m = L.circleMarker([N.lat[i], N.lon[i]], {
      renderer: napCanvas, radius: 5.5, color: '#ffffff', weight: 1.2, fillColor: COL[N.lv[i]], fillOpacity: 0.95
    });
    m._pi = i;
    markers[i] = m;
  }
  function clusterIcon(c) {
    var ms = c.getAllChildMarkers(), cnt = [0, 0, 0, 0], n = ms.length;
    for (var j = 0; j < n; j++) cnt[N.lv[ms[j]._pi]]++;
    var acc = 0, stops = [];
    [3, 2, 1, 0].forEach(function (lv) {
      if (!cnt[lv]) return;
      stops.push(COL[lv] + ' ' + (acc / n * 360).toFixed(1) + 'deg ' + ((acc + cnt[lv]) / n * 360).toFixed(1) + 'deg');
      acc += cnt[lv];
    });
    var size = n < 10 ? 26 : n < 100 ? 32 : n < 1000 ? 38 : 46, inner = size - 9;
    var label = n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : n;
    return L.divIcon({
      className: '', iconSize: [size, size],
      html: '<div class="pc" title="Risk ' + cnt[3] + ' · High ' + cnt[2] + ' · Optimal ' + cnt[1] + ' · Low ' + cnt[0] +
        '" style="width:' + size + 'px;height:' + size + 'px;background:conic-gradient(' + stops.join(',') + ')">' +
        '<span style="width:' + inner + 'px;height:' + inner + 'px">' + label + '</span></div>'
    });
  }
  var cluster = L.markerClusterGroup({
    chunkedLoading: true, chunkInterval: 120, chunkDelay: 10,
    showCoverageOnHover: false, spiderfyOnMaxZoom: true, zoomToBoundsOnClick: true, removeOutsideVisibleBounds: true,
    maxClusterRadius: function (z) { return z >= 18 ? 14 : z >= 16 ? 28 : z >= 14 ? 42 : 60; },
    spiderLegPolylineOptions: { weight: 1.5, color: '#222', opacity: 0.6 },
    iconCreateFunction: clusterIcon
  });
  cluster.on('click', function (e) { if (e.layer && e.layer._pi != null) openNap(e.layer._pi); });
  cluster.addTo(map);

  // ---------- OLT markers ----------
  var oltLayer = L.layerGroup().addTo(map);
  var oltMarkers = D.olts.map(function (o, k) {
    var mk = L.marker([o.lat, o.lon], {
      zIndexOffset: 1000, title: o.id,
      icon: L.divIcon({ className: '', iconSize: [26, 26], iconAnchor: [13, 13],
        html: '<div class="olt-icon" style="background:' + COL[o.lv] + '"></div>' })
    });
    mk.bindTooltip(esc(o.id) + ' · ' + pct(o.util), { direction: 'top', offset: [0, -12] });
    mk.on('click', function () { openOlt(k); });
    return mk;
  });

  // ---------- boundaries: outline + choropleths ----------
  var outline = L.geoJSON(D.geoM, { pane: 'outline', interactive: false,
    style: { color: '#7d8796', weight: 1.4, opacity: 0.85, fill: false, dashArray: '4 3' } }).addTo(map);
  var aggB = [], aggM = [];
  function styleFor(a) {
    if (!a || !a.t) return { color: '#777', weight: 0.6, fillOpacity: 0.04, fillColor: '#999' };
    var c = oltClass(a.u / a.t);
    return { color: '#333', weight: 0.7, fillColor: COL[c], fillOpacity: 0.5 };
  }
  function areaPopup(name, sub, a) {
    if (!a || !a.t) return '<div class="pp"><h3>' + esc(name) + '</h3>' + esc(sub) + '<br>No NAPs (with the current filters).</div>';
    var rows = [3, 2, 1, 0].map(function (lv) { return '<tr><td>' + tag(lv) + '</td><td>' + fmt(a.c[lv]) + '</td></tr>'; }).join('');
    return '<div class="pp"><h3>' + esc(name) + '</h3><div class="hint">' + esc(sub) + '</div>' +
      '<table class="kv"><tr><td>Utilization</td><td><b>' + pct(a.u / a.t) + '</b> (' + fmt(a.u) + ' of ' + fmt(a.t) + ' ports)</td></tr>' +
      '<tr><td>NAPs</td><td>' + fmt(a.n) + '</td></tr></table><table class="grid">' + rows + '</table></div>';
  }
  var choroB = L.geoJSON(D.geoB, {
    pane: 'choro', style: function (f) { return styleFor(null); },
    onEachFeature: function (f, layer) {
      layer._fi = D.geoB.features.indexOf(f);
      layer.on('click', function (e) {
        var p = f.properties;
        L.popup().setLatLng(e.latlng).setContent(areaPopup(p.barangay, p.municipality, aggB[layer._fi])).openOn(map);
      });
      layer.bindTooltip(function () { var a = aggB[layer._fi]; return esc(f.properties.barangay) + (a && a.t ? ' · ' + pct(a.u / a.t) : ''); }, { sticky: true });
    }
  });
  var choroM = L.geoJSON(D.geoM, {
    pane: 'choro', style: function () { return styleFor(null); },
    onEachFeature: function (f, layer) {
      layer._fi = D.geoM.features.indexOf(f);
      layer.on('click', function (e) {
        L.popup().setLatLng(e.latlng).setContent(areaPopup(f.properties.municipality, 'Municipality', aggM[layer._fi])).openOn(map);
      });
      layer.bindTooltip(function () { var a = aggM[layer._fi]; return esc(f.properties.municipality) + (a && a.t ? ' · ' + pct(a.u / a.t) : ''); }, { sticky: true });
    }
  });

  // ---------- heat layers ----------
  var heatGrad = [
    { 0.2: '#c6dbef', 0.5: '#6baed6', 0.8: '#2171b5', 1: '#08306b' },
    { 0.2: '#c7e9c0', 0.5: '#74c476', 0.8: '#238b45', 1: '#00441b' },
    { 0.2: '#fdd0a2', 0.5: '#fd8d3c', 0.8: '#d94801', 1: '#7f2704' },
    { 0.2: '#fcbba1', 0.5: '#fb6a4a', 0.8: '#cb181d', 1: '#67000d' }
  ];
  var heats = LV.map(function (_, lv) { return L.heatLayer([], { radius: 14, blur: 16, maxZoom: 17, minOpacity: 0.2, gradient: heatGrad[lv] }); });

  // ---------- relocation and hotspot layers ----------
  var relocLayer = L.layerGroup().addTo(map);
  var hotLayer = L.layerGroup();
  function arrowHead(a, b, len) {
    var lat0 = a[0] * Math.PI / 180, kx = 111320 * Math.cos(lat0), ky = 110540;
    var dx = (b[1] - a[1]) * kx, dy = (b[0] - a[0]) * ky, d = Math.sqrt(dx * dx + dy * dy) || 1;
    len = Math.min(len, d * 0.4);
    var ux = dx / d, uy = dy / d, w = len * 0.55;
    // tip at 60% of the way, so the head is never hidden under the target marker
    var tx = a[1] * kx + dx * 0.6, ty = a[0] * ky + dy * 0.6;
    var bx = tx - ux * len, by = ty - uy * len;
    return [[ty / ky, tx / kx], [(by + ux * w) / ky, (bx - uy * w) / kx], [(by - ux * w) / ky, (bx + uy * w) / kx]];
  }
  function relocPopup(k) {
    var c = R.c[k], t = R.t[k];
    return '<div class="pp"><h3>Relocation #' + R.rank[k] + '</h3><table class="kv">' +
      '<tr><td>Move NAP</td><td><a data-nap="' + c + '">' + esc(N.id[c]) + '</a> (' + N.u[c] + ' used)</td></tr>' +
      '<tr><td>To near</td><td><a data-nap="' + t + '">' + esc(N.id[t]) + '</a> ' + tag(N.lv[t]) + '</td></tr>' +
      '<tr><td>Hotspot</td><td><a data-hot="' + esc(R.h[k]) + '">' + esc(R.h[k]) + '</a> ' + tag(R.lv[k]) + '</td></tr>' +
      '<tr><td>Distance</td><td>' + fmt(R.d[k]) + ' m' + (R.sl[k] ? ' · same LCP' : ' · other LCP, same OLT') + '</td></tr>' +
      '<tr><td>Subscriber gain</td><td>up to ' + R.g[k] + '</td></tr>' +
      (R.rh[k] ? '<tr><td>Re-home first</td><td>' + esc(R.rh[k]) + '</td></tr>' : '') + '</table></div>';
  }
  var hotById = {};
  D.hot.id.forEach(function (h, k) { hotById[h] = k; });
  function hotPopup(k) {
    var H = D.hot;
    return '<div class="pp"><h3>Demand hotspot ' + esc(H.id[k]) + ' ' + tag(H.lv[k]) + '</h3><table class="kv">' +
      '<tr><td>Area</td><td>' + esc(H.bg[k]) + ', ' + esc(H.m[k]) + '</td></tr>' +
      '<tr><td>NAPs</td><td>' + H.n[k] + ' (Risk ' + H.risk[k] + ', High ' + H.high[k] + ')</td></tr>' +
      '<tr><td>Radius</td><td>' + fmt(H.rad[k]) + ' m</td></tr>' +
      '<tr><td>Ports needed</td><td>' + fmt(H.need[k]) + ' to bring all to Optimal</td></tr>' +
      '<tr><td>Idle ports nearby</td><td>' + fmt(H.idle[k]) + ' on Low NAPs within ' + M.dropReach + ' m</td></tr>' +
      '<tr><td>Net need</td><td>' + fmt(H.net[k]) + ' ports → ' + H.cap[k] + ' NAP(s)</td></tr>' +
      '<tr><td>Relocations sent</td><td>' + H.asg[k] + '</td></tr></table></div>';
  }

  // ---------- filters ----------
  var state = { muni: '', brgy: '', olt: '', levels: [true, true, true, true], from: null, to: null, show: '' };
  var mask = new Uint8Array(NN);
  var FLAGGED = F.olt_inferred | F.placeholder_stack | F.cross_fed | F.pon_unknown | F.level_differs_tableau;
  function pass(i) {
    if (!state.levels[N.lv[i]]) return false;
    if (state.muni !== '' && D.brgys[N.b[i]][0] !== +state.muni) return false;
    if (state.brgy !== '' && N.b[i] !== +state.brgy) return false;
    if (state.olt !== '' && N.o[i] !== +state.olt) return false;
    if (state.from != null && (N.r[i] < 0 || N.r[i] < state.from)) return false;
    if (state.to != null && (N.r[i] < 0 || N.r[i] > state.to)) return false;
    var s = state.show;
    if (s) {
      if (s === 'flagged') return (N.f[i] & FLAGGED) !== 0;
      if (s === 'zero') return N.lv[i] === 0 && N.u[i] === 0;
      return has(i, s);
    }
    return true;
  }
  function isFiltered() {
    return state.muni !== '' || state.brgy !== '' || state.olt !== '' || state.from != null || state.to != null ||
      state.show !== '' || state.levels.some(function (x) { return !x; });
  }

  function applyFilters() {
    var list = [];
    for (var i = 0; i < NN; i++) { mask[i] = pass(i) ? 1 : 0; if (mask[i]) list.push(markers[i]); }
    cluster.clearLayers();
    cluster.addLayers(list);
    refreshSummary();
    refreshChoro();
    refreshHeat();
    refreshReloc();
    refreshOlts();
    refreshHot();
    document.getElementById('filterNote').textContent = isFiltered() ? '(filtered)' : '(all NAPs)';
  }

  function refreshSummary() {
    var cnt = [0, 0, 0, 0], n = 0, u = 0, t = 0, a = 0, zero = 0, rel = 0, sell = 0, olts = {};
    for (var i = 0; i < NN; i++) {
      if (!mask[i]) continue;
      n++; cnt[N.lv[i]]++; u += N.u[i]; t += N.t[i]; a += N.a[i];
      if (N.lv[i] === 0 && N.u[i] === 0) zero++;
      if (has(i, 'relocate')) rel++;
      if (has(i, 'sell_existing')) sell++;
      if (N.o[i] >= 0) olts[N.o[i]] = 1;
    }
    var bar = [3, 2, 1, 0].map(function (lv) { return n ? '<div style="width:' + (100 * cnt[lv] / n) + '%;background:' + COL[lv] + '"></div>' : ''; }).join('');
    var rows = [3, 2, 1, 0].map(function (lv) {
      return '<tr><td><span class="sw" style="background:' + COL[lv] + '"></span> ' + LV[lv] + '</td><td>' + fmt(cnt[lv]) +
        '</td><td>' + (n ? pct(cnt[lv] / n) : '–') + '</td></tr>';
    }).join('');
    document.getElementById('summary').innerHTML =
      '<div class="stats"><div class="stat"><div class="k">NAPs</div><div class="big">' + fmt(n) + '</div></div>' +
      '<div class="stat"><div class="k">Port utilization</div><div class="big">' + (t ? pct(u / t) : '–') + '</div></div>' +
      '<div class="stat"><div class="k">Ports used / total</div><b>' + fmt(u) + '</b> / ' + fmt(t) + '</div>' +
      '<div class="stat"><div class="k">Sellable (available)</div><b>' + fmt(a) + '</b></div></div>' +
      '<div class="bar">' + bar + '</div><table class="grid"><tr><th>Level</th><th>NAPs</th><th>Share</th></tr>' + rows + '</table>' +
      '<table class="kv" style="margin-top:6px"><tr><td>OLTs</td><td>' + fmt(Object.keys(olts).length) + '</td></tr>' +
      '<tr><td>Low with 0 used ports</td><td>' + fmt(zero) + '</td></tr>' +
      '<tr><td>Recommended to relocate</td><td>' + fmt(rel) + '</td></tr>' +
      '<tr><td>Low near demand (sell)</td><td>' + fmt(sell) + '</td></tr></table>';
    for (var lv = 0; lv < 4; lv++) cntSpans[lv].textContent = '(' + fmt(cnt[lv]) + ')';
  }

  function refreshChoro() {
    var nb = D.geoB.features.length, nm = D.geoM.features.length;
    aggB = new Array(nb); aggM = new Array(nm);
    for (var i = 0; i < NN; i++) {
      if (!mask[i]) continue;
      var b = D.brgys[N.b[i]], fb = b[2], fm = D.munis[b[0]][1];
      [[aggB, fb], [aggM, fm]].forEach(function (x) {
        var arr = x[0], f = x[1];
        if (f < 0) return;
        var a = arr[f] || (arr[f] = { n: 0, u: 0, t: 0, c: [0, 0, 0, 0] });
        a.n++; a.u += N.u[i]; a.t += N.t[i]; a.c[N.lv[i]]++;
      });
    }
    choroB.eachLayer(function (l) { l.setStyle(styleFor(aggB[l._fi])); });
    choroM.eachLayer(function (l) { l.setStyle(styleFor(aggM[l._fi])); });
  }

  function refreshHeat() {
    heats.forEach(function (h, lv) {
      if (!map.hasLayer(h)) return;
      var pts = [];
      for (var i = 0; i < NN; i++) if (mask[i] && N.lv[i] === lv) pts.push([N.lat[i], N.lon[i], 1]);
      h.setLatLngs(pts);
    });
  }

  var relocSrc = [], relocHeads = [];
  function srcRadius() { var z = map.getZoom(); return z < 12 ? 2.5 : z < 15 ? 4.5 : 7; }
  // arrowhead ~14 px long whatever the zoom
  function arrowLen() { return 16 * 40075016.686 * Math.cos(map.getCenter().lat * Math.PI / 180) / Math.pow(2, map.getZoom() + 8); }
  function refreshReloc() {
    relocLayer.clearLayers();
    relocSrc = []; relocHeads = [];
    for (var k = 0; k < RN; k++) {
      var c = R.c[k], t = R.t[k];
      if (!mask[c]) continue;
      var a = [N.lat[c], N.lon[c]], b = [N.lat[t], N.lon[t]], col = COL[R.lv[k]];
      var line = L.polyline([a, b], { renderer: relocCanvas, color: col, weight: 3, opacity: 0.9 });
      var head = L.polygon(arrowHead(a, b, arrowLen()), { renderer: relocCanvas, color: col, weight: 1, fillColor: col, fillOpacity: 1 });
      head._ab = [a, b];
      relocHeads.push(head);
      var src = L.circleMarker(a, { renderer: relocCanvas, radius: srcRadius(), color: '#111', weight: 2, fill: false });
      relocSrc.push(src);
      (function (kk) { [line, head, src].forEach(function (x) { x.on('click', function (e) { L.popup().setLatLng(e.latlng).setContent(relocPopup(kk)).openOn(map); }); }); })(k);
      relocLayer.addLayer(line); relocLayer.addLayer(head); relocLayer.addLayer(src);
    }
  }

  function refreshHot() {
    hotLayer.clearLayers();
    var H = D.hot, muniName = state.muni !== '' ? D.munis[+state.muni][0] : null;
    for (var k = 0; k < H.id.length; k++) {
      if (muniName && H.m[k] !== muniName) continue;
      if (!state.levels[H.lv[k]]) continue;
      var c = L.circle([H.lat[k], H.lon[k]], { renderer: hotCanvas, radius: Math.max(H.rad[k], 25), color: COL[H.lv[k]], weight: 1.5, fillOpacity: 0.12 });
      (function (kk) { c.on('click', function (e) { L.popup().setLatLng(e.latlng).setContent(hotPopup(kk)).openOn(map); }); })(k);
      hotLayer.addLayer(c);
    }
  }

  function refreshOlts() {
    oltLayer.clearLayers();
    var show = {};
    if (state.olt !== '') show[+state.olt] = 1;
    else if (isFiltered()) { for (var i = 0; i < NN; i++) if (mask[i] && N.o[i] >= 0) show[N.o[i]] = 1; }
    oltMarkers.forEach(function (mk, k) { if (!isFiltered() || show[k]) oltLayer.addLayer(mk); });
  }

  // ---------- popups ----------
  function openNap(i) {
    var codes = N.ps[i], sc = {};
    for (var c = 0; c < codes.length; c++) sc[codes[c]] = (sc[codes[c]] || 0) + 1;
    var ports = codes.split('').map(function (ch, p) {
      return '<div class="port" style="background:' + PORT[ch][1] + '" title="Port ' + (p + 1) + ': ' + PORT[ch][0] + '">P' + (p + 1) + '</div>';
    }).join('');
    var breakdown = Object.keys(PORT).filter(function (ch) { return sc[ch]; })
      .map(function (ch) { return PORT[ch][0] + ' ' + sc[ch]; }).join(', ');
    var olt = oltOf(i), pon = ponOf(i);
    var pole = poleOf(i).filter(function (j) { return j !== i; });
    var poleHtml = pole.length ? pole.slice(0, 25).map(function (j) {
      return '<a data-nap="' + j + '">' + esc(N.id[j]) + '</a> ' + tag(N.lv[j]);
    }).join('<br>') + (pole.length > 25 ? '<br>… and ' + (pole.length - 25) + ' more' : '') : 'none';
    var h = '<div class="pp"><h3>' + esc(N.id[i]) + ' ' + tag(N.lv[i]) + '</h3><table class="kv">' +
      '<tr><td>LCP</td><td>' + esc(lcpOf(i)) + '</td></tr>' +
      '<tr><td>OLT</td><td>' + (olt ? '<a data-olt="' + N.o[i] + '">' + esc(olt) + '</a>' : '–') +
        (has(i, 'olt_inferred') ? ' <i>(inferred)</i>' : '') + '</td></tr>' +
      '<tr><td>PON port</td><td>' + esc(pon || 'unknown') + '</td></tr>' +
      '<tr><td>Barangay</td><td>' + esc(brgyOf(i)) + '</td></tr>' +
      '<tr><td>Municipality</td><td>' + esc(muniOf(i)) + '</td></tr>' +
      '<tr><td>Ports</td><td><b>' + N.u[i] + '</b> used · ' + N.a[i] + ' available · ' + N.t[i] + ' total</td></tr>' +
      '<tr><td>Utilization</td><td>' + pct(N.u[i] / N.t[i]) + '</td></tr>' +
      '<tr><td>Status</td><td>' + esc(breakdown) + '</td></tr>' +
      '<tr><td>RFS date</td><td>' + day(N.r[i]) + (has(i, 'new_rfs') ? ' <i>(within ' + M.newMonths + ' months)</i>' : '') + '</td></tr>' +
      '<tr><td>Distance to OLT</td><td>' + (N.d[i] == null ? '–' : N.d[i].toFixed(2) + ' km') +
        (has(i, 'dist_estimated') ? ' <i>(estimated, straight line to approximate OLT)</i>' : '') + '</td></tr>' +
      '</table><div class="ports">' + ports + '</div>' +
      '<div><b>Other NAPs on this pole:</b><div class="scroll">' + poleHtml + '</div></div>';
    if (has(i, 'relocate')) {
      var k = relocBy[i], t = R.t[k];
      h += '<div class="warn"><b>Relocate (#' + R.rank[k] + ')</b> → near <a data-nap="' + t + '">' + esc(N.id[t]) + '</a>, ' +
        fmt(R.d[k]) + ' m, hotspot <a data-hot="' + esc(R.h[k]) + '">' + esc(R.h[k]) + '</a> ' + tag(R.lv[k]) +
        (R.rh[k] ? '<br>Re-home first: ' + esc(R.rh[k]) : '') + '</div>';
    }
    if (has(i, 'sell_existing')) {
      var s = sellBy[i], nd = D.sell.n[s];
      h += '<div class="warn"><b>Sell from this NAP:</b> Risk/High demand ' + (D.sell.d[s] <= 1 ? 'on the same pole' : fmt(D.sell.d[s]) + ' m away') +
        (nd >= 0 ? ' (<a data-nap="' + nd + '">' + esc(N.id[nd]) + '</a>)' : '') + ', within drop reach. Not relocated.</div>';
    }
    if (relocTo[i]) {
      h += '<div class="warn"><b>Relocation target</b> for ' + relocTo[i].map(function (kk) {
        return '<a data-nap="' + R.c[kk] + '">' + esc(N.id[R.c[kk]]) + '</a>';
      }).join(', ') + '</div>';
    }
    var w = [];
    if (has(i, 'placeholder_stack')) w.push('Shares its coordinate with ' + pole.length + ' other NAPs: possible placeholder location.');
    if (has(i, 'olt_inferred')) w.push('OLT ID blank in the raw file; filled from Tableau.');
    if (has(i, 'cross_fed')) w.push('Cross-fed: NAP site prefix differs from its OLT.');
    if (has(i, 'new_vs_tableau')) w.push('New since the Tableau export.');
    if (has(i, 'level_differs_tableau')) w.push('Tableau: ' + LV[N.tl[i]] + ' (' + N.tu[i] + ' used).');
    if (w.length) h += '<div class="warn">' + w.map(esc).join('<br>') + '</div>';
    h += '</div>';
    L.popup({ maxWidth: 380, autoPanPadding: [30, 30] }).setLatLng([N.lat[i], N.lon[i]]).setContent(h).openOn(map);
  }

  function openOlt(k) {
    var o = D.olts[k], pons = {}, lv = [0, 0, 0, 0];
    for (var i = 0; i < NN; i++) {
      if (N.o[i] !== k) continue;
      var p = N.p[i] >= 0 ? D.pons[N.p[i]] : '(unknown)';
      var r = pons[p] || (pons[p] = { n: 0, u: 0, t: 0, lcp: {}, c: [0, 0, 0, 0] });
      r.n++; r.u += N.u[i]; r.t += N.t[i]; r.lcp[lcpOf(i)] = 1; r.c[N.lv[i]]++; lv[N.lv[i]]++;
    }
    var rows = Object.keys(pons).sort(natCmp).map(function (p) {
      var r = pons[p], cl = oltClass(r.u / r.t);
      return '<tr><td>' + esc(p.replace('Frame:', 'F').replace('/Slot:', '/S').replace('/Port:', '/P')) + '</td><td title="' +
        esc(Object.keys(r.lcp).join(', ')) + '">' + Object.keys(r.lcp).length + '</td><td>' + r.n + '</td><td>' + r.u + '/' + r.t +
        '</td><td style="color:' + (cl >= 0 ? COL[cl] : '#333') + ';font-weight:600">' + pct(r.u / r.t) + '</td></tr>';
    }).join('');
    var h = '<div class="pp"><h3>' + esc(o.id) + ' ' + tag(o.lv) + '</h3><table class="kv">' +
      '<tr><td>Utilization</td><td><b>' + pct(o.util) + '</b> (' + fmt(o.used) + ' of ' + fmt(o.ports) + ' ports)</td></tr>' +
      '<tr><td>Available</td><td>' + fmt(o.avail) + ' ports</td></tr>' +
      '<tr><td>NAPs / LCPs / PONs</td><td>' + fmt(o.naps) + ' / ' + fmt(o.lcps) + ' / ' + fmt(o.pons) + '</td></tr>' +
      '<tr><td>NAPs by level</td><td>' + [3, 2, 1, 0].map(function (l) { return tag(l) + ' ' + fmt(lv[l]); }).join(' ') + '</td></tr>' +
      '<tr><td>Municipalities</td><td>' + esc(o.munis) + '</td></tr>' +
      '<tr><td>Location</td><td>' + esc(o.src) + '</td></tr></table>' +
      '<div style="margin-top:6px"><b>Per PON port</b> <a data-filter-olt="' + k + '">show only this OLT</a></div>' +
      '<div class="scroll" style="max-height:220px"><table class="grid"><tr><th>PON</th><th>LCPs</th><th>NAPs</th><th>Used</th><th>Util</th></tr>' +
      rows + '</table></div></div>';
    L.popup({ maxWidth: 400 }).setLatLng([o.lat, o.lon]).setContent(h).openOn(map);
  }

  function gotoNap(i) {
    if (mask[i]) {
      cluster.zoomToShowLayer(markers[i], function () { openNap(i); });
    } else {
      map.setView([N.lat[i], N.lon[i]], 18);
      openNap(i);
      msg('Note: this NAP is hidden by the current filters.');
    }
  }
  function gotoOlt(k) { map.setView([D.olts[k].lat, D.olts[k].lon], Math.max(map.getZoom(), 13)); openOlt(k); }
  function gotoHot(id) {
    var k = hotById[id]; if (k == null) return;
    if (!map.hasLayer(hotLayer)) map.addLayer(hotLayer);
    map.setView([D.hot.lat[k], D.hot.lon[k]], 17);
    L.popup().setLatLng([D.hot.lat[k], D.hot.lon[k]]).setContent(hotPopup(k)).openOn(map);
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest('[data-nap],[data-olt],[data-hot],[data-filter-olt]');
    if (!a) return;
    e.preventDefault();
    if (a.dataset.nap != null) gotoNap(+a.dataset.nap);
    else if (a.dataset.olt != null) gotoOlt(+a.dataset.olt);
    else if (a.dataset.hot != null) gotoHot(a.dataset.hot);
    else if (a.dataset.filterOlt != null) { el('fOlt').value = a.dataset.filterOlt; state.olt = a.dataset.filterOlt; applyFilters(); }
  });

  // ---------- panel UI ----------
  function el(id) { return document.getElementById(id); }
  function msg(t) { el('searchMsg').textContent = t || ''; }
  function opt(v, t) { var o = document.createElement('option'); o.value = v; o.textContent = t; return o; }

  D.munis.forEach(function (m, k) { el('fMuni').appendChild(opt(k, m[0])); });
  function fillBrgy() {
    var s = el('fBrgy'); s.innerHTML = ''; s.appendChild(opt('', 'All barangays'));
    if (state.muni === '') { s.disabled = true; return; }
    s.disabled = false;
    D.brgys.forEach(function (b, k) { if (b[0] === +state.muni) s.appendChild(opt(k, b[1])); });
  }
  function fillOlt() {
    var s = el('fOlt'), keep = state.olt; s.innerHTML = ''; s.appendChild(opt('', 'All OLTs'));
    var allowed = null;
    if (state.muni !== '') {
      allowed = {};
      for (var i = 0; i < NN; i++) if (D.brgys[N.b[i]][0] === +state.muni && N.o[i] >= 0) allowed[N.o[i]] = 1;
    }
    D.olts.forEach(function (o, k) { if (!allowed || allowed[k]) s.appendChild(opt(k, o.id + ' (' + pct(o.util) + ')')); });
    s.value = keep;
    if (s.value !== keep) state.olt = '';
  }
  var cntSpans = [];
  var levelsBox = el('fLevels');
  [3, 2, 1, 0].forEach(function (lv) {
    var lab = document.createElement('label');
    lab.innerHTML = '<input type="checkbox" checked data-lv="' + lv + '"><span class="sw" style="background:' + COL[lv] + '"></span>' +
      LV[lv] + ' <span class="hint"></span>';
    cntSpans[lv] = lab.querySelector('.hint');
    levelsBox.appendChild(lab);
  });

  function toDays(v) { return v ? Math.floor(Date.parse(v + 'T00:00:00Z') / 864e5) : null; }
  el('fMuni').addEventListener('change', function () { state.muni = this.value; state.brgy = ''; fillBrgy(); fillOlt(); applyFilters(); zoomToFiltered(); });
  el('fBrgy').addEventListener('change', function () { state.brgy = this.value; applyFilters(); zoomToFiltered(); });
  el('fOlt').addEventListener('change', function () { state.olt = this.value; applyFilters(); zoomToFiltered(); });
  levelsBox.addEventListener('change', function (e) { var lv = e.target.dataset.lv; if (lv != null) { state.levels[+lv] = e.target.checked; applyFilters(); } });
  el('fFrom').addEventListener('change', function () { state.from = toDays(this.value); applyFilters(); });
  el('fTo').addEventListener('change', function () { state.to = toDays(this.value); applyFilters(); });
  el('fShow').addEventListener('change', function () { state.show = this.value; applyFilters(); });
  el('resetBtn').addEventListener('click', function () {
    state = { muni: '', brgy: '', olt: '', levels: [true, true, true, true], from: null, to: null, show: '' };
    ['fMuni', 'fBrgy', 'fOlt', 'fFrom', 'fTo', 'fShow'].forEach(function (id) { el(id).value = ''; });
    levelsBox.querySelectorAll('input').forEach(function (c) { c.checked = true; });
    fillBrgy(); fillOlt(); applyFilters(); map.setView(M.center, M.zoom);
  });
  function zoomToFiltered() {
    var b = null;
    for (var i = 0; i < NN; i++) if (mask[i]) { if (!b) b = L.latLngBounds([N.lat[i], N.lon[i]], [N.lat[i], N.lon[i]]); else b.extend([N.lat[i], N.lon[i]]); }
    if (b && isFiltered()) map.fitBounds(b, { padding: [30, 30], maxZoom: 17 });
  }
  var minR = Infinity, maxR = -Infinity;
  for (i = 0; i < NN; i++) if (N.r[i] >= 0) { if (N.r[i] < minR) minR = N.r[i]; if (N.r[i] > maxR) maxR = N.r[i]; }
  el('fFrom').min = el('fTo').min = day(minR);
  el('fFrom').max = el('fTo').max = day(maxR);

  // search
  function doSearch() {
    var q = norm(el('search').value);
    msg('');
    if (!q) return;
    if (napIndex[q] != null) return gotoNap(napIndex[q]);
    if (oltIndex[q] != null) return gotoOlt(oltIndex[q]);
    if (lcpIndex[q]) {
      var ids = lcpIndex[q], b = L.latLngBounds(ids.map(function (j) { return [N.lat[j], N.lon[j]]; }));
      map.fitBounds(b, { padding: [40, 40], maxZoom: 18 });
      msg('LCP ' + q + ': ' + ids.length + ' NAPs');
      return;
    }
    var hits = suggest(q, 2);
    if (hits.length === 1) { el('search').value = hits[0]; return doSearch(); }
    msg(hits.length ? 'Several matches: pick one from the list.' : 'No NAP, LCP or OLT matches "' + q + '".');
  }
  function suggest(q, max) {
    var out = [];
    D.olts.forEach(function (o) { if (out.length < max && norm(o.id).indexOf(q) === 0) out.push(o.id); });
    for (var i = 0; i < NN && out.length < max; i++) if (norm(N.id[i]).indexOf(q) === 0) out.push(N.id[i]);
    return out;
  }
  var sugTimer;
  el('search').addEventListener('input', function () {
    clearTimeout(sugTimer);
    var q = norm(this.value);
    sugTimer = setTimeout(function () {
      var dl = el('searchList'); dl.innerHTML = '';
      if (q.length < 2) return;
      suggest(q, 15).forEach(function (s) { dl.appendChild(opt(s, '')); });
    }, 150);
  });
  el('search').addEventListener('keydown', function (e) { if (e.key === 'Enter') doSearch(); });
  el('searchBtn').addEventListener('click', doSearch);

  // panel show/hide
  el('panelToggle').addEventListener('click', function () { el('app').classList.add('collapsed'); map.invalidateSize(); });
  el('panelShow').addEventListener('click', function () { el('app').classList.remove('collapsed'); map.invalidateSize(); });
  if (window.innerWidth < 700) el('app').classList.add('collapsed');

  // legend + meta
  var legend = [3, 2, 1, 0].map(function (lv) {
    return '<div class="leg"><span class="sw" style="background:' + COL[lv] + '"></span>' + LV[lv] +
      ' <span class="hint">' + ['0–2 used', '3–4 used', '5–6 used', '7–8 used'][lv] + '</span></div>';
  }).join('') +
    '<div class="leg"><span class="olt-icon" style="display:inline-block;width:12px;height:12px;border-width:2px;background:#ccc;margin:0 3px"></span>OLT (color = OLT utilization; approximate location)</div>' +
    '<div class="leg"><span class="pc" style="width:18px;height:18px;background:conic-gradient(' + COL[3] + ' 0 90deg,' + COL[2] + ' 90deg 200deg,' + COL[0] + ' 200deg 360deg)"><span style="width:11px;height:11px"></span></span>Cluster: ring shows the level mix; click to zoom or fan out stacked NAPs</div>' +
    '<div class="leg"><svg width="26" height="10"><line x1="1" y1="5" x2="18" y2="5" stroke="' + COL[3] + '" stroke-width="3"/><polygon points="18,1 25,5 18,9" fill="' + COL[3] + '"/></svg>Relocation: Low NAP (black ring) → Risk/High hotspot</div>' +
    '<div class="sl">Choropleths (port utilization of the area)</div>' +
    ['&lt; 30%', '30–60%', '60–80%', '&gt; 80%'].map(function (t, lv) {
      return '<div class="leg"><span class="sq" style="background:' + COL[lv] + ';opacity:.6"></span>' + t + '</div>';
    }).join('') +
    '<div class="hint" style="margin-top:6px">Heat maps, choropleths and demand hotspots: use the layer switcher (top right). Heat maps show up to zoom 17.</div>';
  el('legend').innerHTML = legend;
  el('meta').innerHTML = 'Data: ' + esc(M.raw) + (M.tableau ? ' + ' + esc(M.tableau) : '') + '<br>Built ' + esc(M.generated) +
    ' · utilized = ' + esc(M.utilized.join(' + ')) + '<br>OLT locations are approximate (centroid of their NAPs) unless a site file was provided.';

  // layer switcher
  var overlays = {
    'NAPs': cluster, 'OLTs': oltLayer, 'Relocation recommendations': relocLayer, 'Demand hotspots (Risk/High groups)': hotLayer,
    'Heat: Risk NAPs': heats[3], 'Heat: High NAPs': heats[2], 'Heat: Optimal NAPs': heats[1], 'Heat: Low NAPs': heats[0],
    'Choropleth: barangay utilization': choroB, 'Choropleth: municipality utilization': choroM, 'Municipality boundaries': outline
  };
  L.control.layers(bases, overlays, { collapsed: window.innerWidth < 1100 }).addTo(map);
  L.control.scale({ imperial: false }).addTo(map);
  map.on('overlayadd', function (e) { if (heats.indexOf(e.layer) >= 0) refreshHeat(); });
  function zoomClass() {
    var z = map.getZoom(), c = map.getContainer().classList;
    c.toggle('zlow', z < 11); c.toggle('zmid', z >= 11 && z < 14);
    relocSrc.forEach(function (m) { m.setRadius(srcRadius()); });
    var al = arrowLen();
    relocHeads.forEach(function (h) { h.setLatLngs(arrowHead(h._ab[0], h._ab[1], al)); });
  }
  map.on('zoomend', zoomClass);
  zoomClass();

  fillBrgy(); fillOlt();
  applyFilters();
  window.pegasus = { map: map, cluster: cluster, state: state, applyFilters: applyFilters, gotoNap: gotoNap, napIndex: napIndex, data: D };
})();
