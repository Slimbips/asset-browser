import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const gamepath = document.getElementById("gamepath");
const status = document.getElementById("status");
const listEl = document.getElementById("list");
const filterEl = document.getElementById("filter");
const catsEl = document.getElementById("cats");
const hint = document.getElementById("hint");
const meta = document.getElementById("meta");
const matlog = document.getElementById("matlog-body");
const canvas = document.getElementById("view");
const dbgBones = document.getElementById("dbg-bones");
const dbgSurfaces = document.getElementById("dbg-surfaces");
const crumbEl = document.getElementById("crumb");
const countEl = document.getElementById("asset-count");
const metaBody = document.getElementById("meta-body");
const depsBody = document.getElementById("deps-body");
const logEl = document.getElementById("log");
const queueEl = document.getElementById("queue");
const dashGrid = document.getElementById("dash-grid");
const sidenav = document.getElementById("sidenav");

let assets = [];
let cat = "weapons";
let dir = "";
let current = null;
let page = "browser";
let lastMesh = null;
let lastFrame = null;
let queue = [];
let jobSeq = 0;
let logs = [];

const CAT_LABELS = {
  maps: "Maps",
  weapons: "Weapons",
  characters: "Characters",
  vehicles: "Vehicles",
  props: "Props",
  textures: "Textures",
  fx: "FX",
  all: "All",
};

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.22;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.position.set(80, 40, 80);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
const hemi = new THREE.HemisphereLight(0xc8d8ff, 0x1a1208, 1.2);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(40, 80, 20);
scene.add(sun);
const studio = new THREE.Group();
studio.name = "studio-lights";
const keyLight = new THREE.DirectionalLight(0xfff3e4, 3.6);
const fillLight = new THREE.DirectionalLight(0x9eb4d4, 0.7);
const rimLight = new THREE.DirectionalLight(0xdde8ff, 1.35);
const lamp = new THREE.SpotLight(0xfff6ea, 7.5, 0, Math.PI / 5.2, 0.62, 1);
studio.add(keyLight, keyLight.target, fillLight, fillLight.target, rimLight, rimLight.target, lamp, lamp.target);
scene.add(studio);
studio.visible = false;
const ground = new THREE.Mesh(
  new THREE.CircleGeometry(40, 48),
  new THREE.MeshStandardMaterial({ color: 0x151c2c, roughness: 1, metalness: 0 })
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -8;
scene.add(ground);
let pedestal = null;
let pedestalLoad = null;
let model = null;
let boneHelper = null;
let surfaceHelper = null;
let lastSkeleton = [];

function resize() {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
document.addEventListener("fullscreenchange", resize);

function frame() {
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(frame);
}

async function api(url) {
  const r = await fetch(url);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function esc(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function assetDir(path) {
  const p = (path || "").replace(/\\/g, "/");
  const i = p.lastIndexOf("/");
  return i <= 0 ? "" : p.slice(0, i);
}

function inCat(a) {
  if (cat === "all") return true;
  if (cat === "maps") return a.kind === "map" || (a.ext || "").toLowerCase() === ".bsp";
  return a.category === cat;
}

function browsePath(a) {
  return ((a.list_path || a.path || "") + "").replace(/\\/g, "/");
}

function isTextureAsset(a) {
  if (!a) return false;
  if (a.kind === "texture") return true;
  const e = (a.ext || "").toLowerCase();
  return e === ".tga" || e === ".jpg" || e === ".jpeg" || e === ".png" || e === ".dds";
}

function texUrl(path, size) {
  let u = "/api/tex?path=" + encodeURIComponent(path || "");
  if (size) u += "&w=" + size;
  return u;
}

function previewable(a) {
  return !!(isTextureAsset(a) || a.skelmodel || a.kind === "map" || (a.ext || "").toLowerCase() === ".bsp");
}

function coveredByTik(a, pool) {
  if ((a.ext || "").toLowerCase() !== ".skd") return false;
  const folder = assetDir(a.path);
  return pool.some((t) => {
    if ((t.ext || "").toLowerCase() !== ".tik") return false;
    if (t.skelmodel === a.path) return true;
    if ((t.skelmodels || []).some((s) => s === a.path)) return true;
    return assetDir(t.path) === folder && t.skelmodel;
  });
}

function listingPool() {
  const base = assets.filter((a) => {
    if (!inCat(a)) return false;
    if (isTextureAsset(a)) return cat === "textures";
    return previewable(a);
  });
  return base.filter((a) => !coveredByTik(a, base));
}

function kidsIn(pool, folderPath) {
  const prefix = folderPath + "/";
  return pool.filter((a) => {
    const p = browsePath(a);
    return p === folderPath || p.startsWith(prefix);
  });
}

function commonDir(pool) {
  const segs = pool
    .map((a) => browsePath(a).split("/").slice(0, -1))
    .filter((s) => s.length);
  if (!segs.length) return "";
  let i = 0;
  while (true) {
    const part = segs[0][i];
    if (!part || !segs.every((s) => s[i] === part)) break;
    i++;
  }
  return segs[0].slice(0, i).join("/");
}

function usesCatHome() {
  return cat !== "all" && cat !== "textures";
}

function catHomeDir(pool) {
  const root = commonDir(pool);
  if (!usesCatHome()) return root;
  const split = splitLevel(pool, root);
  if (!split.keptFolders.length) return root;
  const candidates = split.keptFolders.filter((f) => splitLevel(pool, f.folderPath).files.length > 0);
  if (!candidates.length) return root;
  let best = candidates[0];
  for (const f of candidates) {
    if (f.kids.length > best.kids.length) best = f;
    else if (f.kids.length === best.kids.length && f.name.toLowerCase() === cat) best = f;
  }
  if (split.files.length >= best.kids.length) return root;
  return best.folderPath;
}

function pinSort(a, b) {
  return b.kids.length - a.kids.length || a.name.localeCompare(b.name);
}

function defaultDir(pool) {
  return catHomeDir(pool);
}

function typeLabel(a) {
  if (isTextureAsset(a)) return "Texture";
  if (a.kind === "map" || (a.ext || "").toLowerCase() === ".bsp") return "Map";
  return CAT_LABELS[a.category] || a.category || "Asset";
}

function skelTiltX(asset) {
  // SKD is Z-up. Characters/props: +Z is head/top. Weapons are authored
  // with the grip/clip on +Z, so the same tilt leaves them upside down.
  if (asset && asset.category === "weapons") return Math.PI / 2;
  return -Math.PI / 2;
}

function orientPreviewGroup(group, asset) {
  if (!asset || asset.category !== "weapons") {
    group.rotation.x = skelTiltX(asset);
    // Yaw in world space after the Z-up tilt. Euler Y would tumble them
    // onto their side because it runs in local axes.
    if (asset && asset.category === "characters") {
      group.rotateOnWorldAxis(new THREE.Vector3(0, 1, 0), -Math.PI / 2);
    }
    return;
  }
  group.updateMatrixWorld(true);
  const raw = new THREE.Box3().setFromObject(group).getSize(new THREE.Vector3());
  // Viewmodels store height on +Z. World pickups already have height on Y;
  // tilting those puts the camera on the top of the gun.
  if (raw.z >= raw.y) group.rotation.x = Math.PI / 2;
}

function formatSize(n) {
  const b = Number(n) || 0;
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  return (b / (1024 * 1024)).toFixed(1) + " MB";
}

function setStatus(text, kind) {
  status.className = kind || "ready";
  status.innerHTML = "<i></i> " + esc(text);
}

function logStamp() {
  const d = new Date();
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");
}

function logLine(msg) {
  logs.push("[" + logStamp() + "] " + msg);
  logs = logs.slice(-200);
  renderLog();
}

function renderLog() {
  if (!logEl) return;
  if (!logs.length) {
    logEl.innerHTML = `<p class="muted">No log output.</p>`;
    return;
  }
  logEl.innerHTML = logs
    .map((line) => {
      const m = /^\[([^\]]+)\]\s*(.*)$/.exec(line);
      if (!m) return `<div class="log-line">${esc(line)}</div>`;
      return `<div class="log-line"><span class="log-time">[${esc(m[1])}]</span> ${esc(m[2])}</div>`;
    })
    .join("");
  logEl.scrollTop = logEl.scrollHeight;
}

function countsMap() {
  const counts = {};
  for (const a of assets) {
    if (!previewable(a) && a.category !== "textures") continue;
    counts[a.category] = (counts[a.category] || 0) + 1;
  }
  return counts;
}

function openCat(next) {
  cat = next;
  dir = defaultDir(listingPool());
  renderCats();
  renderList();
  syncNav();
}

function showPage(next, nextCat) {
  page = next;
  document.getElementById("page-browser").hidden = next !== "browser";
  document.getElementById("page-dashboard").hidden = next !== "dashboard";
  document.getElementById("page-settings").hidden = next !== "settings";
  if (nextCat) openCat(nextCat);
  if (next === "dashboard") renderDash();
  syncNav();
}

function syncNav() {
  for (const b of sidenav.querySelectorAll("button")) {
    const nav = b.dataset.nav;
    const c = b.dataset.cat;
    let on = false;
    if (nav === "dashboard" || nav === "settings") on = page === nav;
    else on = page === "browser" && c === cat;
    b.classList.toggle("on", on);
  }
}

function renderCrumb() {
  if (!crumbEl) return;
  const home = usesCatHome() ? catHomeDir(listingPool()) : "";
  const hideTrail = !!(home && dir === home);
  const bits = [`<button type="button" data-dir="${esc(home || "")}">${esc(CAT_LABELS[cat] || cat)}</button>`];
  const parts = hideTrail ? [] : dir ? dir.split("/").filter(Boolean) : [];
  let acc = "";
  for (const part of parts) {
    acc = acc ? acc + "/" + part : part;
    bits.push(`<span class="sep">/</span><button type="button" data-dir="${esc(acc)}">${esc(part)}</button>`);
  }
  crumbEl.innerHTML = bits.join("");
}

function thumbStyle(a) {
  if (a && a._thumb) return `style="background-image:url('${a._thumb}')"`;
  return "";
}

function cardHtml(a) {
  const on = current && current.id === a.id ? " on" : "";
  const label = typeLabel(a);
  return `<article data-id="${esc(a.id)}" class="card file${on}">
    <div class="thumb" ${thumbStyle(a)}>${a._thumb ? "" : esc(label.slice(0, 3))}</div>
    <div class="body"><span class="name">${esc(a.display_name || a.name)}</span>
    <small>${esc(label)} · ${formatSize(a.size)}</small></div></article>`;
}

function folderCard(name, folderPath, kids, extraClass) {
  const sample = kids.find((a) => a._thumb) || kids[0];
  const has = !!(sample && sample._thumb);
  const cls = extraClass ? " " + extraClass : "";
  return `<article class="card folder${cls}" data-dir="${esc(folderPath)}">
    <div class="thumb folder-thumb${has ? " has-thumb" : ""}" ${has ? thumbStyle(sample) : ""}></div>
    <div class="body"><span class="name">${esc(name)}</span>
    <small>${kids.length} assets</small></div></article>`;
}

function splitLevel(pool, at) {
  const folders = new Map();
  const files = [];
  const prefix = at ? at + "/" : "";
  for (const a of pool) {
    const p = browsePath(a);
    if (at) {
      if (!p.startsWith(prefix) && p !== at) continue;
      if (p === at || assetDir(p) === at) {
        files.push(a);
        continue;
      }
      const next = p.slice(prefix.length).split("/")[0];
      if (next) folders.set(next, (folders.get(next) || 0) + 1);
    } else {
      const next = p.split("/")[0];
      if (p.includes("/")) folders.set(next, (folders.get(next) || 0) + 1);
      else files.push(a);
    }
  }
  const keptFolders = [];
  for (const [name] of folders) {
    const folderPath = at ? at + "/" + name : name;
    const kids = kidsIn(pool, folderPath);
    if (kids.length === 1) files.push(kids[0]);
    else keptFolders.push({ name, folderPath, kids });
  }
  keptFolders.sort((a, b) => a.name.localeCompare(b.name));
  files.sort((a, b) => a.name.localeCompare(b.name));
  return { keptFolders, files };
}

function renderList() {
  const q = filterEl.value.trim().toLowerCase();
  const pool = listingPool();
  if (q) {
    const rows = pool.filter((a) => (a.name + a.path + (a.display_name || "") + browsePath(a)).toLowerCase().includes(q));
    listEl.innerHTML = rows.slice(0, 400).map(cardHtml).join("") || `<p class="muted">No matches.</p>`;
    renderCrumb();
    observeThumbs();
    return;
  }
  const home = usesCatHome() ? catHomeDir(pool) : "";
  if (home && (!dir || dir === assetDir(home))) dir = home;
  let split = splitLevel(pool, dir);
  while (split.keptFolders.length === 1 && split.files.length === 0) {
    if (home && split.keptFolders[0].folderPath === home) break;
    dir = split.keptFolders[0].folderPath;
    split = splitLevel(pool, dir);
  }
  const pins =
    home && dir === home
      ? splitLevel(pool, assetDir(home))
          .keptFolders.filter((f) => f.folderPath !== home)
          .sort(pinSort)
      : [];
  const parent = home && assetDir(dir) === assetDir(home) ? home : assetDir(dir);
  const showUp = dir && dir !== home;
  const up =
    showUp &&
    `<article class="card folder up" data-dir="${esc(parent)}">
      <div class="body"><span class="name">↑ Up</span><small>${esc(dir)}</small></div></article>`;
  listEl.innerHTML =
    (up || "") +
    pins.map((f) => folderCard(f.name, f.folderPath, f.kids, "pin")).join("") +
    split.keptFolders.map((f) => folderCard(f.name, f.folderPath, f.kids)).join("") +
    split.files.slice(0, 400).map(cardHtml).join("");
  renderCrumb();
  observeThumbs();
}

function renderCats() {
  const counts = countsMap();
  const keys = ["all", "weapons", "characters", "maps", "vehicles", "props", "textures"];
  catsEl.innerHTML = keys
    .map((k) => {
      const n = k === "all" ? assets.filter((a) => previewable(a)).length : counts[k] || 0;
      return `<button type="button" data-cat="${k}" class="${k === cat ? "on" : ""}">${CAT_LABELS[k] || k}<span class="n">${n}</span></button>`;
    })
    .join("");
}

function renderDash() {
  const counts = countsMap();
  const keys = ["maps", "characters", "weapons", "vehicles", "props", "textures"];
  dashGrid.innerHTML = keys
    .map(
      (k) =>
        `<article class="dash-card" data-cat="${k}"><span>${CAT_LABELS[k]}</span><b>${counts[k] || 0}</b></article>`
    )
    .join("");
}

function boneLabelTexture(text) {
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 48;
  const g = c.getContext("2d");
  g.fillStyle = "rgba(0,0,0,0.55)";
  g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = "#ffe08a";
  g.font = "22px Segoe UI, sans-serif";
  g.fillText(text, 10, 32);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function makeSurfaceLabels(data, groups) {
  const group = new THREE.Group();
  group.name = "surface-labels";
  const pos = data.positions || [];
  const idx = data.indices || [];
  for (const g of groups) {
    const start = g.start || 0;
    const count = g.count || 0;
    if (count < 3) continue;
    let x = 0;
    let y = 0;
    let z = 0;
    let n = 0;
    for (let i = 0; i < count; i++) {
      const vi = idx[start + i] * 3;
      if (vi + 2 >= pos.length) continue;
      x += pos[vi];
      y += pos[vi + 1];
      z += pos[vi + 2];
      n++;
    }
    if (!n) continue;
    const spr = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: boneLabelTexture(g.surface || g.name || "?"),
        depthTest: false,
      })
    );
    spr.position.set(x / n, y / n, z / n);
    spr.scale.set(22, 4.2, 1);
    group.add(spr);
  }
  group.visible = !!(dbgSurfaces && dbgSurfaces.checked);
  return group;
}

function makeBoneHelper(skeleton, size) {
  const group = new THREE.Group();
  group.name = "bones";
  const s = Math.max(size * 0.015, 0.35);
  const positions = [];
  for (const b of skeleton) {
    const sph = new THREE.Mesh(
      new THREE.SphereGeometry(s, 10, 8),
      new THREE.MeshBasicMaterial({ color: 0xffcc44 })
    );
    sph.position.set(b.pos[0], b.pos[1], b.pos[2]);
    group.add(sph);
    const spr = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: boneLabelTexture(b.index + " " + b.name), depthTest: false })
    );
    spr.position.set(b.pos[0], b.pos[1] + s * 2.2, b.pos[2]);
    spr.scale.set(s * 14, s * 2.6, 1);
    group.add(spr);
    if (b.parent_index >= 0 && skeleton[b.parent_index]) {
      const p = skeleton[b.parent_index].pos;
      positions.push(p[0], p[1], p[2], b.pos[0], b.pos[1], b.pos[2]);
    }
  }
  if (positions.length) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    group.add(new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ color: 0x66ddff })));
  }
  group.visible = !!(dbgBones && dbgBones.checked);
  return group;
}

