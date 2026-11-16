// 霧島澪 · 设计档案 —— 独立页面脚本。
// 与六库页（gallery.mjs）完全解耦：数据只读 /ref_lookbook/catalog/mio，
// 布局是「系列 → 卷 → 9 件」，重点是每件自带的中英提示词，所以详情面板以提示词为主体。
const API = '/ref_lookbook/catalog/mio';
const ASSET_BASE = '/ref_lookbook/assets/';
const PAGE = 60;
const SERIES_ORDER = ['发型', '服装', '姿势'];

const state = {
  rows: [],
  volumes: [],
  bySlug: new Map(),
  byId: new Map(),
  series: new Map(),
  view: { type: 'volume', slug: null },
  query: '',
  list: [],     // 当前视图下的有序记录，供弹窗上一个/下一个
  shown: PAGE,
  current: -1,
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
    $('head-title').textContent = '数据读取失败';
    $('head-lede').textContent = `没能读到 mio 索引（${error.message}）。确认 library/data/mio-zh.json 在，然后刷新。`;
    return;
  }
  if (!state.rows.length) {
    $('head-title').textContent = '索引是空的';
    return;
  }

  state.rows.forEach((row) => state.byId.set(row.id, row));
  state.volumes.forEach((volume) => state.bySlug.set(volume.slug, volume));
  state.volumes.forEach((volume) => {
    if (!state.series.has(volume.series_zh)) state.series.set(volume.series_zh, []);
    state.series.get(volume.series_zh).push(volume);
  });
  state.series.forEach((list) => list.sort((a, b) => a.vol - b.vol));

  const total = state.rows.length;
  $('stat').textContent = `${state.volumes.length} 卷 · ${total} 件`;
  $('all-count').textContent = total.toLocaleString();

  renderRail();
  bindEvents();
  route();
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'ref-gallery-ready', library: 'mio' }, location.origin);
  }
}

// ---------- 左栏 ----------
// 菜单三层里这里是澪图库的下级：一级「澪图库」（顶部）→ 二级「系列」可折叠 → 三级「卷」可点。
// 系列默认展开，点标题收起；从外部跳到某个卷时，如果它所在的系列是收起的，自动展开。
function renderRail() {
  const host = $('volumes');
  host.replaceChildren();
  const rank = (name) => {
    const index = SERIES_ORDER.indexOf(name);
    return index < 0 ? 99 : index;
  };
  const names = [...state.series.keys()].sort((a, b) => rank(a) - rank(b));
  names.forEach((name) => {
    const list = state.series.get(name);
    const head = el('button', undefined, 'series-head');
    head.type = 'button';
    head.setAttribute('aria-expanded', 'true');
    head.append(
      el('span', name, 'series-name'),
      el('span', `${list.length} 卷`, 'series-n'),
      el('span', undefined, 'series-caret'),
    );
    const body = el('div', undefined, 'series-body');
    head.addEventListener('click', () => {
      const open = head.getAttribute('aria-expanded') === 'true';
      head.setAttribute('aria-expanded', String(!open));
      body.hidden = open;
    });
    list.forEach((volume) => body.append(volumeButton(volume)));
    const group = el('section', undefined, 'series');
    group.append(head, body);
    host.append(group);
  });
}

function volumeButton(volume) {
  const button = el('button', undefined, 'vol-button');
  button.type = 'button';
  button.dataset.slug = volume.slug;
  button.append(
    el('span', `Vol.${String(volume.vol).padStart(2, '0')}`, 'vol-no'),
    el('span', volume.theme_zh || volume.label, 'vol-name'),
    el('span', String(volume.count), 'vol-n'),
  );
  button.addEventListener('click', () => go({ type: 'volume', slug: volume.slug }));
  return button;
}

function markRail() {
  document.querySelectorAll('#volumes .series-body button').forEach((button) => {
    const hit = state.view.type === 'volume' && button.dataset.slug === state.view.slug;
    button.setAttribute('aria-current', String(hit));
    const body = button.parentElement;
    if (hit && body.hidden) {
      body.hidden = false;
      body.previousElementSibling?.setAttribute('aria-expanded', 'true');
    }
  });
  $('all').setAttribute('aria-current', String(state.view.type === 'all'));
}

