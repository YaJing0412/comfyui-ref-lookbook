# 图库目录

本目录随仓库发行的是**中文索引与分类数据**（`data/`，约 1.7 MB）与**内置缩略图**（`<库>/thumbs/`，4,344 张 WebP，约 13 MB，重打包自 ai-ref-library-cn，离线开箱可浏览）：

| 库 | 记录 | 索引 | 缩略图（内置） | 原图 / 预览（运行时缓存） |
| --- | --- | --- | --- | --- |
| 服装 | 1,407 套 | `data/costume-zh.json` | `costume/thumbs/` | `costume/{png,img}/` |
| 姿势 | 288 个动作 / 1,439 张 | `data/pose-zh.json` | `pose/thumbs/` | `pose/{png,img}/` |
| 脸部 | 1,498 张 | `data/face-zh.json` | `face/thumbs/` | `face/{png,img}/` |

三个库目录结构完全一致：`library/<库>/{thumbs,png,img}/`，没有哪个库平铺在 `library/` 根下。

合计 3,193 条记录、4,344 张参考图。

## 图片怎么来

缩略图已随仓库内置，不需要联网。原图（png）不随仓库分发，节点与图库页面取原图时按这个顺序（实现见 `catalog.ensure_original`）：

1. 本机 `library/<库>/png/<文件名>` 有 → 直接读，不联网。
2. 没有 → 向作者站点取一次，缓存到同一路径，之后离线可用。
3. 断网或取失败 → 报错并给出该图的地址与应放位置。

原图由「浏览大图」和「节点出图」共用：任一处取过，另一处直接命中本地。
所以**看过的图就已经存在本机了，不会重复下载**；删掉 `png/` 目录只会让下次用到时再取一次。个别内置缩略图若缺失，同样按单张从源站取一次并缓存。

| 库 | 原图地址 |
| --- | --- |
| 服装 | `https://ai-costume-gallery.pages.dev/png/<名>.png` |
| 姿势 | `https://ai-pose-gallery.pages.dev/img/<名>.png` |
| 脸部 | `https://ai-portrait-gallery.pages.dev/img/full/<名>.png` |

想完全离线：按索引里的文件名把原图放进上面三个目录（「原图」字段就是相对路径），再设 `COMFYUI_REF_LOOKBOOK_OFFLINE=1`。

## 授权

服装与姿势库的上游授权**禁止再分发图片本体（含加工版）**，也禁止批量自动抓取；脸部库为 CC0。原图与全尺寸预览（`png/`、`img/`）在 `.gitignore` 里，只能本机生成。内置缩略图重打包自 ai-ref-library-cn 的内嵌缩略图，属超出上游明示授权的已知取舍，详见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)；上游版本与数量见 [SOURCE.json](SOURCE.json)。

姿势与脸部索引整理自参考项目 ai-ref-library-cn 的元数据，并按本地素材校正。
