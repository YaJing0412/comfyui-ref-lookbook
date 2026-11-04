"""ComfyUI reference gallery: 服装 / 服装动画 / 姿势 / 脸部 / 深度姿势 / 二次元。随仓库发行索引与内置缩略图，原图按需向作者站点取一次。"""
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


class _GalleryNode:
    """六个图库共用同一套加载逻辑，差异只在索引、控件名、返回值命名与形态维度。"""

    LIBRARY = 'costume'
    ID_WIDGET = 'costume_id'
    DEFAULT_ID = 'SPR-0001'
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
    def _relative(cls, values):
        row = item(cls.LIBRARY, str(values[cls.ID_WIDGET]))
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
        item_id = str(values[self.ID_WIDGET])
        row = item(self.LIBRARY, item_id)
        img = _load_rgb(self.LIBRARY, row, values.get(self.VARIANT_WIDGET),
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
    ID_TOOLTIP = '点击浏览服装图库，按中文、英文或编号搜索，再使用此服装。'
    DESCRIPTION = '中文服装图库：1,407 套，分类筛选与中英文搜索，输出完整 PNG 原图。'

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
    VARIANT_TOOLTIP = '同一姿势的五个机位，切换后输出对应原图。'
    ID_TOOLTIP = '点击浏览姿势图库，按系列、动作或编号搜索，每个姿势含五个机位。'
    RETURN_NAMES = ('image', 'width', 'height', 'pose_id', 'description', 'description_ja')
    DESCRIPTION = '中文姿势图库：288 个姿势 × 5 个机位（1,439 张），输出完整 PNG 原图。'

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

@routes.get('/ref_lookbook/web/{filename}')
async def web_route(request):
    filename = request.match_info['filename']
    if filename not in ('gallery.mjs', 'style.css', 'icon.svg', 'ref_gallery.js'):
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / 'web' / filename, headers={'Cache-Control': 'no-cache'})

@routes.get('/ref_lookbook/gallery')
async def gallery_route(request):
    return web.FileResponse(ROOT / 'web' / 'gallery.html', headers={'Cache-Control': 'no-cache'})

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


