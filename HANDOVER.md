# 交接文档

给接手的人（或下一个 AI 会话）看的一页纸：这东西由哪几块组成、哪些约定不能破、怎么验证、怎么发版，以及**每次改动都记在最后的「变更台账」里**。

> 维护约定（硬性）：**每次改代码/工作流/文档后，必须在文末「变更台账」追加一条**，写清四件事——改了什么、涉及哪些文件、为什么改、影响范围（谁会受影响、要不要重启/刷新/重拖工作流）。追加式，不要覆盖旧记录。

---

## 一、这是什么

ComfyUI 插件 + 随包素材库：把「发型 / 脸部 / 服装 / 姿势 / 深度 / 二次元」六套参考图做成画布节点，点按钮选图，再配一份四库合一（发型 + 脸 + 服装 + 姿势）的示例工作流，用 Qwen Image 2.1 出角色立绘。

- 分发仓：`github.com/YaJing0412/comfyui-ref-lookbook`（本目录 `D:/AI/comfyui-ref-lookbook` 是推送用的 checkout）
- 开发目录（真源）：`D:/迅雷下载/ComfyUI-aki-v3/ComfyUI/custom_nodes/comfyui-costume-gallery-main`
- 两者内容一致，**改完要同步**；只推分发仓，`CHANGELOG.md`、`更新日志.md` 不进远端

```
__init__.py              节点定义（图库节点 7 个 + 四合一配方 + 提示词拼接）+ 前端路由注册   826 行
catalog.py               索引加载、编号解析、素材路径、按需下载、卷清单                     409 行
server.py                不开 ComfyUI 时的独立 HTTP 服务（只读浏览页）                      352 行
bulk.py                  整库下载（不对外宣传，文档里一律不提）                            199 行
web/ref_gallery.js       ComfyUI 内前端：图库弹窗、配方节点画布绘制、示例开关               976 行
web/gallery.mjs          六库浏览页（/ref_lookbook/gallery）                                569 行
web/mio.mjs              澪设计档案页（/ref_lookbook/mio）                                  373 行
web/gallery.html|style.css  两个页面的骨架与样式（共用一份 css）
example_workflows/ref_gallery_qwen21.json   唯一的示例工作流（23 节点，两条链 + 开关）
example_workflows/ref_gallery_qwen21.md     使用指南（四图分工、提示词、参数、深度模式）
library/                 索引（data/*.json）+ 随包缩略图（thumbs）+ 澪库原图（mio/thumbs）
tests/                   136 Python + 22 前端
```

## 二、必须守住的约定

