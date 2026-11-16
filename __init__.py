"""ComfyUI reference gallery: 服装 / 服装动画 / 姿势 / 脸部 / 深度姿势 / 二次元，
外加独立的霧島澪设计档案（带作者原版提示词）。随仓库发行索引与内置缩略图，原图按需向作者站点取一次。
"""
import asyncio
import re
import shutil
from pathlib import Path

import folder_paths
import numpy as np
import torch
from PIL import Image, ImageOps
from aiohttp import web
from server import PromptServer
from .catalog import (ANGLES, LIBRARIES, OFFLINE_ENV, ROOT, VARIANTS, asset, asset_by_id, describe, ensure_original,
                      item, local_path, meta, missing_originals, offline, pick, records, site, variant_values)
from . import bulk

# 尺寸处理：默认出原图，接 ControlNet 或跟其他素材拼图时再统一到目标尺寸。
RESIZE_MODES = ('原图尺寸', '指定尺寸（居中裁剪）', '指定尺寸（留白填充）')
RESIZE_TOOLTIP = '原图尺寸最清晰；要跟别的素材对齐（拼图、ControlNet）再用指定尺寸。'
# 拼图底色与留白填充色：纯白，跟服装 / 姿势原图的透明底合成色一致，避免出现两块不同底色。
PANEL_BG = (255, 255, 255)
STYLE_PRESETS = {
    '高清日系动漫': ('日系二次元插画，赛璐璐与厚涂结合，光影通透，高画质',
                'anime illustration, cel shading, soft lighting, clean lineart, masterpiece'),
    '写实摄影人像': ('电影级写实人像摄影，85mm 定焦，真实肤质，自然景深',
                'photorealistic portrait, 85mm lens, realistic skin texture, cinematic lighting'),
    '韩系半厚涂': ('韩系唯美半厚涂立绘，细腻高光，柔美体积感',
               'semi-realistic anime character art, smooth rendering, luminous highlights'),
    '干净角色设定图': ('游戏角色设定图，干净纯白背景，轮廓清晰，服装褶皱细节丰富',
                'character design reference sheet, clean white background, crisp silhouette, fabric folds'),
}


def _pil_resampling():
    """PIL 9.1 起 LANCZOS 挪进 Image.Resampling，旧版还在顶层。"""
    return getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', 1)


def _fit_image(img, mode, width, height):
    """按 resize_mode 统一尺寸：原样返回 / 居中裁剪 / 留白填充。"""
    if mode == '指定尺寸（居中裁剪）':
        return ImageOps.fit(img, (int(width), int(height)), method=_pil_resampling())
    if mode == '指定尺寸（留白填充）':
        return ImageOps.pad(img, (int(width), int(height)), method=_pil_resampling(), color=PANEL_BG)
    return img


def _load_rgb(library, row, variant=None, resize_mode='原图尺寸', width=1024, height=1280, flip=False):
    """读一张原图（缺则取一次并缓存），去 EXIF、透明底合成白、可选翻转与缩放，返回 RGB。"""
    path = ensure_original(library, pick(row, '原图', variant))
    with Image.open(path) as source:
        img = ImageOps.exif_transpose(source).convert('RGBA')
        img = Image.alpha_composite(Image.new('RGBA', img.size, 'white'), img).convert('RGB')
    if flip:
        img = ImageOps.mirror(img)
    return _fit_image(img, resize_mode, width, height)


def _to_tensor(img):
    return torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0).unsqueeze(0)


def _describe_zh(row, limit=8):
    """分类 / 二级分类：中文关键词。配方节点拼 prompt 用。"""
    head = ' / '.join(part for part in (row.get('分类'), row.get('分类2')) if part)
    words = '、'.join((row.get('关键词') or [])[:limit])
    return f'{head}：{words}' if words else head


def _describe_en(row):
    """只认真正的英文词条。脸部与姿势索引里没有英文，宁可在 prompt 里省略，
    也别把日文塞进英文 prompt——模型对日文的理解远不如英文。"""
    return row.get('英文关键词') or ''


# 澪设计档案的编号形态：H-01-01 发型 / C-01-01 服装 / P-01-01 姿势。
# 写实库的编号完全不同（SPR-0001、POS-SEXY-P001、FACE-0001、DEP-SEXY-P001、ANE-H001），
# 所以靠编号前缀就能判断该去哪本索引里找，不会跟 POS- 撞上。
MIO_ID = re.compile(r'^([HCP])-\d{2}-\d{2}$')


def _library_for_id(default, item_id, kinds):
    """编号属于澪设计档案（且该节点接受这一类）就去澪库，否则留在默认库。

    服装与姿势节点原本只能读写实库，而弹窗顶部可以切到「澪图库」——选完被静默丢掉，
    用户看到的就是「选了没反应」。按编号认库，选什么就出什么。
    """
    match = MIO_ID.match(str(item_id or ''))
    if match and match.group(1) in kinds:
        return 'mio'
    return default


