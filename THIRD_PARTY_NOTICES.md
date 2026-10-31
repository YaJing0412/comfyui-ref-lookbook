# 第三方内容、版权与致谢

## 素材来源

四套素材来自原作者公开的 AI 作图参考图库；中文分类、动作描述、编号与内置缩略图，取自上游仓库 [sleepy-zone/ai-ref-library-cn](https://github.com/sleepy-zone/ai-ref-library-cn) 与深度姿势站的源仓库 [Brilliant666/ai-image-gallery](https://github.com/Brilliant666/ai-image-gallery)。

| 库 | 原始站点 | 记录 | 授权原文要点 | 能否再分发图片 |
| --- | --- | --- | --- | --- |
| 服装 | [衣装集 COSTUME-DB-01](https://ai-costume-gallery.pages.dev/) | 1,407 套 | 無償で利用できます（作品制作での商用利用・編集・参考利用OK）。画像データそのもの（元サイズ・加工後を含む）の再配布・転載・再販は禁止。一括ダウンロード（ツール等による自動取得を含む）も禁止。生成の参考に1枚ずつ使う分は可。 | ❌ 禁止（含加工版） |
| 姿势 | [姿勢集 POSE-DB-01](https://ai-pose-gallery.pages.dev/) | 288 动作 / 1,439 张 | 同上 | ❌ 禁止（含加工版） |
| 脸部 | [AIモデル顔データベース](https://ai-portrait-gallery.pages.dev/) | 1,498 张 | CC0で自由に配布 | ✅ 可以（原图仍不分发） |
| 深度姿势 | [デプスポーズ集 POSE-DB-02](https://ai-pose-depth-gallery.pages.dev/) | 288 动作 / 1,439 张 | 同上（与姿势集同作者、同条款） | ❌ 禁止（含加工版） |

四个库全部为 AI 生成内容，不含真实人物。数据快照：服装 2026-10-29，姿势与脸部 2026-10-30，深度 2026-10-31。

原作者：服装、姿势、深度姿势三站均为 ギア（[@giaaibusi](https://x.com/giaaibusi)），脸部站标注运营者为 あぎ（[@agi_aibusi](https://x.com/agi_aibusi)）。感谢两位把素材公开出来。本项目保留原始 ID、日文 / 英文关键词与素材路径，另附中文翻译供检索；本项目是独立的本地图库实践，不代表原作者的官方版本或背书。

## 数据来源

姿势与脸部的中文标签、动作清单、发型分类，以及服装 / 姿势 / 脸部三库的内置缩略图，来自第三方仓库 [sleepy-zone/ai-ref-library-cn](https://github.com/sleepy-zone/ai-ref-library-cn)（AI 作图素材库中文版，收录脸 / 姿势 / 服装三库）；服装库的中文索引另取自 [ai-costume-gallery-zh](https://github.com/wangweihong/ai-costume-gallery-zh)。

深度姿势库不在上述仓库里：它的条目与文件名由本项目的姿势库索引派生（`POS-` → `DEP-`、`pose/` → `depth/`），再按 [Brilliant666/ai-image-gallery](https://github.com/Brilliant666/ai-image-gallery) 的 `sites/pose-depth/manifest.json` 逐条校对，缩略图从深度站取回。使用方式是先把这些素材与仓库取到本机、再离线整理，不是当作代码参考，也没有复制它们的界面代码。

上游的中文检索仓库同样只收录缩略图、不含原图，自带中文译文与「随机组合」提示词功能；仓库未附开源许可，因此本项目**不主张**对其代码或数据的任何权利，中文标签与缩略图的版权仍归上游作者。前三个库的缩略图是原样取用、未再加工；深度库则是把深度站的 360 px 缩略图统一转码成 WebP，画面内容同样未改。个别库的条目数量差异（如脸部 1,499 → 1,498）来自本地原图核对，与上游索引无关。

## 本仓库分发边界

**原图不分发。** `library/` 里的 `png/`、`img/` 全部列入 `.gitignore`，原图只能由使用者本机在运行时获取或自行放入。

**缩略图随仓库内置**（`library/<库>/thumbs/`，5,783 张 WebP，约 18 MB）：为离线浏览，服装 / 姿势 / 脸部三库原样取自 `ai-ref-library-cn` 的内嵌缩略图（200×250），深度库取自深度站缩略图并统一转码为 360 px WebP，画面内容均未改动。需要明确：上表「画像データそのもの（元サイズ・加工後を含む）の再配布は禁止」按字面同样涵盖缩略图，内置缩略图**超出了上游明示的授权范围**，这是本项目的已知取舍；作为对冲，取图链路保留「按单张从源站取一次并缓存」的完整回退，权利人提出异议时会把缩略图移出仓库，功能不受影响。

程序不做全库预取或批量导出：原图只在节点真正出图或看大图时按单张请求。这与「用工具把数据库一次性抓下来」是两件事，后者被上游明确禁止，本项目不提供该能力。

## 许可范围

| 内容 | 路径 | 说明 |
| --- | --- | --- |
| 本项目程序代码与工作流 | `__init__.py`、`catalog.py`、`web/`、`tests/`、`example_workflows/*.json`、`example_workflows/*.md` | MIT，见 [LICENSE](LICENSE) |
| 中文索引与译文 | `library/data/`、`library/SOURCE.json` | 基于源站元数据及其译文；不因汉化而获得素材授权，不适用 MIT |
| 内置缩略图 | `library/<库>/thumbs/` | 前三库取自 [ai-ref-library-cn](https://github.com/sleepy-zone/ai-ref-library-cn) 的内嵌缩略图，深度库取自深度站缩略图；图片版权归上游作者，不适用 MIT，权利人可要求移除 |
| 示例效果图 | `example_workflows/assets/` | 本项目工作流实跑输出，随代码以 MIT 发布 |
| 上游参考项目许可原文 | `licenses/` | 原样保留，未修改 |

公开可访问不等于放弃权利或不限用途授权。本项目不对第三方素材主张权利，也不提供使用、再分发或商业利用这些素材的额外授权。翻译不能替代原作者的使用条款，商用前请自行核对。

## 参考项目致谢

- [ai-costume-gallery-zh](https://github.com/wangweihong/ai-costume-gallery-zh)：服装库界面结构、分类与中文索引思路。
- [comfyui-pose-gallery](https://github.com/wangweihong/comfyui-pose-gallery)：节点预览与弹窗桥接方式。
- [ai-pose-gallery-zh](https://github.com/anhao/ai-pose-gallery-zh)：姿势素材汉化与分类口径。

界面与脚本由本项目独立编写，未复制参考项目代码。参考关系不意味着上述维护者为本项目或素材使用提供背书或授权。数据来源 `ai-ref-library-cn` 见上文「数据来源」一节。

## 权利联系

权利人如对收录内容有异议，请通过本项目 Issue 提供素材 ID、涉及路径与说明，维护者会核实并删除或调整。联系入口见 README 末尾。
