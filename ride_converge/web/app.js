const riderColors = ["#3975d7", "#875dcc", "#d7792d", "#d44f69", "#298c80", "#866544", "#596b7a", "#a95c9d"];

const state = {
  origins: [
    { id: crypto.randomUUID(), name: "A", address: "西单地铁站", point: null, detail: "待搜索或提交时自动定位" },
    { id: crypto.randomUUID(), name: "B", address: "丰台科技园", point: null, detail: "待搜索或提交时自动定位" },
    { id: crypto.randomUUID(), name: "C", address: "北京工业大学", point: null, detail: "待搜索或提交时自动定位" },
  ],
  waypoints: [],
  destination: { address: "潭柘寺", point: null, detail: "待搜索或提交时自动定位" },
  activePick: null,
  plan: null,
  selectedResult: 0,
};

const map = L.map("map", { zoomControl: true }).setView([39.94, 116.42], 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap 贡献者",
}).addTo(map);

const selectionLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
const markerLayers = new Map();
let toastTimer = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 4200);
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({ error: "服务器返回了无法识别的内容" }));
  if (!response.ok) throw new Error(data.error || "请求失败");
  return data;
}

function markerIcon(label, color, meeting = false) {
  return L.divIcon({
    className: "leaflet-div-icon",
    html: `<div class="marker-pin${meeting ? " marker-meet" : ""}" style="background:${color}"><span>${escapeHtml(label)}</span></div>`,
    iconSize: meeting ? [36, 36] : [30, 30],
    iconAnchor: meeting ? [18, 34] : [15, 28],
  });
}

function setSelectionMarker(key, label, point, color) {
  const old = markerLayers.get(key);
  if (old) selectionLayer.removeLayer(old);
  if (!point) {
    markerLayers.delete(key);
    return;
  }
  const marker = L.marker([point.wgs.lat, point.wgs.lng], { icon: markerIcon(label, color) }).addTo(selectionLayer);
  markerLayers.set(key, marker);
}

function clearPoint(origin) {
  origin.point = null;
  origin.detail = "地址已修改，请重新搜索或直接生成方案";
  setSelectionMarker(origin.id, "", null, "");
}

function renderOrigins() {
  const container = document.querySelector("#origins");
  container.innerHTML = "";
  state.origins.forEach((origin, index) => {
    const card = document.createElement("div");
    card.className = "location-card";
    card.innerHTML = `
      <div class="location-head">
        <span class="location-badge" style="background:${riderColors[index]}">${escapeHtml(origin.name || index + 1)}</span>
        <input class="rider-name" aria-label="第 ${index + 1} 名骑行者名称" value="${escapeHtml(origin.name)}" maxlength="30">
        <span class="location-state ${origin.point ? "ready" : ""}">${origin.point ? "已定位" : "待搜索"}</span>
        <button class="remove-origin" type="button" aria-label="删除骑行者">删除</button>
      </div>
      <label class="sr-only">${escapeHtml(origin.name)} 的起点地址</label>
      <input class="text-input origin-address" value="${escapeHtml(origin.address)}" placeholder="输入起点名称或地址" autocomplete="off">
      <div class="location-actions">
        <button class="secondary-button search-origin" type="button">搜索定位</button>
        <button class="map-pick-button pick-origin ${state.activePick?.id === origin.id ? "active" : ""}" type="button">${state.activePick?.id === origin.id ? "请点击地图" : "地图选点"}</button>
      </div>
      <p class="location-detail">${escapeHtml(origin.detail)}</p>`;

    card.querySelector(".rider-name").addEventListener("input", (event) => {
      origin.name = event.target.value;
      card.querySelector(".location-badge").textContent = origin.name.slice(0, 2) || String(index + 1);
    });
    card.querySelector(".origin-address").addEventListener("input", (event) => {
      origin.address = event.target.value;
      if (origin.point) {
        clearPoint(origin);
        card.querySelector(".location-state").textContent = "待搜索";
        card.querySelector(".location-state").classList.remove("ready");
      }
    });
    card.querySelector(".search-origin").addEventListener("click", () => searchOrigin(origin, index));
    card.querySelector(".pick-origin").addEventListener("click", () => toggleMapPick({ type: "origin", id: origin.id }));
    card.querySelector(".remove-origin").addEventListener("click", () => removeOrigin(origin.id));
    container.appendChild(card);
  });
}