class _GalleryNode:
    """六个图库共用同一套加载逻辑，差异只在索引、控件名、返回值命名与形态维度。"""

    LIBRARY = 'costume'
    ID_WIDGET = 'costume_id'
    DEFAULT_ID = 'SPR-0001'
    # 除本库编号外，还接受澪设计档案里的哪几类（字母对应 H 发型 / C 服装 / P 姿势）。
    # 由单库节点自己声明：服装节点不该取到发型图，深度节点更不能把普通姿势当深度图。
    MIO_KINDS = ()
    ID_TOOLTIP = '点击浏览图库，按中文、编号或关键词搜索，再使用此素材。'
    ANGLE = False                       # 是否有「形态」这一维：姿势是机位，二次元是彩图 / 线稿
    VARIANT_WIDGET = 'angle'            # 该维度的控件名，决定前端怎么读
    VARIANT_TOOLTIP = '同一素材的不同版本，切换后输出对应原图。'
    FUNCTION = 'load_costume'
    RETURN_TYPES = ('IMAGE', 'INT', 'INT', 'STRING', 'STRING', 'STRING')
    RETURN_NAMES = ('image', 'width', 'height', 'costume_id', 'description', 'keywords_en')
    CATEGORY = 'image/Reference Gallery'
    DESCRIPTION = ''

    @classmethod
    def INPUT_TYPES(cls):
        required = {cls.ID_WIDGET: ('STRING', {'default': cls.DEFAULT_ID, 'multiline': False, 'tooltip': cls.ID_TOOLTIP})}
        # 尺寸与翻转一律放 optional：老工作流与 API 调用方不传这些键时照常运行，
        # 默认「原图尺寸」等于保持以前的行为，不会因为升级节点把已有图的分辨率改掉。
        optional = {
            'resize_mode': (list(RESIZE_MODES), {'default': RESIZE_MODES[0], 'tooltip': RESIZE_TOOLTIP}),
            'width': ('INT', {'default': 1024, 'min': 64, 'max': 8192, 'step': 8,
                              'tooltip': '仅在指定尺寸时生效。'}),
            'height': ('INT', {'default': 1280, 'min': 64, 'max': 8192, 'step': 8,
                               'tooltip': '仅在指定尺寸时生效。'}),
            'flip_horizontal': ('BOOLEAN', {'default': False, 'tooltip': '水平翻转，人物朝左 / 朝右互换。'}),
        }
        if cls.ANGLE:
            # 形态放 optional：界面上照样是下拉框，但 API 调用方不传这个键时不会整条链被判失败，
            # 缺省回落到列表第一个值。这个坑踩过一次：放 required 会让整条输出链被静默丢弃。
            values = variant_values(cls.LIBRARY)
            optional[cls.VARIANT_WIDGET] = (values, {'default': values[0], 'tooltip': cls.VARIANT_TOOLTIP})
        return {'required': required, 'optional': optional}

    @classmethod
    def _library_for(cls, values):
        """实际取图的库：单库节点按编号认澪库，跨来源节点（发型）另有自己的解析。"""
        return _library_for_id(cls.LIBRARY, values.get(cls.ID_WIDGET), cls.MIO_KINDS)

    @classmethod
    def _relative(cls, values):
        row = item(cls._library_for(values), str(values[cls.ID_WIDGET]))
        return pick(row, '原图', values.get(cls.VARIANT_WIDGET))

    @classmethod
    def VALIDATE_INPUTS(cls, **values):
        # 只校验 ID 与视角，不触发下载：避免在节点面板上调参时卡住界面。
        try:
            cls._relative(values)
        except ValueError as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(cls, **values):
        path = local_path(cls._relative(values))
        # 尺寸与翻转也进缓存键：同一张图改成指定尺寸后必须重算，不能命中旧结果。
        shape = f'{values.get("resize_mode", RESIZE_MODES[0])}:{values.get("width")}:{values.get("height")}:{values.get("flip_horizontal")}'
        if path.is_file():
            stat = path.stat()
            return f'{path.name}:{stat.st_mtime_ns}:{stat.st_size}:{shape}'
        return f'{cls._relative(values)}:pending:{shape}'

    def _load(self, **values):
        library = self._library_for(values)
        item_id = str(values[self.ID_WIDGET])
        row = item(library, item_id)
        img = _load_rgb(library, row, values.get(self.VARIANT_WIDGET),
                        values.get('resize_mode', RESIZE_MODES[0]),
                        values.get('width', 1024), values.get('height', 1280),
                        bool(values.get('flip_horizontal')))
        width, height = img.size
        extra = row.get('英文关键词') or row.get('日文') or ''
        return _to_tensor(img), width, height, item_id, describe(row), extra


class CostumeGallery(_GalleryNode):
    LIBRARY = 'costume'
    ID_WIDGET = 'costume_id'
    DEFAULT_ID = 'SPR-0001'
    MIO_KINDS = ('C',)      # 也接澪设计档案里的服装（C-01-01 这种编号）
    ID_TOOLTIP = '点击浏览服装图库，按中文、英文或编号搜索，再使用此服装。弹窗顶部可切到澪图库选作者款。'
    DESCRIPTION = '中文服装图库：1,407 套，分类筛选与中英文搜索；弹窗顶部还能切到澪设计档案选 117 件作者款。'

    def load_costume(self, **values):
        return self._load(**values)


class CostumeAnimeGallery(_GalleryNode):
    """服装动画版：分类与编号规则跟写实服装完全一样，但是另一个站点的另一批图，独立成库。"""

    LIBRARY = 'costume-anime'
    ID_WIDGET = 'costume_anime_id'
    DEFAULT_ID = 'SPR-0001'
    FUNCTION = 'load_costume_anime'
    ID_TOOLTIP = '点击浏览服装动画图库，按中文、英文或编号搜索，再使用此服装。'
    RETURN_NAMES = ('image', 'width', 'height', 'costume_anime_id', 'description', 'keywords_en')
    DESCRIPTION = '服装动画图库：1,320 套动漫画风的无人物服装参考，8 个分类，中英关键词搜索，输出完整 PNG 原图。'

    def load_costume_anime(self, **values):
        return self._load(**values)