class CharacterRecipe(_GalleryNode):
    """三合一角色配方：一次取脸部、服装、姿势，输出三张图 + 横向参考拼图 + 中英文合成提示词。

    思路参考上游 ai-pose-gallery-zh 的「三合一合成配方」节点，字段换成我们六库的中文索引：
    脸部定长相与发型，服装定穿着，姿势定动作与构图，三者拼成一张参考整图直接丢给 img2img / ControlNet。
    """

    LIBRARY = 'face'
    ID_WIDGET = 'face_id'
    DEFAULT_ID = 'FACE-0001'
    FUNCTION = 'build_recipe'
    CATEGORY = 'image/Reference Gallery'
    DESCRIPTION = '三合一配方：脸部 + 服装 + 姿势，输出三张图、横向参考拼图与中英文合成提示词。'
    RETURN_TYPES = ('IMAGE', 'IMAGE', 'IMAGE', 'IMAGE', 'INT', 'INT', 'STRING', 'STRING')
    RETURN_NAMES = ('face_image', 'costume_image', 'pose_image', 'reference_sheet',
                    'width', 'height', 'prompt_zh', 'prompt_en')

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
            },
        }

    def _pose_library(self, values):
        return 'depth' if values.get('use_depth') else 'pose'

    @classmethod
    def IS_CHANGED(cls, **values):
        """三张图任一换图 / 换版本 / 改尺寸都要重算，缓存键必须覆盖整组参数。"""
        costume_lib = values.get('costume_library') or 'costume'
        pose_lib = 'depth' if values.get('use_depth') else 'pose'
        pose_id = str(values.get('pose_id') or 'POS-SEXY-P001')
        if pose_lib == 'depth':
            pose_id = pose_id.replace('POS-', 'DEP-', 1)
        parts = []
        for library, item_id, variant in (
                ('face', str(values.get('face_id') or cls.DEFAULT_ID), None),
                (costume_lib, str(values.get('costume_id') or 'SPR-0001'), None),
                (pose_lib, pose_id, values.get('pose_angle'))):
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
        """三个 ID 与服装库都要先校验；只查索引，不触发下载。"""
        try:
            item('face', str(values.get('face_id') or cls.DEFAULT_ID))
            library = values.get('costume_library') or 'costume'
            if library not in cls.COSTUME_LIBRARIES:
                return f'未知服装库：{library}'
            item(library, str(values.get('costume_id') or 'SPR-0001'))
            pose_id = str(values.get('pose_id') or 'POS-SEXY-P001')
            # 深度模式与出图时同一套换算：POS- → DEP-，否则校验会拿姿势编号去深度库查而判整条链失败。
            if values.get('use_depth'):
                item('depth', pose_id.replace('POS-', 'DEP-', 1))
            else:
                item('pose', pose_id)
        except ValueError as exc:
            return str(exc)
        return True

    def build_recipe(self, face_id=DEFAULT_ID, costume_id='SPR-0001', pose_id='POS-SEXY-P001',
                     style_preset='高清日系动漫', extra_prompt='', resize_mode=RESIZE_MODES[1],
                     width=1024, height=1280, flip_pose_horizontal=False,
                     pose_angle=None, costume_library='costume', use_depth=False):
        # 深度库编号与姿势库一一对应，只是前缀不同（POS- → DEP-），直接换前缀沿用同一套机位。
        pose_library = 'depth' if use_depth else 'pose'
        pose_key = pose_id.replace('POS-', 'DEP-', 1) if use_depth else pose_id

        face_row = item('face', str(face_id))
        costume_lib = costume_library if costume_library in self.COSTUME_LIBRARIES else 'costume'
        costume_row = item(costume_lib, str(costume_id))
        pose_row = item(pose_library, str(pose_key))

        face_img = _load_rgb('face', face_row, None, resize_mode, width, height, False)
        costume_img = _load_rgb(costume_lib, costume_row, None, resize_mode, width, height, False)
        pose_img = _load_rgb(pose_library, pose_row, pose_angle, resize_mode, width, height,
                             bool(flip_pose_horizontal))

        # 三张统一尺寸后横向拼成一张参考整图。原图尺寸模式下三张大小不一，
        # 统一按最大宽高居中裁剪，谁都不会被截断成一条边。
        panel_w = max(face_img.width, costume_img.width, pose_img.width)
        panel_h = max(face_img.height, costume_img.height, pose_img.height)
        sheet = Image.new('RGB', (panel_w * 3 + 24, panel_h), PANEL_BG)
        for index, panel in enumerate((face_img, costume_img, pose_img)):
            fitted = panel if panel.size == (panel_w, panel_h) else ImageOps.fit(
                panel, (panel_w, panel_h), method=_pil_resampling())
            sheet.paste(fitted, (index * (panel_w + 12), 0))

        style_zh, style_en = STYLE_PRESETS.get(style_preset, STYLE_PRESETS['高清日系动漫'])
        extra = (extra_prompt or '').strip()
        costume_label = '' if costume_lib == 'costume' else f'·{LIBRARIES[costume_lib]["label"]}'

        zh = [f'融合参考图生成一张完整的角色立绘：{style_zh}。',
              f'【人像与发型】{_describe_zh(face_row)}。',
              f'【服装{costume_label}】{_describe_zh(costume_row)}。',
              f'【动作与构图】{_describe_zh(pose_row)}。']
        if extra:
            zh.append(f'【补充细节】{extra}。')
        zh.append('要求面部自然生动，服装贴合身体动态，肢体透视与手部结构准确，光影统一。')

        # 英文只取有英文词条的库（目前只有服装），面部与姿势交给参考图本身，别硬翻日文。
        en = [style_en]
        costume_en = _describe_en(costume_row)
        if costume_en:
            en.append(f'wearing {costume_en}')
        en.append('match the face, hairstyle and pose from the reference sheet')
        if extra:
            en.append(extra)

        return (_to_tensor(face_img), _to_tensor(costume_img), _to_tensor(pose_img), _to_tensor(sheet),
                sheet.width, sheet.height, ''.join(zh), ', '.join(part for part in en if part))


NODE_CLASS_MAPPINGS = {'CostumeGallery': CostumeGallery, 'CostumeAnimeGallery': CostumeAnimeGallery,
                       'PoseGallery': PoseGallery, 'FaceGallery': FaceGallery,
                       'DepthGallery': DepthGallery, 'AnimeGallery': AnimeGallery,
                       'CharacterRecipe': CharacterRecipe}
NODE_DISPLAY_NAME_MAPPINGS = {
    'CostumeGallery': 'Costume Gallery 服装图库',
    'CostumeAnimeGallery': 'Costume Anime Gallery 服装动画图库',
    'PoseGallery': 'Pose Gallery 姿势图库',
    'FaceGallery': 'Face Gallery 脸部图库',
    'DepthGallery': 'Depth Gallery 深度姿势图库',
    'AnimeGallery': 'Anime Gallery 二次元图库',
    'CharacterRecipe': 'Character Recipe 三合一角色配方',
}
WEB_DIRECTORY = './web'
__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
