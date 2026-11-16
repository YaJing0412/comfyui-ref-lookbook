import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// 自有图库节点：六个单库 + 发型（两个来源）+ 澪设计档案 + 角色配方（四合一）

// 澪设计档案的编号形态：H-01-01 发型 / C-01-01 服装 / P-01-01 姿势。
// 写实库的编号完全不同（SPR-0001、POS-SEXY-P001、FACE-0001…），所以看前缀就知道该读哪本库。
const MIO_ID = /^([HCP])-\d{2}-\d{2}$/;

// 编号属于澪库、并且该节点声明接受这一类时，实际读澪库；否则留在默认库。
// 起因：服装 / 姿势节点的弹窗顶部能切到「澪图库」，选完却被 onSelect 静默丢掉，
// 用户看到的就是「选了没反应」——所以库必须跟着编号走，前后端用同一套判断。
function libraryOf(config, itemId, base) {
  const match = MIO_ID.exec(String(itemId ?? ""));
  return match && (config.mioKinds || []).includes(match[1]) ? "mio" : base;
}

const KIND_LABELS = { H: "发型", C: "服装", P: "姿势" };

// 这个节点收不收这件素材。弹窗顶部可以在「日系图库 / 澪图库」之间来回切，
// 所以选到的库跟节点原本的库不一样很正常——要么按类别收下，要么明确拒绝，不能默默丢掉。
function canTake(config, data) {
  if (!data.library) return true;            // 老页面不带库名：照旧收下
  if (data.library === "anime") return Boolean(config.sourceMap) || config.library === "anime";
  // 深度姿势只有配方节点能收：它那边有多一层「用深度图」开关。
  if (data.library === "depth") return Boolean(config.depthIdWidget) || config.library === "depth";
  if (data.library !== "mio") return data.library === config.library;
  // 澪库：按编号类别判断。发型节点只收 H，服装 / 姿势节点各自收 C / P，澪设计档案节点三类都收。
  const kinds = config.mioKinds || (config.library === "mio" ? ["H", "C", "P"] : []);
  const kind = MIO_ID.exec(String(data.id))?.[1];
  return Boolean(kind) && kinds.includes(kind);
}

function refuseText(config, data) {
  const kind = KIND_LABELS[MIO_ID.exec(String(data.id))?.[1]];
  if (kind) return `这件是「${kind}」，当前节点只收「${config.label}」。请换用对应的${kind}节点，或用「澪设计档案」节点（三类都能选）。`;
  return `这件素材不属于当前节点（只收「${config.label}」）。请换用对应的节点，或用「澪设计档案」节点。`;
}

const LIBRARIES = {
  CostumeGallery: {
    library: "costume",
    idWidget: "costume_id",
    // 也接澪设计档案里的服装：弹窗顶部切到澪图库选到的 C-01-01 要能真的用上。
    mioKinds: ["C"],
    // 当前编号已经是澪库的（C-01-01）就直接开澪库页的服装系列，省一次切库。
    openFor: { mio: { page: "mio", hash: "#s-cloth" } },
    label: "服装",
    button: "浏览服装图库 · 搜索 / 分类 / 关键词",
  },
  CostumeAnimeGallery: {
    library: "costume-anime",
    idWidget: "costume_anime_id",
    label: "服装动画",
    button: "浏览服装动画图库 · 1,320 套动漫衣装",
  },
  PoseGallery: {
    library: "pose",
    idWidget: "pose_id",
    angleWidget: "angle",
    // 也接澪设计档案里的姿势（P-01-01 这种编号；那边每个动作只有一张，跟机位无关）。
    mioKinds: ["P"],
    openFor: { mio: { page: "mio", hash: "#s-pose" } },
    label: "姿势",
    button: "浏览姿势图库 · 288 个动作 / 五个机位",
  },
  FaceGallery: {
    library: "face",
    idWidget: "face_id",
    label: "脸部",
    button: "浏览脸部图库 · 特写 / 造型 / 发型",
  },
  DepthGallery: {
    library: "depth",
    idWidget: "depth_id",
    angleWidget: "angle",
    label: "深度姿势",
    button: "浏览深度姿势图库 · 288 个动作 / 五个机位",
  },
  AnimeGallery: {
    library: "anime",
    idWidget: "anime_id",
    variantWidget: "variant",
    label: "二次元",
    button: "浏览二次元图库 · 服装 / 发型与眼睛 / 姿势",
  },
  // 发型：一个节点两个来源，库名跟着 hair_source 控件走。
  // 两个来源各有自己的浏览页面，所以打开时按当前来源决定去哪：
  // 澪设计是独立档案页，带 #s-hair 直接落到发型系列；二次元在六库页里，带 cat 直接落到发型分类。
  HairGallery: {
    library: "mio",
    sourceWidget: "hair_source",
    sourceMap: { "澪设计": "mio", "二次元": "anime" },
    idDefaults: { mio: "H-01-01", anime: "ANE-H001" },
    // 澪图库里还有服装和姿势，发型节点只认 H 开头的编号。
    mioKinds: ["H"],
    openFor: {
      mio: { page: "mio", hash: "#s-hair" },
      anime: { query: `cat=${encodeURIComponent("发型与眼睛")}` },
    },
    idWidget: "hair_id",
    label: "发型",
    button: "浏览发型库 · 澪设计 54 件 / 二次元 230 条",
  },
  // 四合一配方：一个节点挂四个槽（发型 / 脸 / 服装 / 姿势），各自一个按钮、一张缩略图。
  CharacterRecipe: {
    label: "角色配方",
    slots: [
      // 发型槽自带来源切换：澪设计（mio）或二次元（anime），选完自动把开关拨到对应那边。
      { library: "mio", sourceWidget: "hair_source", mioKinds: ["H"],
        sourceMap: { "澪设计": "mio", "二次元": "anime" },
        idDefaults: { mio: "H-01-01", anime: "ANE-H001" },
        openFor: { mio: { page: "mio", hash: "#s-hair" },
                   anime: { query: `cat=${encodeURIComponent("发型与眼睛")}` } },
        idWidget: "hair_id", label: "发型", button: "选发型（澪设计 / 二次元）" },
      { library: "face", idWidget: "face_id", label: "脸部", button: "选脸部" },
      { library: "costume", idWidget: "costume_id", label: "服装", button: "选服装（写实 / 动画）", mioKinds: ["C"] },
      { library: "pose", idWidget: "pose_id", variantWidget: "pose_angle", label: "姿势",
        button: "选姿势（跟随深度开关）", depthIdWidget: "use_depth", mioKinds: ["P"] },
    ],
  },
  // 霧島澪设计档案：布局是「系列 → 卷 → 9 件」且每件带作者原版提示词，
  // 所以挂独立页面 /ref_lookbook/mio，不塞进六库页签（page 字段）。
  MioGallery: {
    library: "mio",
    idWidget: "mio_id",
    label: "澪设计档案",
    button: "浏览澪设计档案 · 发型 / 服装 / 姿势",
    page: "mio",
    useLabel: "使用此作品",
  },
};

