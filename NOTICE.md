# 来源与致谢

## 代码与界面参考

| 项目 | 用途 | 许可 |
| --- | --- | --- |
| [wangweihong/ai-costume-gallery-zh](https://github.com/wangweihong/ai-costume-gallery-zh) | 服装库界面结构、分类与中文索引思路 | MIT，原文见 [licenses/ai-costume-gallery-zh-LICENSE.md](licenses/ai-costume-gallery-zh-LICENSE.md)（Deeyu） |
| [wangweihong/comfyui-pose-gallery](https://github.com/wangweihong/comfyui-pose-gallery) | ComfyUI 节点预览与弹窗桥接方式 | MIT，原文见 [licenses/comfyui-pose-gallery-LICENSE.md](licenses/comfyui-pose-gallery-LICENSE.md)（Anhao） |
| [anhao/ai-pose-gallery-zh](https://github.com/anhao/ai-pose-gallery-zh) | 姿势素材汉化与分类口径；三合一配方节点的思路（三库同取 + 横向拼图 + 中英文提示词组装） | 参考思路，未复制代码 |

本仓库的界面与脚本为独立编写，未复制上述项目代码；参考关系不代表上述作者为本项目背书。

## 素材来源

六套素材均由原作者公开。**原图不分发**；姿势、脸部的中文标签与动作清单、服装 / 姿势 / 脸部三库的内置缩略图取自上游仓库 [sleepy-zone/ai-ref-library-cn](https://github.com/sleepy-zone/ai-ref-library-cn)（提前完整下载后离线整理，不是代码参考）；深度姿势库的索引由姿势库派生、按 [ai-image-gallery](https://github.com/Brilliant666/ai-image-gallery) 的 manifest 校对，缩略图取自深度站；二次元库与服装动画库的中文索引与分类取自 [Deeyu/ai-costume-gallery-zh](https://github.com/Deeyu/ai-costume-gallery-zh) 的 anime / costume-anime 索引，缩略图分别取自 CharaDB 与动画服装站：

| 库 | 源站 | 作者 | 授权 |
| --- | --- | --- | --- |
| 服装 | [衣装集 COSTUME-DB-01](https://ai-costume-gallery.pages.dev/) | ギア [@giaaibusi](https://x.com/giaaibusi) | 可商用 / 可编辑 / 可参考；禁止再分发图片本体；禁止批量自动抓取 |
| 服装动画 | [衣装集 アニメ版 COSTUME-ANIME-DB](https://ai-costume-anime-gallery.pages.dev/) | ギア [@giaaibusi](https://x.com/giaaibusi) | 可商用 / 可编辑 / 可参考；禁止再分发、转载、转售图片本体；禁止批量获取；不得用于表现真实人物或未成年人 |
| 姿势 | [姿勢集 POSE-DB-01](https://ai-pose-gallery.pages.dev/) | ギア [@giaaibusi](https://x.com/giaaibusi) | 同上 |
| 脸部 | [AIモデル顔データベース](https://ai-portrait-gallery.pages.dev/) | あぎ [@agi_aibusi](https://x.com/agi_aibusi) | CC0 |
| 深度姿势 | [デプスポーズ集 POSE-DB-02](https://ai-pose-depth-gallery.pages.dev/) | ギア [@giaaibusi](https://x.com/giaaibusi) | 与姿势集同条款：可参考使用，禁止再分发图片本体 |
| 二次元 | [キャラ組み立てDB CharaDB](https://charadb-2fi.pages.dev/) | たき AI [@taki_auto](https://x.com/taki_auto) | 参考使用；禁止再分发、转载、转售图片本体 |

原图只在运行时由使用者自己的机器向源站按单张取，取回即落盘 `library/<库>/png/`，缓存留在本机；`library/` 里随仓库发行的是中文索引、分类数据与内置缩略图。授权细节、许可范围与删除请求方式见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，素材版本与地址模板见 [library/SOURCE.json](library/SOURCE.json)。