function renderWaypoints() {
  const container = document.querySelector("#waypoints");
  container.innerHTML = "";
  state.waypoints.forEach((waypoint, index) => {
    const card = document.createElement("div");
    card.className = "location-card waypoint-card";
    const active = state.activePick?.type === "waypoint" && state.activePick?.id === waypoint.id;
    card.innerHTML = `
      <div class="location-head">
        <span class="location-badge waypoint">W${index + 1}</span>
        <strong>途经点 ${index + 1}</strong>
        <span class="location-state ${waypoint.point ? "ready" : ""}">${waypoint.point ? "已定位" : "待搜索"}</span>
        <button class="remove-origin" type="button" aria-label="删除途经点">删除</button>
      </div>
      <label class="sr-only">途经点 ${index + 1} 地址</label>
      <input class="text-input waypoint-address" value="${escapeHtml(waypoint.address)}" placeholder="输入必须共同经过的地点" autocomplete="off">
      <div class="location-actions">
        <button class="secondary-button search-waypoint" type="button">搜索定位</button>
        <button class="map-pick-button pick-waypoint ${active ? "active" : ""}" type="button">${active ? "请点击地图" : "地图选点"}</button>
      </div>
      <div class="waypoint-order">
        <button class="move-waypoint-up" type="button" ${index === 0 ? "disabled" : ""}>↑ 上移</button>
        <button class="move-waypoint-down" type="button" ${index === state.waypoints.length - 1 ? "disabled" : ""}>↓ 下移</button>
        <span>共同路线顺序：W${index + 1}</span>
      </div>
      <p class="location-detail">${escapeHtml(waypoint.detail)}</p>`;
    card.querySelector(".waypoint-address").addEventListener("input", (event) => {
      waypoint.address = event.target.value;
      if (waypoint.point) {
        clearPoint(waypoint);
        renderWaypoints();
      }
    });
    card.querySelector(".search-waypoint").addEventListener("click", () => searchWaypoint(waypoint, index));
    card.querySelector(".pick-waypoint").addEventListener("click", () => toggleMapPick({ type: "waypoint", id: waypoint.id }));
    card.querySelector(".move-waypoint-up").addEventListener("click", () => moveWaypoint(index, -1));
    card.querySelector(".move-waypoint-down").addEventListener("click", () => moveWaypoint(index, 1));
    card.querySelector(".remove-origin").addEventListener("click", () => removeWaypoint(waypoint.id));
    container.appendChild(card);
  });
}

function renderDestination() {
  const input = document.querySelector("#destination-address");
  input.value = state.destination.address;
  document.querySelector("#destination-detail").textContent = state.destination.detail;
  const status = document.querySelector("#destination-state");
  status.textContent = state.destination.point ? "已定位" : "待搜索";
  status.classList.toggle("ready", Boolean(state.destination.point));
  const pick = document.querySelector("#pick-destination");
  const active = state.activePick?.type === "destination";
  pick.classList.toggle("active", active);
  pick.textContent = active ? "请点击地图" : "地图选点";
}

function addOrigin() {
  if (state.origins.length >= 8) return showToast("最多支持 8 名骑行者");
  const index = state.origins.length;
  state.origins.push({
    id: crypto.randomUUID(),
    name: String.fromCharCode(65 + index),
    address: "",
    point: null,
    detail: "输入起点名称后搜索，或直接在地图上选点。",
  });
  renderOrigins();
  document.querySelector("#origins .location-card:last-child .origin-address").focus();
}

function addWaypoint() {
  if (state.waypoints.length >= 8) return showToast("最多支持 8 个途经点");
  state.waypoints.push({
    id: crypto.randomUUID(),
    address: "",
    point: null,
    detail: "输入地点后搜索，途经点将按当前顺序连接。",
  });
  renderWaypoints();
  document.querySelector("#waypoints .waypoint-card:last-child .waypoint-address").focus();
}