let activeDialog = null;

// 六个节点与「任意加载图像节点」共用同一个选择器：图库页里可以随时切库。
// page：某些库有独立页面（目前只有 mio），此时直接开那个页面，不带 ?lib= 参数。
function openGalleryDialog({ library, title, onSelect, page, query, hash }) {
  activeDialog?.close();
  let frame = null;

  const dialog = document.createElement("dialog");
  dialog.style.cssText =
    "position:relative;width:96vw;height:94vh;max-width:1800px;max-height:96vh;padding:0;border:1px solid #777;border-radius:12px;background:#f7f5ef;";

  const header = document.createElement("div");
  header.style.cssText =
    "height:48px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:#e9efe9;color:#253c32;font:14px sans-serif;";
  const label = document.createElement("strong");
  label.textContent = title;
  const done = document.createElement("button");
  done.textContent = "关闭";
  done.style.cssText =
    "cursor:pointer;padding:6px 16px;border-radius:6px;border:1px solid #bac9bd;background:white;color:#253c32;";
  done.onclick = () => close();
  header.append(label, done);

  frame = document.createElement("iframe");
  // query / hash 用来把用户直接送到要选的那一类：澪设计送 #s-hair（发型系列），
  // 二次元送 cat=发型与眼睛（发型分类）。没有就能省掉，不影响别的库。
  const base = page
    ? api.apiURL(`/ref_lookbook/${page}`)
    : api.apiURL(`/ref_lookbook/gallery?lib=${library}${query ? `&${query}` : ""}`);
  frame.src = hash ? `${base}${hash}` : base;
  frame.title = "参考图库";
  frame.style.cssText = "width:100%;height:calc(100% - 48px);border:0;";

  // 选错类别时给一句人话，而不是把弹窗一关、画布上什么都没变（原来就是这样丢掉选择的）。
  const toast = document.createElement("div");
  toast.style.cssText =
    "position:absolute;top:60px;left:50%;transform:translateX(-50%);z-index:9;max-width:80%;padding:9px 18px;" +
    "border-radius:8px;background:#8b2e2e;color:#fff;font:13px/1.5 sans-serif;box-shadow:0 4px 14px rgba(0,0,0,.18);" +
    "opacity:0;transition:opacity .18s;pointer-events:none;";
  let toastTimer = 0;
  const notice = (text) => {
    toast.textContent = text;
    toast.style.opacity = "1";
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.style.opacity = "0"; }, 4500);
  };

  dialog.append(header, frame, toast);

  const receive = (event) => {
    if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
    if (event.data?.type === "ref-gallery-ready") {
      frame.contentWindow.postMessage(
        { type: "ref-gallery-current", library, id: "", angle: undefined },
        location.origin,
      );
    }
    if (event.data?.type !== "ref-gallery-select" || typeof event.data.id !== "string") return;
    // onSelect 返回 false 表示这一件不属于当前节点：留着弹窗并提示，别关掉装作成功。
    if (onSelect(event.data) === false) return;
    close();
  };

  function close() {
    window.removeEventListener("message", receive);
    clearTimeout(toastTimer);
    activeDialog = null;
    dialog.remove();
  }

  window.addEventListener("message", receive);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close();
  });
  document.body.append(dialog);
  dialog.showModal();
  activeDialog = { close, notice, setStatus: (text) => { label.textContent = text; } };
  return activeDialog;
}