function ensurePedestal() {
  if (pedestal) return Promise.resolve(pedestal);
  if (!pedestalLoad) {
    pedestalLoad = new GLTFLoader()
      .loadAsync("/pedestal.glb?v=1")
      .then((gltf) => {
        pedestal = gltf.scene;
        pedestal.name = "weapon-pedestal";
        pedestal.traverse((o) => {
          if (o.isMesh) {
            o.castShadow = true;
            o.receiveShadow = true;
          }
        });
        scene.add(pedestal);
        pedestal.visible = false;
        return pedestal;
      })
      .catch((err) => {
        console.warn("pedestal", err);
        pedestalLoad = null;
        return null;
      });
  }
  return pedestalLoad;
}

function hidePedestal() {
  if (!pedestal) return;
  pedestal.visible = false;
  pedestal.scale.set(1, 1, 1);
  pedestal.position.set(0, 0, 0);
}

function setStudioLighting(center, dist, on) {
  studio.visible = on;
  hemi.intensity = on ? 0.42 : 1.2;
  sun.intensity = on ? 0.04 : 1.4;
  if (!on) return;
  const aim = center.clone();
  const d = Math.max(dist * 1.2, 10);
  keyLight.position.copy(aim).add(new THREE.Vector3(-1.05, 0.95, 0.45).normalize().multiplyScalar(d));
  keyLight.target.position.copy(aim);
  fillLight.position.copy(aim).add(new THREE.Vector3(1.05, 0.22, 0.38).normalize().multiplyScalar(d));
  fillLight.target.position.copy(aim);
  rimLight.position.copy(aim).add(new THREE.Vector3(0.28, 0.52, -1).normalize().multiplyScalar(d));
  rimLight.target.position.copy(aim);
  lamp.position.copy(aim).add(new THREE.Vector3(0.22, 1.5, 0.95).normalize().multiplyScalar(d * 0.72));
  lamp.target.position.copy(aim);
  lamp.distance = d * 3.2;
  lamp.castShadow = true;
  keyLight.castShadow = true;
  const r = Math.max(dist * 0.5, 6);
  keyLight.shadow.mapSize.set(1024, 1024);
  keyLight.shadow.bias = -0.0006;
  keyLight.shadow.normalBias = 0.03;
  const cam = keyLight.shadow.camera;
  cam.left = cam.bottom = -r;
  cam.right = cam.top = r;
  cam.near = 0.5;
  cam.far = d * 3;
  cam.updateProjectionMatrix();
  lamp.shadow.mapSize.set(1024, 1024);
  lamp.shadow.bias = -0.0005;
  lamp.shadow.normalBias = 0.04;
  keyLight.target.updateMatrixWorld();
  fillLight.target.updateMatrixWorld();
  rimLight.target.updateMatrixWorld();
  lamp.target.updateMatrixWorld();
}