class PoseGallery(_GalleryNode):
    LIBRARY = 'pose'
    VARIANT_WIDGET = 'angle'
    ID_WIDGET = 'pose_id'
    DEFAULT_ID = 'POS-SEXY-P001'
    FUNCTION = 'load_pose'
    ANGLE = True
    MIO_KINDS = ('P',)      # 也接澪设计档案里的姿势（P-01-01 这种编号；那边每个动作只有一张，跟机位无关）
    VARIANT_TOOLTIP = '同一姿势的五个机位，切换后输出对应原图。澪设计的姿势只有一张，机位对它不起作用。'
    ID_TOOLTIP = '点击浏览姿势图库，按系列、动作或编号搜索，每个姿势含五个机位。'
    RETURN_NAMES = ('image', 'width', 'height', 'pose_id', 'description', 'description_ja')
    DESCRIPTION = '中文姿势图库：288 个姿势 × 5 个机位（1,439 张）；弹窗顶部还能切到澪设计档案选 216 个作者姿势。'

    def load_pose(self, **values):
        return self._load(**values)


class FaceGallery(_GalleryNode):
    LIBRARY = 'face'
    ID_WIDGET = 'face_id'
    DEFAULT_ID = 'FACE-0001'
    FUNCTION = 'load_face'
    ID_TOOLTIP = '点击浏览脸部图库，按脸部特写 / 造型、发型或编号搜索。'
    RETURN_NAMES = ('image', 'width', 'height', 'face_id', 'description', 'description_ja')
    DESCRIPTION = '中文脸部图库：1,498 张正面、纯色背景的 AI 头部参考图，输出完整 PNG 原图。'

    def load_face(self, **values):
        return self._load(**values)


class DepthGallery(_GalleryNode):
    """深度姿势：与姿势库同一批 288 个姿势、同样五个机位，灰度表示远近，适合 ControlNet depth。"""

    LIBRARY = 'depth'
    VARIANT_WIDGET = 'angle'
    ID_WIDGET = 'depth_id'
    DEFAULT_ID = 'DEP-SEXY-P001'
    FUNCTION = 'load_depth'
    ANGLE = True
    VARIANT_TOOLTIP = '同一姿势的五个机位，切换后输出对应原图。'
    ID_TOOLTIP = '点击浏览深度姿势图库，按系列、动作或编号搜索，每个姿势含五个机位。'
    RETURN_NAMES = ('image', 'width', 'height', 'depth_id', 'description', 'description_ja')
    DESCRIPTION = '深度姿势图库：288 个姿势 × 5 个机位（1,439 张），灰度深度图，可直接接 ControlNet depth。'

    def load_depth(self, **values):
        return self._load(**values)


routes = PromptServer.instance.routes

@routes.get('/ref_lookbook/catalog')
async def catalog_route(request):
    return await _catalog('costume')

@routes.get('/ref_lookbook/catalog/{library}')
async def catalog_library_route(request):
    return await _catalog(request.match_info['library'])

async def _catalog(library):
    if library not in LIBRARIES:
        return web.json_response({'error': f'未知图库：{library}'}, status=404)
    try:
        payload = meta(library)
        return web.json_response({
            'library': library,
            'meta': payload,
            # 前端据此拼原图地址：站点首页 + 原图模板，索引里不落这些字段，换源只改一处。
            # line_template 只有二次元库有：线稿在源站是另一条路径，且本地名带 _line 后缀。
            'origin': {'site': site(library), 'template': LIBRARIES[library]['origin'],
                       'line_template': LIBRARIES[library].get('line_origin', ''),
                       'offline': offline(), 'env': OFFLINE_ENV},
            'records': records(library),
        })
    except (ValueError, FileNotFoundError) as exc:
        return web.json_response({'error': str(exc)}, status=503)

@routes.get('/ref_lookbook/assets/{kind}/{filename}')
async def asset_route(request):
    return await _file(asset, request.match_info['kind'], request.match_info['filename'], 'costume')

@routes.get('/ref_lookbook/assets/{library}/{kind}/{filename}')
async def asset_library_route(request):
    return await _file(asset, request.match_info['kind'], request.match_info['filename'], request.match_info['library'])

@routes.get('/ref_lookbook/asset/{library}/{kind}/{item_id}')
async def asset_by_id_route(request):
    kind = request.match_info['kind']
    try:
        return web.FileResponse(await asyncio.to_thread(
            asset_by_id, request.match_info['library'], request.match_info['item_id'],
            kind, request.query.get('angle'), kind in ('thumbs', 'png')),
            headers={'Cache-Control': 'private, max-age=3600'})
    except (ValueError, FileNotFoundError, KeyError):
        raise web.HTTPNotFound()

async def _file(resolver, kind, filename, library):
    """缩略图与原图都允许联网补一次。

    原图这里也放开自助获取：用户在弹窗里看过的大图会立即落进 library/<库>/png/，
    下次再打开、以及之后节点出图都直接命中本地，不会重复下载。
    仓库仍然不分发图片本体，缓存只存在使用者本机。
    """
    try:
        path = await asyncio.to_thread(resolver, kind, filename, library, kind in ('thumbs', 'png'))
        return web.FileResponse(path, headers={'Cache-Control': 'private, max-age=3600'})
    except (ValueError, FileNotFoundError):
        raise web.HTTPNotFound()

ANGLE_SLUGS = {'正面': 'front', '俯视': 'high', '仰视': 'low', '侧面': 'side', '斜45°': '45deg',
               '彩图': 'color', '线稿': 'line'}
# 服装动画版与写实服装共用 SPR / SUM / AUT … 编号（上游两版各自独立编号，不做互补），
# 落到 input 目录会互相覆盖，所以这一库的文件名带库前缀。其余库编号前缀天然唯一
# （POS- / FACE- / DEP- / ANE-），保持原样，免得打断已经存好的工作流。
LIB_TAG = {'costume-anime': 'anime-'}