// —— 让任意「加载图像」节点也能调起素材库 ——
// 判定：节点输出 IMAGE，且有一个内容像图片文件名的下拉/文本框（LoadImage、LoadImageMask、
// 各种第三方 Image Load 节点都符合）。选中素材后把原图落到 input 目录，再把文件名填回去。
function imageCandidates(nodeData) {
  const spec = nodeData?.input?.required ?? {};
  const names = [];
  for (const [name, def] of Object.entries(spec)) {
    const opts = Array.isArray(def) ? def[1] : null;
    const list = opts?.options ?? (Array.isArray(def?.[0]) ? def[0] : null);
    if (!Array.isArray(list)) continue;
    const looksLikeImages =
      list.some((v) => typeof v === "string" && /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(v)) ||
      (list.length === 0 && /^(image|file|filename|path)$/i.test(name));
    if (looksLikeImages) names.push(name);
  }
  return names;
}

function imageFileWidget(node, nodeData) {
  for (const name of imageCandidates(nodeData)) {
    const widget = node.widgets?.find((w) => w.name === name);
    if (widget) return widget;
  }
  return node.widgets?.find((w) => w.name === "image" && typeof w.value === "string") ?? null;
}

function hasImageOutput(nodeData) {
  return (nodeData?.output ?? []).some((o) => (Array.isArray(o) ? o[0] : o) === "IMAGE");
}

function applyFileName(node, widget, name) {
  const values = widget.options?.values;
  if (Array.isArray(values) && !values.includes(name)) values.unshift(name);
  widget.value = name;
  // 新版前端把图片控件做成 Vue 组件，赋值会走 setValue；老式控件再补一次回调。
  widget.callback?.(name);
  node.onWidgetChanged?.(widget.name, name, undefined, widget);
  node.setDirtyCanvas?.(true, true);
  app.graph?.setDirtyCanvas?.(true, true);
}

async function importFromGallery(payload, node, widget, setStatus) {
  setStatus?.("正在导入素材…");
  const response = await api.fetchApi("/ref_lookbook/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ library: payload.library, id: payload.id, angle: payload.angle }),
  });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `导入失败（HTTP ${response.status}）`);
  applyFileName(node, widget, result.name);
  return result;
}

