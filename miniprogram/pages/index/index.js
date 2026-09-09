const { apiBaseUrl } = require("../../config");
const COLORS = ["#3478f6", "#f59e0b", "#8b5cf6", "#06b6d4", "#db2777", "#64748b", "#ca8a04", "#0f766e"];
let nextId = 1;
const place = (address = "", name = "") => ({ id: nextId++, name, address, point: null });
const position = point => ({ latitude: point.gcj.lat, longitude: point.gcj.lng });
const distance = metres => ((metres || 0) / 1000).toFixed(1) + " 公里";

Page({
  data: {
    city: "北京",
    origins: [place("西单地铁站", "A"), place("丰台科技园", "B"), place("北京工业大学", "C")],
    waypoints: [], destination: place("潭柘寺"),
    options: { maxDetour: "0.15", corridor: "1500", top: "5" }, optionsOpen: false,
    mapCenter: { latitude: 39.9042, longitude: 116.4074 }, mapScale: 10,
    markers: [], polylines: [], legend: [],
    sheetMode: "normal", sheetHeight: 330, mapHeight: 410, viewportHeight: 740, panel: "edit",
    searchOpen: false, searchQuery: "", searchCity: "北京", searchTitle: "",
    searchResults: [], searched: false, searching: false, error: "",
    mapPicking: false, pickedPlace: null, planning: false,
    results: [], selectedResult: 0, activeResult: null
  },

  onLoad() {
    this._version = 0; this._searchVersion = 0; this._plans = [];
    this._window = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    this.setSheet("normal");
  },
  onReady() { this._map = wx.createMapContext("routeMap", this); this.fitMap(); },
  onUnload() { this._version++; this._searchVersion++; },
  onResize(event) { this._window = { ...this._window, ...event.size }; this.setSheet(this.data.sheetMode); },
  sheetGeometry() {
    const info = this._window || {};
    const height = Number(info.windowHeight) > 0 ? Number(info.windowHeight) : 740;
    const safeBottom = info.safeArea && Number.isFinite(info.screenHeight) ? Math.max(0, info.screenHeight - info.safeArea.bottom) : 0;
    const collapsed = Math.min(140 + safeBottom, Math.round(height * 0.45));
    const expanded = Math.max(collapsed, Math.round(height * 0.76));
    const normal = Math.max(collapsed, Math.min(expanded, Math.round(height * 0.46)));
    return { height, collapsed, normal, expanded };
  },
  setSheet(mode) {
    const sizes = this.sheetGeometry();
    const sheetHeight = sizes[mode];
    // 原生 map 有自己的默认高度，不能只靠 top/bottom 拉伸。
    // 面板和地图显式分配可用视窗，也让底图来源标识保持可见。
    this.setData({ sheetMode: mode, sheetHeight, mapHeight: sizes.height - sheetHeight, viewportHeight: sizes.height }, () => {
      if (wx.nextTick) wx.nextTick(() => this.fitMap());
      else this.fitMap();
    });
  },
  toggleSheet() {
    if (Date.now() < (this._suppressSheetTapUntil || 0)) return;
    this.setSheet(this.data.sheetMode === "collapsed" ? "normal" : "collapsed");
  },
  expandSheet() { this.setSheet(this.data.sheetMode === "expanded" ? "normal" : "expanded"); },
  onSheetTouchStart(event) {
    if (!event.touches.length) return;
    this._sheetDrag = { y: event.touches[0].clientY, height: this.data.sheetHeight, mode: this.data.sheetMode, moved: false, updatedAt: 0 };
  },
  onSheetTouchMove(event) {
    const drag = this._sheetDrag;
    if (!drag || !event.touches.length) return;
    const delta = event.touches[0].clientY - drag.y;
    if (Math.abs(delta) < 6 && !drag.moved) return;
    drag.moved = true;
    const now = Date.now();
    if (now - drag.updatedAt < 24) return;
    drag.updatedAt = now;
    const sizes = this.sheetGeometry();
    const sheetHeight = Math.max(sizes.collapsed, Math.min(sizes.expanded, drag.height - delta));
    this.setData({ sheetHeight, mapHeight: sizes.height - sheetHeight });
  },
  onSheetTouchEnd(event) {
    const drag = this._sheetDrag;
    this._sheetDrag = null;
    if (!drag || !event.changedTouches.length) return;
    const delta = event.changedTouches[0].clientY - drag.y;
    if (!drag.moved && Math.abs(delta) < 6) return;
    const sizes = this.sheetGeometry();
    const modes = ["collapsed", "normal", "expanded"];
    const target = Math.max(sizes.collapsed, Math.min(sizes.expanded, drag.height - delta));
    let nearest = modes.reduce((best, mode) => Math.abs(sizes[mode] - target) < Math.abs(sizes[best] - target) ? mode : best, drag.mode);
    // 较短的上/下滑也能切换一档；拖动后的 tap 不再次反转面板状态。
    if (nearest === drag.mode && Math.abs(delta) > 25) nearest = modes[Math.max(0, Math.min(2, modes.indexOf(drag.mode) + (delta < 0 ? 1 : -1)))];
    this._suppressSheetTapUntil = Date.now() + 250;
    this.setSheet(nearest);
  },
  onSheetTouchCancel() {
    const drag = this._sheetDrag;
    this._sheetDrag = null;
    if (drag) this.setSheet(drag.mode);
  },
  toggleOptions() { this.setData({ optionsOpen: !this.data.optionsOpen }); },
  noop() {},
  invalidate() {
    this._version++; this._plans = [];
    this.setData({ results: [], activeResult: null, panel: "edit", polylines: [], error: "" });
  },
  onOptionInput(event) {
    this.invalidate();
    this.setData({ ["options." + event.currentTarget.dataset.field]: event.detail.value }, () => this.refreshMap());
  },
  onOriginNameInput(event) {
    this.invalidate();
    this.setData({ ["origins[" + Number(event.currentTarget.dataset.index) + "].name"]: event.detail.value }, () => this.refreshMap());
  },
  addOrigin() {
    if (this.data.origins.length >= 8) return this.toast("最多添加 8 名骑行者");
    const names = this.data.origins.map(item => item.name);
    const name = "ABCDEFGH".split("").find(item => !names.includes(item)) || "骑友";
    this.invalidate();
    this.setData({ origins: [...this.data.origins, place("", name)] }, () => this.refreshMap());
  },
  removeOrigin(event) {
    if (this.data.origins.length <= 2) return;
    this.invalidate();
    this.setData({ origins: this.data.origins.filter((_, i) => i !== Number(event.currentTarget.dataset.index)) }, () => this.refreshMap());
  },
  addWaypoint() {
    if (this.data.waypoints.length >= 8) return this.toast("最多添加 8 个途经点");
    this.invalidate();
    this.setData({ waypoints: [...this.data.waypoints, place()] }, () => this.refreshMap());
  },
  removeWaypoint(event) {
    this.invalidate();
    this.setData({ waypoints: this.data.waypoints.filter((_, i) => i !== Number(event.currentTarget.dataset.index)) }, () => this.refreshMap());
  },
  moveWaypoint(event) {
    const index = Number(event.currentTarget.dataset.index), target = index + Number(event.currentTarget.dataset.step);
    if (target < 0 || target >= this.data.waypoints.length) return;
    const waypoints = [...this.data.waypoints];
    [waypoints[index], waypoints[target]] = [waypoints[target], waypoints[index]];
    this.invalidate(); this.setData({ waypoints }, () => this.refreshMap());
  },
  editRoute() { this.setData({ panel: "edit" }); this.setSheet("normal"); },
  backToResults() { this.setData({ panel: "results" }); this.setSheet("normal"); },
  openSearch(event) {
    const { kind = "destination", index = 0 } = event.currentTarget.dataset;
    const target = kind === "origin" ? this.data.origins[index] : kind === "waypoint" ? this.data.waypoints[index] : this.data.destination;
    this._target = { kind, id: target.id }; this._searchVersion++;
    this.setData({ searchOpen: true, searchQuery: target.address, searchCity: this.data.city,
      searchTitle: kind === "origin" ? target.name + " 的起点" : kind === "waypoint" ? "途经点 " + (Number(index) + 1) : "最终目的地",
      searchResults: [], searched: false, searching: false, error: "" });
    if (target.address) this.searchPlace();
  },
  closeSearch() { this._searchVersion++; this.setData({ searchOpen: false, searching: false, error: "" }); },
  onSearchInput(event) {
    this._searchVersion++;
    this.setData({ searchQuery: event.detail.value, searchResults: [], searched: false, searching: false, error: "" });
  },
  onCityInput(event) {
    this._searchVersion++;
    this.setData({ searchCity: event.detail.value, searchResults: [], searched: false, searching: false, error: "" });
  },
  clearQuery() { this.onSearchInput({ detail: { value: "" } }); },
  async searchPlace() {
    if (!this.data.searchQuery.trim() || !this.data.searchCity.trim()) return this.toast("请填写城市和地点");
    const version = ++this._searchVersion;
    this.setData({ searching: true, error: "", searchResults: [], searched: false });
    try {
      const result = await this.request("/api/search/places", { city: this.data.searchCity.trim(), query: this.data.searchQuery.trim() });
      if (version === this._searchVersion) this.setData({ searchResults: result.results, searched: true });
    } catch (error) {
      if (version === this._searchVersion) this.setData({ error: error.message });
    } finally {
      if (version === this._searchVersion) this.setData({ searching: false });
    }
  },
  chooseSearchResult(event) {
    const result = this.data.searchResults[Number(event.currentTarget.dataset.index)];
    if (result) this.applyPlace(result);
  },
  applyPlace(result) {
    const { kind, id } = this._target;
    const collection = kind === "origin" ? "origins" : "waypoints";
    const index = kind === "destination" ? -1 : this.data[collection].findIndex(item => item.id === id);
    if (kind !== "destination" && index < 0) return;
    const key = kind === "destination" ? "destination" : collection + "[" + index + "]";
    const original = kind === "destination" ? this.data.destination : this.data[collection][index];
    this.invalidate(); this._searchVersion++;
    this.setData({ [key]: { ...original, address: result.label, resolvedAddress: result.address, point: result.point },
      city: this.data.searchCity.trim() || this.data.city, searchOpen: false, mapPicking: false, searching: false, pickedPlace: null
    }, () => { this.refreshMap(); this.setSheet("normal"); });
  },
  startMapPicking() {
    this._searchVersion++;
    this.setData({ searchOpen: false, mapPicking: true, pickedPlace: null, searching: false, error: "" });
    this.setSheet("collapsed");
  },
  cancelMapPicking() {
    this._searchVersion++;
    this.setData({ mapPicking: false, pickedPlace: null, searchOpen: true, searching: false, error: "" });
    this.refreshMap(); this.setSheet("normal");
  },
  async onMapTap(event) {
    if (!this.data.mapPicking) return;
    const version = ++this._searchVersion;
    this.setData({ searching: true, pickedPlace: null, error: "" });
    try {
      const result = await this.request("/api/reverse", { lng: event.detail.longitude, lat: event.detail.latitude, coordinate_system: "gcj" });
      if (version !== this._searchVersion) return;
      this.setData({ pickedPlace: result });
      this.refreshMap([{ id: 99, ...position(result.point), iconPath: "/assets/origin.png", width: 28, height: 36, label: { content: "选中位置", color: "#3478f6", bgColor: "#ffffff", padding: 8 } }], false);
    } catch (error) {
      if (version === this._searchVersion) this.setData({ error: error.message });
    } finally {
      if (version === this._searchVersion) this.setData({ searching: false });
    }
  },
  confirmMapPick() { if (this.data.pickedPlace) this.applyPlace(this.data.pickedPlace); },
  request(path, data) {
    return new Promise((resolve, reject) => wx.request({
      url: apiBaseUrl + path, method: "POST", data, timeout: 120000,
      success: response => response.statusCode >= 200 && response.statusCode < 300 ? resolve(response.data) : reject(new Error(response.data && response.data.error || "路线服务暂时不可用，请稍后重试")),
      fail: () => reject(new Error("连接路线服务失败，请检查网络或服务状态后重试"))
    }));
  },
  async generatePlan() {
    if (this.data.planning) return;
    const { origins, waypoints, destination, options } = this.data;
    // 未经用户确认的地址不自动采用第一个搜索结果，逐个引导选择地点。
    const missingOrigin = origins.findIndex(item => !item.point);
    const missingWaypoint = waypoints.findIndex(item => !item.point);
    if (missingOrigin >= 0 || missingWaypoint >= 0 || !destination.point) {
      const kind = missingOrigin >= 0 ? "origin" : missingWaypoint >= 0 ? "waypoint" : "destination";
      this.openSearch({ currentTarget: { dataset: { kind, index: missingOrigin >= 0 ? missingOrigin : Math.max(0, missingWaypoint) } } });
      return this.toast("请先从搜索结果中确认每个地点");
    }
    if (origins.some(item => !item.name.trim()) || new Set(origins.map(item => item.name.trim())).size !== origins.length) return this.toast("骑行者名称不能为空或重复");
    const detour = Number(options.maxDetour), corridor = Number(options.corridor), top = Number(options.top);
    if (!options.maxDetour.trim() || !options.corridor.trim() || !options.top.trim() || !Number.isFinite(detour) || detour < 0 || detour > 1 || !Number.isFinite(corridor) || corridor <= 0 || !Number.isInteger(top) || top < 1 || top > 5) return this.toast("请检查参数：绕行 0～1、走廊大于 0、方案 1～5 个");
    this.invalidate(); this.refreshMap();
    const version = this._version;
    this.setData({ planning: true });
    try {
      const result = await this.request("/api/plan", { city: this.data.city, origins, waypoints, destination,
        options: { max_detour_ratio: detour, route_corridor_m: corridor, top_n: top } });
      if (version !== this._version) return;
      this._plans = result.results;
      const results = result.results.map((item, index) => ({
        id: index, label: item.label, address: item.address, maxMeetText: distance(item.max_to_meet_distance_m),
        sharedText: distance(item.shared_distance_m), detourText: item.max_detour_ratio == null ? "未评估" : (item.max_detour_ratio * 100).toFixed(1) + "%",
        isFallback: Boolean(item.is_fallback), hasSharedRoute: item.has_shared_route !== false,
        sharedStops: (item.shared_targets || []).map(target => target.address).join(" → "),
        riders: item.riders.map((rider, i) => ({ name: rider.name, color: COLORS[i], distance: distance(rider.to_meet_distance_m) }))
      }));
      this.setData({ results, panel: results.length ? "results" : "edit", error: results.length ? "" : "没有找到满足条件的方案，请调整途经点或绕行限制" }, () => { this.showResult(0); this.setSheet("normal"); });
    } catch (error) {
      if (version === this._version) this.setData({ error: error.message });
    } finally { this.setData({ planning: false }); }
  },
  onResultChange(event) { this.showResult(event.detail.current); },
  selectResult(event) { this.showResult(Number(event.currentTarget.dataset.index)); },
  showResult(index) {
    const result = this._plans[index]; if (!result) return;
    const makeLine = (points, color, width) => ({ points: (points || []).map(([latitude, longitude]) => ({ latitude, longitude })), color, width, arrowLine: true });
    const polylines = (result.routes.riders_gcj || []).map((route, i) => makeLine(route, COLORS[i], 3));
    polylines.push(makeLine(result.routes.shared_gcj, "#16a56a", 5));
    this.setData({ selectedResult: index, activeResult: this.data.results[index], polylines: polylines.filter(line => line.points.length > 1),
      }, () => this.refreshMap());
  },
  refreshMap(extra = [], fit = true) {
    const markers = [];
    const add = (item, label, color, icon = "origin") => {
      if (item.point) markers.push({ id: markers.length + 1, ...position(item.point), iconPath: "/assets/" + icon + ".png", width: 28, height: 36, label: { content: label, color: "#ffffff", bgColor: color, borderRadius: 12, padding: 6 } });
    };
    this.data.origins.forEach((item, i) => add(item, item.name, COLORS[i]));
    this.data.waypoints.forEach((item, i) => add(item, "途经" + (i + 1), "#f59e0b", "waypoint"));
    add(this.data.destination, "终点", "#ef5350", "destination");
    const selected = this._plans[this.data.selectedResult];
    if (this.data.activeResult && selected) {
      const meeting = position(selected.point);
      const existing = selected.is_fallback && markers.find(marker => marker.latitude === meeting.latitude && marker.longitude === meeting.longitude);
      if (existing) {
        existing.label = { ...existing.label, content: "集合点", bgColor: "#16a56a" };
        existing.iconPath = "/assets/meeting.png";
      } else add(selected, "汇合", "#16a56a", "meeting");
    }
    this.setData({ markers: [...markers, ...extra], legend: this.data.origins.map((item, i) => ({ name: item.name, color: COLORS[i] })) }, () => { if (fit) this.fitMap(); });
  },
  fitMap() {
    if (!this._map || this.data.mapPicking) return;
    const points = this.data.markers.map(({ latitude, longitude }) => ({ latitude, longitude }));
    this.data.polylines.forEach(line => points.push(...line.points));
    if (points.length) this._map.includePoints({ points, padding: [85, 55, 30, 30] });
  },
  changeZoom(delta) {
    const update = scale => this.setData({ mapScale: Math.max(3, Math.min(20, scale + delta)) });
    if (this._map && this._map.getScale) this._map.getScale({ success: result => update(result.scale), fail: () => update(this.data.mapScale) });
    else update(this.data.mapScale);
  },
  zoomIn() { this.changeZoom(1); },
  zoomOut() { this.changeZoom(-1); },
  toast(title) { wx.showToast({ title, icon: "none", duration: 3000 }); }
});
