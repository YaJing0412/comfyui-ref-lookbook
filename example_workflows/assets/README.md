# 效果图清单

本目录是 `ref_gallery_combo_qwen21.json` 的实跑素材，文档按固定路径引用。换图时保持文件名不变，引用处无需改。

`compare/` 与 `results/` 是工作流输出；`ui/` 是 ComfyUI 界面截图。JPEG 质量 88–92，长边 ≤1600 px，合计约 1.8 MB。

## 目录

| 路径 | 内容 |
| --- | --- |
| `ui/gallery-window.jpg` | 图库弹窗：三个页签、分类筛选、卡片网格（1,407 套服装） |
| `ui/load-image-button.jpg` | 原生「加载图像」节点上的「从参考图库导入 · 服装 / 姿势 / 脸部」按钮 |
| `ui/workflow-overview.jpg` | 完整画布：三路图库 → 提示词 → 采样 → 成图 / 对比图两路输出 |
| `compare/pose-navy-lace-arm-up.jpg` | 线稿人偶（举臂）→ 深蓝蕾丝 |
| `compare/pose-navy-lace-hands-on-hips.jpg` | 线稿人偶（叉腰）→ 深蓝蕾丝 |
| `compare/pose-mint-cat.jpg` | 线稿人偶（蹲坐）→ 薄荷绿猫耳 |
| `compare/face-red-kimono.jpg` | 脸部特写（短发粉挑染）→ 白红巫女装 |
| `compare/photo-white-cat.jpg` | 自上传照片 → 白粉猫装 |
| `results/star-magician.jpg` | 星空魔术师 |
| `results/navy-lace-arm-up.jpg` | 深蓝蕾丝 · 举臂 |
| `results/navy-lace-hands-on-hips.jpg` | 深蓝蕾丝 · 叉腰 |
| `results/mint-cat.jpg` | 薄荷绿猫耳 |
| `results/white-cat.jpg` | 白粉猫装 |
| `results/red-kimono.jpg` | 白红巫女装 |

`compare/` 是参考图 + 成图左右拼接（工作流 `ImageStitch` 直出），`results/` 是同批成图单张。

## 替换规范

- 格式 JPEG，质量 88 以上；要用 PNG 就把两处文档里的扩展名一起改掉。
- 长边不超过 1600 px（对比图与成图 1400 以内），单张 250 KB 以内，仓库体积敏感。
- 换素材组合可以，但要同步改本表与 `ref_gallery_combo_qwen21.md` 的说明文字，保证描述与图对得上。
