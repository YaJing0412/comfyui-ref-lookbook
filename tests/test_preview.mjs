import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// 预览改成了画在节点画布上（不再用 DOM 控件），所以用假 canvas 记录绘制内容。
const code = readFileSync(new URL('../web/ref_gallery.js', import.meta.url), 'utf8')
  .replace(/^import .*;\s*$/gm, '');

const ORIGIN = 'http://127.0.0.1:8188';

class FakeImage {
  constructor() {
    this._src = '';
    this.complete = false;
    this.naturalWidth = 0;
    this.naturalHeight = 0;
  }
  get src() { return this._src; }
  set src(value) { this._src = value; this.complete = false; this.naturalWidth = 0; this.naturalHeight = 0; }
  load(width = 400, height = 600) {
    this.complete = true;
    this.naturalWidth = width;
    this.naturalHeight = height;
    this.onload?.();
  }
  fail() { this.onerror?.(); }
}

class FakeContext {
  constructor() { this.texts = []; this.images = []; }
  save() {} restore() {} beginPath() {} fill() {} stroke() {} rect() {} roundRect() {}
  fillText(text) { this.texts.push(String(text)); }
  drawImage(image, x, y, w, h) { this.images.push({ image, x, y, w, h }); }
}

function harness() {
  const images = [];
  const dialogs = [];
  const extensions = [];
  const registered = new Map();
  // 弹窗靠 window 的 message 事件收结果，测试里要手动派一条才能验证「选中到底收没收下」。
  const listeners = {};

  class Element {
    constructor(tag) {
      this.tag = tag;
      this.style = {};
      this.children = [];
      this.attributes = {};
      this.contentWindow = { id: tag };
    }
    append(...children) { this.children.push(...children); }
    remove() {}
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener() {}
    showModal() { this.open = true; }
    querySelector() { return null; }
  }

  class Node {
    constructor() { this.widgets = []; this.size = [360, 500]; this.flags = {}; }
    addWidget(type, name, value, callback) { this.widgets.push({ type, name, value, callback }); }
    addDOMWidget() { throw new Error('预览不应再使用 DOM 控件'); }
    setSize(size) { this.size = size; }
    setDirtyCanvas() {}
  }

  // 开关节点是纯前端的 LiteGraph 节点，这里给一个最小基类，足够验证状态与绘制。
  class FakeLGraphNode {
    constructor(title) {
      this.title = title;
      this.properties = {};
      this.size = [140, 80];
      this.pos = [0, 0];
      this.mode = 0;
      this.graph = null;
    }
    setDirtyCanvas() {}
  }

  const context = {
    app: {
      registerExtension(value) { extensions.push(value); },
      graph: { change() {}, setDirtyCanvas() {} },
    },
    LiteGraph: {
      LGraphNode: FakeLGraphNode,
      registerNodeType(type, ctor) { registered.set(type, ctor); },
    },
    api: {
      apiURL: (path) => '/api' + path,
      fetchApi: async () => ({ ok: true, json: async () => ({ name: 'ref_SPR-0002.png' }) }),
    },
    document: {
      createElement(tag) {
        const element = new Element(tag);
        if (tag === 'img') { images.push(element); return element; }
        if (tag === 'dialog') { dialogs.push(element); return element; }
        return element;
      },
      body: { append() {} },
    },
    window: {
      removeEventListener() {},
      addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    },
    location: { origin: ORIGIN },
    globalThis: {},
    console,
    // 弹窗里的提示条用 timer 自动淡出；测试只需要它可调用，不需要真的计时。
    setTimeout: () => 0,
    clearTimeout: () => {},
  };
  context.globalThis = context;
  context.Image = function Image() {
    const image = new FakeImage();
    images.push(image);
    return image;
  };

  vm.runInNewContext(code, context);
  // ComfyUI 启动时会对每个 extension 调一次 registerCustomNodes，测试里手动补上。
  extensions.forEach((ext) => ext.registerCustomNodes?.());
  const extension = extensions.find((ext) => ext.beforeRegisterNodeDef);

  async function createNode(nodeName, widgets, nodeData = {}) {
    await extension.beforeRegisterNodeDef(Node, { name: nodeName, ...nodeData });
    const node = new Node();
    node.widgets = widgets;
    node.onNodeCreated?.();
    return node;
  }

  return { createNode, images, dialogs, context, extensions, registered, listeners };
}

const drawText = (node) => {
  const ctx = new FakeContext();
  node.onDrawForeground(ctx);
  return ctx;
};

