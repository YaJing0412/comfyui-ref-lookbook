import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// 四个自有图库节点
const LIBRARIES = {
  CostumeGallery: {
    library: "costume",
    idWidget: "costume_id",
    label: "服装",
    button: "浏览服装图库 · 搜索 / 分类 / 关键词",
  },
  PoseGallery: {
    library: "pose",
    idWidget: "pose_id",
    angleWidget: "angle",
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
};

let activeDialog = null;

// 四个节点与「任意加载图像节点」共用同一个选择器：图库页里可以随时切库。
function openGalleryDialog({ library, title, onSelect }) {
  activeDialog?.close();
  let frame = null;

  const dialog = document.createElement("dialog");
  dialog.style.cssText =
    "width:96vw;height:94vh;max-width:1800px;max-height:96vh;padding:0;border:1px solid #777;border-radius:12px;background:#f7f5ef;";

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
  frame.src = api.apiURL(`/ref_lookbook/gallery?lib=${library}`);
  frame.title = "参考图库";
  frame.style.cssText = "width:100%;height:calc(100% - 48px);border:0;";
  dialog.append(header, frame);

  const receive = (event) => {
    if (event.origin !== location.origin || event.source !== frame?.contentWindow) return;
    if (event.data?.type === "ref-gallery-ready") {
      frame.contentWindow.postMessage(
        { type: "ref-gallery-current", library, id: "", angle: undefined },
        location.origin,
      );
    }
    if (event.data?.type !== "ref-gallery-select" || typeof event.data.id !== "string") return;
    onSelect(event.data);
    close();
  };

  function close() {
    window.removeEventListener("message", receive);
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
  activeDialog = { close, setStatus: (text) => { label.textContent = text; } };
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

    const created = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      created?.apply(this, arguments);
      const node = this;
      const value = node.widgets.find((w) => w.name === config.idWidget);
      // 形态维度的控件名各库不同：姿势 / 深度姿势是 angle（五个机位），二次元是 variant（彩图 / 线稿）。
      const variantName = config.variantWidget || config.angleWidget;
      const angleWidget = variantName ? node.widgets.find((w) => w.name === variantName) : null;

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
        return api.apiURL(`/ref_lookbook/asset/${config.library}/thumbs/${encodeURIComponent(id)}${query}`);
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
        const note = `${config.label}缩略图缺失：${itemId}${suffix}。内置图库不完整，请重新安装节点以补齐 library/${config.library}/thumbs。`;
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

      const bind = (widget) => {
        if (!widget) return;
        const previous = widget.callback;
        widget.callback = function () {
          previous?.apply(this, arguments);
          update();
        };
      };
      bind(value);
      bind(angleWidget);

      function openPicker() {
        openGalleryDialog({
          library: config.library,
          title: `参考图库 · 选择${config.label}后点击「使用此${config.label}」`,
          onSelect: (data) => {
            if (data.library && data.library !== config.library) return;
            value.value = data.id;
            if (angleWidget && typeof data.angle === "string" && data.angle) angleWidget.value = data.angle;
            value.callback?.(value.value);
            angleWidget?.callback?.(angleWidget.value);
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
      "从参考图库导入 · 服装 / 姿势 / 脸部",
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
