# 来源与致谢

## 代码与界面参考

| 项目 | 用途 | 许可 |
| --- | --- | --- |
| [wangweihong/ai-costume-gallery-zh](https://github.com/wangweihong/ai-costume-gallery-zh) | 服装库界面结构、分类与中文索引思路 | MIT，原文见 [licenses/ai-costume-gallery-zh-LICENSE.md](licenses/ai-costume-gallery-zh-LICENSE.md)（Deeyu） |
| [wangweihong/comfyui-pose-gallery](https://github.com/wangweihong/comfyui-pose-gallery) | ComfyUI 节点预览与弹窗桥接方式 | MIT，原文见 [licenses/comfyui-pose-gallery-LICENSE.md](licenses/comfyui-pose-gallery-LICENSE.md)（Anhao） |
| [anhao/ai-pose-gallery-zh](https://github.com/anhao/ai-pose-gallery-zh) | 姿势素材汉化与分类口径 | 参考思路，未复制代码 |
| `ai-ref-library-cn`（本地参考项目） | 姿势动作清单、脸部发型分类与中文标签（`pose.js` / `face.js`） | 参考数据整理，不随本仓库分发 |

本仓库的界面与脚本为独立编写，未复制上述项目代码；参考关系不代表上述作者为本项目背书。

## 素材来源

三套素材均由原作者公开。**原图不分发**；缩略图随仓库内置，重打包自参考项目 `ai-ref-library-cn` 的内嵌缩略图：

| 库 | 源站 | 作者 | 授权 |
| --- | --- | --- | --- |
| 服装 | [衣装集 COSTUME-DB-01](https://ai-costume-gallery.pages.dev/) | ギア [@giaaibusi](https://x.com/giaaibusi) | 可商用 / 可编辑 / 可参考；禁止再分发图片本体；禁止批量自动抓取 |
| 姿势 | [姿勢集 POSE-DB-01](https://ai-pose-gallery.pages.dev/) | ギア [@giaaibusi](https://x.com/giaaibusi) | 同上 |
| 脸部 | [AIモデル顔データベース](https://ai-portrait-gallery.pages.dev/) | あぎ [@agi_aibusi](https://x.com/agi_aibusi) | CC0 |

原图只在运行时由使用者自己的机器向源站按单张取，取回即落盘 `library/<库>/png/`，缓存留在本机；`library/` 里随仓库发行的是中文索引、分类数据与内置缩略图。授权细节、许可范围与删除请求方式见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，素材版本与地址模板见 [library/SOURCE.json](library/SOURCE.json)。