function placePedestalUnder(object) {
  if (!pedestal || !object) return;
  object.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(object);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  pedestal.visible = true;
  pedestal.scale.set(1, 1, 1);
  pedestal.position.set(0, 0, 0);
  pedestal.updateMatrixWorld(true);
  const native = new THREE.Box3().setFromObject(pedestal);
  const nativeSize = native.getSize(new THREE.Vector3());
  const want = Math.max(size.x, size.z) * 0.95;
  const have = Math.max(nativeSize.x, nativeSize.z, 0.001);
  pedestal.scale.setScalar(want / have);
  pedestal.updateMatrixWorld(true);
  const scaled = new THREE.Box3().setFromObject(pedestal);
  const gap = Math.max(size.y * 0.015, 0.25);
  pedestal.position.set(
    center.x - (scaled.min.x + scaled.max.x) * 0.5,
    box.min.y - gap - scaled.max.y,
    center.z - (scaled.min.z + scaled.max.z) * 0.5
  );
}

function clearModel() {
  if (!model) return;
  scene.remove(model);
  model.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) {
      const mats = Array.isArray(o.material) ? o.material : [o.material];
      for (const m of mats) {
        if (m.map) m.map.dispose();
        m.dispose();
      }
    }
  });
  model = null;
  boneHelper = null;
}

function checkerboardTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  for (let y = 0; y < 8; y++) {
    for (let x = 0; x < 8; x++) {
      g.fillStyle = (x + y) % 2 ? "#e14cff" : "#111111";
      g.fillRect(x * 8, y * 8, 8, 8);
    }
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = THREE.RepeatWrapping;
  t.wrapT = THREE.RepeatWrapping;
  t.repeat.set(8, 8);
  t.colorSpace = THREE.SRGBColorSpace;
  t.needsUpdate = true;
  t.magFilter = THREE.NearestFilter;
  t.minFilter = THREE.NearestFilter;
  return t;
}

function renderMatLog(materials, skinLog, pose, skeleton, visibilityNote) {
  const blocks = [];
  const found = (materials || []).filter((m) => m.status === "FOUND" || m.status === "SKY").length;
  const total = (materials || []).length;
  if (total) {
    blocks.push(`<div class="row sum">textures ${found}/${total} found</div>`);
  }
  if (pose) {
    blocks.push(`<div class="row dim">pose: ${pose}</div>`);
  }
  if (visibilityNote) {
    blocks.push(`<div class="row dim">${visibilityNote}</div>`);
  }
  if (skeleton && skeleton.length) {
    const lines = skeleton
      .map((b) => {
        const p = b.parent_index >= 0 ? skeleton[b.parent_index]?.name : "world";
        return `${b.index} ${b.name} (${b.type}) &lt;- ${p}  [${b.pos.map((n) => n.toFixed(2)).join(", ")}]`;
      })
      .join("\n");
    blocks.push(`<div class="row dim">bones\n${lines}</div>`);
  }
  if (materials && materials.length) {
    blocks.push(
      materials
        .map((m) => {
          const st = m.status === "FOUND" || m.status === "SKY" ? "found" : m.status === "NODRAW" ? "nodraw" : "missing";
          const tex = m.texture || "(none)";
          const src = m.source ? ` [${m.source}]` : "";
          const def = m.shader_file
            ? `\n  def: ${m.shader_def}  (${m.shader_file})`
            : "\n  def: (no .shader — implicit image)";
          const miss = m.missing ? `\n  ${m.missing}` : "";
          const notes = m.notes && m.notes.length ? `\n  ${m.notes.join(" · ")}` : "";
          return `<div class="row ${st}"><strong>${m.surface}</strong> -&gt; ${m.shader || "(none)"} -&gt; ${tex}${src} -&gt; ${m.status}
<span class="dim">  from: ${m.shader_from}${def}${notes}${miss}</span></div>`;
        })
        .join("")
    );
  }
  if (skinLog && skinLog.length) {
    blocks.push(
      skinLog
        .map((s) => {
          const lb = s.local_bounds || {};
          const wb = s.world_bounds || {};
          const fmt = (b) =>
            b && b.min
              ? `[${b.min.map((n) => n.toFixed(1)).join(",")}] .. [${b.max.map((n) => n.toFixed(1)).join(",")}]`
              : "";
          return `<div class="row dim"><strong>${s.surface}</strong>${s.nodraw ? " [NODRAW]" : ""}
  verts ${s.vertex_count} · tris ${s.triangle_count ?? "?"} · weights ${s.num_weights}${s.weight_max ? ` (${Number(s.weight_min).toFixed(2)}–${Number(s.weight_max).toFixed(2)})` : ""} · bones ${JSON.stringify(s.bone_names || s.bone_indices)}${s.hide_reason ? `\n  ${s.hide_reason}` : ""}
  local ${fmt(lb)}
  world ${fmt(wb)}</div>`;
        })
        .join("")
    );
  }
  matlog.innerHTML = blocks.join("") || "No surfaces.";
}

function applyRenderMode() {
  if (!model) return;
  const mode = document.getElementById("render-mode")?.value || "solid";
  model.traverse((o) => {
    const mats = o.material ? (Array.isArray(o.material) ? o.material : [o.material]) : [];
    for (const m of mats) {
      if (!m) continue;
      m.wireframe = mode === "wire";
      if ("emissive" in m && mode === "unlit") m.emissive.setHex(0x444444);
    }
  });
}