def import_to_input(library, item_id, angle, source):
    """把素材物化成 ComfyUI input 目录下的真实文件，供 LoadImage 等原生节点直接选用。

    文件名与素材 ID 一一对应，重复导入同一素材只会覆盖同一个文件，不会让 input 目录越滚越大。
    """
    suffix = f'_{ANGLE_SLUGS.get(angle, re.sub(r"[^0-9A-Za-z]", "", str(angle or "")))}'
    stem = LIB_TAG.get(library, '') + re.sub(r'[^0-9A-Za-z._-]', '_', item_id)
    target = Path(folder_paths.get_input_directory()) / f'ref_{stem}{suffix if angle else ""}{source.suffix or ".png"}'
    if target.is_file() and target.stat().st_size == source.stat().st_size and target.read_bytes() == source.read_bytes():
        return target.name
    # 先写临时文件再原子替换：避免执行中的 LoadImage 读到写了一半的图。
    staging = target.with_name(target.name + '.part')
    shutil.copyfile(source, staging)
    staging.replace(target)
    return target.name

@routes.post('/ref_lookbook/import')
async def import_route(request):
    """给任意「加载图像」节点用：把图库素材落到 input 目录，返回可直接填进 image 控件的文件名。"""
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({'error': '请求体必须是 JSON'}, status=400)
    library, item_id = str(payload.get('library') or ''), str(payload.get('id') or '')
    angle = payload.get('angle') or None
    if library not in LIBRARIES:
        return web.json_response({'error': f'未知图库：{library}'}, status=404)
    try:
        relative = pick(item(library, item_id), '原图', angle)
        source = ensure_original(library, relative)
        name = import_to_input(library, item_id, angle if angle in variant_values(library) else None, source)
    except ValueError as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except FileNotFoundError as exc:
        return web.json_response({'error': str(exc)}, status=503)
    return web.json_response({'name': name, 'library': library, 'id': item_id, 'angle': angle,
                              'bytes': source.stat().st_size})

@routes.get('/ref_lookbook/fetch-all')
async def fetch_all_plan_route(request):
    """整库下载前的预估：缺多少张、大概多大、存到哪、磁盘还剩多少。"""
    return web.json_response(await asyncio.to_thread(bulk.plan))


@routes.post('/ref_lookbook/fetch-all/start')
async def fetch_all_start_route(request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    libraries = payload.get('libraries') if isinstance(payload, dict) else None
    try:
        job = await asyncio.to_thread(bulk.start, libraries)
    except ValueError as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except RuntimeError as exc:
        return web.json_response({'error': str(exc)}, status=409)
    return web.json_response({'job': job})


@routes.get('/ref_lookbook/fetch-all/status')
async def fetch_all_status_route(request):
    return web.json_response(bulk.status())


@routes.post('/ref_lookbook/fetch-all/stop')
async def fetch_all_stop_route(request):
    return web.json_response(bulk.cancel())


@routes.get('/ref_lookbook/status')
async def status_route(request):
    """自检：各库记录数、缩略图与原图的本机缓存情况。"""
    if offline():
        network = 'only-local'
    else:
        network = 'upstream-on-demand'
    report = {'network': network, 'env': OFFLINE_ENV, 'libraries': {}}
    for name in LIBRARIES:
        try:
            entry = {'label': LIBRARIES[name]['label'], 'records': len(records(name)),
                     'site': site(name), 'index': LIBRARIES[name]['index']}
            try:
                entry['missing_originals'] = missing_originals(name)
            except (OSError, ValueError):
                entry['missing_originals'] = None
            report['libraries'][name] = entry
        except (ValueError, FileNotFoundError) as exc:
            report['libraries'][name] = {'label': LIBRARIES[name]['label'], 'error': str(exc)}
    return web.json_response(report)

# 允许下发的静态文件白名单：与 server.py 的 WEB_FILES 同一份，加文件记得两边一起改。
WEB_FILES = ('gallery.mjs', 'style.css', 'icon.svg', 'ref_gallery.js', 'mio.mjs')

@routes.get('/ref_lookbook/web/{filename}')
async def web_route(request):
    filename = request.match_info['filename']
    if filename not in WEB_FILES:
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / 'web' / filename, headers={'Cache-Control': 'no-cache'})

@routes.get('/ref_lookbook/gallery')
async def gallery_route(request):
    return web.FileResponse(ROOT / 'web' / 'gallery.html', headers={'Cache-Control': 'no-cache'})

@routes.get('/ref_lookbook/mio')
async def mio_route(request):
    """霧島澪设计档案：独立页面，不进六库页签（数据是「系列 → 卷 → 9 件」+ 作者原版提示词）。"""
    return web.FileResponse(ROOT / 'web' / 'mio.html', headers={'Cache-Control': 'no-cache'})

class AnimeGallery(_GalleryNode):
    """二次元库：发型 / 眼睛 / 服装 / 姿势混在一个库里，靠「分类」区分，姿势额外带线稿。"""

    LIBRARY = 'anime'
    VARIANT_WIDGET = 'variant'
    ID_WIDGET = 'anime_id'
    DEFAULT_ID = 'ANE-H001'
    FUNCTION = 'load_anime'
    ANGLE = True
    VARIANT_TOOLTIP = '彩图或线稿。只有姿势两种都有，其余素材选线稿会自动回落到彩图。'
    ID_TOOLTIP = '点击浏览二次元图库，按服装 / 发型与眼睛 / 姿势分类或编号搜索。'
    RETURN_NAMES = ('image', 'width', 'height', 'anime_id', 'description', 'keywords_en')
    DESCRIPTION = '二次元图库：1,027 条（服装 440 / 发型与眼睛 306 / 姿势 281），共 1,308 个图片版本，姿势含线稿。'

    def load_anime(self, **values):
        return self._load(**values)