app.registerExtension({
  name: "comfyui-ref-lookbook.browser",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const config = LIBRARIES[nodeData.name];
    if (!config) {
      registerImporter(nodeType, nodeData);
      return;
    }
    if (config.slots) {
      registerRecipeNode(nodeType, config);
      return;
    }

    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      created?.apply(this, arguments);
      const node = this;
      const value = node.widgets.find((w) => w.name === config.idWidget);
      // 形态维度的控件名各库不同：姿势 / 深度姿势是 angle（五个机位），二次元是 variant（彩图 / 线稿）。
      const variantName = config.variantWidget || config.angleWidget;
      const angleWidget = variantName ? node.widgets.find((w) => w.name === variantName) : null;
      // 来源控件（目前只有发型节点有）：库名跟着它走，澪设计 → mio，二次元 → anime。
      const sourceWidget = config.sourceWidget
        ? node.widgets.find((w) => w.name === config.sourceWidget) ?? null
        : null;
      // 预览与取图都按「实际库」走：没有来源开关的节点（服装 / 姿势）跟着编号走，
      // 编号是 C-01-01 / P-01-01 时读澪库；发型节点的库仍由来源下拉决定。
      const currentLibrary = () => {
        const base = (sourceWidget && config.sourceMap?.[String(sourceWidget.value)]) || config.library;
        return sourceWidget ? base : libraryOf(config, value?.value, base);
      };

      // 预览直接画在节点画布上，不用 DOM 控件：DOM 控件的定位由前端布局决定，
      // 一旦图片原始尺寸大于分配区域就会溢出节点边框。
      const previewImage = new Image();
      previewImage.decoding = "async";
      let previewState = "idle";
      let previewNote = "";

      const sourceOf = (id) => {
        const angle = angleWidget ? String(angleWidget.value ?? "") : "";
        const query = angle ? `?angle=${encodeURIComponent(angle)}` : "";
        // 节点内只用内置缩略图：仓库随包发行 thumbs，离线可预览；个别缺失时服务端按需向作者站点取一次。
        return api.apiURL(`/ref_lookbook/asset/${currentLibrary()}/thumbs/${encodeURIComponent(id)}${query}`);
      };

      const markReady = () => {
        previewState = "ready";
        node.setDirtyCanvas(true, false);
      };
      const markError = (note) => {
        previewState = "error";
        previewNote = note;
        node.setDirtyCanvas(true, false);
      };

      let previewRequest = 0;
      const update = () => {
        const request = ++previewRequest;
        const itemId = String(value.value);
        const url = sourceOf(itemId);
        const suffix = angleWidget ? `（${angleWidget.value}）` : "";
        const note = `${config.label}缩略图缺失：${itemId}${suffix}。内置图库不完整，请重新安装节点以补齐 library/${currentLibrary()}/thumbs。`;
        previewState = "loading";
        node.setDirtyCanvas(true, false);
        previewImage.onload = () => {
          if (request === previewRequest) markReady();
        };
        previewImage.onerror = () => {
          if (request !== previewRequest) return;
          markError(note);
          // 顺手探一次真实状态码：404 是缩略图没随包，其它状态是请求本身出了问题。
          // 用户报「不显示」时，F12 控制台这一行就能定位，不用来回猜。
          if (typeof fetch === "function") {
            fetch(url, { method: "HEAD" })
              .then((r) => console.warn("[参考图库] 缩略图加载失败", { id: itemId, url, status: r.status }))
              .catch(() => console.warn("[参考图库] 缩略图加载失败", { id: itemId, url, status: "网络不可达" }));
          } else {
            console.warn("[参考图库] 缩略图加载失败", { id: itemId, url });
          }
        };
        previewImage.src = url;
        if (previewImage.complete && previewImage.naturalWidth) markReady();
      };

      // 换了来源但编号还是另一个库的：回落到该来源的默认编号。两个库的编号空间不重叠
      // （H-01-01 / ANE-H001），不换的话预览会一直 404——后端其实会自动回落，但控件上还显示旧编号，对不上。
      const syncSourceId = () => {
        if (!sourceWidget || !value) return;
        const library = currentLibrary();
        const itemId = String(value.value ?? "");
        const fits = library === "mio" ? /^H-\d{2}-\d{2}$/.test(itemId) : itemId.startsWith("ANE-");
        if (!fits && config.idDefaults?.[library]) value.value = config.idDefaults[library];
      };

      const bind = (widget, extra) => {
        if (!widget) return;
        const previous = widget.callback;
        widget.callback = function () {
          previous?.apply(this, arguments);
          extra?.();
          update();
        };
      };
      bind(value);
      bind(angleWidget);
      bind(sourceWidget, syncSourceId);

      function openPicker() {
        const library = currentLibrary();
        const target = config.openFor?.[library] ?? {};
        const useLabel = config.useLabel || `使用此${config.label}`;
        openGalleryDialog({
          library,
          page: target.page ?? config.page,
          query: target.query,
          hash: target.hash,
          title: `参考图库 · 选择${config.label}后点击「${useLabel}」`,
          onSelect: (data) => {
            // 带来源的节点（发型）：用户在弹窗里切到另一个来源选了一件，就把开关拨过去再收下。
            // 但来源对不代表类别对——在澪图库里点到一件服装，发型节点收不了，得说清楚。
            if (config.sourceMap) {
              const name = Object.keys(config.sourceMap).find((key) => config.sourceMap[key] === data.library);
              if (name && sourceWidget) sourceWidget.value = name;
            }
            if (!canTake(config, data)) {
              activeDialog?.notice?.(refuseText(config, data));
              return false;
            }
            value.value = data.id;
            if (angleWidget && typeof data.angle === "string" && data.angle) angleWidget.value = data.angle;
            value.callback?.(value.value);
            angleWidget?.callback?.(angleWidget.value);
            sourceWidget?.callback?.(sourceWidget.value);
            node.setDirtyCanvas(true, true);
            app.graph.change();
          },
        });
      }

      // 预览区域的纵坐标取最后一个控件的下沿，图片按剩余高度等比缩放居中。
      // 控件高度不能写死：不同 ComfyUI 前端版本的控件高度不一样（20 / 22 / 26 都见过），
      // 写死会导致把预览区算成 0 高度，节点上什么都不画——换个版本的机器就复现。
      const widgetBottom = (widget) => {
        if (typeof widget.last_y !== "number") return 0;
        let height = 20;
        if (typeof widget.computeSize === "function") {
          try {
            const size = widget.computeSize(node.size[0]);
            if (Array.isArray(size) && Number(size[1]) > 0) height = Number(size[1]);
          } catch {
            /* 少数前端版本在未布局时抛错，退回默认值 */
          }
        }
        return widget.last_y + height + 6;
      };
      const previewRect = () => {
        const margin = 10;
        let top = 30;
        for (const widget of node.widgets ?? []) top = Math.max(top, widgetBottom(widget));
        const width = Math.max(0, node.size[0] - margin * 2);
        const height = Math.max(0, node.size[1] - top - margin);
        return { x: margin, y: top, width, height };
      };

      const drawPreview = (ctx) => {
        let rect = previewRect();
        if (rect.height < 40) {
          // 兜底：控件把空间吃光时退到节点下半部分，宁可和控件重叠也要把图显示出来。
          const top = Math.max(40, node.size[1] * 0.5);
          rect = { x: 10, y: top, width: Math.max(0, node.size[0] - 20), height: Math.max(0, node.size[1] - top - 8) };
        }
        if (rect.width < 24 || rect.height < 24) return;
        ctx.save();
        ctx.fillStyle = "#f8f7f3";
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(rect.x, rect.y, rect.width, rect.height, 6);
        else ctx.rect(rect.x, rect.y, rect.width, rect.height);
        ctx.fill();
        ctx.strokeStyle = "#d8d4c8";
        ctx.lineWidth = 1;
        ctx.stroke();

        if (previewState === "ready" && previewImage.naturalWidth) {
          const scale = Math.min(rect.width / previewImage.naturalWidth, rect.height / previewImage.naturalHeight);
          const w = previewImage.naturalWidth * scale;
          const h = previewImage.naturalHeight * scale;
          ctx.drawImage(previewImage, rect.x + (rect.width - w) / 2, rect.y + (rect.height - h) / 2, w, h);
        } else if (previewState === "error") {
          ctx.fillStyle = "#8b2e2e";
          ctx.font = "12px sans-serif";
          const lines = [`${config.label}缩略图未加载：${String(value.value)}`,
            `library/${config.library}/thumbs/ · 按 F12 看控制台提示`];
          lines.forEach((line, index) => {
            ctx.fillText(line, rect.x + 10, rect.y + 26 + index * 18, rect.width - 20);
          });
          if (previewNote) console.warn("[参考图库]", previewNote);
        } else {
          ctx.fillStyle = "#8a8579";
          ctx.font = "12px sans-serif";
          ctx.fillText("正在加载缩略图…", rect.x + 10, rect.y + 24);
        }
        ctx.restore();
      };

      const draw = node.onDrawForeground;
      node.onDrawForeground = function (ctx) {
        draw?.apply(this, arguments);
        if (this.flags?.collapsed) return;
        drawPreview(ctx);
      };

      const mouseDown = node.onMouseDown;
      node.onMouseDown = function (event, pos, canvas) {
        const rect = previewRect();
        if (pos[0] >= rect.x && pos[0] <= rect.x + rect.width && pos[1] >= rect.y && pos[1] <= rect.y + rect.height) {
          openPicker();
          return true;
        }
        return mouseDown?.apply(this, arguments);
      };

      node.addWidget("button", config.button, null, openPicker, { serialize: false });

      const configured = node.onConfigure;
      node.onConfigure = function () {
        configured?.apply(this, arguments);
        update();
      };
      const removed = node.onRemoved;
      node.onRemoved = function () {
        activeDialog?.close();
        removed?.apply(this, arguments);
      };
      node.setSize([360, angleWidget ? 600 : 540]);
      update();
    };
  },
});

