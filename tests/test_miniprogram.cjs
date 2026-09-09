// 不依赖微信运行时的交互回归测试：node --test tests/test_miniprogram.cjs
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function createPage() {
  let page;
  const wx = { getWindowInfo: () => ({ windowHeight: 760 }), showToast() {}, createMapContext: () => ({ includePoints() {} }) };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../miniprogram/pages/index/index.js'), 'utf8'), {
    require: () => ({ apiBaseUrl: 'https://example.test' }), wx,
    Page: definition => { page = definition; }
  });
  page.setData = (values, callback) => {
    for (const [key, value] of Object.entries(values)) {
      const parts = key.replace(/\[(\d+)\]/g, '.$1').split('.');
      let object = page.data;
      for (const part of parts.slice(0, -1)) object = object[part];
      object[parts.at(-1)] = value;
    }
    if (callback) callback();
  };
  page.onLoad(); page.onReady();
  return page;
}
const event = dataset => ({ currentTarget: { dataset } });
const candidate = (id, lat) => ({ id, label: '地点' + id, address: '地址' + id, point: { gcj: { lng: 116.4, lat } } });

test('选择第二条搜索结果，保持姓名并保存对应坐标', async () => {
  const page = createPage();
  const choices = [candidate('1', 39.9), candidate('2', 39.8)];
  page.request = async () => ({ results: choices });
  page.openSearch(event({ kind: 'origin', index: 1 }));
  await new Promise(setImmediate);
  assert.equal(page.data.searchResults.length, 2);
  assert.equal(page.data.origins[1].point, null);
  page.chooseSearchResult(event({ index: 1 }));
  assert.equal(page.data.origins[1].name, 'B');
  assert.equal(page.data.origins[1].point.gcj.lat, 39.8);
  assert.equal(page.data.searchOpen, false);
});
test('旧搜索响应不能覆盖新关键词的搜索结果', async () => {
  const page = createPage();
  let resolveFirst;
  page.request = () => new Promise(resolve => { resolveFirst = resolve; });
  page.openSearch(event({ kind: 'destination' }));
  page.onSearchInput({ detail: { value: '新关键词' } });
  page.request = async () => ({ results: [candidate('新', 39.7)] });
  await page.searchPlace();
  resolveFirst({ results: [candidate('旧', 39.9)] });
  await new Promise(setImmediate);
  assert.equal(page.data.searchResults[0].label, '地点新');
});
test('搜索无结果和失败均有可恢复状态', async () => {
  const page = createPage();
  page.setData({ searchQuery: '不存在' });
  page.request = async () => ({ results: [] });
  await page.searchPlace();
  assert.equal(page.data.searched, true);
  assert.equal(page.data.searching, false);
  page.request = async () => { throw new Error('服务不可用'); };
  await page.searchPlace();
  assert.equal(page.data.error, '服务不可用');
  assert.equal(page.data.searching, false);
});
test('途经点排序与删除清除旧路线', () => {
  const page = createPage();
  page.addWaypoint(); page.addWaypoint();
  const first = page.data.waypoints[0].id;
  page.setData({ results: [{}], polylines: [{}], activeResult: {} });
  page.moveWaypoint(event({ index: '0', step: '1' }));
  assert.equal(page.data.waypoints[1].id, first);
  assert.equal(page.data.results.length, 0);
  assert.equal(page.data.polylines.length, 0);
  page.removeWaypoint(event({ index: '1' }));
  assert.equal(page.data.waypoints.length, 1);
});
test('规划前要求确认地点，不擅自使用第一条结果', async () => {
  const page = createPage();
  const called = [];
  page.request = async url => { called.push(url); return { results: [] }; };
  await page.generatePlan();
  assert.equal(page.data.searchOpen, true);
  assert.equal(page.data.planning, false);
  assert.ok(!called.includes('/api/plan'));
});
test('选点必须点击确认，取消后不会写入', async () => {
  const page = createPage();
  page.request = async url => url === '/api/reverse' ? candidate('地图', 39.9) : { results: [] };
  page.openSearch(event({ kind: 'destination' }));
  page.startMapPicking();
  await page.onMapTap({ detail: { longitude: 116.4, latitude: 39.9 } });
  assert.equal(page.data.destination.point, null);
  page.cancelMapPicking();
  assert.equal(page.data.destination.point, null);
  page.startMapPicking();
  await page.onMapTap({ detail: { longitude: 116.4, latitude: 39.9 } });
  page.confirmMapPick();
  assert.equal(page.data.destination.address, '地点地图');
});
test('底部面板支持三种高度且不超过视窗', () => {
  const page = createPage();
  page.setSheet('collapsed'); const collapsed = page.data.sheetHeight;
  page.setSheet('normal'); const normal = page.data.sheetHeight;
  page.setSheet('expanded'); const expanded = page.data.sheetHeight;
  assert.ok(collapsed < normal && normal < expanded && expanded < 760);
});
test('WXML 中的事件处理函数全部存在', () => {
  const page = createPage();
  const template = fs.readFileSync(path.join(__dirname, '../miniprogram/pages/index/index.wxml'), 'utf8');
  for (const match of template.matchAll(/(?:bind|catch)[a-z]+="([A-Za-z]+)"/g)) assert.equal(typeof page[match[1]], 'function', match[1]);
});