function removeWaypoint(id) {
  state.waypoints = state.waypoints.filter((waypoint) => waypoint.id !== id);
  setSelectionMarker(id, "", null, "");
  if (state.activePick?.id === id) state.activePick = null;
  renderWaypoints();
  state.waypoints.forEach((waypoint, index) => setSelectionMarker(waypoint.id, `W${index + 1}`, waypoint.point, "#d7792d"));
}

function moveWaypoint(index, direction) {
  const target = index + direction;
  if (target < 0 || target >= state.waypoints.length) return;
  [state.waypoints[index], state.waypoints[target]] = [state.waypoints[target], state.waypoints[index]];
  renderWaypoints();
  state.waypoints.forEach((waypoint, waypointIndex) => {
    setSelectionMarker(waypoint.id, `W${waypointIndex + 1}`, waypoint.point, "#d7792d");
  });
}

function removeOrigin(id) {
  if (state.origins.length <= 2) return showToast("至少需要两名骑行者");
  state.origins = state.origins.filter((origin) => origin.id !== id);
  setSelectionMarker(id, "", null, "");
  if (state.activePick?.id === id) state.activePick = null;
  renderOrigins();
}

async function searchOrigin(origin, index) {
  if (!origin.address.trim()) return showToast("请先输入起点名称或地址");
  setLocationBusy(true, `正在搜索 ${origin.name || `骑行者${index + 1}`} 的起点……`);
  try {
    const result = await api("/api/search", { city: document.querySelector("#city").value, query: origin.address });
    origin.point = result.point;
    origin.detail = result.address;
    setSelectionMarker(origin.id, origin.name || String(index + 1), origin.point, riderColors[index]);
    renderOrigins();
    map.setView([origin.point.wgs.lat, origin.point.wgs.lng], 14);
  } catch (error) {
    showToast(error.message);
  } finally {
    setLocationBusy(false);
  }
}

async function searchDestination() {
  if (!state.destination.address.trim()) return showToast("请先输入目的地名称或地址");
  setLocationBusy(true, "正在搜索目的地……");
  try {
    const result = await api("/api/search", { city: document.querySelector("#city").value, query: state.destination.address });
    state.destination.point = result.point;
    state.destination.detail = result.address;
    setSelectionMarker("destination", "D", result.point, "#254514");
    renderDestination();
    map.setView([result.point.wgs.lat, result.point.wgs.lng], 14);
  } catch (error) {
    showToast(error.message);
  } finally {
    setLocationBusy(false);
  }
}

async function searchWaypoint(waypoint, index) {
  if (!waypoint.address.trim()) return showToast("请先输入途经点名称或地址");
  setLocationBusy(true, `正在搜索途经点 W${index + 1}……`);
  try {
    const result = await api("/api/search", { city: document.querySelector("#city").value, query: waypoint.address });
    waypoint.point = result.point;
    waypoint.detail = result.address;
    setSelectionMarker(waypoint.id, `W${index + 1}`, waypoint.point, "#d7792d");
    renderWaypoints();
    map.setView([waypoint.point.wgs.lat, waypoint.point.wgs.lng], 14);
  } catch (error) {
    showToast(error.message);
  } finally {
    setLocationBusy(false);
  }
}

function toggleMapPick(target) {
  const same = state.activePick?.type === target.type && state.activePick?.id === target.id;
  state.activePick = same ? null : target;
  document.querySelector("#pick-hint").textContent = state.activePick ? "请在地图上点击目标位置" : "搜索地点后将在地图中标记";
  map.getContainer().style.cursor = state.activePick ? "crosshair" : "grab";
  renderOrigins();
  renderWaypoints();
  renderDestination();
}