// 四合一配方节点：发型 / 脸部 / 服装 / 姿势四个槽各一个按钮、一张缩略图，点图直接换该槽位的素材。
// 预览区按槽位数等分，比单图节点占地方，默认节点也开得更大。
function registerRecipeNode(nodeType, config) {
  const created = nodeType.prototype.onNodeCreated;
  nodeType.prototype.onNodeCreated = function () {
    created?.apply(this, arguments);
    const node = this;
    const widgetOf = (name) => (name ? node.widgets?.find((w) => w.name === name) ?? null : null);

    const slots = config.slots.map((slot) => {
      const image = new Image();
      image.decoding = "async";
      return {
        ...slot,
        idWidget: widgetOf(slot.idWidget),
        variantWidget: widgetOf(slot.variantWidget),
        depthWidget: widgetOf(slot.depthIdWidget),
        // slot.sourceWidget 是控件名，这里换成控件本身；带来源的槽（发型）靠它决定读哪个库。
        sourceControl: widgetOf(slot.sourceWidget),
        image,
        state: "idle",
      };
    });

    // 深度开关打开时，姿势槽位改读深度库，编号前缀 POS- → DEP-（两库 288 条一一对应）。
    // 发型槽没有深度开关，走 sourceControl 那条分支。
    const resolve = (slot) => {
      const raw = String(slot.idWidget?.value ?? "");
      const bySource = slot.sourceControl ? slot.sourceMap?.[String(slot.sourceControl.value)] : "";
      // 澪库编号（C-01-01 / P-01-01）优先：那边没有深度版，也不能走 POS- → DEP- 的换算。
      const mio = ["costume", "pose"].includes(slot.library) && libraryOf(slot, raw, "") === "mio";
      const depth = !mio && Boolean(slot.depthWidget?.value) && slot.library === "pose";
      return {
        depth,
        library: mio ? "mio" : (bySource || (depth ? "depth" : slot.library)),
        id: depth ? raw.replace(/^POS-/, "DEP-") : raw,
        angle: slot.variantWidget ? String(slot.variantWidget.value ?? "") : "",
      };
    };

    let request = 0;
    const update = () => {
      const ticket = ++request;
      for (const slot of slots) {
        const { library, id, angle } = resolve(slot);
        const query = angle ? `?angle=${encodeURIComponent(angle)}` : "";
        slot.state = "loading";
        slot.image.onload = () => {
          if (ticket !== request) return;
          slot.state = "ready";
          node.setDirtyCanvas(true, false);
        };
        slot.image.onerror = () => {
          if (ticket !== request) return;
          slot.state = "error";
          node.setDirtyCanvas(true, false);
        };
        slot.image.src = api.apiURL(`/ref_lookbook/asset/${library}/thumbs/${encodeURIComponent(id)}${query}`);
        if (slot.image.complete && slot.image.naturalWidth) slot.state = "ready";
      }
      node.setDirtyCanvas(true, false);
    };

    // 换了来源但编号还是另一个库的：换成该来源的默认编号（H-01-01 / ANE-H001），否则缩略图一直缺图。
    const syncSourceId = (slot) => {
      if (!slot.sourceControl || !slot.idWidget) return;
      const library = slot.sourceMap?.[String(slot.sourceControl.value)];
      const itemId = String(slot.idWidget.value ?? "");
      const fits = library === "mio" ? /^H-\d{2}-\d{2}$/.test(itemId) : itemId.startsWith("ANE-");
      if (!fits && slot.idDefaults?.[library]) slot.idWidget.value = slot.idDefaults[library];
    };

    const bind = (widget, extra) => {
      if (!widget) return;
      const previous = widget.callback;
      widget.callback = function () {
        previous?.apply(this, arguments);
        extra?.();
        update();
      };
    };
    slots.forEach((slot) => {
      bind(slot.idWidget);
      bind(slot.variantWidget);
      bind(slot.depthWidget);
      bind(slot.sourceControl, () => syncSourceId(slot));
    });

    const widgetBottom = (widget) => {
      if (typeof widget.last_y !== "number") return 0;
      let height = 20;
      if (typeof widget.computeSize === "function") {
        try {
          const size = widget.computeSize(node.size[0]);
          if (Array.isArray(size) && Number(size[1]) > 0) height = Number(size[1]);
        } catch {
          /* 未布局时个别前端版本会抛错，退回默认值 */
        }
      }
      return widget.last_y + height + 6;
    };
    const previewRect = () => {
      const margin = 10;
      let top = 30;
      for (const widget of node.widgets ?? []) top = Math.max(top, widgetBottom(widget));
      const width = Math.max(0, node.size[0] - margin * 2);
      const height = Math.max(0, node.size[1] - top - margin);
      return { x: margin, y: top, width, height };
    };
    const slotRect = (rect, index) => {
      const gap = 6;
      const width = Math.max(0, (rect.width - gap * (slots.length - 1)) / slots.length);
      return { x: rect.x + index * (width + gap), y: rect.y, width, height: rect.height };
    };

    const openPicker = (slot) => {
      const library = slot.sourceControl
        ? (slot.sourceMap?.[String(slot.sourceControl.value)] || slot.library)
        : slot.library;
      const target = slot.openFor?.[library] ?? {};
      openGalleryDialog({
        library,
        page: target.page ?? slot.page,
        query: target.query,
        hash: target.hash,
        title: `参考图库 · 选择${slot.label}后点击「使用此${slot.label}」`,
        onSelect: (data) => {
          if (!slot.idWidget) return;
          // 先判断这个槽收不收：澪图库里服装 / 姿势 / 发型混在一起，选错了要当场说清楚。
          const view = { library: slot.library, mioKinds: slot.mioKinds, sourceMap: slot.sourceMap,
                         depthIdWidget: slot.depthWidget, label: slot.label };
          if (!canTake(view, data)) {
            activeDialog?.notice?.(refuseText(view, data));
            return false;
          }
          // 带来源的槽（发型）：用户在弹窗里切到另一个来源选了一件，就把来源开关拨过去再收下。
          if (slot.sourceMap) {
            const name = Object.keys(slot.sourceMap).find((key) => slot.sourceMap[key] === data.library);
            if (name && slot.sourceControl) slot.sourceControl.value = name;
          }
          const pickedDepth = data.library === "depth" && slot.depthWidget;
          slot.idWidget.value = pickedDepth ? String(data.id).replace(/^DEP-/, "POS-") : data.id;
          if (pickedDepth) slot.depthWidget.value = true;
          if (slot.variantWidget && typeof data.angle === "string" && data.angle) slot.variantWidget.value = data.angle;
          slot.idWidget.callback?.(slot.idWidget.value);
          slot.variantWidget?.callback?.(slot.variantWidget.value);
          slot.depthWidget?.callback?.(slot.depthWidget.value);
          slot.sourceControl?.callback?.(slot.sourceControl.value);
          node.setDirtyCanvas(true, true);
          app.graph.change();
        },
      });
    };

    const drawSlots = (ctx) => {
      let rect = previewRect();
      if (rect.height < 40) {
        const top = Math.max(40, node.size[1] * 0.5);
        rect = { x: 10, y: top, width: Math.max(0, node.size[0] - 20), height: Math.max(0, node.size[1] - top - 8) };
      }
      if (rect.width < 30 || rect.height < 24) return;

      slots.forEach((slot, index) => {
        const box = slotRect(rect, index);
        if (box.width < 12) return;
        ctx.save();
        ctx.fillStyle = "#f8f7f3";
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(box.x, box.y, box.width, box.height, 6);
        else ctx.rect(box.x, box.y, box.width, box.height);
        ctx.fill();
        ctx.strokeStyle = "#d8d4c8";
        ctx.lineWidth = 1;
        ctx.stroke();

        const labelY = box.y + 14;
        ctx.fillStyle = "#6b6558";
        ctx.font = "11px sans-serif";
        ctx.fillText(slot.label, box.x + 6, labelY, box.width - 12);

        const inner = { x: box.x + 4, y: box.y + 20, width: box.width - 8, height: box.height - 26 };
        if (slot.state === "ready" && slot.image.naturalWidth) {
          const scale = Math.min(inner.width / slot.image.naturalWidth, inner.height / slot.image.naturalHeight);
          const w = slot.image.naturalWidth * scale;
          const h = slot.image.naturalHeight * scale;
          ctx.drawImage(slot.image, inner.x + (inner.width - w) / 2, inner.y + (inner.height - h) / 2, w, h);
        } else {
          ctx.fillStyle = slot.state === "error" ? "#8b2e2e" : "#8a8579";
          ctx.font = "11px sans-serif";
          const text = slot.state === "error" ? "缩略图缺失" : "载入中…";
          ctx.fillText(text, inner.x + 4, inner.y + 16, inner.width - 8);
        }
        ctx.restore();
      });
    };

    const draw = node.onDrawForeground;
    node.onDrawForeground = function (ctx) {
      draw?.apply(this, arguments);
      if (this.flags?.collapsed) return;
      drawSlots(ctx);
    };

    const mouseDown = node.onMouseDown;
    node.onMouseDown = function (event, pos, canvas) {
      const rect = previewRect();
      for (let index = 0; index < slots.length; index += 1) {
        const box = slotRect(rect, index);
        if (pos[0] >= box.x && pos[0] <= box.x + box.width && pos[1] >= box.y && pos[1] <= box.y + box.height) {
          openPicker(slots[index]);
          return true;
        }
      }
      return mouseDown?.apply(this, arguments);
    };

    slots.forEach((slot) => {
      node.addWidget("button", slot.button, null, () => openPicker(slot), { serialize: false });
    });

    const configured = node.onConfigure;
    node.onConfigure = function () {
      configured?.apply(this, arguments);
      update();
    };
    const removed = node.onRemoved;
    node.onRemoved = function () {
      activeDialog?.close();
      removed?.apply(this, arguments);
    };
    // 四个槽位横排，默认比三槽时更宽一点，否则每张图窄得看不清。
    node.setSize([600, 900]);
    update();
  };
}

