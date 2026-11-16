// 澪图库页面脚本。
// 界面骨架、样式表、控件层级与六库页（gallery.mjs / style.css）完全一致：
//   一级 .lib-nav（日系图库 / 澪图库）→ 二级 .tabs（系列）→ 三级 .categories（卷）→ 网格 → 详情。
// 唯一的差别是数据维度：这里的二级是「系列」、三级是「卷」，六库那边是「库」和「分类」。
// 所以只复用标签样式，不复制样式表 —— 新增按系列组织的库照这一份抄，别再写第二个 CSS。
const API = '/ref_lookbook/catalog/mio';
const ASSET_BASE = '/ref_lookbook/assets/';
const PAGE = 60;
const SERIES_ORDER = ['发型', '服装', '姿势'];

const state = {
  rows: [],
  volumes: [],
  bySlug: new Map(),
  byId: new Map(),
  series: new Map(),   // series_zh -> { slug, volumes: [] }
  view: { type: 'all' },
  query: '',
  list: [],            // 当前视图下的有序记录，供弹窗上一个 / 下一个
  shown: PAGE,
  current: -1,
  selectedId: '',      // 节点回填时高亮的那一件
};

const $ = (id) => document.getElementById(id);

/** 索引里是 'mio/thumbs/x.jpg' 这种相对路径，页面统一转成绝对路径（不论当前 URL 带不带尾斜杠都不出错）。 */
function assetUrl(relative) {
  const parts = String(relative || '').split('/');
  return parts.length >= 3 ? ASSET_BASE + parts.slice(-3).join('/') : '';
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

// ---------- 数据 ----------
async function boot() {
  try {
    const response = await fetch(API, { cache: 'no-store' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.rows = payload.records || [];
    state.volumes = (payload.meta && payload.meta.volumes) || [];
  } catch (error) {
    $('status').textContent = `没能读到 mio 索引（${error.message}），请刷新重试。`;
    $('total').textContent = '暂时无法读取';
    $('section-title').textContent = '数据读取失败';
    return;
  }
  if (!state.rows.length) {
    $('status').textContent = '索引是空的，检查 library/data/mio-zh.json。';
    return;
  }

  state.rows.forEach((row) => state.byId.set(row.id, row));
  state.volumes.forEach((volume) => state.bySlug.set(volume.slug, volume));
  state.volumes.forEach((volume) => {
    const name = volume.series_zh;
    if (!state.series.has(name)) state.series.set(name, { slug: volume.series, volumes: [] });
    state.series.get(name).volumes.push(volume);
  });
  state.series.forEach((group) => group.volumes.sort((a, b) => a.vol - b.vol));

  const total = state.rows.length;
  $('total').textContent = `${state.volumes.length} 卷 / ${total.toLocaleString()} 件`;

  renderSeriesTabs();
  bindEvents();
  route();
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'ref-gallery-ready', library: 'mio' }, location.origin);
  }
}

// ---------- 二级：系列页签 ----------
function seriesRank(name) {
  const index = SERIES_ORDER.indexOf(name);
  return index < 0 ? 99 : index;
}

function seriesNames() {
  return [...state.series.keys()].sort((a, b) => seriesRank(a) - seriesRank(b));
}

function rowsOf(series) {
  return series ? state.rows.filter((row) => row['分类'] === series) : state.rows;
}

function renderSeriesTabs() {
  const current = activeSeries();
  const items = [{ name: '', label: '全部', count: state.rows.length, hash: '#all' }]
    .concat(seriesNames().map((name) => ({
      name,
      label: name,
      count: rowsOf(name).length,
      hash: `#s-${state.series.get(name).slug}`,
    })));
  $('series').replaceChildren(...items.map((item) => {
    const link = el('a', item.label);
    link.href = item.hash;
    link.append(el('span', item.count.toLocaleString()));
    if ((current || '') === item.name) link.setAttribute('aria-current', 'page');
    return link;
  }));
}

// ---------- 三级：卷 ----------
// 选中系列才列卷：全部状态下 43 卷会铺满六七行，把搜索和网格顶到屏幕外，
// 而「先选系列再选卷」本来就是这个页面的浏览顺序。六库页的分类条同理只在该库内有意义。
function activeSeries() {
  if (state.view.type === 'series') return state.view.series;
  if (state.view.type === 'volume') {
    const volume = state.bySlug.get(state.view.slug);
    return volume ? volume.series_zh : '';
  }
  return '';
}