class MioGallery(_GalleryNode):
    """霧島澪设计档案：作者系列型素材（发型 6 卷 / 服装 13 卷 / 姿势 24 卷，共 387 件）。

    与六个图库的两点不同，决定了它是独立节点而不是第七个页签：
      1. 每件自带作者写好的中英文提示词，所以比别的节点多两个 STRING 输出；
      2. 源站只有一档图（最长边约 418 px，没有大图目录），定位是「参考 + 提示词」，
         不是高分辨率出图素材——要放大出图就靠 prompt 自己重绘。
    """

    LIBRARY = 'mio'
    ID_WIDGET = 'mio_id'
    DEFAULT_ID = 'H-01-01'
    FUNCTION = 'load_mio'
    ID_TOOLTIP = '点击浏览澪设计档案，按系列、卷或编号搜索；每件带作者原版中英文提示词。'
    RETURN_TYPES = ('IMAGE', 'INT', 'INT', 'STRING', 'STRING', 'STRING', 'STRING')
    RETURN_NAMES = ('image', 'width', 'height', 'mio_id', 'description', 'prompt', 'prompt_zh')
    DESCRIPTION = '霧島澪设计档案：43 卷 387 件（发型 / 服装 / 姿势），每件附作者原版中英文提示词。'

    def load_mio(self, **values):
        item_id = str(values[self.ID_WIDGET])
        row = item(self.LIBRARY, item_id)
        img = _load_rgb(self.LIBRARY, row, None,
                        values.get('resize_mode', RESIZE_MODES[0]),
                        values.get('width', 1024), values.get('height', 1280),
                        bool(values.get('flip_horizontal')))
        width, height = img.size
        return (_to_tensor(img), width, height, item_id, describe(row),
                row.get('提示词') or '', row.get('提示词中文') or '')


# 发型有两个来源，节点用 hair_source 切换：
#   澪设计 —— 6 卷 54 件，每件带作者写好的中英文提示词，能整句写进配方的 prompt；
#   二次元 —— 「发型与眼睛」下 230 条发型，量大、覆盖二次元头型，但只有中日英关键词。
# 两边编号空间不同（H-01-01 / ANE-H001），切来源时编号要能自动回落，见 _resolve。
HAIR_SOURCES = {'澪设计': ('mio', 'H-01-01'), '二次元': ('anime', 'ANE-H001')}


class HairGallery(_GalleryNode):
    """发型图库：一个节点收两个来源。

    与六个单库节点的差别只在库不是固定的：_library_for 跟着 hair_source 走，
    加载、校验、缓存继承基类，不另写一套。
    """

    LIBRARY = 'mio'
    ID_WIDGET = 'hair_id'
    DEFAULT_ID = 'H-01-01'
    FUNCTION = 'load_hair'
    SOURCE_WIDGET = 'hair_source'
    ID_TOOLTIP = '点击浏览发型库：澪设计 6 卷 54 件（带作者提示词），或二次元发型 230 条。'
    RETURN_TYPES = ('IMAGE', 'INT', 'INT', 'STRING', 'STRING', 'STRING', 'STRING', 'STRING')
    # hair_detail 追加在末尾：连线按序号存，插到中间会把老工作流的 prompt / prompt_zh 全部错位。
    RETURN_NAMES = ('image', 'width', 'height', 'hair_id', 'description', 'prompt', 'prompt_zh', 'hair_detail')
    DESCRIPTION = ('发型图库：澪设计 54 件（6 卷，作者原版提示词）+ 二次元 230 条动漫头型，切换来源共用一套控件。'
                   'hair_detail 只讲头发本身（长度 / 分层 / 发尾 / 刘海），可直接拼进提示词。')

    @classmethod
    def INPUT_TYPES(cls):
        data = super().INPUT_TYPES()
        data['optional'][cls.SOURCE_WIDGET] = (list(HAIR_SOURCES), {
            'default': '澪设计',
            'tooltip': '澪设计：6 卷 54 件，每件带作者中英文提示词。二次元：230 条动漫头型，只有关键词。'
                       '切来源后编号会自动回落到该来源的第一件。',
        })
        return data

    @classmethod
    def _resolve(cls, values):
        """按来源定库，并把编号约束在该来源的发型里：换了来源但编号还是另一个库的，回落到默认。

        静默回落而不是报错——切来源是下拉框一下的事，节点直接变红不如直接跳到该来源的第一件。
        """
        name = str(values.get(cls.SOURCE_WIDGET) or '')
        library, fallback = HAIR_SOURCES.get(name, HAIR_SOURCES['澪设计'])
        for candidate in (str(values.get(cls.ID_WIDGET) or fallback), fallback):
            try:
                row = item(library, candidate)
            except ValueError:
                continue
            if cls._is_hair(library, row):
                return library, candidate, row
        raise ValueError(f'{LIBRARIES[library]["label"]}里找不到可用发型：{values.get(cls.ID_WIDGET)}')

    @staticmethod
    def _is_hair(library, row):
        # 澪设计按「分类」分系列（发型 / 服装 / 姿势）；二次元把发型和眼睛放在同一个分类里。
        return row.get('分类') == ('发型' if library == 'mio' else '发型与眼睛')

    @classmethod
    def _library_for(cls, values):
        return cls._resolve(values)[0]

    @classmethod
    def _relative(cls, values):
        return pick(cls._resolve(values)[2], '原图', None)

    def _load(self, **values):
        library, item_id, row = self._resolve(values)
        img = _load_rgb(library, row, None,
                        values.get('resize_mode', RESIZE_MODES[0]),
                        values.get('width', 1024), values.get('height', 1280),
                        bool(values.get('flip_horizontal')))
        width, height = img.size
        if library == 'mio':
            prompt, prompt_zh = row.get('提示词') or '', row.get('提示词中文') or ''
            # 只讲头发本身的句子（「深棕长发过胸，中分，层次发尾向内收成内扣弧度」）。
            # 作者整句提示词里带「肖像 / 上半身」这类取景词，直接拼进全身立绘的提示词会把构图带歪。
            detail = row.get('描述') or prompt_zh
        else:
            # 二次元索引没有整句提示词：英文取「英文关键词」，中文取「关键词」，缺英文时退回日文。
            prompt = ', '.join(row.get('英文关键词') or []) or row.get('日文') or ''
            prompt_zh = '、'.join(row.get('关键词') or [])
            detail = prompt_zh
        return (_to_tensor(img), width, height, item_id, describe(row), prompt, prompt_zh, detail)

    # ComfyUI 执行时按 FUNCTION 名字取方法：这里少一个 load_hair，节点在画布上能连能点，
    # 一点运行就报 "missing the load_hair method"。测试直接调 _load 会绕过它，所以另加断言盯住。
    def load_hair(self, **values):
        return self._load(**values)