1. **`RETURN_NAMES` 只能往末尾追加。** ComfyUI 的连线按输出序号存盘，插到中间会让老工作流整体错位、一打开就串图（`hair_image`、`hair_detail` 都是这么加的）。
2. **`widgets_values` 按控件位置存。** 新增控件只能排在已有控件之后；`forceInput` 的插槽不占控件位，不会进 `widgets_values`（`PromptJoin.extra` 就是）。
3. **旧工作流不能验证失败。** 新控件一律放 `optional`（`hair_id` / `hair_source` 就这么处理的），否则老图一打开节点就红。
4. **`FUNCTION` 字符串必须与同名方法对应。** 写错时节点能拖能连，一点运行才报 `missing the xxx method`——`test_every_function_name_has_a_method` 专门盯这个。
5. **纯前端节点**（`ref_lookbook/WorkflowSwitch`）：`isVirtualNode = true` 不进 prompt，`skip_list = true` 不进节点库。**整组静音用 `mode=2`（NEVER）**，不能用 `4`（BYPASS）——BYPASS 会把输入透传到输出，关不干净。
6. **LiteGraph 组框字段**：新版叫 `_bounding`（Float32Array），老版 `bounding`，再老只有 `pos`+`size`。`groupBox()` 三种都认，别再只读一种。
7. **前端脚本是 `Cache-Control: no-store`**：升级后普通 F5 就够。但浏览器里**已经打开着的页面**不会自动换代码——新增前端节点后没刷新，工作流会提示「缺少节点包」，画布上只剩空框。
8. **新增后端节点必须重启 ComfyUI**（刷新页面无效），再重新拖工作流。
9. **数量硬约束**：`example_workflows/` 只允许一份 json；六库 + 澪库编号互不相交（测试会查）。
10. **`cfg = 1` 时负面提示词完全不起作用**，约束只能写在正面提示词里。示例工作流的 KSampler 就是 `cfg=1`。
11. **跨库选择靠编号前缀认库，前后端必须同一套规则。** 前端 `libraryOf()`（`MIO_ID` + `mioKinds`）与后端 `_library_for_id()` + `MIO_KINDS` 是一对：改一侧必须同步另一侧，否则会出现「预览对了、出图报未知 ID」这种割裂。**选了不属于该节点的类别时绝不能静默 return**——v1.9.0 之前服装节点选澪库服装就是被静默丢掉，用户只看到「没反应」。要么收下，要么 `return false` + 弹提示。
12. **全站只有一份样式表 `web/style.css`。** 澪页与六库页共用同一个骨架；以后再有按系列 / 按卷组织的库，照抄 `web/mio.html` 改数据接口与栏目名即可，**不要新建第二个 CSS**——界面统一靠的就是这一点（旧的 `mio.css` 必须 404，有测试盯着）。
13. **工作流 json 以开发目录为准。** 浏览器里另存会重排格式、可能丢掉部分连线（v1.9.1 就遇到分发仓副本缺 CLIP 连线、`widgets_values` 多空值），同步时别为了「看着更新」反向覆盖；`test_widget_values_match_input_types` 会第一时间抓出来。

## 三、发型为什么容易「不生效」（v1.8.0 的核心教训）

- 图 4 是白色人台上的假发照，模型当「物品图」处理，权重压不过图 2 那张带头发的人像。
- 实测：**选短发立刻生效**（`H-02-01` → 贴头短发）；**长发选长发就看不出差别**，选 `H-01-09`（长直内扣层次）出图是图 2 那种大波浪。
- 所以提示词里必须给「字」：`PromptJoin` 把发型的 `hair_detail`（长度 / 分缝 / 发尾走向）拼在模板后面。手工搭链时发型不生效，**先检查这段文字在不在**。
- `hair_detail` 刻意不用作者整句提示词（那句带「肖像 / 上半身」，会把全身构图带歪）。

## 四、怎么验证

```bash
# Python（桩掉 folder_paths / server 后 importlib 加载插件）
python -m unittest discover -s tests
# 前端
node --test tests/test_preview.mjs      # 或项目既有的跑法
```

真机验证套路（比出图快，省显存）：

1. 本机 ComfyUI 常驻 `127.0.0.1:8188`；
2. 起一个**自己专属**的 headless Chrome：`chrome --headless=new --remote-debugging-port=9333 --user-data-dir=<临时目录>`；
3. CDP `Runtime.evaluate`：`await app.loadGraphData(JSON)` → 查 `LiteGraph.registered_node_types`、`app.graph._nodes` 的 `mode`、`await app.graphToPrompt()`（**看静音组是否真的没进队列**）；
4. 需要看图再 `POST /prompt` 提交 `graphToPrompt()` 的 output，轮询 `/history/<id>`，用 `/view?filename=` 取图；单张约 4–6 分钟。

⚠️ 收尾只关自己启的那个 Chrome（按 task 停），**不要按进程名 kill 全部 chrome.exe**——会关掉用户的窗口。之前的会话干过一次，已致歉。

## 五、发版流程

> **铁律（2026-11-16 起）：改完不自动推送。** 本地改完只做同步与本地 commit，`git push` 必须等老大明确说「推送」。
>
> **版本号两档**：本地调整 / 优化 / 修小 bug → 只递增 **patch**（1.9.0 → 1.9.1 → 1.9.2 …）；老大要求推送时 → 先提到**下一个 minor**再推（本地 1.7.11 → 推送 1.8.0；本地 1.9.1 → 推送 1.10.0）。