function setTool(mode) {
  controls.enableRotate = mode === "orbit";
  controls.enablePan = mode === "pan";
  controls.enableZoom = mode !== "pan";
  if (mode === "zoom") {
    controls.enableRotate = false;
    controls.enablePan = false;
    controls.enableZoom = true;
  }
  for (const b of document.querySelectorAll("#preview-tools [data-tool]")) {
    b.classList.toggle("on", b.dataset.tool === mode);
  }
}

function resetView() {
  if (!lastFrame) return;
  camera.near = lastFrame.near;
  camera.far = lastFrame.far;
  camera.position.copy(lastFrame.pos);
  camera.updateProjectionMatrix();
  controls.target.copy(lastFrame.target);
  controls.minDistance = lastFrame.min;
  controls.maxDistance = lastFrame.max;
  controls.update();
}

function assetTags(asset) {
  const tags = [];
  const cat = asset.category || "";
  if (cat === "weapons") tags.push("weapon");
  else if (cat === "characters") tags.push("character");
  else if (cat === "vehicles") tags.push("vehicle");
  else if (cat === "props") tags.push("prop");
  else if (cat === "textures") tags.push("texture");
  else if (cat) tags.push(cat);
  const blob = ((asset.display_name || "") + " " + (asset.name || "") + " " + (asset.path || "")).toLowerCase();
  if (/rifle|kar98|garand|springfield|enfield|mosin|k98/.test(blob)) tags.push("rifle");
  if (/pistol|colt|luger|hi-standard|webley/.test(blob)) tags.push("pistol");
  if (/allied|usarmy|ranger|american|british/.test(blob)) tags.push("allied");
  if (/german|axis|mauser|mp40|kar/.test(blob)) tags.push("axis");
  tags.push("ww2");
  return [...new Set(tags)];
}

function favKey(asset) {
  return asset.id || asset.path || asset.name || "";
}

function readFavs() {
  try {
    return JSON.parse(localStorage.getItem("mohaa-favs") || "[]");
  } catch (_) {
    return [];
  }
}

function writeFavs(list) {
  localStorage.setItem("mohaa-favs", JSON.stringify(list));
}

function updateInspector(asset, data) {
  const set = (id, v) => {
    const el = document.getElementById(id);
    if (el) el.textContent = v;
  };
  const found = (data.materials || []).filter((m) => m.status === "FOUND" || m.status === "SKY").length;
  const name = asset.display_name || asset.name || "—";
  set("ins-name", name);
  set("ins-type", typeLabel(asset).replace(/s$/, "") || "—");
  set("ins-game", "Medal of Honor: Allied Assault");
  const tik = (asset.tik_path || "").toLowerCase().endsWith(".tik") || (asset.ext || "").toLowerCase() === ".tik";
  const skelExt = ((asset.skelmodel || asset.ext || "").split(".").pop() || "").toLowerCase();
  if (isTextureAsset(asset)) {
    set("ins-fmt", (asset.ext || ".tga") + " (Game)");
  } else {
    const fmt = [(tik ? ".tik" : ""), (skelExt ? "." + skelExt : "")].filter(Boolean);
    set("ins-fmt", (fmt.join(" / ") || "—") + (fmt.length ? " (Game)" : ""));
  }
  set("ins-size", asset.size ? formatSize(asset.size) : "—");
  const polys = data.triangleCount;
  set("ins-tris", isTextureAsset(asset) ? "—" : polys == null ? "—" : Number(polys).toLocaleString("en-US"));
  const texN = (data.materials || []).length;
  set("ins-tex", isTextureAsset(asset) ? "1" : texN ? found + (found === texN ? "" : " / " + texN) : "—");
  const animN = Array.isArray(data.anims) ? data.anims.length : data.pose ? 1 : 0;
  set("ins-anims", isTextureAsset(asset) ? "0" : String(animN));
  const desc = document.getElementById("ins-desc");
  if (desc) {
    if (isTextureAsset(asset)) {
      desc.textContent = name + " from Medal of Honor: Allied Assault, shown on a studio wall.";
    } else {
      const kind = (typeLabel(asset) || "asset").replace(/s$/, "").toLowerCase();
      desc.textContent = name + " from Medal of Honor: Allied Assault. " + (kind === "weapon" ? "World War II " + kind + "." : "MOHAA " + kind + " asset.");
    }
  }
  const tagsEl = document.getElementById("ins-tags");
  if (tagsEl) {
    tagsEl.innerHTML = assetTags(asset)
      .map((t) => "<span class=\"ins-tag\">" + esc(t) + "</span>")
      .join("");
  }
  const star = document.getElementById("ins-star");
  if (star) {
    star.hidden = false;
    star.classList.toggle("on", readFavs().includes(favKey(asset)));
  }
  const em = document.getElementById("export-mode");
  if (em) {
    em.hidden = asset.category !== "characters";
    const skel = em.querySelector('input[value="skeletal"]');
    if (skel && asset.category === "characters") skel.checked = true;
  }
  const mapOpts = document.getElementById("export-map-opts");
  if (mapOpts) {
    const isMap = asset.kind === "map" || (asset.ext || "").toLowerCase() === ".bsp" || asset.category === "maps";
    mapOpts.hidden = !isMap;
  }
  if (metaBody) {
    metaBody.textContent = [
      "name: " + (asset.display_name || asset.name),
      "path: " + asset.path,
      "skelmodel: " + (asset.skelmodel || ""),
      "tik: " + (asset.tik_path || ""),
      "verts: " + data.vertexCount,
      "tris: " + data.triangleCount,
      "bones: " + data.bones,
      "pose: " + (data.pose || ""),
    ].join("\n");
  }
  renderTexGrid(asset, data);
  if (depsBody) {
    const tex = (data.materials || []).map((m) => (m.texture || m.shader || "") + "  " + m.status);
    depsBody.textContent = ["tik: " + (asset.tik_path || "(none)"), "model: " + (asset.skelmodel || ""), "", ...tex].join("\n");
  }
}