const LIB_DATA = { name: 'CostumeGallery' };

test('preview draws the bundled thumbnail inside the node, never a DOM widget', async () => {
  const { createNode, images } = harness();
  const node = await createNode('CostumeGallery', [{ name: 'costume_id', value: 'SPR-0001' }], LIB_DATA);
  assert.equal(images.length, 1, '预览用一个 Image 对象');
  assert.equal(images[0].src, '/api/ref_lookbook/asset/costume/thumbs/SPR-0001');
  images[0].load(400, 600);
  const ctx = drawText(node);
  assert.equal(ctx.images.length, 1, '加载完成后应画到画布上');
  const rect = ctx.images[0];
  assert.ok(rect.x >= 0 && rect.y > 0, '绘制起点在节点内');
  assert.ok(rect.x + rect.w <= node.size[0], '图片不超出右侧');
  assert.ok(rect.y + rect.h <= node.size[1], '图片不超出底部');
});

test('pose preview follows the angle widget', async () => {
  const { createNode, images } = harness();
  const node = await createNode(
    'PoseGallery',
    [{ name: 'pose_id', value: 'POS-SEXY-P001' }, { name: 'angle', value: '侧面' }],
    { name: 'PoseGallery' },
  );
  assert.equal(images[0].src, '/api/ref_lookbook/asset/pose/thumbs/POS-SEXY-P001?angle=%E4%BE%A7%E9%9D%A2');
  node.widgets[1].value = '正面';
  node.widgets[1].callback();
  assert.equal(images[0].src, '/api/ref_lookbook/asset/pose/thumbs/POS-SEXY-P001?angle=%E6%AD%A3%E9%9D%A2');
});

test('missing thumbnail paints the id and the repair hint instead of a blank node', async () => {
  const { createNode, images } = harness();
  const node = await createNode(
    'PoseGallery',
    [{ name: 'pose_id', value: 'POS-SEXY-P001' }, { name: 'angle', value: '侧面' }],
    { name: 'PoseGallery' },
  );
  images[0].fail();
  const ctx = drawText(node);
  const text = ctx.texts.join(' ');
  assert.match(text, /POS-SEXY-P001/);
  assert.match(text, /library\/pose\/thumbs/);
  assert.equal(ctx.images.length, 0);
});

test('a slow older request cannot blank the newly selected item', async () => {
  const { createNode, images } = harness();
  const node = await createNode('CostumeGallery', [{ name: 'costume_id', value: 'SPR-0001' }], LIB_DATA);
  const previousError = images[0].onerror;
  node.widgets[0].value = 'SPR-0002';
  node.widgets[0].callback();
  images[0].load(400, 600);
  previousError?.();
  const ctx = drawText(node);
  assert.equal(ctx.images.length, 1, '旧请求的失败不应覆盖新图片');
});

test('Load Image gets a gallery import button that opens the picker', async () => {
  const { createNode, dialogs } = harness();
  const nodeData = {
    name: 'LoadImage',
    output: [['IMAGE', 'IMAGE'], ['MASK', 'MASK']],
    input: { required: { image: [['a.png', 'b.png'], { image_upload: true }] } },
  };
  const node = await createNode('LoadImage', [{ name: 'image', value: 'a.png', options: { values: ['a.png', 'b.png'] } }], nodeData);
  const button = node.widgets.find((widget) => String(widget.name).includes('从参考图库导入'));
  assert.ok(button, 'Load Image 应多出一个导入按钮');
  button.callback();
  assert.equal(dialogs.length, 1, '点按钮应弹出图库');
  // 弹窗里除了 header / toast 还有 iframe，按标签找，别用位置。
  const frame = dialogs[0].children.find((child) => child.tag === 'iframe');
  assert.match(frame.src, /\/ref_lookbook\/gallery\?lib=costume/);
});

test('nodes without an image filename widget are left alone', async () => {
  const { createNode } = harness();
  const node = await createNode('KSampler', [{ name: 'seed', value: 0 }], {
    name: 'KSampler',
    output: [['LATENT', 'LATENT']],
    input: { required: { seed: ['INT', {}] } },
  });
  assert.equal(node.onNodeCreated, undefined, '不相关节点不该被包装');
  assert.equal(node.widgets.length, 1);
});