1. 改 `pyproject.toml` 版本 + `README.md` 版本行 + `更新日志.md` 新条目（只写使用者能感知的变化）+ 本文件台账；
2. 同步到 `D:/AI/comfyui-ref-lookbook`，`git add` **只写明确路径**（禁止 `git add -A`）；
3. **不推**：`更新日志.md`、`CHANGELOG.md`（已在 `.git/info/exclude`）；
4. **推送前**：确认老大已明确同意，并把版本提到下一个 minor；
5. 推送要带代理：`git -c http.proxy=http://127.0.0.1:7897 push origin main`（端口会变，推不动先 `netstat -ano | grep LISTENING | grep 127.0.0.1`）；
6. 仓库 README 与 `更新日志.md` 是两份：README 是对外主页，`更新日志.md` 只留本地。

---

## 六、变更台账

> 新记录加在最上面。格式：**改了什么 / 涉及文件 / 原因 / 影响范围**。

### 2026-11-16 · v1.9.1 · README 精简 + 推送与版本号新规

- **改了什么**：
  - `README.md` 从 297 行压到 224 行。删掉「澪设计档案（独立页面）」整节（内容并入图库一览的条目与用法第 8 条）、验证章节里逐条罗列测试名的长段落、图片取用逻辑的重复描述、`bulk.py` 相关痕迹；目录树由六行库目录合并成一行花括号写法。
  - 新增维护规则（本文件「五、发版流程」与项目长期记忆）：**改完绝不自动推送**，`git push` 必须等老大明确确认；**本地调整只递增 patch**（1.9.0 → 1.9.1 …），**要求推送时才提到下一个 minor**（本地 1.9.1 → 推送 1.10.0）。
  - 顺带校正本文件里的过期数字：`__init__.py` 784 → 826 行、`web/ref_gallery.js` 899 → 976 行、测试 131+17 → 136+22。
- **涉及文件**：`README.md`、`pyproject.toml`（1.9.0 → 1.9.1）、`更新日志.md`（本地）、`HANDOVER.md`（开发目录 + 分发仓两份）。
- **原因**：老大要求精简 README（删重复与不必要的说明），并把「不自动推送、本地只进 patch」定为硬性流程。
- **影响范围**：
  - **纯文档，零功能改动。** 所有节点、工作流、后端代码未动，出图结果不受影响。
  - 不需要重启 ComfyUI，不需要刷新页面，老工作流不用重拖。
  - **远端没变**：本次只在本地提交与同步，没有 `git push`。下次推送时版本要先提到 1.10.0。

### 2026-11-16 · 示例工作流说明精简（纯文档，无功能变更）

- **改了什么**：把 `ref_gallery_qwen21.json` 内 id=100 的 MarkdownNote 从 2174 字压到 1238 字。删除开关原理、发型库背景、提示词整段模板、深度模式详解、缓存机制、重复的 LoRA 路径论证；保留两种用法、四图顺序、上手三步、照片换脸、必要前提、核心参数、输出目录。标题改「使用说明 · 快速上手」，节点高度 900 → 650。
- **涉及文件**：开发目录与分发仓的 `example_workflows/ref_gallery_qwen21.json`、`HANDOVER.md`（两份）。配套详细版 `example_workflows/ref_gallery_qwen21.md` 未动。
- **原因**：用户要求精简工作流中的使用说明，删除冗余、重复、背景铺垫和无关描述，只留快速上手所需的内容。
- **影响范围**：
  - **只改画布内的说明文字**，节点、连线、控件、参数、输出路径一律没动；15 项工作流测试全过，老工作流与出图结果完全不受影响。
  - 不需要重启 ComfyUI。说明随 json 存盘，**已拖进画布的旧工作流要重新拖一次新 json** 才会看到精简版；新建画布直接生效。
  - 深度模式的说明从画布移除，但功能本身仍在配方节点里（`use_depth`），需要时看配套 `.md` 文档。