// ---------- 视图 ----------
function go(view) {
  state.view = view;
  state.shown = PAGE;
  closeViewer();
  const hash = view.type === 'all' ? '#all' : `#${view.slug}`;
  if (location.hash !== hash) history.replaceState(null, '', hash);
  render();
}

function route() {
  const hash = decodeURIComponent(location.hash.replace(/^#/, ''));
  if (hash === 'all') {
    state.view = { type: 'all' };
  } else if (state.bySlug.has(hash)) {
    state.view = { type: 'volume', slug: hash };
  } else {
    const first = state.volumes[0];
    state.view = { type: 'volume', slug: first ? first.slug : null };
  }
  state.shown = PAGE;
  render();
}

function matches(row) {
  if (!state.query) return true;
  const haystack = (row['检索'] || '').toLowerCase();
  return state.query.split(/\s+/).filter(Boolean).every((word) => haystack.includes(word));
}

function render() {
  const grid = $('grid');
  const head = $('head');
  let rows = [];

  if (state.view.type === 'all') {
    rows = state.rows.filter(matches);
    head.querySelector('#head-eyebrow').textContent = '全部作品';
    $('head-title').textContent = state.query ? `搜索：${state.query}` : '43 卷，387 件';
    $('head-lede').textContent = state.query
      ? `在全部 ${state.rows.length} 件里筛出 ${rows.length} 件。空格分隔多个词时需同时包含。`
      : '按系列与卷浏览作者的完整设计档案。点任意作品看作者写好的中英文提示词。';
    $('head-meta').textContent = `${rows.length.toLocaleString()} 件`;
    $('empty').hidden = rows.length > 0;
  } else if (state.view.type === 'volume') {
    const volume = state.bySlug.get(state.view.slug);
    rows = state.rows.filter((row) => row['卷slug'] === state.view.slug);
    if (state.query) rows = rows.filter(matches);
    if (volume) {
      $('head-eyebrow').textContent = `${volume.series_zh} · ${volume.label}`;
      $('head-title').textContent = volume.theme_zh || volume.title;
      $('head-lede').textContent = volume.note || volume.theme_en || '';
      const bits = [`${volume.count} 件`, volume.date, volume.theme_en].filter(Boolean);
      $('head-meta').textContent = bits.join(' · ');
    }
    $('empty').hidden = rows.length > 0;
  }

  state.list = rows;
  grid.replaceChildren();
  grid.classList.toggle('thirds', state.view.type === 'volume');
  const slice = state.view.type === 'all' ? rows.slice(0, state.shown) : rows;
  const fragment = document.createDocumentFragment();
  slice.forEach((row) => fragment.append(card(row)));
  grid.append(fragment);

  const rest = state.view.type === 'all' ? rows.length - slice.length : 0;
  $('more').hidden = rest <= 0;
  if (rest > 0) $('more').textContent = `加载更多（还有 ${rest} 件）`;
  markRail();
  if (window.innerWidth > 960) window.scrollTo({ top: 0, behavior: 'auto' });
}

function card(row) {
  const button = el('button', undefined, 'card');
  button.type = 'button';
  button.dataset.id = row.id;
  const image = document.createElement('img');
  image.loading = 'lazy';
  image.decoding = 'async';
  image.src = assetUrl(row['缩略图']);
  image.alt = `${row['名称'] || row.id} · ${row['分类2'] || ''}`;
  const body = el('div', undefined, 'card-body');
  body.append(el('h3', row['名称'] || row.id), el('p', row.id));
  button.append(image, body);
  button.addEventListener('click', () => openViewer(row.id));
  return button;
}

// ---------- 详情 ----------
function openViewer(id) {
  const row = state.byId.get(id);
  if (!row) return;
  state.current = state.list.findIndex((item) => item.id === id);
  $('v-img').src = assetUrl(row['缩略图']);
  $('v-img').alt = `${row['名称'] || row.id} · ${row['分类2'] || ''}`;
  $('v-caption').textContent = `${row['卷'] || ''} · ${row['分类2'] || ''}`;
  $('v-eyebrow').textContent = `${row.id} · ${row['分类'] || ''}`;
  $('v-title').textContent = row['名称'] || row.id;
  $('v-desc').textContent = row['描述'] || '';
  $('v-prompt').value = row['提示词'] || '（作者未提供英文提示词）';
  $('v-prompt-zh').value = row['提示词中文'] || '（作者未提供中文提示词）';
  $('v-meta').textContent = [row['卷'], row['卷主题'], row['日期']].filter(Boolean).join(' · ');
  const source = $('v-source');
  if (row['来源']) {
    source.href = row['来源'];
    source.hidden = false;
  } else {
    source.hidden = true;
  }
  // 只有在 ComfyUI 节点的 iframe 里才给「使用此素材」——独立浏览时这个按钮无处可去。
  $('v-use').hidden = window.parent === window;
  const total = state.list.length;
  $('v-prev').disabled = state.current <= 0;
  $('v-next').disabled = state.current < 0 || state.current >= total - 1;
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
  setTimeout(() => {
    button.textContent = label;
    delete button.dataset.done;
  }, 1400);
}

// ---------- 事件 ----------
function bindEvents() {
  let timer = 0;
  $('q').addEventListener('input', (event) => {
    const value = event.target.value.trim().toLowerCase();
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.query = value;
      // 有搜索词就跨全库搜，否则回到当前卷 —— 不然用户在一卷里搜不到会以为没这素材。
      if (value && state.view.type !== 'all') {
        state.view = { type: 'all' };
        state.shown = PAGE;
        history.replaceState(null, '', '#all');
      } else if (!value && state.view.type === 'all' && state.volumes[0]) {
        // 清空搜索且原本在全部视图时留在原地，不强行跳卷。
      }
      state.shown = PAGE;
      render();
    }, 160);
  });

  $('all').addEventListener('click', () => go({ type: 'all' }));
  $('more').addEventListener('click', () => {
    state.shown += PAGE;
    render();
  });

  $('v-close').addEventListener('click', closeViewer);
  $('v-prev').addEventListener('click', () => step(-1));
  $('v-next').addEventListener('click', () => step(1));
  $('v-use').addEventListener('click', () => {
    const row = state.list[state.current];
    if (row && window.parent !== window) {
      window.parent.postMessage({ type: 'ref-gallery-select', library: 'mio', id: row.id }, location.origin);
    }
  });
  // 与六库页同一套 iframe 协议：节点打开时把当前 ID 推过来，这里直接翻到那一件。
  window.addEventListener('message', (event) => {
    if (event.origin !== location.origin || event.source !== window.parent) return;
    if (event.data?.type !== 'ref-gallery-current') return;
    const id = event.data.id;
    if (typeof id !== 'string' || !state.byId.has(id)) return;
    const row = state.byId.get(id);
    if (state.view.type !== 'volume' || state.view.slug !== row['卷slug']) {
      state.view = { type: 'volume', slug: row['卷slug'] };
      state.shown = PAGE;
      render();
    }
    openViewer(id);
  });
  $('v-copy-id').addEventListener('click', (event) => {
    const row = state.list[state.current];
    if (row) copy(row.id, event.currentTarget);
  });
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', () => {
      const field = button.dataset.copy === 'en' ? 'v-prompt' : 'v-prompt-zh';
      copy($(field).value, button);
    });
  });

  $('viewer').addEventListener('click', (event) => {
    if (event.target === $('viewer')) closeViewer();  // 点遮罩关闭
  });

  window.addEventListener('keydown', (event) => {
    if (!$('viewer').open) return;
    if (event.key === 'ArrowLeft') { event.preventDefault(); step(-1); }
    if (event.key === 'ArrowRight') { event.preventDefault(); step(1); }
  });

  window.addEventListener('hashchange', route);
  window.addEventListener('resize', () => {
    $('more').hidden = state.view.type !== 'all' || state.list.length <= state.shown;
  });
}

boot();