test('preview survives taller widget rows from other ComfyUI builds', async () => {
  const { createNode, images } = harness();
  // 别的版本控件高 34px、last_y 也不一样，写死 +26 会把预览区算成 0 高度。
  const widgets = [
    { name: 'costume_id', value: 'SPR-0001', last_y: 30, computeSize: () => [300, 34] },
    { name: 'browse', value: null, last_y: 70, computeSize: () => [300, 34] },
    { name: 'import', value: null, last_y: 110, computeSize: () => [300, 34] },
  ];
  const node = await createNode('CostumeGallery', widgets, LIB_DATA);
  node.size = [360, 420];
  images[0].load(400, 600);
  const ctx = drawText(node);
  assert.equal(ctx.images.length, 1, '控件更高时预览仍要画出来');
  assert.ok(ctx.images[0].y >= 110 + 34, `预览不能压到控件上，实际 y=${ctx.images[0].y}`);
  assert.ok(ctx.images[0].y + ctx.images[0].h <= node.size[1], '不超出节点底部');
});

test('preview falls back to the lower half instead of drawing nothing', async () => {
  const { createNode, images } = harness();
  // 极端情况：控件加起来比节点还高（用户把节点拖得很矮）
  const widgets = [{ name: 'costume_id', value: 'SPR-0001', last_y: 470, computeSize: () => [300, 34] }];
  const node = await createNode('CostumeGallery', widgets, LIB_DATA);
  node.size = [360, 500];
  images[0].load(400, 600);
  const ctx = drawText(node);
  assert.equal(ctx.images.length, 1, '空间不够也要兜底画出来，不能一片空白');
});

test('hair node preview follows its source switch', async () => {
  const { createNode, images } = harness();
  const widgets = [
    { name: 'hair_id', value: 'H-01-01' },
    { name: 'hair_source', value: '澪设计' },
  ];
  const node = await createNode('HairGallery', widgets, { name: 'HairGallery' });
  assert.equal(images[0].src, '/api/ref_lookbook/asset/mio/thumbs/H-01-01',
    '澪设计来源读的是 mio 库');
  assert.equal(node.widgets.find((w) => w.name === 'browse')?.name ?? 'browse', 'browse');

  const source = widgets.find((widget) => widget.name === 'hair_source');
  source.value = '二次元';
  source.callback();
  assert.equal(widgets.find((w) => w.name === 'hair_id').value, 'ANE-H001',
    '换了来源要回落到该来源的第一件，否则预览一直 404');
  assert.equal(images[0].src, '/api/ref_lookbook/asset/anime/thumbs/ANE-H001',
    '二次元来源读的是 anime 库');
});

// —— 跨库选择：服装 / 姿势节点的弹窗顶部能切到澪图库，选完必须真的收下 ——
const openPickerOf = (node) => node.widgets.find((widget) => widget.type === 'button').callback();

function selectFromDialog(dialogs, listeners, data) {
  const dialog = dialogs.at(-1);
  const frame = dialog.children.find((child) => child.tag === 'iframe');
  const receive = listeners.message.at(-1);
  receive({ origin: ORIGIN, source: frame.contentWindow, data: { type: 'ref-gallery-select', ...data } });
  return dialog;
}

test('costume node accepts a mio costume and reads the mio library', async () => {
  const { createNode, images, dialogs, listeners } = harness();
  const node = await createNode('CostumeGallery', [{ name: 'costume_id', value: 'SPR-0001' }], LIB_DATA);
  openPickerOf(node);
  const frame = dialogs.at(-1).children.find((child) => child.tag === 'iframe');
  assert.match(frame.src, /\/ref_lookbook\/gallery\?lib=costume/, '默认还是打开写实服装库');

  selectFromDialog(dialogs, listeners, { library: 'mio', id: 'C-01-01' });
  assert.equal(node.widgets[0].value, 'C-01-01', '在澪图库里选的服装要真的写进节点');
  assert.equal(images[0].src, '/api/ref_lookbook/asset/mio/thumbs/C-01-01',
    '预览要跟着编号切到澪库，否则会去写实库里找一个不存在的编号');
});