class PromptJoin:
    """提示词拼接：一段静态说明 + 上游节点给的动态描述，用空行拼成一段。

    为什么要这个节点：图库选的发型只以「图」的形式进模型，而长发选长发时模型更听脸部参考的话——
    图 4 的发尾层次、分缝会被图 2 的卷度盖掉（实测：选短发能生效，选另一个长直发就看不出区别）。
    把发型自带的文字描述拼进提示词，等于同时给了「图 + 字」，才压得住图 2 自带的头发。
    空值自动跳过，所以只接一路也能用。
    """

    CATEGORY = 'image/Reference Gallery'
    FUNCTION = 'join'
    RETURN_TYPES = ('STRING',)
    RETURN_NAMES = ('prompt',)
    DESCRIPTION = '提示词拼接：一段静态说明 + 最多两路动态描述（如发型节点的 hair_detail），空值自动跳过。'

    @classmethod
    def INPUT_TYPES(cls):
        return {
            'required': {
                'text': ('STRING', {'default': '', 'multiline': True,
                                    'tooltip': '静态部分：四张参考图各自负责什么。'}),
            },
            'optional': {
                # forceInput：只在画布上出插槽、不占控件位，工作流里的 widgets_values 只存 text 一个。
                'extra': ('STRING', {'forceInput': True,
                                     'tooltip': '接 Hair Gallery 的 hair_detail：所选发型的具体描述。'}),
                'extra2': ('STRING', {'forceInput': True,
                                      'tooltip': '可再接一路：补充细节、风格或负面词。'}),
            },
        }

    @staticmethod
    def join(text, extra='', extra2=''):
        parts = [str(part).strip() for part in (text, extra, extra2) if part and str(part).strip()]
        return ('\n\n'.join(parts),)


