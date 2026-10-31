"""ComfyUI reference gallery: 服装 / 姿势 / 脸部。随仓库发行索引与内置缩略图，原图按需向作者站点取一次。"""
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
from .catalog import (ANGLES, LIBRARIES, OFFLINE_ENV, ROOT, asset, asset_by_id, describe, ensure_original,
                      item, local_path, meta, missing_originals, offline, pick, records, site)

class _GalleryNode:
    """三个图库共用同一套加载逻辑，差异只在索引、控件名与返回值命名。"""

    LIBRARY = 'costume'
    ID_WIDGET = 'costume_id'
    DEFAULT_ID = 'SPR-0001'
    ID_TOOLTIP = '点击浏览图库，按中文、编号或关键词搜索，再使用此素材。'
    ANGLE = False
    FUNCTION = 'load_costume'
    RETURN_TYPES = ('IMAGE', 'INT', 'INT', 'STRING', 'STRING', 'STRING')
    RETURN_NAMES = ('image', 'width', 'height', 'costume_id', 'description', 'keywords_en')
    CATEGORY = 'image/Reference Gallery'
    DESCRIPTION = ''

    @classmethod
    def INPUT_TYPES(cls):
        required = {cls.ID_WIDGET: ('STRING', {'default': cls.DEFAULT_ID, 'multiline': False, 'tooltip': cls.ID_TOOLTIP})}
        inputs = {'required': required}
        if cls.ANGLE:
            # 视角放 optional：界面上照样是下拉框，但 API 调用方不传这个键时不会整条链被判失败，
            # 缺省回落到列表第一个机位。
            inputs['optional'] = {
                'angle': (ANGLES, {'default': ANGLES[0], 'tooltip': '同一姿势的五个机位，切换后输出对应原图。'}),
            }
        return inputs

    @classmethod
    def _relative(cls, values):
        row = item(cls.LIBRARY, str(values[cls.ID_WIDGET]))
        return pick(row, '原图', values.get('angle'))

    @classmethod
    def _target(cls, values):
        """原图：本地有就直接用，没有则从上游取一次并缓存，之后完全离线。"""
        return ensure_original(cls.LIBRARY, cls._relative(values))

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
        if path.is_file():
            stat = path.stat()
            return f'{path.name}:{stat.st_mtime_ns}:{stat.st_size}'
        return f'{cls._relative(values)}:pending'

    def _load(self, **values):
        item_id = str(values[self.ID_WIDGET])
        row = item(self.LIBRARY, item_id)
        with Image.open(self._target(values)) as source:
            img = ImageOps.exif_transpose(source).convert('RGBA')
            img = Image.alpha_composite(Image.new('RGBA', img.size, 'white'), img).convert('RGB')
            width, height = img.size
            tensor = torch.from_numpy(np.asarray(img).astype(np.float32) / 255.0).unsqueeze(0)
        extra = row.get('英文关键词') or row.get('日文') or ''
        return tensor, width, height, item_id, describe(row), extra


class CostumeGallery(_GalleryNode):
    LIBRARY = 'costume'
    ID_WIDGET = 'costume_id'
    DEFAULT_ID = 'SPR-0001'
    ID_TOOLTIP = '点击浏览服装图库，按中文、英文或编号搜索，再使用此服装。'
    DESCRIPTION = '中文服装图库：1,407 套，分类筛选与中英文搜索，输出完整 PNG 原图。'

    def load_costume(self, **values):
        return self._load(**values)


class PoseGallery(_GalleryNode):
    LIBRARY = 'pose'
    ID_WIDGET = 'pose_id'
    DEFAULT_ID = 'POS-SEXY-P001'
    FUNCTION = 'load_pose'
    ANGLE = True
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
            'origin': {'site': site(library), 'template': LIBRARIES[library]['origin'],
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

ANGLE_SLUGS = {'正面': 'front', '俯视': 'high', '仰视': 'low', '侧面': 'side', '斜45°': '45deg'}

def import_to_input(library, item_id, angle, source):
    """把素材物化成 ComfyUI input 目录下的真实文件，供 LoadImage 等原生节点直接选用。

    文件名与素材 ID 一一对应，重复导入同一素材只会覆盖同一个文件，不会让 input 目录越滚越大。
    """
    suffix = f'_{ANGLE_SLUGS.get(angle, re.sub(r"[^0-9A-Za-z]", "", str(angle or "")))}'
    stem = re.sub(r'[^0-9A-Za-z._-]', '_', item_id)
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
        name = import_to_input(library, item_id, angle if angle in ANGLES else None, source)
    except ValueError as exc:
        return web.json_response({'error': str(exc)}, status=400)
    except FileNotFoundError as exc:
        return web.json_response({'error': str(exc)}, status=503)
    return web.json_response({'name': name, 'library': library, 'id': item_id, 'angle': angle,
                              'bytes': source.stat().st_size})

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

NODE_CLASS_MAPPINGS = {'CostumeGallery': CostumeGallery, 'PoseGallery': PoseGallery, 'FaceGallery': FaceGallery}
NODE_DISPLAY_NAME_MAPPINGS = {
    'CostumeGallery': 'Costume Gallery 服装图库',
    'PoseGallery': 'Pose Gallery 姿势图库',
    'FaceGallery': 'Face Gallery 脸部图库',
}
WEB_DIRECTORY = './web'
__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
