'use strict';
const $ = (id) => document.getElementById(id);

const LIBS = {
  costume: {
    label: '服装', unit: '套', note: '服装参考档案',
    headline: '为角色，找到合适的衣装。',
    blurb: '从四季日常到特别场合，浏览无人物的服装搭配参考。<br>搜索并选择服装，直接输出到 ComfyUI 图像工作流。',
    placeholder: '试试 蕾丝、牛仔、白色 或 SPR-0001',
    source: 'https://ai-costume-gallery.pages.dev/',
  },
  pose: {
    label: '姿势', unit: '个', note: '姿势参考档案',
    headline: '让角色，摆出准确的姿势。',
    blurb: '288 个无脸灰色人偶线稿，每个动作五个机位。<br>选好姿势与角度，直接接进姿态或线稿控制流程。',
    placeholder: '试试 站立、坐姿、双人 或 POS-SEXY-P001',
    source: 'https://ai-pose-gallery.pages.dev/',
  },
  face: {
    label: '脸部', unit: '张', note: '脸部参考档案',
    headline: '先把脸定下来。',
    blurb: '正面、纯色背景的头部参考，覆盖短发到长发四种发型。<br>选好脸再套服装，人设不容易跑。',
    placeholder: '试试 短发、长发、造型 或 FACE-0001',
    source: 'https://ai-portrait-gallery.pages.dev/',
  },
  depth: {
    label: '深度姿势', unit: '个', note: '深度姿势档案',
    headline: '把姿势，变成深度控制。',
    blurb: '同一批 288 个姿势的灰度深度图，每个动作五个机位。<br>直接接 ControlNet depth，姿态还原更稳。',
    placeholder: '试试 站立、坐姿、双人 或 DEP-SEXY-P001',
    source: 'https://ai-pose-depth-gallery.pages.dev/',
  },
};

const requested = new URLSearchParams(location.search).get('lib');
const lib = Object.hasOwn(LIBS, requested) ? requested : 'costume';
const config = LIBS[lib];
const angleOrder = ['正面', '俯视', '仰视', '侧面', '斜45°'];

let records = [], filtered = [], category = '', subcategory = '', angle = '';
let shown = 0, current = 0, selectedId = '';
// 每次翻页自增：异步加载的原图回来时用它判断用户是否已经翻走，避免旧图盖新图。
let detailToken = 0;
let originTemplate = '', originSite = '', offlineOnly = false;
const PAGE = 60;

const isMap = (value) => value !== null && typeof value === 'object';

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function thumbOf(row) {
  if (row.封面) return row.封面;
  return isMap(row.缩略图) ? Object.values(row.缩略图)[0] : row.缩略图;
}

function angleKeys(row) {
  if (Array.isArray(row.视角)) return row.视角;
  if (isMap(row.原图)) return Object.keys(row.原图);
  return [];
}

function assetOf(row, field, pick) {
  const value = row[field];
  if (!isMap(value)) return value;
  return value[pick] || Object.values(value)[0];
}

// 索引里存的是相对路径（如 pose/thumbs/x.webp），页面统一改成可访问的 /ref_lookbook/assets/... URL
function asUrl(value) {
  if (isMap(value)) return Object.fromEntries(Object.entries(value).map(([key, path]) => [key, asUrl(path)]));
  if (typeof value !== 'string' || !value) return value;
  const parts = value.split('/');
  return `assets/${lib}/${parts.at(-2)}/${parts.at(-1)}`;
}

function withUrls(row) {
  return {
    ...row,
    缩略图: asUrl(row.缩略图),
    预览图: asUrl(row.预览图),
    原图: asUrl(row.原图),
    原图源: remoteOf(row.原图),
    封面: asUrl(row.封面),
  };
}

// 原图不进仓库：按文件名拼上游地址，本地缺图时直接向作者站点取，个人保存不额外授权也不再分发。
function remoteOf(value) {
  if (isMap(value)) return Object.fromEntries(Object.entries(value).map(([key, path]) => [key, remoteOf(path)]));
  if (typeof value !== 'string' || !value || !originTemplate) return '';
  const stem = value.split('/').at(-1).replace(/\.[^.]+$/, '');
  return originTemplate.replace('{stem}', encodeURIComponent(stem));
}