class CharacterRecipe(_GalleryNode):
    """四合一角色配方：一次取发型、脸部、服装、姿势，输出四张图 + 横向参考拼图 + 中英文合成提示词。

    思路参考上游 ai-pose-gallery-zh 的「三合一合成配方」节点，字段换成我们自己的中文索引：
    发型定头顶造型，脸部定长相，服装定穿着，姿势定动作与构图，四者拼成一张参考整图直接丢给 img2img / ControlNet。
    """

    LIBRARY = 'face'
    ID_WIDGET = 'face_id'
    DEFAULT_ID = 'FACE-0001'
    FUNCTION = 'build_recipe'
    CATEGORY = 'image/Reference Gallery'
    DESCRIPTION = '四合一配方：发型 + 脸部 + 服装 + 姿势，输出四张图、横向参考拼图与中英文合成提示词。'
    RETURN_TYPES = ('IMAGE', 'IMAGE', 'IMAGE', 'IMAGE', 'INT', 'INT', 'STRING', 'STRING', 'IMAGE')
    # hair_image 追加在末尾而不是插到最前：旧工作流的连线是按序号存的，插到前面会把 face/costume/pose
    # 全部错位一格，老图一打开就串图。
    RETURN_NAMES = ('face_image', 'costume_image', 'pose_image', 'reference_sheet',
                    'width', 'height', 'prompt_zh', 'prompt_en', 'hair_image')

    COSTUME_LIBRARIES = ('costume', 'costume-anime')

    @classmethod
    def INPUT_TYPES(cls):
        images = variant_values('pose')
        return {
            'required': {
                'face_id': ('STRING', {'default': cls.DEFAULT_ID, 'multiline': False,
                                       'tooltip': '点击浏览脸部图库：决定长相与发型。'}),
                'costume_id': ('STRING', {'default': 'SPR-0001', 'multiline': False,
                                          'tooltip': '点击浏览服装图库：决定穿着。'}),
                'pose_id': ('STRING', {'default': 'POS-SEXY-P001', 'multiline': False,
                                       'tooltip': '点击浏览姿势图库：决定动作与构图。'}),
                'style_preset': (list(STYLE_PRESETS), {'default': '高清日系动漫',
                                                       'tooltip': '风格方向盘，会同时写进中英文提示词。'}),
                # 单行而不是多行：多行输入框在新版前端会自适应撑满节点剩余高度（实测 398 px），
                # 把底下三张预览挤成负高度，节点上什么都看不到。要写长提示词拉宽节点即可。
                'extra_prompt': ('STRING', {'default': '', 'multiline': False,
                                            'tooltip': '可选补充，例如：银色双眸、教室窗边逆光、微风吹拂发丝。'}),
                'resize_mode': (list(RESIZE_MODES), {'default': RESIZE_MODES[1], 'tooltip': RESIZE_TOOLTIP}),
                'width': ('INT', {'default': 1024, 'min': 64, 'max': 8192, 'step': 8}),
                'height': ('INT', {'default': 1280, 'min': 64, 'max': 8192, 'step': 8}),
                'flip_pose_horizontal': ('BOOLEAN', {'default': False,
                                                     'tooltip': '只翻转姿势图：人物朝向与服装、脸部不一致时用它对齐。'}),
            },
            # 全部放 optional：API 调用方省略任何一个键都能跑，不会整条链被丢。
            'optional': {
                'pose_angle': (images, {'default': images[0], 'tooltip': '姿势的五个机位。'}),
                'costume_library': (list(cls.COSTUME_LIBRARIES),
                                    {'default': 'costume', 'tooltip': '写实服装或服装动画，编号规则一致。'}),
                'use_depth': ('BOOLEAN', {'default': False,
                                          'tooltip': '把姿势图换成同编号的深度图，可直接接 ControlNet depth。'}),
                # 发型是后加的槽位，必须排在已有控件之后：工作流 JSON 里的 widgets_values 是按位置存的，
                # 插到中间会把老工作流的 pose_angle / costume_library / use_depth 整体错位一格。
                'hair_id': ('STRING', {'default': 'H-01-01', 'multiline': False,
                                       'tooltip': '点击浏览发型图库：澪设计 54 件或二次元 230 条。'}),
                'hair_source': (list(HAIR_SOURCES), {'default': '澪设计',
                                                     'tooltip': '澪设计带作者原版提示词，二次元量大。切来源后编号自动回落。'}),
            },
        }

    def _pose_library(self, values):
        return self._pose_target(values)[0]

    @staticmethod
    def _costume_target(values):
        """服装实际读哪本索引：澪库编号（C-01-01）优先，其次看 costume_library 下拉。"""
        chosen = str(values.get('costume_library') or 'costume')
        if chosen not in CharacterRecipe.COSTUME_LIBRARIES:
            chosen = 'costume'
        return _library_for_id(chosen, values.get('costume_id') or 'SPR-0001', ('C',)), \
            str(values.get('costume_id') or 'SPR-0001')

    @staticmethod
    def _pose_target(values):
        """姿势实际读哪本索引与哪个编号。

        澪库的姿势只有一张图、没有深度版，所以编号是 P-01-01 时直接读澪库，
        既不换 POS- → DEP- 前缀，也不理 use_depth（换了前缀会变成查不到）。
        """
        pose_id = str(values.get('pose_id') or 'POS-SEXY-P001')
        library = _library_for_id('depth' if values.get('use_depth') else 'pose', pose_id, ('P',))
        if library == 'mio':
            return 'mio', pose_id
        return library, (pose_id.replace('POS-', 'DEP-', 1) if values.get('use_depth') else pose_id)

    @classmethod
    def IS_CHANGED(cls, **values):
        """四张图任一换图 / 换版本 / 改尺寸都要重算，缓存键必须覆盖整组参数。"""
        costume_lib, costume_key = cls._costume_target(values)
        pose_lib, pose_key = cls._pose_target(values)
        parts = []
        targets = [('face', str(values.get('face_id') or cls.DEFAULT_ID), None),
                   (costume_lib, costume_key, None),
                   (pose_lib, pose_key, values.get('pose_angle'))]
        try:
            hair_library, hair_id, hair_row = HairGallery._resolve(values)
        except ValueError:
            return f'missing:hair:{values.get("hair_id")}'
        targets.append((hair_library, hair_id, None))
        for library, item_id, variant in targets:
            try:
                path = local_path(pick(item(library, item_id), '原图', variant))
            except ValueError:
                return f'missing:{library}:{item_id}'
            stat = path.stat() if path.is_file() else None
            parts.append(f'{path.name}:{stat.st_mtime_ns if stat else "pending"}')
        shape = f'{values.get("resize_mode")}:{values.get("width")}:{values.get("height")}:{values.get("flip_pose_horizontal")}'
        return '|'.join(parts) + '|' + shape + '|' + str(values.get('style_preset')) + '|' + str(values.get('extra_prompt'))

    @classmethod
    def VALIDATE_INPUTS(cls, **values):
        """四个 ID 与服装库都要先校验；只查索引，不触发下载。"""
        try:
            item('face', str(values.get('face_id') or cls.DEFAULT_ID))
            chosen = values.get('costume_library') or 'costume'
            if chosen not in cls.COSTUME_LIBRARIES:
                return f'未知服装库：{chosen}'
            costume_lib, costume_key = cls._costume_target(values)
            item(costume_lib, costume_key)
            pose_lib, pose_key = cls._pose_target(values)
            item(pose_lib, pose_key)
            # 发型与 HairGallery 同一套解析：编号跟来源不匹配时会在那里回落到默认件，不会把整条链判失败。
            HairGallery._resolve(values)
        except ValueError as exc:
            return str(exc)
        return True

    def build_recipe(self, face_id=DEFAULT_ID, costume_id='SPR-0001', pose_id='POS-SEXY-P001',
                     style_preset='高清日系动漫', extra_prompt='', resize_mode=RESIZE_MODES[1],
                     width=1024, height=1280, flip_pose_horizontal=False,
                     pose_angle=None, costume_library='costume', use_depth=False,
                     hair_id='H-01-01', hair_source='澪设计'):
        # 深度库编号与姿势库一一对应，只是前缀不同（POS- → DEP-），直接换前缀沿用同一套机位。
        # 澪设计的姿势没有深度版，编号是 P-01-01 时整条链改读澪库。
        pose_library, pose_key = self._pose_target(values={
            'pose_id': pose_id, 'use_depth': use_depth})

        face_row = item('face', str(face_id))
        costume_lib, costume_key = self._costume_target(
            values={'costume_library': costume_library, 'costume_id': costume_id})
        costume_row = item(costume_lib, costume_key)
        pose_row = item(pose_library, pose_key)
        hair_library, hair_key, hair_row = HairGallery._resolve(
            {'hair_id': hair_id, 'hair_source': hair_source})

        face_img = _load_rgb('face', face_row, None, resize_mode, width, height, False)
        costume_img = _load_rgb(costume_lib, costume_row, None, resize_mode, width, height, False)
        pose_img = _load_rgb(pose_library, pose_row, pose_angle, resize_mode, width, height,
                             bool(flip_pose_horizontal))
        hair_img = _load_rgb(hair_library, hair_row, None, resize_mode, width, height, False)

        # 四张统一尺寸后横向拼成一张参考整图，顺序按「头顶造型 → 长相 → 穿着 → 动作」：
        # 原图尺寸模式下四张大小不一，统一按最大宽高居中裁剪，谁都不会被截断成一条边。
        panels = (hair_img, face_img, costume_img, pose_img)
        panel_w = max(panel.width for panel in panels)
        panel_h = max(panel.height for panel in panels)
        sheet = Image.new('RGB', (panel_w * len(panels) + 12 * (len(panels) - 1), panel_h), PANEL_BG)
        for index, panel in enumerate(panels):
            fitted = panel if panel.size == (panel_w, panel_h) else ImageOps.fit(
                panel, (panel_w, panel_h), method=_pil_resampling())
            sheet.paste(fitted, (index * (panel_w + 12), 0))

        style_zh, style_en = STYLE_PRESETS.get(style_preset, STYLE_PRESETS['高清日系动漫'])
        extra = (extra_prompt or '').strip()
        # 只有「服装动画」需要标注画风；澪设计的服装也是写实向，不必再加后缀。
        costume_label = '' if costume_lib in ('costume', 'mio') else f'·{LIBRARIES[costume_lib]["label"]}'

        zh = [f'参考图合成一张完整的角色立绘：{style_zh}。四张图分工固定——图1 姿势与构图、图2 长相、'
              f'图3 服装、图4 头发，冲突时以分工为准。',
              f'【发型·只认图4】{_describe_zh(hair_row)}。把人物头顶的头发整体换成图4 的样子：长度、层次、'
              f'发尾走向、发色、刘海、分缝都照它；图2 自带的头发一律不要。图4 里的白色人台、脖子、'
              f'纯色背景不要画进来。',
              f'【人像·图2 只取长相】{_describe_zh(face_row)}。',
              f'【服装{costume_label}·图3】{_describe_zh(costume_row)}。',
              f'【动作与构图·图1】{_describe_zh(pose_row)}。']
        # 澪设计的发型自带作者写的一句描述，比索引关键词具体得多（发尾内扣 / 层次 / 分缝），
        # 用它比用作者整句提示词安全：整句里带「肖像 / 上半身」这类取景词，会把全身立绘的构图带歪。
        detail_zh = hair_row.get('描述') or hair_row.get('提示词中文') or ''
        if hair_library == 'mio' and detail_zh:
            zh.append(f'【发型细节】{detail_zh}。')
        if extra:
            zh.append(f'【补充细节】{extra}。')
        zh.append('要求面部自然生动，服装贴合身体动态，肢体透视与手部结构准确，光影统一。')

        # 英文只取有英文词条的库（服装、二次元发型），澪设计的发型与脸部、姿势交给参考图本身，别硬翻中文。
        en = [style_en,
              'hairstyle comes from image 4 only: match its length, layers, hair ends, colour, bangs and parting, '
              'and replace the hair seen in image 2 completely']
        costume_en = _describe_en(costume_row)
        if costume_en:
            en.append(f'wearing {costume_en}')
        hair_en = _describe_en(hair_row)
        if hair_en:
            en.append(f'hairstyle: {hair_en}')
        en.append('single photo of one person, no reference sheet, no collage, no mannequin or plain backdrop')
        if extra:
            en.append(extra)

        return (_to_tensor(face_img), _to_tensor(costume_img), _to_tensor(pose_img), _to_tensor(sheet),
                sheet.width, sheet.height, ''.join(zh), ', '.join(part for part in en if part),
                _to_tensor(hair_img))