function renderTexGrid(asset, data) {
  const el = document.getElementById("ins-texgrid");
  if (!el) return;
  if (isTextureAsset(asset) && asset.path) {
    el.innerHTML =
      '<button type="button" class="ins-texcell on" data-path="' +
      esc(asset.path) +
      '"><img src="' +
      texUrl(asset.path, 256) +
      '" alt=""><span>' +
      esc(asset.display_name || asset.name || "") +
      "</span></button>";
    return;
  }
  const mats = (data.materials || []).filter((m) => m.texture || m.texture_url);
  if (!mats.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = mats
    .map((m) => {
      const p = m.texture || "";
      const miss = (m.status !== "FOUND" && m.status !== "SKY") || !p;
      const url = p ? texUrl(p, 256) : "";
      return (
        '<button type="button" class="ins-texcell' +
        (miss ? " miss" : "") +
        '" data-path="' +
        esc(p) +
        '" title="' +
        esc(m.surface || p) +
        '">' +
        (url && !miss ? '<img src="' + url + '" alt="">' : "") +
        "<span>" +
        esc(m.surface || m.shader || "") +
        "</span></button>"
      );
    })
    .join("");
}

function textureAssetFromPath(path, name) {
  const found = assets.find((a) => a.path === path && isTextureAsset(a));
  if (found) return found;
  const base = (path || "").split("/").pop() || name || "texture";
  const ext = "." + (base.split(".").pop() || "tga").toLowerCase();
  return {
    id: path,
    kind: "texture",
    category: "textures",
    path,
    name: base.replace(/_/g, " "),
    display_name: (name || base).replace(/_/g, " "),
    ext,
    size: 0,
    skelmodel: "",
  };
}

function captureThumb(asset) {
  try {
    asset._thumb = canvas.toDataURL("image/jpeg", 0.6);
  } catch (_) {}
}

const thumbCanvas = document.createElement("canvas");
thumbCanvas.width = 256;
thumbCanvas.height = 160;
const thumbRenderer = new THREE.WebGLRenderer({ canvas: thumbCanvas, antialias: true, alpha: false });
thumbRenderer.setSize(256, 160, false);
thumbRenderer.setPixelRatio(1);
const thumbScene = new THREE.Scene();
thumbScene.background = new THREE.Color(0x10181f);
const thumbCam = new THREE.PerspectiveCamera(28, 256 / 160, 0.1, 8000);

function frameObject(cam, object, controlsObj, opts) {
  object.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(object);
  if (opts && opts.extra && opts.extra.visible && opts.category !== "weapons") {
    opts.extra.updateMatrixWorld(true);
    box.expandByObject(opts.extra);
  }
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const fov = (cam.fov * Math.PI) / 180;
  const category = (opts && opts.category) || "";
  const ratio = size.x / Math.max(size.y, 0.001);
  const maxXZ = Math.max(size.x, size.z);
  const isFlat = size.y < maxXZ * 0.48;

  let fill;
  let dir;
  let look = center.clone();
  let fit = size.clone();
  if (category === "weapons") {
    fill = ratio > 1.8 ? 0.88 : 0.84;
    // Short pistols/grenades need a near side-on camera; a large yaw
    // looks down the barrel and makes them appear to lie on their side.
    const yaw = THREE.MathUtils.clamp((ratio - 1) * 0.18, 0.05, 0.26);
    const lift = opts && opts.extra ? 0.28 : 0.06;
    dir = new THREE.Vector3(opts && opts.extra ? 0.62 : yaw, lift, 1);
    if (opts && opts.extra) {
      dir.applyAxisAngle(new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(-45));
      fill = 0.86;
    }
    dir.normalize();
  } else if (category === "props") {
    // Beds/tables are wide and short: a near-horizontal camera looks
    // along the top surface and fills the pane with fabric. Frame from
    // a 3/4 elevated view and fit the bounding sphere instead.
    fill = 0.76;
    dir = new THREE.Vector3(0.55, isFlat ? 0.92 : 0.5, 1).normalize();
  } else if (category === "characters") {
    // Bust shot: helmet/head + shoulders, not a tiny full-body figure.
    fill = 0.96;
    dir = new THREE.Vector3(0.34, 0.1, 1).normalize();
    look.y = box.max.y - size.y * 0.2;
    fit.y = size.y * 0.4;
    fit.x = Math.min(size.x, fit.y * 1.2);
    fit.z = Math.min(size.z, fit.y);
  } else if (category === "textures") {
    fill = 0.86;
    dir = new THREE.Vector3(-0.72, 0.2, 0.78).normalize();
  } else {
    fill = ratio > 1.8 ? 0.88 : 0.84;
    const yaw = THREE.MathUtils.clamp((ratio - 1) * 0.18, 0.05, 0.26);
    dir = new THREE.Vector3(yaw, 0.12, 1).normalize();
  }

  let dist;
  if (category === "props") {
    const radius = 0.5 * Math.hypot(size.x, size.y, size.z);
    const hFov = 2 * Math.atan(Math.tan(fov / 2) * Math.max(cam.aspect, 0.001));
    dist = Math.max(radius / (Math.sin(Math.min(fov, hFov) / 2) * fill), 1);
  } else {
    const fitH = fit.y / (2 * Math.tan(fov / 2));
    const fitW = fit.x / (2 * Math.tan(fov / 2) * cam.aspect);
    const depth = category === "characters" ? 0 : fit.z * 0.55;
    dist = Math.max(fitH, fitW, depth, 1) / fill;
  }
  cam.near = Math.max(dist / 80, 0.05);
  cam.far = dist + Math.max(size.x, size.y, size.z) * 8;
  cam.position.copy(look).addScaledVector(dir, dist);
  cam.lookAt(look);
  cam.updateProjectionMatrix();
  if (controlsObj) {
    controlsObj.target.copy(look);
    controlsObj.minDistance = dist * 0.35;
    controlsObj.maxDistance = dist * 8;
    controlsObj.update();
  }
  return { center, size, dist };
}
thumbScene.add(new THREE.HemisphereLight(0xc8d8ff, 0x1a1208, 1.2));
const thumbSun = new THREE.DirectionalLight(0xffffff, 1.35);
thumbSun.position.set(40, 80, 20);
thumbScene.add(thumbSun);

let thumbObs = null;
let thumbBusy = false;
let pendingThumbs = [];
let mainLoading = false;

function paintThumb(asset) {
  if (!asset || !asset._thumb) return;
  const el = listEl.querySelector('.card.file[data-id="' + CSS.escape(asset.id) + '"] .thumb');
  if (!el) return;
  el.style.backgroundImage = 'url("' + asset._thumb + '")';
  el.textContent = "";
}

function observeThumbs() {
  if (thumbObs) thumbObs.disconnect();
  thumbObs = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        const asset = assets.find((a) => a.id === e.target.dataset.id);
        if (!asset || asset._thumb || asset._thumbTried || !previewable(asset)) continue;
        if (asset.kind === "map" || (asset.ext || "").toLowerCase() === ".bsp") continue;
        if (isTextureAsset(asset)) {
          asset._thumbTried = true;
          asset._thumb = texUrl(asset.path, 256);
          paintThumb(asset);
          continue;
        }
        asset._thumbTried = true;
        pendingThumbs.push(asset);
      }
      if (!thumbBusy) runThumbQueue();
    },
    { root: listEl, rootMargin: "120px", threshold: 0.01 }
  );
  listEl.querySelectorAll(".card.file").forEach((el) => thumbObs.observe(el));
}

async function runThumbQueue() {
  thumbBusy = true;
  while (pendingThumbs.length) {
    if (mainLoading) {
      await new Promise((r) => setTimeout(r, 180));
      continue;
    }
    const asset = pendingThumbs.shift();
    if (!asset || asset._thumb) continue;
    try {
      await makeThumb(asset);
      paintThumb(asset);
    } catch (_) {}
  }
  thumbBusy = false;
}

function waitTexture(loader, url) {
  return new Promise((resolve) => {
    const t = setTimeout(() => resolve(null), 1800);
    loader.load(
      url,
      (tex) => {
        clearTimeout(t);
        tex.colorSpace = THREE.SRGBColorSpace;
        resolve(tex);
      },
      undefined,
      () => {
        clearTimeout(t);
        resolve(null);
      }
    );
  });
}

async function makeThumb(asset) {
  if (isTextureAsset(asset)) {
    asset._thumb = texUrl(asset.path, 256);
    return;
  }
  const qs = new URLSearchParams({ path: asset.skelmodel });
  if (asset.tik_path && asset.kind !== "map") qs.set("tik", asset.tik_path);
  const data = await api("/api/mesh?" + qs.toString());
  const vertCap = asset.category === "characters" ? 40000 : 12000;
  if ((data.vertexCount || 0) > vertCap) {
    const tex = (data.materials || []).find((m) => m.status === "FOUND" && m.texture_url);
    if (tex) asset._thumb = tex.texture_url;
    return;
  }
  const isMap = asset.kind === "map" || (asset.ext || "").toLowerCase() === ".bsp";
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(data.positions, 3));
  geo.setAttribute("normal", new THREE.Float32BufferAttribute(data.normals, 3));
  geo.setAttribute("uv", new THREE.Float32BufferAttribute(data.uvs, 2));
  geo.setIndex(data.indices);
  const loader = new THREE.TextureLoader();
  const mats = [];
  const pending = [];
  const groups = ((data.materials && data.materials.length ? data.materials : null) ||
    (data.groups.length ? data.groups : [{ start: 0, count: data.indices.length, status: "MISSING" }])
  ).filter((g) => !g.nodraw && g.status !== "NODRAW" && g.status !== "SKY" && (g.count || 0) > 0);
  for (const g of groups) {
    geo.addGroup(g.start, g.count, mats.length);
    const mat = new THREE.MeshLambertMaterial({ color: 0xffffff, side: THREE.DoubleSide });
    if (g.status === "FOUND" && g.texture_url) {
      pending.push(
        waitTexture(loader, g.texture_url).then((tex) => {
          if (tex) mat.map = tex;
        })
      );
    }
    mats.push(mat);
  }
  await Promise.all(pending);
  const mesh = new THREE.Mesh(geo, mats.length ? mats : new THREE.MeshLambertMaterial({ color: 0x8899aa }));
  geo.computeBoundingBox();
  const box = geo.boundingBox || new THREE.Box3(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  const center = box.getCenter(new THREE.Vector3());
  mesh.position.sub(center);
  const group = new THREE.Group();
  group.add(mesh);
  orientPreviewGroup(group, asset);
  thumbScene.add(group);
  frameObject(thumbCam, group, null, { category: asset.category });
  thumbRenderer.render(thumbScene, thumbCam);
  asset._thumb = thumbCanvas.toDataURL("image/jpeg", 0.72);
  thumbScene.remove(group);
  group.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) {
      const mm = Array.isArray(o.material) ? o.material : [o.material];
      for (const m of mm) {
        if (m.map) m.map.dispose();
        m.dispose();
      }
    }
  });
  void isMap;
}

function jobElapsed(j) {
  if (!j.started) return "00:00";
  const end = j.ended || Date.now();
  const s = Math.max(0, Math.floor((end - j.started) / 1000));
  return String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
}