### 2026-11-16 · v1.9.0 · 服装 / 姿势节点接上澪图库（修「选了没反应」）

- **改了什么**
  1. 后端新增 `MIO_ID` 正则与 `_library_for_id()`：编号是 `H-/C-/P-\d\d-\d\d` 时读 `mio` 库。`_GalleryNode` 加类属性 `MIO_KINDS`（默认空），`CostumeGallery` 设 `('C',)`、`PoseGallery` 设 `('P',)`；`_library_for` 统一走它，`_load` / `_relative` / `VALIDATE_INPUTS` / `IS_CHANGED` 自动一致。
  2. `CharacterRecipe` 新增 `_costume_target()` / `_pose_target()`，`build_recipe` / `VALIDATE_INPUTS` / `IS_CHANGED` 三处共用：服装 `C-` 编号优先于 `costume_library` 下拉；姿势 `P-` 编号直接读澪库，且**不**做 `POS-`→`DEP-` 换算（澪库没有深度版）。
  3. 前端加 `libraryOf()` / `canTake()` / `refuseText()`：单库节点的 `currentLibrary()` 按编号推断库（发型节点仍由来源下拉决定），预览 URL 跟着切库；`onSelect` 改为「收下 / 明确拒绝」两条路，拒绝时 `return false`，弹窗不关并弹红条说明原因。
  4. 弹窗加 toast 提示层（`notice()`）：原本选错就静默关闭，用户完全不知道发生了什么。
  5. 配置层：`CostumeGallery` / `PoseGallery` / 配方服装槽与姿势槽加 `mioKinds`，前两者加 `openFor.mio`（`#s-cloth` / `#s-pose`），编号已是澪库时再点浏览直接落到对应系列。
  6. 文档与版本：README 用法第 2 / 8 条、测试计数与版本行，更新日志 v1.9.0，`pyproject.toml` → 1.9.0。
- **涉及文件**：`__init__.py`、`web/ref_gallery.js`、`tests/test_nodes.py`、`tests/test_preview.mjs`、`README.md`、`更新日志.md`、`pyproject.toml`、`HANDOVER.md`（本文件）。
- **原因**：用户反馈「服装和姿势节点我选择澪图库里面的没有反应」。真实前端复现确认：弹窗顶部切到澪图库、选中 `C-01-01` → 弹窗关闭但 `costume_id` 仍是 `SPR-0001`。根因是 `onSelect` 里 `data.library !== config.library → return` 静默丢弃，而后端 `item('costume', 'C-01-01')` 本来就会报「未知服装 ID」——前后端两边都没有跨库的概念。
- **影响范围**：
  - **纯前端行为变化 + 后端节点内部逻辑，老工作流不用重拖**；`MIO_KINDS` / `_library_for_id` 只影响「编号属于澪库」这一种情况，原有编号走原路，出图结果不变。
  - **升级后只刷新页面（F5）就能用浏览与回填**；但要让后端真正按澪库出图，**仍需重启 ComfyUI**（`__init__.py` 改了）。这一点容易搞混：前端先好用、后端还在报错。
  - 深度姿势节点与服装动画节点**故意不接**澪库（前者会把普通姿势当深度图，后者画风不同）；以后要给它们开口，改 `MIO_KINDS` 即可，但要想清楚语义。
  - 配方节点里 `use_depth` 对 `P-` 编号失效（澪库无深度版），这是预期行为，已在提示与文档里写明。

### 2026-11-16 · v1.8.0 · 发型替换修复 + 提示词改中文