map.on("click", async (event) => {
  if (!state.activePick) return;
  const target = state.activePick;
  setLocationBusy(true, "正在识别地图位置……");
  try {
    const result = await api("/api/reverse", { lng: event.latlng.lng, lat: event.latlng.lat });
    if (target.type === "destination") {
      state.destination.address = result.address;
      state.destination.detail = result.address;
      state.destination.point = result.point;
      setSelectionMarker("destination", "D", result.point, "#254514");
    } else if (target.type === "waypoint") {
      const index = state.waypoints.findIndex((waypoint) => waypoint.id === target.id);
      if (index >= 0) {
        const waypoint = state.waypoints[index];
        waypoint.address = result.address;
        waypoint.detail = result.address;
        waypoint.point = result.point;
        setSelectionMarker(waypoint.id, `W${index + 1}`, result.point, "#d7792d");
      }
    } else {
      const index = state.origins.findIndex((origin) => origin.id === target.id);
      if (index >= 0) {
        const origin = state.origins[index];
        origin.address = result.address;
        origin.detail = result.address;
        origin.point = result.point;
        setSelectionMarker(origin.id, origin.name || String(index + 1), result.point, riderColors[index]);
      }
    }
    state.activePick = null;
    map.getContainer().style.cursor = "grab";
    document.querySelector("#pick-hint").textContent = "地图选点已完成";
    renderOrigins();
    renderWaypoints();
    renderDestination();
  } catch (error) {
    showToast(error.message);
  } finally {
    setLocationBusy(false);
  }
});

function setLocationBusy(busy, text = "") {
  document.querySelector("#system-status").lastChild.textContent = busy ? text : "地图服务就绪";
}

function numericValue(selector, fallback) {
  const value = Number(document.querySelector(selector).value);
  return Number.isFinite(value) ? value : fallback;
}

async function createPlan() {
  const origins = state.origins.map((origin, index) => ({
    name: origin.name.trim() || `骑行者${index + 1}`,
    address: origin.address.trim(),
    point: origin.point,
  }));
  const waypoints = state.waypoints.map((waypoint) => ({
    address: waypoint.address.trim(),
    point: waypoint.point,
  }));
  if (origins.some((origin) => !origin.address)) return showToast("请填写所有骑行者的起点");
  if (waypoints.some((waypoint) => !waypoint.address)) return showToast("请填写所有途经点");
  if (!state.destination.address.trim()) return showToast("请填写共同目的地");

  const button = document.querySelector("#plan-button");
  button.disabled = true;
  document.querySelector("#loading-panel").hidden = false;
  document.querySelector("#results-panel").hidden = true;
  try {
    const plan = await api("/api/plan", {
      city: document.querySelector("#city").value.trim() || "北京",
      origins,
      waypoints,
      destination: { address: state.destination.address.trim(), point: state.destination.point },
      options: {
        max_detour_ratio: numericValue("#max-detour", 0.15),
        route_corridor_m: numericValue("#corridor", 1500),
        min_direction_cosine: numericValue("#direction", 0.65),
        min_contiguous_shared_m: numericValue("#shared-segment", 600),
        top_n: numericValue("#top-n", 3),
      },
    });
    plan.waypoints.forEach((waypoint, index) => {
      const current = state.waypoints[index];
      if (current) {
        current.point = waypoint.point;
        current.detail = waypoint.address;
        setSelectionMarker(current.id, `W${index + 1}`, current.point, "#d7792d");
      }
    });
    state.plan = plan;
    state.selectedResult = 0;
    plan.origins.forEach((origin, index) => {
      const current = state.origins[index];
      if (current) {
        current.point = origin.point;
        current.detail = origin.address;
        setSelectionMarker(current.id, current.name, current.point, riderColors[index]);
      }
    });
    state.destination.point = plan.destination.point;
    state.destination.detail = plan.destination.address;
    setSelectionMarker("destination", "D", plan.destination.point, "#254514");
    renderOrigins();
    renderWaypoints();
    renderDestination();
    renderResults();
    selectResult(0);
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    document.querySelector("#loading-panel").hidden = true;
  }
}

function formatKm(meters) { return `${(meters / 1000).toFixed(1)} 公里`; }
function formatMinutes(seconds) { return `${Math.round(seconds / 60)} 分钟`; }