test('生成方案使用选定坐标，切换卡片同步地图路线', async () => {
  const page = createPage();
  page.data.origins.forEach((item, i) => { item.point = candidate(String(i), 39.9 + i / 100).point; });
  page.data.destination.point = candidate('终', 39.8).point;
  let submitted;
  const result = id => ({ label: '汇合点' + id, point: candidate(id, 39.85).point,
    max_to_meet_distance_m: 5000, shared_distance_m: 10000, max_detour_ratio: .05,
    riders: page.data.origins.map(item => ({ name: item.name, to_meet_distance_m: 5000 })),
    routes: { riders_gcj: [[[39.9, 116.4], [39.85, 116.4]]], shared_gcj: [[39.85, 116.4], [39.8, 116.5 + id / 100]] } });
  page.request = async (url, data) => { submitted = data; return { results: [result(0), result(1)] }; };
  await page.generatePlan();
  assert.equal(submitted.origins[1].point.gcj.lat, 39.91);
  assert.equal(page.data.panel, 'results');
  assert.equal(page.data.activeResult.label, '汇合点0');
  page.onResultChange({ detail: { current: 1 } });
  assert.equal(page.data.activeResult.label, '汇合点1');
  assert.equal(page.data.polylines.at(-1).points.at(-1).longitude, 116.51);
  assert.equal(page.data.planning, false);
});

test('安全区计入收起高度，底部按钮不落入手势区域', () => {
  const page = createPage();
  page._window = { windowHeight: 740, screenHeight: 844, safeArea: { bottom: 810 } };
  page.setSheet('collapsed');
  assert.equal(page.data.sheetHeight, 174);
});

test('原生地图显式绑定高度，地图加面板始终填满视窗', () => {
  const page = createPage();
  const template = fs.readFileSync(path.join(__dirname, '../miniprogram/pages/index/index.wxml'), 'utf8');
  assert.match(template, /<map[^>]*style="height: \{\{mapHeight\}\}px;"/);
  for (const height of [568, 740, 844]) {
    page.onResize({ size: { windowHeight: height } });
    for (const mode of ['collapsed', 'normal', 'expanded']) {
      page.setSheet(mode);
      assert.equal(page.data.mapHeight + page.data.sheetHeight, height);
      assert.equal(page.data.viewportHeight, height);
      assert.ok(page.data.mapHeight > 0);
    }
  }
});

test('下拉面板时地图实时增高，松手后收起', () => {
  const page = createPage();
  const original = page.data.mapHeight;
  page.onSheetTouchStart({ touches: [{ clientY: 400 }] });
  page.onSheetTouchMove({ touches: [{ clientY: 500 }] });
  assert.equal(page.data.mapHeight, original + 100);
  assert.equal(page.data.mapHeight + page.data.sheetHeight, 760);
  page.onSheetTouchEnd({ changedTouches: [{ clientY: 600 }] });
  assert.equal(page.data.sheetMode, 'collapsed');
  assert.equal(page.data.mapHeight, 760 - 140);
  page.toggleSheet();
  assert.equal(page.data.sheetMode, 'collapsed', '拖动后产生的 tap 不应重新展开');
});

test('上拉面板扩大表单，但不会留下灰色空隙', () => {
  const page = createPage();
  page.onSheetTouchStart({ touches: [{ clientY: 400 }] });
  page.onSheetTouchMove({ touches: [{ clientY: 200 }] });
  assert.equal(page.data.mapHeight + page.data.sheetHeight, 760);
  page.onSheetTouchEnd({ changedTouches: [{ clientY: 200 }] });
  assert.equal(page.data.sheetMode, 'expanded');
  assert.equal(page.data.mapHeight + page.data.sheetHeight, 760);
});

test('取消拖动恢复原有面板和地图尺寸', () => {
  const page = createPage();
  const previous = page.data.mapHeight;
  page.onSheetTouchStart({ touches: [{ clientY: 400 }] });
  page.onSheetTouchMove({ touches: [{ clientY: 500 }] });
  page.onSheetTouchCancel();
  assert.equal(page.data.sheetMode, 'normal');
  assert.equal(page.data.mapHeight, previous);
});

test('短距离下滑也可以收起面板，点击可以重新展开', () => {
  const page = createPage();
  page.onSheetTouchStart({ touches: [{ clientY: 400 }] });
  page.onSheetTouchEnd({ changedTouches: [{ clientY: 435 }] });
  assert.equal(page.data.sheetMode, 'collapsed');
  page._suppressSheetTapUntil = 0;
  page.toggleSheet();
  assert.equal(page.data.sheetMode, 'normal');
});

test('保底方案显示未评估绕行，不重复绘制终点集合标记', async () => {
  const page = createPage();
  page.data.origins.forEach((item, i) => { item.point = candidate(String(i), 39.9 + i / 100).point; });
  page.data.destination.point = candidate('终', 39.8).point;
  page.request = async () => ({ results: [{ label: '终点', point: page.data.destination.point,
    is_fallback: true, fallback_reason: '没有符合约束的点', fallback_instruction: '分别前往终点',
    has_shared_route: false, shared_targets: [], max_detour_ratio: null,
    max_to_meet_distance_m: 5000, shared_distance_m: 0,
    riders: page.data.origins.map(item => ({ name: item.name, to_meet_distance_m: 5000 })),
    routes: { riders_gcj: [[[39.9, 116.4], [39.8, 116.4]]], shared_gcj: [] }
  }] });
  await page.generatePlan();
  assert.equal(page.data.activeResult.isFallback, true);
  assert.equal(page.data.activeResult.detourText, '未评估');
  assert.equal(page.data.activeResult.hasSharedRoute, false);
  assert.equal(page.data.polylines.length, 1);
  assert.equal(page.data.markers.filter(item => item.latitude === 39.8).length, 1);
  assert.equal(page.data.markers.at(-1).label.content, '集合点');
});

test('界面不显示保底标记，内部仍保留分段路线逻辑', () => {
  for (const file of ['miniprogram/pages/index/index.wxml', 'miniprogram/pages/index/index.js', 'ride_converge/web/app.js']) {
    const source = fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
    assert.ok(!source.includes('保底'), file);
  }
});