function renderCategories() {
  const box = $('categories');
  const series = activeSeries();
  if (!series) { box.hidden = true; box.replaceChildren(); return; }
  const volumes = state.series.get(series).volumes;
  const selected = state.view.type === 'volume' ? state.view.slug : '';
  const all = el('button', '全部');
  all.append(el('span', rowsOf(series).length.toLocaleString()));
  all.setAttribute('aria-pressed', String(!selected));
  all.addEventListener('click', () => go({ type: 'series', series }));
  const chips = volumes.map((volume) => {
    const button = el('button', `Vol.${String(volume.vol).padStart(2, '0')} · ${volume.theme_zh || volume.label}`);
    button.append(el('span', String(volume.count)));
    button.setAttribute('aria-pressed', String(volume.slug === selected));
    button.title = volume.note || volume.theme_en || '';
    button.addEventListener('click', () => go({ type: 'volume', slug: volume.slug }));
    return button;
  });
  box.hidden = false;
  box.replaceChildren(all, ...chips);
}

// ---------- 视图 ----------
function hashOf(view) {
  if (view.type === 'series') return `#s-${state.series.get(view.series).slug}`;
  if (view.type === 'volume') return `#${view.slug}`;
  return '#all';
}

function go(view) {
  state.view = view;
  state.shown = PAGE;
  closeViewer();
  const hash = hashOf(view);
  if (location.hash !== hash) history.replaceState(null, '', hash);
  render();
}

function route() {
  const hash = decodeURIComponent(location.hash.replace(/^#/, ''));
  if (hash.startsWith('s-')) {
    const hit = seriesNames().find((name) => state.series.get(name).slug === hash.slice(2));
    state.view = hit ? { type: 'series', series: hit } : { type: 'all' };
  } else if (state.bySlug.has(hash)) {
    state.view = { type: 'volume', slug: hash };
  } else {
    state.view = { type: 'all' };
  }
  state.shown = PAGE;
  render();
}

function matches(row) {
  if (!state.query) return true;
  const haystack = (row['检索'] || '').toLowerCase();
  return state.query.split(/\s+/).filter(Boolean).every((word) => haystack.includes(word));
}

function currentRows() {
  let rows;
  if (state.view.type === 'volume') {
    const volume = state.bySlug.get(state.view.slug);
    rows = state.rows.filter((row) => row['卷slug'] === state.view.slug);
    if (!rows.length && volume) rows = state.rows.filter((row) => row['分类'] === volume.series_zh);
  } else if (state.view.type === 'series') {
    rows = rowsOf(state.view.series);
  } else {
    rows = state.rows;
  }
  return rows.filter(matches);
}

function titleOf() {
  if (state.view.type === 'volume') {
    const volume = state.bySlug.get(state.view.slug);
    return volume ? `Vol.${String(volume.vol).padStart(2, '0')} ${volume.theme_zh || volume.label}` : '卷不存在';
  }
  if (state.view.type === 'series') return state.view.series;
  return '全部作品';
}

function render() {
  const rows = currentRows();
  state.list = rows;
  renderSeriesTabs();
  renderCategories();

  $('section-title').textContent = state.query ? `搜索：${state.query}` : titleOf();
  $('status').textContent = `共 ${rows.length.toLocaleString()} 件 · 已显示 ${Math.min(rows.length, state.shown).toLocaleString()} 件`;
  $('empty').hidden = rows.length > 0;

  // 卷视图固定 3 列：每卷正好 9 件，三行九宫格，跟源站的合集图排布一致。
  const grid = $('grid');
  grid.classList.toggle('thirds', state.view.type === 'volume' && !state.query);
  const slice = rows.slice(0, state.shown);
  const fragment = document.createDocumentFragment();
  slice.forEach((row) => fragment.append(card(row)));
  grid.replaceChildren(fragment);

  const rest = rows.length - slice.length;
  $('more').hidden = rest <= 0;
  if (rest > 0) $('more').textContent = `加载更多（还有 ${rest} 件）`;
  if (window.innerWidth > 960) window.scrollTo({ top: 0, behavior: 'auto' });
}

function card(row) {
  const button = el('button', undefined, 'card');
  button.type = 'button';
  button.setAttribute('aria-label', `查看 ${row.id} ${row['名称'] || ''}`);
  button.setAttribute('aria-current', String(row.id === state.selectedId));
  const image = document.createElement('img');
  image.loading = 'lazy';
  image.decoding = 'async';
  image.src = assetUrl(row['缩略图']);
  image.alt = `${row.id} ${row['名称'] || ''} ${row['卷主题'] || ''}`;
  image.width = 300; image.height = 300;
  const info = el('div', undefined, 'card-info');
  const heading = el('div', undefined, 'card-heading');
  heading.append(el('h3', row.id), el('span', row['卷主题'] || row['分类2'] || '', 'card-cat'));
  info.append(heading, el('p', [row['名称'], ...(row['关键词'] || [])].filter(Boolean).join(' · ')));
  button.append(image, info);
  button.addEventListener('click', () => openViewer(row.id));
  return button;
}

// ---------- 详情 ----------
function openViewer(id) {
  const row = state.byId.get(id);
  if (!row) return;
  state.current = state.list.findIndex((item) => item.id === id);
  $('large').src = assetUrl(row['缩略图']);
  $('large').alt = `${row.id} ${row['名称'] || ''}`;
  $('detail-cat').textContent = [row['分类'], row['卷'], row['卷主题']].filter(Boolean).join(' · ');
  $('detail-title').textContent = row['名称'] || row.id;
  $('position').textContent = `${state.current + 1} / ${state.list.length} · ${row.id}`;
  $('desc').textContent = row['描述'] || '';
  $('prompt-en').value = row['提示词'] || '（作者未提供英文提示词）';
  $('prompt-zh').value = row['提示词中文'] || '（作者未提供中文提示词）';
  $('meta').textContent = [row['卷'], row['日期'], row['来源']].filter(Boolean).join(' · ');
  const source = $('source');
  if (row['来源']) { source.href = row['来源']; source.hidden = false; } else { source.hidden = true; }
  // 只有在 ComfyUI 节点的 iframe 里才给「使用此素材」——独立浏览时这个按钮无处可去。
  $('use-item').hidden = window.parent === window;
  $('prev').disabled = state.current <= 0;
  $('next').disabled = state.current < 0 || state.current >= state.list.length - 1;
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.textContent = '复制';
    delete button.dataset.done;
  });
  const dialog = $('viewer');
  if (!dialog.open) dialog.showModal();
}