function convertingLabel(kind) {
  const k = String(kind || "").toLowerCase();
  if (k.includes("unreal") || k === "batch") return "Exporting to Unreal...";
  return "Converting to FBX...";
}

function renderQueue() {
  const count = document.getElementById("q-count");
  if (count) count.textContent = queue.length ? "(" + queue.length + ")" : "";
  if (!queue.length) {
    queueEl.innerHTML = `<p class="muted">No conversion jobs.</p>`;
    return;
  }
  const playSvg =
    '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>';
  const chevSvg =
    '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M7 10l5 5 5-5z"/></svg>';
  queueEl.innerHTML = queue
    .map((j) => {
      const thumb = j.thumb ? `style="background-image:url('${j.thumb}')"` : "";
      return `<div class="q-item${j.running ? " run" : ""}" data-id="${esc(j.id)}">
      <div class="q-row">
        <label class="q-check"><input type="checkbox" ${j.selected ? "checked" : ""} data-act="sel"></label>
        <div class="q-thumb" ${thumb}></div>
        <div class="q-name" title="${esc(j.name)}">${esc(j.name)}</div>
        <div class="q-status">${esc(j.status)}</div>
        <div class="q-play">${j.running ? playSvg : ""}</div>
        <div class="bar"><i style="width:${j.pct}%"></i></div>
        <div class="q-pct">${j.pct}%</div>
        <div class="q-time">${jobElapsed(j)}</div>
        <button type="button" class="q-chev${j.open ? " open" : ""}" data-act="open" aria-label="Details">${chevSvg}</button>
      </div>
      ${j.open ? `<div class="q-detail">${esc(j.path || "")} · ${esc(j.kind || "")}</div>` : ""}
    </div>`;
    })
    .join("");
}

async function enqueue(kind) {
  if (!current) {
    logLine("No asset selected for " + kind);
    return;
  }
  let exportKind = kind;
  const mode = document.querySelector("#export-mode input:checked")?.value;
  const isCharacter = (current.category || cat || "") === "characters";
  const isMap =
    current.kind === "map" ||
    (current.ext || "").toLowerCase() === ".bsp" ||
    (current.category || "") === "maps";
  // Hidden skeletal radio stays checked after characters; BSP maps have no SKD bones.
  const wantSkel = !isMap && (isCharacter || mode === "skeletal");
  if (wantSkel) {
    if (kind === "Unreal" || kind === "Batch") exportKind = "unreal-skel";
    else if (kind === "FBX") exportKind = "fbx-skel";
  }
  const selectedAsset = current;
  const intoUnreal = kind === "Unreal" || kind === "Batch";
  let destination = null;
  if (intoUnreal) {
    destination = await validateProject();
    if (!destination) { projectInput.focus(); return; }
    if (current !== selectedAsset) { logLine("Asset changed; select Export again."); return; }
  }
  const qs = new URLSearchParams({
    path: current.skelmodel || current.path || "",
    kind: exportKind,
    category: current.category || cat || "",
    name: current.display_name || current.name || "",
  });
  if (destination) qs.set("project", destination.project);
  if (current.tik_path && current.kind !== "map") qs.set("tik", current.tik_path);
  if (isMap) {
    qs.set("textures", document.getElementById("map-opt-textures")?.checked ? "1" : "0");
    qs.set("furniture", document.getElementById("map-opt-furniture")?.checked ? "1" : "0");
  }
  const job = {
    id: "job-" + (++jobSeq),
    name: current.display_name || current.name || "Asset",
    path: current.path || current.skelmodel || "",
    kind: exportKind,
    status: "Queued...",
    pct: 0,
    thumb: current._thumb || "",
    started: 0,
    ended: 0,
    running: false,
    selected: false,
    open: false,
    failed: false,
    projectName: destination?.name || "",
    qs: qs.toString(),
    lastProg: "",
  };
  queue.push(job);
  renderQueue();
  pumpQueue();
}

function pumpQueue() {
  if (queue.some((j) => j.running)) return;
  const next = queue.find((j) => !j.running && !j.failed && j.pct < 100);
  if (!next) return;
  runJob(next);
}

function runJob(job) {
  job.running = true;
  job.selected = true;
  job.started = Date.now();
  job.status = convertingLabel(job.kind);
  job.pct = Math.max(job.pct, 5);
  renderQueue();
  logLine("Loaded asset: " + job.name + (job.path ? " (" + job.path + ")" : ""));
  const poll = setInterval(() => {
    fetch("/api/export/progress")
      .then((r) => r.json())
      .then((p) => {
        if (typeof p.pct === "number" && p.pct > job.pct && job.pct < 100) {
          job.pct = Math.min(95, p.pct);
        }
        if (p.status && job.pct < 100) {
          job.status = p.status;
          if (p.status !== job.lastProg) {
            job.lastProg = p.status;
            logLine(p.status);
          }
        }
        renderQueue();
      })
      .catch(() => {});
  }, 400);
  api("/api/export?" + job.qs)
    .then((data) => {
      job.pct = 100;
      const ue = data.unreal || {};
      const jobKind = job.kind;
      if (String(jobKind).toLowerCase().includes("unreal") || String(jobKind).toLowerCase() === "batch") {
        job.status = ue.imported ? "Imported in Unreal" : "FBX ready";
      } else {
        job.status = data.fbx ? "FBX ready" : "Done";
      }
      renderQueue();
      const lods = Array.isArray(data.lods) ? data.lods.length : 0;
      const lodFiles = Array.isArray(data.lod_files) ? data.lod_files.length : 0;
      logLine(
        jobKind +
          " → " +
          (data.fbx || "") +
          (lods ? " + " + lods + " LOD" + (lods === 1 ? "" : "s") : "") +
          (lodFiles ? " (kept " + lodFiles + " .lod sidecar" + (lodFiles === 1 ? "" : "s") + ")" : "") +
          (ue.imported ? " (imported in " + job.projectName + ")" : ue.reason ? " (" + ue.reason + ")" : "")
      );
      if (data.skel_debug) {
        const d = data.skel_debug;
        logLine(
          "skel bones=" +
            d.bone_count +
            " verts=" +
            d.vertex_count +
            " weighted=" +
            d.weighted_vertices +
            " maxInf=" +
            d.max_influences +
            " zeroInf=" +
            d.zero_influences +
            " errors=" +
            d.error_count
        );
      }
      if (Array.isArray(data.anims) && data.anims.length) {
        logLine(
          "anims " +
            data.anims
              .map((a) => (a.alias || "") + " " + (a.frames || 0) + "f")
              .join(", ")
        );
      }
      if (ue.character_ready) {
        logLine("Manny retarget " + ue.character_ready);
      }
    })
    .catch((err) => {
      job.status = "Failed";
      job.failed = true;
      job.pct = 100;
      renderQueue();
      logLine(job.kind + " failed: " + err.message);
    })
    .finally(() => {
      clearInterval(poll);
      job.running = false;
      job.ended = Date.now();
      renderQueue();
      pumpQueue();
    });
}

async function loadWallMap(loader, url) {
  return new Promise((resolve) => {
    const t = setTimeout(() => resolve(null), 12000);
    loader.load(
      url,
      (tex) => {
        clearTimeout(t);
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.wrapS = THREE.ClampToEdgeWrapping;
        tex.wrapT = THREE.ClampToEdgeWrapping;
        tex.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
        resolve(tex);
      },
      undefined,
      () => {
        clearTimeout(t);
        resolve(null);
      }
    );
  });
}