function tagText(row) {
  return (row.关键词 || []).join(' · ');
}

function chipsOf(field) {
  const counts = new Map([['', records.length]]);
  records.forEach((row) => { if (row[field]) counts.set(row[field], (counts.get(row[field]) || 0) + 1); });
  return counts;
}

function renderChips(container, field, active, onPick, label) {
  const counts = chipsOf(field);
  if (counts.size <= 2) { container.replaceChildren(); container.hidden = true; return; }
  container.hidden = false;
  container.replaceChildren(...[...counts].map(([name, count]) => {
    const button = element('button', name || label);
    button.append(element('span', count.toLocaleString()));
    button.setAttribute('aria-pressed', String(active === name));
    button.addEventListener('click', () => onPick(name));
    return button;
  }));
}

function renderCategories() {
  renderChips($('categories'), '分类', category, (name) => { category = name; subcategory = ''; applyFilters(); }, '全部');
  renderChips($('subcategories'), '分类2', subcategory, (name) => { subcategory = name; applyFilters(); }, '全部');
}

function applyFilters() {
  const words = $('q').value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  filtered = records.filter((row) => (!category || row.分类 === category)
    && (!subcategory || row.分类2 === subcategory)
    && words.every((word) => (row.检索 || '').includes(word)));
  shown = 0;
  $('grid').replaceChildren();
  renderCategories();
  const title = [category, subcategory].filter(Boolean).join(' · ') || `全部${config.label}`;
  $('section-title').textContent = title;
  $('empty').hidden = filtered.length > 0;
  appendPage();
}

function appendPage() {
  const start = shown;
  const cards = filtered.slice(start, start + PAGE).map((row, index) => {
    const button = element('button', undefined, 'card');
    button.setAttribute('aria-label', `查看 ${row.id} ${row.分类}`);
    button.setAttribute('aria-current', String(row.id === selectedId));
    const img = element('img');
    img.src = thumbOf(row);
    img.alt = [row.id, row.分类, row.分类2, tagText(row)].filter(Boolean).join(' ');
    img.loading = 'lazy'; img.decoding = 'async'; img.width = 300; img.height = 450;
    img.addEventListener('error', () => { img.alt = `${row.id} 缩略图缺失：内置图库不完整，请重新安装节点`; });
    const info = element('div', undefined, 'card-info');
    const heading = element('div', undefined, 'card-heading');
    heading.append(element('h3', row.id), element('span', row.分类2 || row.分类, 'card-cat'));
    info.append(heading, element('p', tagText(row)));
    button.append(img, info);
    button.addEventListener('click', () => { current = start + index; showDetail(); $('viewer').showModal(); });
    return button;
  });
  $('grid').append(...cards); shown += cards.length;
  $('status').textContent = `共 ${filtered.length.toLocaleString()} ${config.unit} · 已显示 ${shown.toLocaleString()} ${config.unit}`;
  $('more').hidden = shown >= filtered.length;
  $('more').textContent = `加载更多（剩余 ${filtered.length - shown} ${config.unit}）`;
}

function currentAsset(field) {
  return assetOf(filtered[current], field, angle);
}

function renderAngles(row) {
  const keys = angleKeys(row);
  const box = $('angles');
  if (keys.length <= 1) { box.hidden = true; box.replaceChildren(); return; }
  box.hidden = false;
  if (!keys.includes(angle)) angle = keys[0];
  box.replaceChildren(...keys.map((key) => {
    const button = element('button', key);
    button.setAttribute('aria-pressed', String(angle === key));
    button.addEventListener('click', () => { angle = key; showDetail(); });
    return button;
  }));
}

