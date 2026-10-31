# 图库目录

本目录随仓库发行的是**中文索引与分类数据**（`data/`，约 2.1 MB）与**内置缩略图**（`<库>/thumbs/`，5,783 张 WebP，约 18 MB；前三库原样取自 [ai-ref-library-cn](https://github.com/sleepy-zone/ai-ref-library-cn)，深度库取自深度站并转 360 px WebP，离线开箱可浏览）：

| 库 | 记录 | 索引 | 缩略图（内置） | 原图 / 预览（运行时缓存） |
| --- | --- | --- | --- | --- |
| 服装 | 1,407 套 | `data/costume-zh.json` | `costume/thumbs/` | `costume/{png,img}/` |
| 姿势 | 288 个动作 / 1,439 张 | `data/pose-zh.json` | `pose/thumbs/` | `pose/{png,img}/` |
| 脸部 | 1,498 张 | `data/face-zh.json` | `face/thumbs/` | `face/{png,img}/` |
| 深度姿势 | 288 个动作 / 1,439 张 | `data/depth-zh.json` | `depth/thumbs/` | `depth/{png,img}/` |

四个库目录结构完全一致：`library/<库>/{thumbs,png,img}/`，没有哪个库平铺在 `library/` 根下。

合计 3,481 条记录、5,783 张参考图。深度姿势库与姿势库是同一批 288 个动作、同样 1,439 个文件名，内容换成灰度深度图。

## 图片怎么来

缩略图已随仓库内置，不需要联网。原图（png）与全尺寸预览（img）不随仓库分发，节点与图库页面取原图时按这个顺序（实现见 `catalog.ensure_original`）：

1. 本机 `library/<库>/png/<文件名>` 有 → 直接读，不联网。
2. 没有 → 向作者站点取一次，缓存到同一路径，之后离线可用。
3. 断网或取失败 → 报错并给出该图的地址与应放位置。

原图由「浏览大图」和「节点出图」共用：任一处取过，另一处直接命中本地。
所以**看过的图就已经存在本机了，不会重复下载**；删掉 `png/` 目录只会让下次用到时再取一次。个别内置缩略图若缺失，同样按单张从源站取一次并缓存。

想一次攒够整个库的原图，用图库页右上角「下载全部原图」：先给预估（缺几张、约占多少空间、磁盘剩余），确认后后台下载，可随时停止，再点一次是续传。实现见 `bulk.py`。

| 库 | 原图地址 |
| --- | --- |
| 服装 | `https://ai-costume-gallery.pages.dev/png/<名>.png` |
| 姿势 | `https://ai-pose-gallery.pages.dev/img/<名>.png` |
| 脸部 | `https://ai-portrait-gallery.pages.dev/img/full/<名>.png` |
| 深度姿势 | `https://ai-pose-depth-gallery.pages.dev/img/<名>.png` |

想完全离线：按索引里的文件名把原图放进四个库各自的 `png/`（「原图」字段就是相对路径），再设 `COMFYUI_REF_LOOKBOOK_OFFLINE=1`。

## 授权

服装、姿势、深度姿势三库的上游授权**禁止再分发图片本体（含加工版）**，也禁止批量自动抓取；脸部库为 CC0。原图与全尺寸预览（`png/`、`img/`）在 `.gitignore` 里，只能本机生成。内置缩略图：前三库原样取自上游仓库 [ai-ref-library-cn](https://github.com/sleepy-zone/ai-ref-library-cn) 的内嵌缩略图，深度库取自深度站缩略图，属超出上游明示授权的已知取舍，详见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)；上游版本与数量见 [SOURCE.json](SOURCE.json)。

姿势与脸部索引取自上游仓库 ai-ref-library-cn 的元数据（`pose.js` / `face.js`），深度姿势索引由姿势索引派生、按深度站 manifest 校对，三者都按本地素材校正。