test('a costume node reopens straight into the mio costume series', async () => {
  const { createNode, dialogs } = harness();
  const node = await createNode('CostumeGallery', [{ name: 'costume_id', value: 'C-01-01' }], LIB_DATA);
  openPickerOf(node);
  const frame = dialogs.at(-1).children.find((child) => child.tag === 'iframe');
  assert.match(frame.src, /\/ref_lookbook\/mio#s-cloth$/, '编号已经是澪库的就直接落到服装系列');
});

test('pose node accepts a mio pose', async () => {
  const { createNode, images, dialogs, listeners } = harness();
  const node = await createNode(
    'PoseGallery',
    [{ name: 'pose_id', value: 'POS-SEXY-P001' }, { name: 'angle', value: '正面' }],
    { name: 'PoseGallery' },
  );
  openPickerOf(node);
  selectFromDialog(dialogs, listeners, { library: 'mio', id: 'P-01-01' });
  assert.equal(node.widgets[0].value, 'P-01-01');
  assert.equal(images[0].src, '/api/ref_lookbook/asset/mio/thumbs/P-01-01?angle=%E6%AD%A3%E9%9D%A2',
    '澪设计的姿势只有一张，多带一个机位参数也照旧能取到');
});

test('picking the wrong kind in the dialog is explained instead of silently dropped', async () => {
  const { createNode, dialogs, listeners } = harness();
  const node = await createNode('CostumeGallery', [{ name: 'costume_id', value: 'SPR-0001' }], LIB_DATA);
  openPickerOf(node);
  const dialog = selectFromDialog(dialogs, listeners, { library: 'mio', id: 'H-01-01' });
  assert.equal(node.widgets[0].value, 'SPR-0001', '发型编号不能写进服装节点');
  const toast = dialog.children.filter((child) => child.tag === 'div').at(-1);
  assert.match(String(toast.textContent), /发型/, '要告诉用户这件是发型，别让弹窗一关什么都没发生');
});

test('recipe costume and pose slots read the mio library for C- / P- ids', async () => {
  const { createNode, images } = harness();
  const node = await createNode('CharacterRecipe', recipeWidgets(), { name: 'CharacterRecipe' });
  const costume = node.widgets.find((widget) => widget.name === 'costume_id');
  costume.value = 'C-01-01';
  costume.callback();
  assert.equal(images[2].src, '/api/ref_lookbook/asset/mio/thumbs/C-01-01');

  const pose = node.widgets.find((widget) => widget.name === 'pose_id');
  pose.value = 'P-01-01';
  pose.callback();
  assert.equal(images[3].src, '/api/ref_lookbook/asset/mio/thumbs/P-01-01?angle=%E6%AD%A3%E9%9D%A2');

  // 打开深度开关也不能把澪库姿势换成 DEP- 编号：那边根本没有深度版。
  const depth = node.widgets.find((widget) => widget.name === 'use_depth');
  depth.value = true;
  depth.callback();
  assert.equal(images[3].src, '/api/ref_lookbook/asset/mio/thumbs/P-01-01?angle=%E6%AD%A3%E9%9D%A2',
    '澪库姿势要无视深度开关');
});

const recipeWidgets = () => ([
  // 槽位顺序按 config.slots：发型 → 脸 → 服装 → 姿势，所以预览图也是这个次序。
  { name: 'hair_id', value: 'H-01-01' },
  { name: 'hair_source', value: '澪设计' },
  { name: 'face_id', value: 'FACE-0001' },
  { name: 'costume_id', value: 'SPR-0001' },
  { name: 'pose_id', value: 'POS-SEXY-P001' },
  { name: 'pose_angle', value: '正面' },
  { name: 'use_depth', value: false },
]);

test('recipe node loads one preview per library slot', async () => {
  const { createNode, images } = harness();
  await createNode('CharacterRecipe', recipeWidgets(), { name: 'CharacterRecipe' });
  assert.equal(images.length, 4, '发型 / 脸部 / 服装 / 姿势各一张预览');
  assert.equal(images[0].src, '/api/ref_lookbook/asset/mio/thumbs/H-01-01',
    '发型槽读的是澪设计库，不是六库里的某个库');
  assert.equal(images[1].src, '/api/ref_lookbook/asset/face/thumbs/FACE-0001');
  assert.equal(images[2].src, '/api/ref_lookbook/asset/costume/thumbs/SPR-0001');
  assert.equal(images[3].src, '/api/ref_lookbook/asset/pose/thumbs/POS-SEXY-P001?angle=%E6%AD%A3%E9%9D%A2');
});

test('recipe node hair slot follows its source switch', async () => {
  const { createNode, images } = harness();
  const node = await createNode('CharacterRecipe', recipeWidgets(), { name: 'CharacterRecipe' });
  const source = node.widgets.find((widget) => widget.name === 'hair_source');
  source.value = '二次元';
  source.callback();
  const hair = node.widgets.find((widget) => widget.name === 'hair_id');
  assert.equal(hair.value, 'ANE-H001', '换了来源但编号还是澪设计的形态，要回落到该来源的第一件');
  assert.equal(images[0].src, '/api/ref_lookbook/asset/anime/thumbs/ANE-H001');

  source.value = '澪设计';
  source.callback();
  assert.equal(hair.value, 'H-01-01', '切回来同样要回落，不能停在 ANE-H001 上');
});

test('recipe node pose slot follows the depth switch', async () => {
  const { createNode, images } = harness();
  const node = await createNode('CharacterRecipe', recipeWidgets(), { name: 'CharacterRecipe' });
  node.widgets.find((widget) => widget.name === 'use_depth').value = true;
  node.widgets.find((widget) => widget.name === 'use_depth').callback();
  assert.equal(images[3].src, '/api/ref_lookbook/asset/depth/thumbs/DEP-SEXY-P001?angle=%E6%AD%A3%E9%9D%A2',
    '打开深度后姿势槽位要读深度库，编号前缀换成 DEP-');
});

test('recipe node draws its four panels on the canvas', async () => {
  const { createNode, images } = harness();
  const node = await createNode('CharacterRecipe', recipeWidgets(), { name: 'CharacterRecipe' });
  images.forEach((image) => image.load(400, 600));
  const ctx = drawText(node);
  assert.equal(ctx.images.length, 4, '四个槽位都应画出来');
  assert.ok(ctx.texts.includes('发型') && ctx.texts.includes('脸部') &&
    ctx.texts.includes('服装') && ctx.texts.includes('姿势'));
  for (const rect of ctx.images) {
    assert.ok(rect.w > 0 && rect.h > 0);
  }
});

// ── 示例开关：一个按钮管一组，点哪组只跑哪组 ──

const fakeGraph = () => ({
  _nodes: [
    { id: 1, pos: [0, 0], size: [300, 300], mode: 0 },   // ① 组
    { id: 2, pos: [0, 400], size: [300, 300], mode: 2 }, // ② 组，json 里预设静音
    { id: 3, pos: [400, 0], size: [300, 300], mode: 0 }, // ③ 两条链共用
  ],
  _groups: [
    { title: '① 单独节点', bounding: [0, 0, 400, 350] },
    { title: '② 四合一配方', bounding: [0, 350, 400, 400] },
    { title: '③ 模型与采样（两条链共用）', bounding: [390, 0, 400, 350] },
  ],
  setDirtyCanvas() {},
  change() {},
});

const switchNode = (graph) => {
  const { registered } = harness();
  assert.ok(registered.has('ref_lookbook/WorkflowSwitch'), '开关节点要注册到 LiteGraph');
  const Switch = registered.get('ref_lookbook/WorkflowSwitch');
  const node = new Switch();
  node.graph = graph ?? fakeGraph();
  return node;
};

test('workflow switch mutes the group it is not running', () => {
  const node = switchNode();
  node.apply();
  assert.deepEqual(node.graph._nodes.map((n) => n.mode), [0, 2, 0], '默认只跑 ①，② 整组静音');

  node.onMouseDown({}, [20, node.buttons()[1].y + 6]);
  assert.deepEqual(Array.from(node.properties.on), [false, true], '点 ② 之后只开 ②');
  assert.deepEqual(node.graph._nodes.map((n) => n.mode), [2, 0, 0], '① 静音，共用模型组不受影响');
});

test('workflow switch never turns both groups off', () => {
  const node = switchNode();
  node.apply();
  node.onMouseDown({}, [20, node.buttons()[0].y + 6]); // 点当前已在跑的那组
  assert.deepEqual(Array.from(node.properties.on), [true, false], '再点当前那组不做反应');
  assert.deepEqual(node.graph._nodes.map((n) => n.mode), [0, 2, 0], '至少留一组在跑，不会两组全关');
});

test('workflow switch draws both buttons with their state', () => {
  const ctx = drawText(switchNode());
  assert.ok(ctx.texts.includes('① 单独节点取图') && ctx.texts.includes('② 四合一配方'),
    '两个按钮的组名都要画出来');
  assert.ok(ctx.texts.includes('运行中') && ctx.texts.includes('已静音'), '按钮上要写清开还是关');
});

test('workflow switch survives a corrupted saved state and missing groups', () => {
  const node = switchNode();
  node.properties = { on: 'corrupted' }; // 手改过 json 或旧版本存盘
  assert.doesNotThrow(() => node.apply());
  assert.deepEqual(Array.from(node.properties.on), [true, false], '状态读不出来就退回默认，不能变成 undefined');

  const empty = switchNode({ _nodes: [], _groups: [], setDirtyCanvas() {}, change() {} });
  assert.doesNotThrow(() => empty.apply(), '组被删掉时不能抛错，否则整张画布加载失败');
});
