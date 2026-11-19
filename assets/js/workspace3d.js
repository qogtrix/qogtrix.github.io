/* AI Engineering Laboratory — 3D workspace (Stage 1).
   Three.js is used ONLY for geometry visualisation. The presets below
   are conceptual geometry (a shaft, a frame, a wing, an arm, a lattice,
   a circuit board). They are NOT engineering models and NOT simulations.
   Geometry statistics are read from the real Three.js objects. */
(function () {
  'use strict';
  var PRESETS = {
    shaft: { label: 'Shaft + bearing (Mechanical)', build: buildShaft },
    frame: { label: 'Beam + column frame (Structural)', build: buildFrame },
    wing: { label: 'Wing section (Aerospace)', build: buildWing },
    arm: { label: 'Robot arm, 3 segments (Robotics)', build: buildArm },
    lattice: { label: 'Crystal lattice (Materials)', build: buildLattice },
    board: { label: 'Circuit board (Electrical)', build: buildBoard }
  };
  var scene, camera, renderer, controls, group, grid, axes, autoRotate = false, wireframe = false;

  function mat(color, opts) {
    var m = new (window.THREE.MeshStandardMaterial)(Object.assign({ color: color, metalness: 0.55, roughness: 0.4 }, opts || {}));
    return m;
  }
  function box(w, h, d, color, x, y, z) { var m = new window.THREE.Mesh(new window.THREE.BoxGeometry(w, h, d), mat(color)); m.position.set(x, y, z); return m; }
  function cyl(rt, rb, h, color, x, y, z, rotZ) { var m = new window.THREE.Mesh(new window.THREE.CylinderGeometry(rt, rb, h, 32), mat(color)); m.position.set(x, y, z); if (rotZ) m.rotation.z = rotZ; return m; }
  function sphere(r, color, x, y, z) { var m = new window.THREE.Mesh(new window.THREE.SphereGeometry(r, 24, 18), mat(color, { metalness: 0.2, roughness: 0.5 })); m.position.set(x, y, z); return m; }

  function buildShaft(g) {
    g.add(cyl(0.35, 0.35, 4.4, 0x38bdf8, 0, 1.2, 0, Math.PI / 2));
    g.add(cyl(0.55, 0.55, 0.5, 0x94a3b8, -1.4, 1.2, 0, Math.PI / 2));
    g.add(cyl(0.55, 0.55, 0.5, 0x94a3b8, 1.4, 1.2, 0, Math.PI / 2));
    g.add(box(0.7, 0.5, 0.7, 0x64748b, -1.4, 0.5, 0)); g.add(box(0.7, 0.5, 0.7, 0x64748b, 1.4, 0.5, 0));
  }
  function buildFrame(g) {
    g.add(box(0.25, 3, 0.25, 0x38bdf8, -1.5, 1.5, 0)); g.add(box(0.25, 3, 0.25, 0x38bdf8, 1.5, 1.5, 0));
    g.add(box(3.4, 0.25, 0.25, 0x818cf8, 0, 3, 0)); g.add(box(3.4, 0.2, 0.2, 0x64748b, 0, 1.6, 0));
    g.add(box(0.18, 1.9, 0.18, 0x94a3b8, -0.75, 2.3, 0)); g.add(box(0.18, 1.9, 0.18, 0x94a3b8, 0.75, 2.3, 0));
  }
  function buildWing(g) {
    var shape = new window.THREE.Shape();
    shape.moveTo(-1.6, 0); shape.quadraticCurveTo(0, 0.55, 1.6, 0.05); shape.quadraticCurveTo(0, -0.08, -1.6, 0);
    var geo = new window.THREE.ExtrudeGeometry(shape, { depth: 0.9, bevelEnabled: false });
    var mesh = new window.THREE.Mesh(geo, mat(0x38bdf8)); mesh.position.set(0, 1.4, -0.45); g.add(mesh);
    g.add(box(0.12, 0.9, 0.12, 0x94a3b8, 0, 0.7, 0));
  }
  function buildArm(g) {
    g.add(cyl(0.55, 0.7, 0.4, 0x64748b, 0, 0.2, 0));
    var s1 = box(0.35, 1.6, 0.35, 0x38bdf8, 0, 1.2, 0); s1.rotation.z = 0.25; g.add(s1);
    var j1 = sphere(0.3, 0xfbbf24, 0.4, 2.0, 0); g.add(j1);
    var s2 = box(0.3, 1.4, 0.3, 0x818cf8, 0.95, 2.5, 0); s2.rotation.z = -0.5; g.add(s2);
    g.add(sphere(0.22, 0x34d399, 1.45, 3.0, 0));
  }
  function buildLattice(g) {
    var cols = [0x38bdf8, 0xf87171];
    for (var ix = 0; ix < 3; ix++) for (var iy = 0; iy < 3; iy++) for (var iz = 0; iz < 3; iz++) {
      g.add(sphere(0.16, cols[(ix + iy + iz) % 2], ix - 1, iy + 0.3, iz - 1));
    }
    g.add(box(2.3, 0.05, 0.05, 0x475569, 0, 0.3, -1)); g.add(box(2.3, 0.05, 0.05, 0x475569, 0, 2.3, -1));
  }
  function buildBoard(g) {
    g.add(box(3.2, 0.12, 2.2, 0x166534, 0, 0.7, 0));
    g.add(box(0.9, 0.25, 0.9, 0x1f2937, -0.8, 0.9, 0)); g.add(box(0.5, 0.35, 0.35, 0x94a3b8, 0.7, 0.95, -0.5));
    for (var i = 0; i < 5; i++) g.add(cyl(0.12, 0.12, 0.3, 0xfbbf24, -1.2 + i * 0.6, 0.95, 0.7));
  }

  function geometryStats() {
    var verts = 0, tris = 0;
    if (!group) return { verts: 0, tris: 0 };
    group.traverse(function (o) {
      if (o.isMesh) {
        var p = o.geometry.attributes.position; if (p) verts += p.count;
        if (o.geometry.index) tris += o.geometry.index.count / 3; else if (p) tris += p.count / 3;
      }
    });
    return { verts: Math.round(verts), tris: Math.round(tris) };
  }
  function updateStats(presetKey) {
    var el = document.getElementById('viewer-stats'); if (!el) return;
    var s = geometryStats();
    el.textContent = 'Preset: ' + (PRESETS[presetKey] ? PRESETS[presetKey].label : presetKey) +
      '  •  Vertices: ' + s.verts.toLocaleString() + '  •  Triangles: ' + s.tris.toLocaleString() +
      '  •  Conceptual geometry preview — not a simulation';
  }
  function setPreset(key) {
    if (!PRESETS[key] || !group) return;
    while (group.children.length) { var c = group.children.pop(); if (c.geometry) c.geometry.dispose(); }
    PRESETS[key].build(group);
    group.traverse(function (o) { if (o.isMesh) o.material.wireframe = wireframe; });
    updateStats(key);
    var sel = document.getElementById('preset-select'); if (sel) sel.value = key;
  }
  function resetView() {
    if (!camera || !controls) return;
    camera.position.set(4.5, 3.5, 6); controls.target.set(0, 1.2, 0); controls.update();
  }
  function init() {
    var container = document.getElementById('viewer');
    if (!container) return;
    var preset = container.getAttribute('data-preset') || 'shaft';
    if (typeof window.THREE === 'undefined') {
      container.innerHTML = '<div class="viewer-fallback"><b>Three.js could not be loaded.</b><br>Check your internet connection and reload. The rest of the site still works.</div>';
      return;
    }
    try {
      var test = document.createElement('canvas');
      if (!(test.getContext('webgl') || test.getContext('experimental-webgl'))) throw new Error('WebGL unavailable');
    } catch (e) {
      container.innerHTML = '<div class="viewer-fallback"><b>WebGL is not available in this browser.</b><br>Try another browser to use the 3D workspace.</div>';
      return;
    }
    scene = new window.THREE.Scene(); scene.background = new window.THREE.Color(0x0a0e13);
    camera = new window.THREE.PerspectiveCamera(45, container.clientWidth / 480, 0.1, 100);
    renderer = new window.THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setSize(container.clientWidth, 480); renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);
    var OrbitControls = window.OrbitControls;
    controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true;
    scene.add(new window.THREE.AmbientLight(0xffffff, 0.7));
    var dir = new window.THREE.DirectionalLight(0xffffff, 1.2); dir.position.set(5, 8, 5); scene.add(dir);
    grid = new window.THREE.GridHelper(8, 16, 0x38bdf8, 0x223047); scene.add(grid);
    axes = new window.THREE.AxesHelper(1.5); scene.add(axes);
    group = new window.THREE.Group(); scene.add(group);
    resetView(); setPreset(preset);
    function animate() { requestAnimationFrame(animate); controls.autoRotate = autoRotate; controls.update(); renderer.render(scene, camera); }
    animate();
    window.addEventListener('resize', function () {
      camera.aspect = container.clientWidth / 480; camera.updateProjectionMatrix(); renderer.setSize(container.clientWidth, 480);
    });
    // Controls
    var sel = document.getElementById('preset-select');
    if (sel) sel.addEventListener('change', function () { setPreset(sel.value); });
    var wf = document.getElementById('toggle-wireframe');
    if (wf) wf.addEventListener('click', function () { wireframe = !wireframe; group.traverse(function (o) { if (o.isMesh) o.material.wireframe = wireframe; }); wf.textContent = wireframe ? 'Wireframe: On' : 'Wireframe: Off'; });
    var rot = document.getElementById('toggle-rotate');
    if (rot) rot.addEventListener('click', function () { autoRotate = !autoRotate; rot.textContent = autoRotate ? 'Auto-rotate: On' : 'Auto-rotate: Off'; });
    var gr = document.getElementById('toggle-grid');
    if (gr) gr.addEventListener('click', function () { grid.visible = !grid.visible; axes.visible = grid.visible; gr.textContent = grid.visible ? 'Grid: On' : 'Grid: Off'; });
    var rs = document.getElementById('reset-view');
    if (rs) rs.addEventListener('click', resetView);
    var shot = document.getElementById('export-shot');
    if (shot) shot.addEventListener('click', function () {
      renderer.render(scene, camera);
      var a = document.createElement('a'); a.href = renderer.domElement.toDataURL('image/png');
      a.download = 'aielab-3d-' + preset + '.png'; a.click();
    });
    window.AIELAB_SET_PRESET = setPreset;
  }
  document.addEventListener('DOMContentLoaded', init);
})();