NODE_CLASS_MAPPINGS = {'CostumeGallery': CostumeGallery, 'CostumeAnimeGallery': CostumeAnimeGallery,
                       'PoseGallery': PoseGallery, 'FaceGallery': FaceGallery,
                       'DepthGallery': DepthGallery, 'AnimeGallery': AnimeGallery,
                       'HairGallery': HairGallery, 'MioGallery': MioGallery,
                       'PromptJoin': PromptJoin, 'CharacterRecipe': CharacterRecipe}
NODE_DISPLAY_NAME_MAPPINGS = {
    'CostumeGallery': 'Costume Gallery 服装图库',
    'CostumeAnimeGallery': 'Costume Anime Gallery 服装动画图库',
    'PoseGallery': 'Pose Gallery 姿势图库',
    'FaceGallery': 'Face Gallery 脸部图库',
    'DepthGallery': 'Depth Gallery 深度姿势图库',
    'AnimeGallery': 'Anime Gallery 二次元图库',
    'HairGallery': 'Hair Gallery 发型图库',
    'MioGallery': 'Mio Gallery 澪设计档案',
    'PromptJoin': 'Prompt Join 提示词拼接',
    'CharacterRecipe': 'Character Recipe 四合一角色配方',
}
WEB_DIRECTORY = './web'
__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