async function loadTextureWall(asset) {
  const path = asset.path || "";
  const loader = new THREE.TextureLoader();
  const tex = path ? await loadWallMap(loader, texUrl(path, 1024)) : null;
  const img = tex && tex.image;
  const iw = (img && (img.width || img.videoWidth)) || 256;
  const ih = (img && (img.height || img.videoHeight)) || 256;
  lastSkeleton = [];
  lastMesh = {
    vertexCount: 0,
    triangleCount: 0,
    bones: 0,
    pose: "",
    materials: [
      {
        surface: asset.display_name || asset.name || "texture",
        shader: path,
        texture: path,
        texture_url: path ? texUrl(path, 256) : "",
        status: tex ? "FOUND" : "MISSING",
        count: 6,
      },
    ],
    anims: [],
  };
  clearModel();
  hidePedestal();
  const h = 160;
  const w = Math.min(Math.max(h * (iw / Math.max(ih, 1)), 48), 280);
  const thick = Math.max(w, h) * 0.022;
  const face = new THREE.MeshPhongMaterial({
    color: 0xffffff,
    map: tex || checkerboardTexture(),
    specular: 0x3a3a3a,
    shininess: 22,
  });
  const dark = new THREE.MeshPhongMaterial({ color: 0x1a1e26, shininess: 8 });
  const wall = new THREE.Mesh(new THREE.BoxGeometry(w, h, thick), [dark, dark, dark, dark, face, dark]);
  wall.position.y = h / 2;
  wall.castShadow = true;
  wall.receiveShadow = true;
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(Math.max(w * 2.1, 180), Math.max(w * 1.55, 140)),
    new THREE.MeshStandardMaterial({ color: 0x10151c, roughness: 0.92, metalness: 0.04 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(0, 0, w * 0.28);
  floor.receiveShadow = true;
  model = new THREE.Group();
  model.add(wall);
  model.add(floor);
  scene.add(model);
  resize();
  const framed = frameObject(camera, wall, controls, { category: "textures" });
  setStudioLighting(framed.center, framed.dist, true);
  ground.visible = false;
  hint.textContent = asset.display_name || asset.name;
  meta.textContent = iw + " × " + ih + " · " + (asset.path || "");
  lastFrame = {
    near: camera.near,
    far: camera.far,
    pos: camera.position.clone(),
    target: controls.target.clone(),
    min: controls.minDistance,
    max: controls.maxDistance,
  };
  applyRenderMode();
  updateInspector(asset, lastMesh);
  renderMatLog(lastMesh.materials, [], "", [], "");
  setStatus("Ready", "ready");
  logLine("Loaded wall " + (asset.path || asset.name));
}

async function loadMesh(asset) {
  current = asset;
  mainLoading = true;
  renderList();
  hint.textContent = "Loading… " + (asset.skelmodel || asset.path || "");
  try {
    if (isTextureAsset(asset)) {
      await loadTextureWall(asset);
      return;
    }
    const qs = new URLSearchParams({ path: asset.skelmodel });
    if (asset.tik_path && asset.kind !== "map") qs.set("tik", asset.tik_path);
    const data = await api("/api/mesh?" + qs.toString());
  console.group("MOHAA materials " + (asset.path || asset.skelmodel));
  for (const m of data.materials || []) {
    console.log(
      `${m.surface} -> ${m.shader || "(none)"} -> ${m.texture || "(none)"} -> ${m.status}`,
      m
    );
  }
  console.log("pose", data.pose);
  console.log("skeleton", data.skeleton);
  console.log("skin", data.skinLog);
  console.groupEnd();
  lastSkeleton = data.skeleton || [];
  lastMesh = data;
  renderMatLog(data.materials || [], data.skinLog || [], data.pose, lastSkeleton, data.visibilityNote);
  clearModel();
  const isMap = (asset.kind === "map" || (asset.ext || "").toLowerCase() === ".bsp");
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.Float32BufferAttribute(data.positions, 3));
  geo.setAttribute("normal", new THREE.Float32BufferAttribute(data.normals, 3));
  geo.setAttribute("uv", new THREE.Float32BufferAttribute(data.uvs, 2));
  geo.setIndex(data.indices);
  const loader = new THREE.TextureLoader();
  const mats = [];
  const groups = ((data.materials && data.materials.length ? data.materials : null) ||
    (data.groups.length ? data.groups : [{ start: 0, count: data.indices.length, status: "MISSING" }])
  ).filter((g) => !g.nodraw && g.status !== "NODRAW" && g.status !== "SKY" && (g.count || 0) > 0);
  for (const g of groups) {
    geo.addGroup(g.start, g.count, mats.length);
    const mat = isMap
      ? new THREE.MeshLambertMaterial({ color: 0xffffff, side: THREE.DoubleSide })
      : new THREE.MeshPhongMaterial({
          color: 0xffffff,
          specular: 0x4a4a4a,
          shininess: 42,
          side: THREE.DoubleSide,
        });
    if (isMap) mat.emissive.setHex(0x3a3a3a);
    if (g.status === "FOUND" && g.texture_url) {
      mat.map = loader.load(g.texture_url);
      mat.map.colorSpace = THREE.SRGBColorSpace;
      if (g.blend) {
        mat.transparent = true;
        mat.depthWrite = false;
        mat.opacity = 0.85;
      }
      if (g.alpha_test) {
        mat.alphaTest = 0.5;
        mat.transparent = true;
      }
    } else {
      mat.map = checkerboardTexture();
      mat.color.set(0xffffff);
    }
    mats.push(mat);
  }
  const mesh = new THREE.Mesh(geo, mats.length ? mats : new THREE.MeshPhongMaterial({ color: 0xffffff }));
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  geo.computeBoundingBox();
  const localBox = geo.boundingBox || new THREE.Box3(new THREE.Vector3(-1, -1, -1), new THREE.Vector3(1, 1, 1));
  const localCenter = localBox.getCenter(new THREE.Vector3());
  const localSize = localBox.getSize(new THREE.Vector3());
  mesh.position.sub(localCenter);
  surfaceHelper = makeSurfaceLabels(data, groups);
  mesh.add(surfaceHelper);
  model = new THREE.Group();
  model.add(mesh);
  if (lastSkeleton.length) {
    boneHelper = makeBoneHelper(lastSkeleton, 24);
    boneHelper.position.sub(localCenter);
    model.add(boneHelper);
  } else {
    boneHelper = null;
  }
  orientPreviewGroup(model, asset);
  scene.add(model);
  resize();
  const showPedestal = !isMap && asset.category === "weapons";
  if (showPedestal) {
    await ensurePedestal();
    placePedestalUnder(model);
  } else {
    hidePedestal();
  }
  const framed = frameObject(camera, model, controls, {
    category: asset.category,
    extra: showPedestal && pedestal && pedestal.visible ? pedestal : null,
  });
  setStudioLighting(framed.center, framed.dist, showPedestal);
  const radius = Math.max(framed.size.x, framed.size.y, framed.size.z, 1);
  const isMapView = isMap || radius > 400;
  ground.visible = !isMapView && asset.category !== "weapons";
  ground.scale.setScalar(Math.max(radius / 20, 1));
  ground.position.y = framed.center.y - framed.size.y * 0.5 - 2;
  hint.textContent = asset.display_name || asset.name;
  meta.textContent = `${data.vertexCount} verts · ${data.triangleCount} tris · ${data.bones} bones · ${data.pose || asset.skelmodel}`;
  lastFrame = {
    near: camera.near,
    far: camera.far,
    pos: camera.position.clone(),
    target: controls.target.clone(),
    min: controls.minDistance,
    max: controls.maxDistance,
  };
  applyRenderMode();
  updateInspector(asset, data);
  setStatus("Ready", "ready");
  logLine("Loaded " + (asset.path || asset.name));
  } catch (err) {
    hidePedestal();
    setStudioLighting(new THREE.Vector3(), 1, false);
    hint.textContent = "Error: " + err.message;
    meta.textContent = asset.path || "";
    setStatus("Error", "err");
    logLine("Error: " + err.message);
  } finally {
    mainLoading = false;
  }
}

document.getElementById("scan-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  setStatus("Scanning", "busy");
  try {
    const data = await api("/api/scan?path=" + encodeURIComponent(gamepath.value));
    assets = data.assets;
    countEl.textContent = assets.length + " assets";
    if (data.game) {
      gamepath.value = data.game;
      try { localStorage.setItem("mohaa-assets-root", data.game); } catch (_) {}
    }
    setStatus("Ready", "ready");
    logLine("Scan: " + data.paks + " pk3s, " + assets.length + " assets, " + data.files + " files");
    showPage("browser", "weapons");
    renderList();
  } catch (err) {
    setStatus("Error", "err");
    logLine("Scan failed: " + err.message);
  }
});

catsEl.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  showPage("browser", b.dataset.cat);
});

if (crumbEl) {
  crumbEl.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    dir = b.dataset.dir || "";
    renderList();
  });
}

filterEl.addEventListener("input", renderList);

listEl.addEventListener("click", async (e) => {
  const folder = e.target.closest(".folder");
  if (folder) {
    dir = folder.dataset.dir || "";
    renderList();
    return;
  }
  const card = e.target.closest(".file");
  if (!card) return;
  const asset = assets.find((a) => a.id === card.dataset.id);
  if (asset) await loadMesh(asset);
});

document.getElementById("ins-texgrid").addEventListener("click", async (e) => {
  const cell = e.target.closest(".ins-texcell");
  if (!cell || cell.classList.contains("miss")) return;
  const path = cell.dataset.path;
  if (!path) return;
  await loadMesh(textureAssetFromPath(path, cell.getAttribute("title") || ""));
});