- **改了什么**
  1. 新增 `PromptJoin`（提示词拼接）节点：`text` 静态模板 + `extra`/`extra2` 两路 `forceInput` 动态文字，空行自动跳过，输出拼好的 `STRING`。
  2. `HairGallery` 新增第 8 路输出 `hair_detail`：澪设计取索引「描述」（只讲头发），二次元取关键词。
  3. `CharacterRecipe.build_recipe` 中文提示词重写：四张图分工写在最前，发型段强调「只认图4、图2 的头发一律不要、白色人台不要画进来」，发型细节改用「描述」；英文提示词补 `replace the hair seen in image 2 completely`。
  4. 示例工作流：① 链路加 `PromptJoin`（模板 + `hair_detail` → 编码器 `prompt`），编码器提示词整段换成中文并留同一份模板做兜底；节点数 22 → 23，① 组 9 → 10。
  5. 测试 +5（131 Python / 17 前端全过），README、使用指南、更新日志同步。
- **涉及文件**：`__init__.py`、`example_workflows/ref_gallery_qwen21.json`、`example_workflows/ref_gallery_qwen21.md`、`README.md`、`更新日志.md`、`pyproject.toml`、`tests/test_nodes.py`、`tests/test_workflows.py`、`HANDOVER.md`（本文件）。
- **原因**：用户反馈「选了发型，出图还是脸参考自带的头发」。实测确认：短发能生效，长发选长发会被图 2 盖掉；提示词里没有任何一句描述所选发型的具体形状。
- **影响范围**：
  - 用旧工作流的用户**不受影响**（`hair_detail` 追加在末尾，`PromptJoin` 是新节点）；
  - 示例工作流节点数变了，`SwitchTests` 的 ① 组计数由 9 改 10；
  - **升级后要重启 ComfyUI**（新后端节点），再重新拖 json；只刷新页面会提示缺少 `PromptJoin`；
  - `CharacterRecipe` 的 `prompt_zh` 文案变了，接 `prompt_zh` 的老用户出图文字会跟着变（预期内）。

### 2026-11-16 · v1.7.1 · 示例工作流加「选一组跑」开关

- **改了什么**：新增纯前端节点 `ref_lookbook/WorkflowSwitch`，按组把另一条链整组静音（`mode=2`）；json 里把 ② 组预设静音；组框读取兼容 `_bounding`/`bounding`/`pos+size`。
- **涉及文件**：`web/ref_gallery.js`、`example_workflows/ref_gallery_qwen21.json`、`README.md`、`更新日志.md`、`tests/test_preview.mjs`、`tests/test_workflows.py`。
- **原因**：两条链合并成一份 json 后，点一次运行两条都跑，白等一半时间。
- **影响范围**：只影响示例工作流与前端；旧 json 打开会当成缺节点（`ref_lookbook/WorkflowSwitch`），需要刷新页面（`no-store`，普通 F5 即可）。

### 2026-11-16 · v1.7.0 · 发型节点 + 三合一扩四合一 + 两份工作流并成一份

- **改了什么**：新增 `HairGallery`（澪设计 54 件 / 二次元 230 条，`hair_source` 切来源，编号不匹配自动回落）；`CharacterRecipe` 加发型槽位与 `hair_image`（追加末尾）、拼图三张 → 四张、提示词加【发型】；`ref_gallery_combo_qwen21.json` 与 `ref_recipe_qwen21.json` 合并为 `ref_gallery_qwen21.json`；去掉了 rgthree 的 `Fast Muter` 依赖。
- **涉及文件**：`__init__.py`、`web/ref_gallery.js`、`web/gallery.mjs`、`example_workflows/*`、`README.md`、`更新日志.md`、`tests/*`。
- **原因**：用户要求「新增发型选择节点，三合一里也加发型，工作流合并成一份」。
- **影响范围**：旧工作流仍能打开（新控件在 `optional`）；配方输出多了 `hair_image`，接在末尾不影响旧连线；旧的两份 json 不再发行。

### 2026-11-16 · v1.6.5 · 澪库详情去掉重复的原推链接

- **改了什么**：详情弹窗底部「查看作者原推」按钮与元信息里的 x.com 链接删掉，只留顶栏右上角作者主页跳转。
- **涉及文件**：`web/mio.mjs`。
- **原因**：用户要求「查看作者原推和推的链接都删掉，有右上角的跳转就行了」。
- **影响范围**：只影响澪设计档案页的详情弹窗，无数据结构变化。