function showDetail() {
  const row = filtered[current];
  angle = angleKeys(row).includes(angle) ? angle : (angleKeys(row)[0] || '');
  $('detail-title').textContent = row.id;
  $('detail-cat').textContent = [row.分类, row.分类2].filter(Boolean).join(' · ');
  $('position').textContent = `${current + 1} / ${filtered.length}`;
  $('tags').textContent = tagText(row);
  $('english').textContent = row.日文 || row.英文关键词 || '—';
  renderAngles(row);

  // 大图：缩略图先占位，本机原图后台加载完再替换。
  // 本机缺原图时后端会取一次并落盘到 library/<库>/png/，首次可能要几秒到几十秒，
  // 所以不能用 <img>.src 直接指过去干等——弹窗会长时间空白。
  const localOriginal = currentAsset('原图');
  const remoteOriginal = currentAsset('原图源');
  const thumb = currentAsset('缩略图');
  const token = ++detailToken;

  const setStatus = (text, state) => {
    if (token !== detailToken) return;
    $('image-status').textContent = text;
    $('image-status').dataset.state = state;
  };
  const showImage = (src) => {
    if (token === detailToken) $('large').src = src;
  };

  if (thumb) showImage(thumb);
  $('large').alt = `${row.id} ${tagText(row)}`;
  setStatus(localOriginal ? '正在载入原图…' : '正在载入原图，首次使用会从作者源站取一次并存入本机…', 'loading');

  const load = (src) => new Promise((resolve, reject) => {
    const probe = new Image();
    probe.onload = () => resolve(src);
    probe.onerror = reject;
    probe.src = src;
  });

  // 一级：本机原图（后端按需获取并缓存）。二级：后端取不到时浏览器直连源站，仅兜底不缓存。
  load(localOriginal)
    .then((src) => { showImage(src); setStatus('原图，已缓存到本机', 'ok'); })
    .catch(() => {
      if (!remoteOriginal) { setStatus('本机无原图且源站不可达，当前仅显示缩略图', 'info'); return; }
      setStatus('本机没有原图，正在向作者源站直接请求…', 'loading');
      return load(remoteOriginal)
        .then((src) => { showImage(src); setStatus('后端取图失败，改由浏览器直连作者源站（本张未缓存到本机）', 'info'); })
        .catch(() => setStatus('原图与缩略图均不可用，请检查素材目录或网络。', 'error'));
    });

  // 下载与"在新标签打开"都优先本机缓存：命中就不必再打源站。
  const originalHref = localOriginal || remoteOriginal;
  $('download').href = originalHref;
  $('download').download = `${row.id}${angle ? '-' + angle : ''}.png`;
  $('open-original').href = originalHref;
  $('prev').disabled = current === 0; $('next').disabled = current === filtered.length - 1;
  $('copy').textContent = '复制 ID';
  $('use-item').disabled = window.parent === window;
  $('use-item').textContent = window.parent === window ? `请从 ComfyUI 节点打开以使用${config.label}` : `使用此${config.label} → ComfyUI`;
}

$('q').addEventListener('input', applyFilters);
$('reset').addEventListener('click', () => { category = ''; subcategory = ''; $('q').value = ''; applyFilters(); });
$('more').addEventListener('click', appendPage);
$('close').addEventListener('click', () => $('viewer').close());
$('help').addEventListener('click', () => $('guide').showModal());
$('prev').addEventListener('click', () => { if (current > 0) { current--; showDetail(); } });
$('next').addEventListener('click', () => { if (current < filtered.length - 1) { current++; showDetail(); } });
$('copy').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(filtered[current].id); $('copy').textContent = '已复制'; }
  catch { $('copy').textContent = '复制失败，请手动复制上方 ID'; }
});
$('download').addEventListener('click', async (event) => {
  const link = event.currentTarget;
  if (new URL(link.href).origin === location.origin) return;
  event.preventDefault();
  if (link.getAttribute('aria-disabled') === 'true') return;
  const href = link.href, filename = link.download;
  link.setAttribute('aria-disabled', 'true');
  link.textContent = '正在下载…';
  let label = '下载 PNG 原图';
  try {
    const response = await fetch(href);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const url = URL.createObjectURL(await response.blob());
    const save = element('a');
    save.href = url; save.download = filename; save.hidden = true;
    document.body.append(save); save.click(); save.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch {
    label = '下载失败，请点“打开原图”';
  } finally {
    link.removeAttribute('aria-disabled');
    link.textContent = label;
  }
});
document.addEventListener('keydown', (e) => {
  if ($('viewer').open) {
    if (e.key === 'ArrowLeft') { e.preventDefault(); $('prev').click(); }
    if (e.key === 'ArrowRight') { e.preventDefault(); $('next').click(); }
  } else if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName) && !$('guide').open) {
    e.preventDefault(); $('q').focus();
  }
});
for (const dialog of [$('viewer'), $('guide')]) dialog.addEventListener('click', (e) => {
  const box = dialog.getBoundingClientRect();
  if (e.target === dialog && (e.clientX < box.left || e.clientX > box.right || e.clientY < box.top || e.clientY > box.bottom)) dialog.close();
});