sidenav.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.nav === "dashboard") showPage("dashboard");
  else if (b.dataset.nav === "settings") showPage("settings");
  else showPage("browser", b.dataset.cat);
});

dashGrid.addEventListener("click", (e) => {
  const card = e.target.closest("[data-cat]");
  if (card) showPage("browser", card.dataset.cat);
});

document.getElementById("preview-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  for (const x of document.querySelectorAll("#preview-tabs button")) x.classList.toggle("on", x === b);
  for (const p of document.querySelectorAll(".preview-col .ptab")) {
    p.hidden = p.dataset.ptab !== b.dataset.ptab;
    p.classList.toggle("on", p.dataset.ptab === b.dataset.ptab);
  }
  if (b.dataset.ptab === "preview") requestAnimationFrame(resize);
});

document.getElementById("preview-tools").addEventListener("click", (e) => {
  const b = e.target.closest("[data-tool]");
  if (!b) return;
  const tool = b.dataset.tool;
  if (tool === "reset") resetView();
  else if (tool === "full") {
    const wrap = document.getElementById("preview-wrap");
    if (!document.fullscreenElement) wrap.requestFullscreen?.();
    else document.exitFullscreen?.();
  } else setTool(tool);
});

document.getElementById("render-mode").addEventListener("change", applyRenderMode);

document.getElementById("bottom-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  for (const x of document.querySelectorAll("#bottom-tabs button")) x.classList.toggle("on", x === b);
  const pane = b.dataset.btab === "log" ? logEl : queueEl;
  pane?.scrollIntoView({ block: "nearest", inline: "nearest" });
});

queueEl.addEventListener("change", (e) => {
  const input = e.target.closest('input[data-act="sel"]');
  if (!input) return;
  const item = input.closest(".q-item");
  const job = queue.find((j) => j.id === item?.dataset.id);
  if (job) job.selected = !!input.checked;
});

queueEl.addEventListener("click", (e) => {
  const act = e.target.closest('[data-act="open"]');
  if (!act) return;
  const item = act.closest(".q-item");
  const job = queue.find((j) => j.id === item?.dataset.id);
  if (!job) return;
  job.open = !job.open;
  renderQueue();
});

document.getElementById("btn-log-clear")?.addEventListener("click", () => {
  logs = [];
  renderLog();
});

setInterval(() => {
  if (queue.some((j) => j.running)) renderQueue();
}, 1000);

renderQueue();
renderLog();

document.getElementById("btn-fbx").addEventListener("click", () => enqueue("FBX"));
document.getElementById("btn-ue").addEventListener("click", () => enqueue("Unreal"));
document.getElementById("btn-batch").addEventListener("click", () => enqueue("Batch"));
document.getElementById("btn-more")?.addEventListener("click", async () => {
  const path = current?.path || current?.skelmodel || "";
  if (!path) return;
  try {
    await navigator.clipboard.writeText(path);
    logLine("Copied " + path);
  } catch (_) {
    logLine(path);
  }
});
document.getElementById("ins-star")?.addEventListener("click", () => {
  if (!current) return;
  const key = favKey(current);
  const favs = readFavs();
  const i = favs.indexOf(key);
  if (i >= 0) favs.splice(i, 1);
  else favs.push(key);
  writeFavs(favs);
  document.getElementById("ins-star").classList.toggle("on", i < 0);
});

if (dbgBones) {
  dbgBones.addEventListener("change", () => {
    if (boneHelper) boneHelper.visible = dbgBones.checked;
  });
}
if (dbgSurfaces) {
  dbgSurfaces.addEventListener("change", () => {
    if (surfaceHelper) surfaceHelper.visible = dbgSurfaces.checked;
  });
}

setTool("orbit");
renderQueue();
resize();
frame();

// The destination is captured per queued job; later changes do not redirect it.
const GAME_STORE = "mohaa-assets-root";
const PROJECT_STORE = "mohaa-unreal-project";
const DEFAULT_GAME = "D:/Games/test/moh_convert_game";
const projectInput = document.getElementById("projectpath");
const projectState = document.getElementById("project-state");
const projectBrowse = document.getElementById("project-browse");
const projectOpen = document.getElementById("project-open");
const gameBrowse = document.getElementById("game-browse");
let projectValidation = 0;
function acceptProject(data) {
  projectInput.value = data.project;
  projectInput.title = data.project;
  projectInput.removeAttribute("aria-invalid");
  projectState.textContent = "✓";
  projectState.className = "valid";
  projectState.title = "Export destination: " + data.name;
  document.getElementById("btn-ue").title = "Export to " + data.name;
  try { localStorage.setItem(PROJECT_STORE, data.project); } catch (_) {}
}
async function localPost(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: {"X-MOHAA-Local": "1", "Content-Type": "application/json"},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || "Request failed");
  return data;
}
async function validateProject(useDefault = false) {
  const revision = ++projectValidation;
  const value = projectInput.value.trim();
  projectState.textContent = "…";
  projectState.className = "";
  try {
    if (!value && !useDefault) throw new Error("Choose an Unreal project first.");
    const data = await api("/api/project" + (value ? "?path=" + encodeURIComponent(value) : ""));
    if (revision !== projectValidation || projectInput.value.trim() !== value) return null;
    acceptProject(data);
    return data;
  } catch (err) {
    if (revision !== projectValidation) return null;
    projectState.textContent = "Check path";
    projectState.className = "invalid";
    projectState.title = err.message;
    projectInput.title = err.message;
    projectInput.setAttribute("aria-invalid", "true");
    document.getElementById("btn-ue").title = "Choose a valid Unreal project below";
    return null;
  }
}
projectInput.addEventListener("input", () => {
  ++projectValidation;
  projectState.textContent = "";
  projectInput.removeAttribute("aria-invalid");
});
projectInput.addEventListener("change", () => validateProject());
projectOpen.addEventListener("click", async () => {
  projectOpen.disabled = true;
  try {
    const destination = await validateProject();
    if (!destination) { projectInput.focus(); return; }
    projectState.textContent = "Opening…";
    const data = await localPost("/api/project/open", {project: destination.project});
    logLine("Opening Unreal project: " + data.name + (data.editor ? " (" + data.editor + ")" : ""));
    acceptProject(destination);
    projectState.title = "Opened " + data.name + " in Unreal Engine";
  } catch (err) {
    projectState.textContent = "Open failed";
    projectState.className = "invalid";
    projectState.title = err.message;
    logLine(err.message);
  } finally { projectOpen.disabled = false; }
});
projectInput.addEventListener("keydown", e => {
  if (e.key === "Enter") { e.preventDefault(); validateProject(); }
});
projectBrowse.addEventListener("click", async () => {
  projectBrowse.disabled = true;
  projectState.textContent = "Choose…";
  const previous = projectInput.value;
  try {
    const data = await localPost("/api/project/pick");
    if (!data.cancelled) { ++projectValidation; acceptProject(data); }
    else if (previous) await validateProject();
    else projectState.textContent = "";
  } catch (err) {
    projectState.textContent = "Paste path";
    projectState.className = "invalid";
    projectState.title = err.message;
    logLine(err.message);
  } finally { projectBrowse.disabled = false; }
});
gameBrowse?.addEventListener("click", async () => {
  gameBrowse.disabled = true;
  setStatus("Choose folder", "busy");
  try {
    const data = await localPost("/api/game/pick");
    if (data.cancelled) {
      setStatus("Ready", "ready");
      return;
    }
    gamepath.value = data.game;
    try { localStorage.setItem(GAME_STORE, data.game); } catch (_) {}
    document.getElementById("scan-form").requestSubmit();
  } catch (err) {
    setStatus("Error", "err");
    logLine(err.message);
  } finally { gameBrowse.disabled = false; }
});
(async function bootPaths() {
  let savedGame = "";
  let savedProject = "";
  try { savedGame = localStorage.getItem(GAME_STORE) || ""; } catch (_) {}
  try { savedProject = localStorage.getItem(PROJECT_STORE) || ""; } catch (_) {}
  try {
    const cfg = await api("/api/paths");
    if (cfg.game) savedGame = cfg.game;
    if (cfg.project) savedProject = cfg.project;
  } catch (_) {}
  gamepath.value = savedGame || DEFAULT_GAME;
  if (savedProject) projectInput.value = savedProject;
  document.getElementById("scan-form").requestSubmit();
  validateProject(true);
})();