function renderResults() {
  const panel = document.querySelector("#results-panel");
  const list = document.querySelector("#result-list");
  const results = state.plan?.results || [];
  document.querySelector("#result-count").textContent = state.plan?.is_fallback ? "集合方案" : `${results.length} 个最近可行点`;
  list.innerHTML = results.map((result, index) => `
    <article class="result-card ${index === state.selectedResult ? "active" : ""}" data-index="${index}" tabindex="0">
      <span class="result-rank">${String(index + 1).padStart(2, "0")}</span>
      <div>
        <h3>${escapeHtml(result.label)}</h3>
        <p class="result-address">${escapeHtml(result.address || "路线会合点")}</p>
        ${result.is_fallback ? `<p class="result-address">${escapeHtml(result.fallback_instruction)}</p>` : ""}
        <div class="result-metrics">
          <span class="metric">最远会合距离 ${formatKm(result.max_to_meet_distance_m)}</span>
          <span class="metric">共同骑行 ${formatKm(result.shared_distance_m)}</span>
          <span class="metric">约 ${formatMinutes(result.shared_duration_s)}</span>
          <span class="metric">最大绕行 ${result.max_detour_ratio == null ? "未评估" : (result.max_detour_ratio * 100).toFixed(1) + "%"}</span>
          <span class="metric">到达差 ${formatMinutes(result.arrival_spread_s)}</span>
        </div>
      </div>
    </article>`).join("");
  list.querySelectorAll(".result-card").forEach((card) => {
    const choose = () => selectResult(Number(card.dataset.index));
    card.addEventListener("click", choose);
    card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") choose(); });
  });
  panel.hidden = false;
}

function selectResult(index) {
  const result = state.plan?.results?.[index];
  if (!result) return;
  state.selectedResult = index;
  document.querySelectorAll(".result-card").forEach((card, cardIndex) => card.classList.toggle("active", cardIndex === index));
  routeLayer.clearLayers();

  result.routes.riders.forEach((points, riderIndex) => {
    L.polyline(points, { color: riderColors[riderIndex], weight: 3, opacity: .82, dashArray: "8 7" }).addTo(routeLayer);
  });
  if (result.routes.shared.length > 1) L.polyline(result.routes.shared, { color: "#315b1b", weight: 5, opacity: .95 }).addTo(routeLayer);
  const meeting = result.point.wgs;
  L.marker([meeting.lat, meeting.lng], { icon: markerIcon("M", "#b9ed52", true), zIndexOffset: 1000 })
    .bindPopup(`<strong>${escapeHtml(result.label)}</strong><br>共同骑行 ${formatKm(result.shared_distance_m)}<br>${result.is_fallback ? "集合点" : "最大绕行 " + (result.max_detour_ratio * 100).toFixed(1) + "%"}`)
    .addTo(routeLayer);
  fitMap();
}

function fitMap() {
  const bounds = [];
  [selectionLayer, routeLayer].forEach((group) => group.eachLayer((layer) => {
    if (typeof layer.getLatLng === "function") bounds.push(layer.getLatLng());
    if (typeof layer.getLatLngs === "function") layer.getLatLngs().flat(Infinity).forEach((point) => {
      if (point && Number.isFinite(point.lat) && Number.isFinite(point.lng)) bounds.push(point);
    });
  }));
  if (bounds.length) map.fitBounds(L.latLngBounds(bounds), { padding: [42, 42], maxZoom: 14 });
  else map.setView([39.94, 116.42], 11);
}

document.querySelector("#add-origin").addEventListener("click", addOrigin);
document.querySelector("#add-waypoint").addEventListener("click", addWaypoint);
document.querySelector("#search-destination").addEventListener("click", searchDestination);
document.querySelector("#pick-destination").addEventListener("click", () => toggleMapPick({ type: "destination" }));
document.querySelector("#destination-address").addEventListener("input", (event) => {
  state.destination.address = event.target.value;
  if (state.destination.point) {
    state.destination.point = null;
    state.destination.detail = "地址已修改，请重新搜索或直接生成方案";
    setSelectionMarker("destination", "", null, "");
    renderDestination();
  }
});
document.querySelector("#plan-button").addEventListener("click", createPlan);
document.querySelector("#fit-map").addEventListener("click", fitMap);
document.querySelector("#close-results").addEventListener("click", () => { document.querySelector("#results-panel").hidden = true; });

renderOrigins();
renderWaypoints();
renderDestination();