// 给 LoadImage 之类的节点加一个「从参考图库导入」按钮
function registerImporter(nodeType, nodeData) {
  if (!hasImageOutput(nodeData)) return;
  if (!imageCandidates(nodeData).length) return;
  const created = nodeType.prototype.onNodeCreated;
  nodeType.prototype.onNodeCreated = function () {
    created?.apply(this, arguments);
    const node = this;
    const widget = imageFileWidget(node, nodeData);
    if (!widget) return;

    node.addWidget(
      "button",
      "从参考图库导入 · 服装 / 姿势 / 脸部 / 发型",
      null,
      () => {
        const dialog = openGalleryDialog({
          library: "costume",
          title: "参考图库 · 选中后复制到 ComfyUI 的 input 目录并填入本节点",
          onSelect: async (data) => {
            try {
              const result = await importFromGallery(data, node, widget, dialog?.setStatus);
              console.log(`[参考图库] ${data.library} ${data.id} → input/${result.name}`);
            } catch (error) {
              console.error(error);
              globalThis.alert?.(`导入失败：${error.message}`);
            }
          },
        });
      },
      { serialize: false },
    );
  };
}

// ── 示例工作流的「选一组跑」开关 ──
//
// 合并后的示例工作流有两条链（① 单独节点取图、② 四合一配方），共用同一组模型加载。
// 点一次运行两条都会跑，白等一半时间；手动静音又得一个个节点点。
// 这个节点把两组各做成一个按钮，点哪组只开哪组、另一组整组静音。
// 纯前端节点：不进 prompt，不参与后端校验，也不依赖任何第三方插件。
const SWITCH_SLOTS = [
  { key: "①", label: "① 单独节点取图" },
  { key: "②", label: "② 四合一配方" },
];
// LiteGraph 的 NEVER：节点不执行，输出也不向下游透传（BYPASS 是 4，会透传，整组关不干净）。
const SWITCH_MUTED = 2;
const SWITCH_PAD = 10;
const SWITCH_BUTTON_TOP = 8;
const SWITCH_BUTTON_HEIGHT = 28;
const SWITCH_BUTTON_GAP = 6;