// ?lib=pose&id=POS-SEXY-P001 直接打开某个素材，方便分享与排查
function openDeepLink() {
  const wanted = new URLSearchParams(location.search).get('id');
  if (!wanted) return;
  const index = filtered.findIndex((row) => row.id === wanted);
  if (index < 0) return;
  current = index;
  showDetail();
  $('viewer').showModal();
}

function applyLibraryChrome() {
  document.body.dataset.lib = lib;
  document.title = `${config.label} · AI 参考图库｜服装 · 姿势 · 脸部 · 深度姿势`;
  $('headline').innerHTML = config.headline;
  $('blurb').innerHTML = config.blurb;
  $('note-label').textContent = config.note;
  $('q').placeholder = config.placeholder;
  $('source-link').href = config.source;
  for (const tab of $('tabs').querySelectorAll('a')) {
    if (tab.dataset.lib === lib) tab.setAttribute('aria-current', 'page');
    else tab.removeAttribute('aria-current');
  }
}

async function init() {
  applyLibraryChrome();
  try {
    const response = await fetch(`catalog/${lib}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    if (payload?.error) throw new Error(payload.error);
    const rows = Array.isArray(payload) ? payload : payload.records;
    if (!Array.isArray(rows) || !rows.length) throw new Error('数据为空');
    originTemplate = payload?.origin?.template || '';
    originSite = payload?.origin?.site || config.source;
    offlineOnly = Boolean(payload?.origin?.offline);
    if (offlineOnly) $('offline-note').hidden = false;
    records = rows.map(withUrls);
    const categories = new Set(records.map((row) => row.分类).filter(Boolean)).size;
    $('total').textContent = `${records.length.toLocaleString()} ${config.unit} / ${categories} 个分类`;
    applyFilters();
    openDeepLink();
    if (window.parent !== window) window.parent.postMessage({ type: 'ref-gallery-ready', library: lib }, location.origin);
  } catch (error) {
    $('status').textContent = '数据加载失败，请刷新重试。请检查节点 library/data 和完整素材目录。';
    $('total').textContent = '暂时无法读取';
    console.error('参考图库数据加载失败', error);
  }
}
init();

/* ---------- 整库原图下载 ----------
   入口只在右上角，使用指南里故意不写，留给用户自己发现。
   任务跑在 ComfyUI 进程里的后台线程，网页关掉也会继续；只有关掉 ComfyUI 才中断，
   下好的图都留在 library/<库>/png/，再点一次会跳过已存在的接着补。 */
const fetchState = { timer: 0, settled: false };

const fmtSize = (bytes) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 MB';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes, index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${index < 2 || value >= 100 ? Math.round(value) : value.toFixed(1)} ${units[index]}`;
};

const fmtSpan = (seconds) => {
  if (!Number.isFinite(seconds) || seconds <= 0) return '—';
  const total = Math.round(seconds);
  if (total < 60) return `${total} 秒`;
  if (total < 3600) return `${Math.round(total / 60)} 分钟`;
  return `${Math.floor(total / 3600)} 小时 ${Math.round((total % 3600) / 60)} 分`;
};

async function fetchStatusJson() {
  try {
    const response = await fetch('fetch-all/status');
    return response.ok ? await response.json() : null;
  } catch { return null; }
}

function renderPlan(plan) {
  const enough = plan.free_bytes == null || plan.free_bytes > plan.estimated_bytes * 1.1;
  $('fetch-plan').innerHTML = plan.missing
    ? `本机还缺 <strong>${plan.missing.toLocaleString()}</strong> 张原图，预计占用 <strong>${fmtSize(plan.estimated_bytes)}</strong>。`
      + `<br>保存到 <code>${plan.root}</code> 下各库的 <code>png/</code>；磁盘当前可用 `
      + `<strong>${plan.free_bytes == null ? '未知' : fmtSize(plan.free_bytes)}</strong>。`
    : '四个图库的原图本机都已经有了，不需要再下载。';

  $('fetch-libs').replaceChildren(...Object.entries(plan.libraries).map(([key, info]) => {
    const li = element('li');
    const box = document.createElement('input');
    box.type = 'checkbox'; box.value = key; box.id = `fetch-lib-${key}`;
    box.checked = info.missing > 0; box.disabled = info.missing === 0;
    const label = element('label');
    label.htmlFor = box.id;
    label.append(box, element('strong', info.label),
      element('span', info.missing
        ? `缺 ${info.missing.toLocaleString()} 张 · 约 ${fmtSize(info.estimated_bytes)}`
        : `已齐全 ${info.have.toLocaleString()} 张`, 'fetch-count'));
    li.append(label);
    return li;
  }));

  const note = [];
  if (plan.missing) {
    note.push('下载期间请保持 ComfyUI 运行、不要关闭本窗口；中途停下或退出程序都不会弄坏已下好的图，再点一次会接着补。');
    note.push(`按 ${plan.workers} 路并行抓取，进度条会显示实时剩余时间。`);
    if (!enough) note.push('磁盘剩余空间可能不够，建议先清理再开始。');
  } else {
    note.push('提示：下载过的图会被节点和弹窗直接复用，之后完全离线。');
  }
  $('fetch-warn').textContent = note.join('');
  $('fetch-start').disabled = !plan.missing || plan.offline || !enough;
  $('fetch-start').textContent = plan.missing ? '开始下载' : '无需下载';
}

function renderProgress(job) {
  if (!job || !job.total) { $('fetch-progress').hidden = true; return; }
  const running = Boolean(job.running);
  const percent = Math.min(100, Math.round(((job.done + job.failed) / job.total) * 100));
  const bar = $('fetch-bar');
  bar.style.width = `${percent}%`;
  bar.dataset.state = running ? 'running' : (job.cancelled ? 'stopped' : 'done');
  $('fetch-progress').hidden = false;

  const head = running
    ? `已下载 ${job.done.toLocaleString()} / ${job.total.toLocaleString()} 张`
    : job.cancelled ? `已停止，本次下载 ${job.done.toLocaleString()} 张`
      : `已完成，共下载 ${job.done.toLocaleString()} 张`;
  const parts = [head, `占 ${fmtSize(job.bytes)}`, `用时 ${fmtSpan(job.elapsed)}`];
  if (running && job.eta) parts.push(`约剩 ${fmtSpan(job.eta)}`);
  if (job.failed) parts.push(`失败 ${job.failed} 张，可再点一次重试`);
  $('fetch-status').textContent = parts.join(' · ');
  $('fetch-errors').textContent = (job.errors || []).slice(0, 3)
    .map((entry) => `${String(entry.file).split('/').pop()}：${entry.error}`).join('　');
  $('fetch-start').hidden = running;
  $('fetch-stop').hidden = !running;
}

function syncFetchButton(job) {
  const button = $('fetch-all');
  if (job?.running && job.total) {
    const percent = Math.min(100, Math.round(((job.done + job.failed) / job.total) * 100));
    button.textContent = `下载中 ${percent}%`;
    button.setAttribute('aria-busy', 'true');
  } else {
    button.textContent = '下载全部原图';
    button.removeAttribute('aria-busy');
  }
}

async function loadPlan() {
  $('fetch-plan').textContent = '正在统计本机缺少的原图…';
  $('fetch-libs').replaceChildren();
  $('fetch-start').disabled = true;
  $('fetch-start').textContent = '开始下载';
  try {
    const response = await fetch('fetch-all');
    const plan = await response.json();
    if (plan?.error) throw new Error(plan.error);
    renderPlan(plan);
  } catch (error) {
    $('fetch-plan').textContent = '统计失败，请稍后刷新页面重试。';
    $('fetch-warn').textContent = String(error?.message || error);
  }
}

async function pollFetch() {
  clearTimeout(fetchState.timer);
  const job = await fetchStatusJson();
  if (job) {
    if ($('fetch-dialog').open) renderProgress(job);
    syncFetchButton(job);
    if (!job.running && job.total && !fetchState.settled) {
      fetchState.settled = true;
      if ($('fetch-dialog').open) await loadPlan();
      return;
    }
  }
  if (job?.running) fetchState.timer = setTimeout(pollFetch, 1200);
}

$('fetch-all').addEventListener('click', async () => {
  if (!$('fetch-dialog').open) $('fetch-dialog').showModal();
  const job = await fetchStatusJson();
  if (job?.running) {
    $('fetch-plan').textContent = '正在下载原图，进度如下。';
    $('fetch-warn').textContent = '下载期间请保持 ComfyUI 运行；关闭这个窗口不影响下载，退出程序才会停。'
      + '已下好的都留着，下次再点接着补。';
    renderProgress(job); syncFetchButton(job); pollFetch(); return;
  }
  await loadPlan();
  pollFetch();
});

$('fetch-start').addEventListener('click', async () => {
  const libraries = [...$('fetch-libs').querySelectorAll('input[type=checkbox]')]
    .filter((box) => box.checked && !box.disabled).map((box) => box.value);
  if (!libraries.length) { $('fetch-warn').textContent = '至少选择要下载的图库。'; return; }
  const button = $('fetch-start');
  button.disabled = true;
  button.textContent = '正在启动…';
  fetchState.settled = false;
  try {
    const response = await fetch('fetch-all/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ libraries }),
    });
    const payload = await response.json();
    if (!response.ok || payload?.error) throw new Error(payload?.error || `HTTP ${response.status}`);
    renderProgress(payload.job);
    syncFetchButton(payload.job);
    pollFetch();
  } catch (error) {
    $('fetch-warn').textContent = `启动失败：${error?.message || error}`;
    button.disabled = false;
    button.textContent = '开始下载';
  }
});

$('fetch-stop').addEventListener('click', async () => {
  $('fetch-stop').disabled = true;
  $('fetch-stop').textContent = '正在停止…';
  try { await fetch('fetch-all/stop', { method: 'POST' }); } catch { /* 停不下来也没关系，下一轮再看 */ }
  $('fetch-stop').disabled = false;
  $('fetch-stop').textContent = '停止';
  pollFetch();
});

// 页面一打开先看一眼有没有正在跑的任务，有就让右上角按钮直接显示进度
fetchStatusJson().then((job) => { if (job?.running) { syncFetchButton(job); pollFetch(); } });

$('use-item').addEventListener('click', () => {
  const row = filtered[current];
  if (window.parent !== window && row) window.parent.postMessage({ type: 'ref-gallery-select', library: lib, id: row.id, angle }, location.origin);
});
window.addEventListener('message', (event) => {
  if (event.origin !== location.origin || event.source !== window.parent || event.data?.type !== 'ref-gallery-current') return;
  if (event.data.library && event.data.library !== lib) return;
  const id = event.data.id;
  if (typeof id !== 'string' || !records.some((row) => row.id === id)) return;
  selectedId = id;
  if (typeof event.data.angle === 'string' && event.data.angle) angle = event.data.angle;
  applyFilters();
});