function step(delta) {
  if (state.current < 0) return;
  const next = state.current + delta;
  if (next < 0 || next >= state.list.length) return;
  openViewer(state.list[next].id);
}

function closeViewer() {
  const dialog = $('viewer');
  if (dialog.open) dialog.close();
}

async function copy(text, button) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.append(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
  if (!button) return;
  const label = button.textContent;
  button.textContent = '已复制';
  button.dataset.done = 'true';
  setTimeout(() => { button.textContent = label; delete button.dataset.done; }, 1400);
}

// ---------- 事件 ----------
function bindEvents() {
  let timer = 0;
  $('q').addEventListener('input', (event) => {
    const value = event.target.value.trim().toLowerCase();
    clearTimeout(timer);
    timer = setTimeout(() => { state.query = value; state.shown = PAGE; render(); }, 160);
  });
  $('reset').addEventListener('click', () => {
    state.query = '';
    $('q').value = '';
    go({ type: 'all' });
  });
  $('more').addEventListener('click', () => { state.shown += PAGE; render(); });

  $('close').addEventListener('click', closeViewer);
  $('prev').addEventListener('click', () => step(-1));
  $('next').addEventListener('click', () => step(1));
  $('use-item').addEventListener('click', () => {
    const row = state.list[state.current];
    if (row && window.parent !== window) {
      window.parent.postMessage({ type: 'ref-gallery-select', library: 'mio', id: row.id }, location.origin);
    }
  });
  $('copy-id').addEventListener('click', (event) => {
    const row = state.list[state.current];
    if (row) copy(row.id, event.currentTarget);
  });
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', () => {
      const field = button.dataset.copy === 'en' ? 'prompt-en' : 'prompt-zh';
      copy($(field).value, button);
    });
  });
  $('viewer').addEventListener('click', (event) => {
    if (event.target === $('viewer')) closeViewer();  // 点遮罩关闭
  });

  document.addEventListener('keydown', (event) => {
    if ($('viewer').open) {
      if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); }
      if (event.key === 'ArrowRight') { event.preventDefault(); step(1); }
    } else if (event.key === '/' && event.target.tagName !== 'INPUT') {
      event.preventDefault(); $('q').focus();
    }
  });

  window.addEventListener('hashchange', route);

  // 与六库页同一套 iframe 协议：节点打开时把当前 ID 推过来，这里直接翻到那一件。
  window.addEventListener('message', (event) => {
    if (event.origin !== location.origin || event.source !== window.parent) return;
    if (event.data?.type !== 'ref-gallery-current') return;
    const id = event.data.id;
    if (typeof id !== 'string' || !state.byId.has(id)) return;
    const row = state.byId.get(id);
    state.selectedId = id;
    const target = { type: 'volume', slug: row['卷slug'] };
    if (hashOf(target) !== location.hash) history.replaceState(null, '', hashOf(target));
    state.view = target;
    state.shown = PAGE;
    render();
    openViewer(id);
  });
}

boot();