function switchButtons(width, state) {
  const boxWidth = Math.max(160, (width || 300) - SWITCH_PAD * 2);
  return SWITCH_SLOTS.map((slot, index) => ({
    slot,
    index,
    on: Boolean(state?.[index]),
    x: SWITCH_PAD,
    y: SWITCH_BUTTON_TOP + index * (SWITCH_BUTTON_HEIGHT + SWITCH_BUTTON_GAP),
    w: boxWidth,
    h: SWITCH_BUTTON_HEIGHT,
  }));
}

function groupBySlot(graph, key) {
  const groups = graph?._groups || graph?.groups || [];
  return groups.find((group) => String(group?.title || "").includes(key)) || null;
}

// 组框取法：新版 LiteGraph 存成 _bounding（Float32Array），老版是 bounding，
// 再不行退回 pos + size。三种命名都认，免得前端一升级就静音错节点。
function groupBox(group) {
  const box = group?.bounding || group?._bounding;
  if (box && box.length >= 4) return [box[0], box[1], box[2], box[3]];
  const pos = group?.pos || group?._pos || [0, 0];
  const size = group?.size || group?._size || [0, 0];
  return [pos[0], pos[1], size[0], size[1]];
}

// 按节点中心判断归属：节点比组框略大一点也能正确归位，不依赖组内缓存。
function nodesInside(group, nodes) {
  if (!group) return [];
  const [x, y, w, h] = groupBox(group);
  return (nodes || []).filter((node) => {
    const size = node?.size || [0, 0];
    const cx = (node.pos?.[0] ?? 0) + size[0] / 2;
    const cy = (node.pos?.[1] ?? 0) + size[1] / 2;
    return cx >= x && cx <= x + w && cy >= y && cy <= y + h;
  });
}

