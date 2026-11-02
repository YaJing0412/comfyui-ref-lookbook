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
  let extension;

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

  const context = {
    app: {
      registerExtension(value) { extension = value; },
      graph: { change() {}, setDirtyCanvas() {} },
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
    window: { removeEventListener() {}, addEventListener() {} },
    location: { origin: ORIGIN },
    globalThis: {},
    console,
  };
  context.globalThis = context;
  context.Image = function Image() {
    const image = new FakeImage();
    images.push(image);
    return image;
  };

  vm.runInNewContext(code, context);

  async function createNode(nodeName, widgets, nodeData = {}) {
    await extension.beforeRegisterNodeDef(Node, { name: nodeName, ...nodeData });
    const node = new Node();
    node.widgets = widgets;
    node.onNodeCreated?.();
    return node;
  }

  return { createNode, images, dialogs, context };
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
  const frame = dialogs[0].children.at(-1);
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