// 把开关状态套到画布上：开着的一组 mode=0，关掉的一组整组静音。
function applySwitchState(graph, state, self) {
  let changed = false;
  SWITCH_SLOTS.forEach((slot, index) => {
    const group = groupBySlot(graph, slot.key);
    if (!group) return;
    const mode = state?.[index] ? 0 : SWITCH_MUTED;
    nodesInside(group, graph?._nodes).forEach((node) => {
      if (node === self) return;
      if (node.mode !== mode) {
        node.mode = mode;
        changed = true;
      }
      node.setDirtyCanvas?.(true, false);
    });
  });
  return changed;
}

app.registerExtension({
  name: "comfyui-ref-lookbook.workflow-switch",
  registerCustomNodes() {
    const NODE_TYPE = "ref_lookbook/WorkflowSwitch";

    // 可重入：新版前端把 LiteGraph 拆成异步 chunk，registerCustomNodes 可能早于它执行，
    // 那时 window.LiteGraph 还是 undefined。直接 return 的话节点类型永远不注册，
    // 工作流一打开就是「缺节点」——所以失败时轮询重试，注册成功即停。
    const register = () => {
      const LiteGraph = globalThis.LiteGraph;
      if (!LiteGraph?.LGraphNode || typeof LiteGraph.registerNodeType !== "function") return false;
      if (LiteGraph.registered_node_types?.[NODE_TYPE]) return true;

      class WorkflowSwitch extends LiteGraph.LGraphNode {
        constructor() {
          super("示例开关");
          this.title = "示例开关 · 点一下选跑哪一组";
          this.size = [300, 78];
          this.resizable = false;
          this.isVirtualNode = true; // 不进 prompt，不会被当成缺后端类
          this.color = "#223";
          this.bgcolor = "#335";
          this.properties = { on: [true, false] };
        }

        // 存盘的开关状态；格式不对（旧版本、手改过 json）就退回默认，别让按钮变成未定义。
        get state() {
          const raw = this.properties?.on;
          if (Array.isArray(raw) && raw.length === SWITCH_SLOTS.length) return raw.map(Boolean);
          return SWITCH_SLOTS.map((_, index) => index === 0);
        }

        buttons() {
          return switchButtons(this.size?.[0], this.state);
        }

        apply() {
          // 顺手把坏掉的存盘状态归一：手改过 json 或旧版本存下来时，下次保存就干净了。
          this.properties.on = [...this.state];
          const changed = applySwitchState(this.graph, this.state, this);
          if (changed) {
            this.graph?.setDirtyCanvas?.(true, true);
            this.graph?.change?.();
          }
          this.setDirtyCanvas?.(true, true);
          return changed;
        }

        // 单选：点哪组只开哪组。点当前已开的那组不做反应，避免两组全关后运行报「没有输出」。
        pick(index) {
          this.properties.on = SWITCH_SLOTS.map((_, i) => i === index);
          this.apply();
        }

        onConfigure(...args) {
          super.onConfigure?.(...args);
          this.properties.on = [...this.state];
          // 刚加载时组框和节点可能还没全部就位，等一帧再套用。
          setTimeout(() => this.apply(), 0);
        }

        onDrawForeground(ctx) {
          ctx.save();
          ctx.textBaseline = "middle";
          ctx.font = "13px sans-serif";
          for (const button of this.buttons()) {
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(button.x, button.y, button.w, button.h, 5);
            else ctx.rect(button.x, button.y, button.w, button.h);
            ctx.fillStyle = button.on ? "#2f6b45" : "#3a3f4a";
            ctx.fill();
            ctx.lineWidth = 1;
            ctx.strokeStyle = button.on ? "#6fd39a" : "#6b7280";
            ctx.stroke();
            ctx.fillStyle = button.on ? "#e8fbf0" : "#b9c0cc";
            ctx.textAlign = "left";
            ctx.fillText(button.slot.label, button.x + 10, button.y + button.h / 2);
            ctx.textAlign = "right";
            ctx.fillText(button.on ? "运行中" : "已静音", button.x + button.w - 12, button.y + button.h / 2);
          }
          ctx.restore();
        }

        onMouseDown(event, pos) {
          const x = pos?.[0] ?? -1;
          const y = pos?.[1] ?? -1;
          for (const button of this.buttons()) {
            const inside = x >= button.x && x <= button.x + button.w &&
              y >= button.y && y <= button.y + button.h;
            if (!inside) continue;
            if (!button.on) this.pick(button.index);
            return true; // 吃掉这次按下，别让它变成拖动节点
          }
          return false;
        }
      }

      WorkflowSwitch.title = "示例开关 · 选跑哪一组";
      WorkflowSwitch.category = "参考图库";
      // 不补进节点库：这是工作流配套的开关，没有后端实现，列出来只会让人以为能单独用。
      WorkflowSwitch.skip_list = true;
      LiteGraph.registerNodeType(NODE_TYPE, WorkflowSwitch);
      globalThis.RefLookbookWorkflowSwitch = WorkflowSwitch; // 前端测试取用
      return true;
    };

    if (register()) return;
    let tries = 0;
    const timer = setInterval(() => {
      if (register() || (tries += 1) > 200) clearInterval(timer); // 最多等 10 秒
    }, 50);
  },
  loadedGraphNode(node) {
    if (node?.type === "ref_lookbook/WorkflowSwitch") node.apply?.();
  },
});

