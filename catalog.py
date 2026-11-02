"""Reference assets: thumbs 随仓库内置，原图按“本地优先 → 上游取一次并缓存”获取。

六个图库共用根目录 library/，每个库一个同名子目录，内部结构完全一致：
  library/{costume,costume-anime,pose,face,depth,anime}/{thumbs,png,img}

仓库随包发行缩略图（thumbs，8,411 张 WebP，约 60 MB：服装 / 姿势 / 脸部三库原样取自上游仓库
sleepy-zone/ai-ref-library-cn 的内嵌缩略图，深度库、二次元库与服装动画库取自各自源站缩略图
并转 360 px WebP，画面均未改）：
  * 图库界面与节点预览读内置缩略图，离线开箱可览；
  * 原图（png）与全尺寸预览（img）不进仓库：节点出图或看大图时按
    “本地优先 → 上游下载并缓存到 library/{库}/png/”的顺序取，用过的原图落盘后完全离线；
  * 用户自己把原图放进对应目录即可完全离线，此时一次网络请求都不会发；
  * 上游站点与素材授权见 NOTICE.md，原图版权归上游作者，本仓库不分发原图。
"""
import json
import os
import shutil
import threading
import urllib.error
import urllib.request
from functools import lru_cache
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LIBRARY = Path(os.environ.get('COMFYUI_REF_LOOKBOOK_LIBRARY', ROOT / 'library')).resolve()
FIELDS = {'png': '原图', 'img': '预览图', 'thumbs': '缩略图'}
ANGLES = ['正面', '俯视', '仰视', '侧面', '斜45°']
# 二次元库的形态维度不是机位，而是彩图 / 线稿（只有姿势两种都有）。
VARIANTS = ['彩图', '线稿']
THUMB_WIDTH = int(os.environ.get('COMFYUI_REF_LOOKBOOK_THUMB_WIDTH', '360'))
THUMB_QUALITY = 78
THUMB_WORKERS = int(os.environ.get('COMFYUI_REF_LOOKBOOK_THUMB_WORKERS', '8'))

LIBRARIES = {
    'costume': {'label': '服装', 'index': 'costume-zh.json', 'meta': 'meta-zh.json', 'base': 'costume',
                'site': 'https://ai-costume-gallery.pages.dev/',
                'origin': 'https://ai-costume-gallery.pages.dev/png/{stem}.png',
                'thumb': 'https://ai-costume-gallery.pages.dev/thumbs/{stem}.webp'},
    # 服装动画版：与写实服装同一批 8 个分类、同一套编号（SPR / SUM / …），但是另一个站、
    # 另一批图，数量也不同（1,407 / 1,320），上游明确不做互补。所以是独立库，不能做形态维度。
    # 编号空间重合 → 导入 ComfyUI input 目录时文件名要带库前缀，见 __init__.LIB_TAG。
    'costume-anime': {'label': '服装动画', 'index': 'costume-anime-zh.json', 'meta': 'meta-costume-anime.json',
                      'base': 'costume-anime',
                      'site': 'https://ai-costume-anime-gallery.pages.dev/',
                      'origin': 'https://ai-costume-anime-gallery.pages.dev/png/{stem}.png',
                      'thumb': 'https://ai-costume-anime-gallery.pages.dev/thumbs/{stem}.webp'},
    'pose': {'label': '姿势', 'index': 'pose-zh.json', 'meta': 'meta-pose.json', 'base': 'pose',
             'site': 'https://ai-pose-gallery.pages.dev/',
             'origin': 'https://ai-pose-gallery.pages.dev/img/{stem}.png',
             'thumb': 'https://ai-pose-gallery.pages.dev/thumbs/{stem}.jpg'},
    'face': {'label': '脸部', 'index': 'face-zh.json', 'meta': 'meta-face.json', 'base': 'face',
             'site': 'https://ai-portrait-gallery.pages.dev/',
             'origin': 'https://ai-portrait-gallery.pages.dev/img/full/{stem}.png',
             'thumb': 'https://ai-portrait-gallery.pages.dev/img/thumb/{stem}.webp'},
    # 深度姿势：与姿势库同一批 288 个姿势 / 1439 个文件名，只是换了域名与图片内容。
    'depth': {'label': '深度姿势', 'index': 'depth-zh.json', 'meta': 'meta-depth.json', 'base': 'depth',
              'site': 'https://ai-pose-depth-gallery.pages.dev/',
              'origin': 'https://ai-pose-depth-gallery.pages.dev/img/{stem}.png',
              'thumb': 'https://ai-pose-depth-gallery.pages.dev/thumbs/{stem}.jpg'},
    # 二次元：发型 / 眼睛 / 服装 / 姿势混在一个库里，用「分类」区分。
    # 形态不是机位而是「彩图 / 线稿」，姿势才有线稿，所以原图字段对姿势是 dict、其余是字符串。
    # 线稿在源站是另一条路径（line/<源ID>.png），且没有现成缩略图：thumb 回退也走 line，
    # 由 _write_thumb 现转 WebP。本地文件名是 <源ID>_line，拼地址时要去掉 _line 后缀。
    'anime': {'label': '二次元', 'index': 'anime-zh.json', 'meta': 'meta-anime.json', 'base': 'anime',
              'site': 'https://charadb-2fi.pages.dev/',
              'origin': 'https://charadb-2fi.pages.dev/img/{stem}.jpg',
              'line_origin': 'https://charadb-2fi.pages.dev/line/{stem}.png',
              'thumb': 'https://charadb-2fi.pages.dev/thumb/{stem}.webp'},
}
DEFAULT_LIBRARY = 'costume'

# 断网 / 内网环境：设为 1 时只用本地原图，缺失直接报错并给出下载地址。
OFFLINE_ENV = 'COMFYUI_REF_LOOKBOOK_OFFLINE'
TIMEOUT = float(os.environ.get('COMFYUI_REF_LOOKBOOK_TIMEOUT', '60'))
USER_AGENT = 'comfyui-ref-lookbook/1.0 (+https://github.com/)'
_MAGIC = {'.png': b'\x89PNG\r\n\x1a\n', '.webp': b'RIFF', '.jpg': b'\xff\xd8\xff'}
# 图库一屏会同时请求几十张缩略图、连翻大图也会连续触发原图获取，都必须限并发，
# 免得上百个请求同时打过去把源站和自己都拖垮。
# 原图并发默认 12：实测源站在 12 路才到吞吐拐点（1 路 0.6 张/秒、12 路 4.9 张/秒，
# 20 路与 12 路持平），单张约 90 KB，12 路合计不到 0.5 MB/s，属于普通浏览的量级。
ORIGIN_ENV = 'COMFYUI_REF_LOOKBOOK_ORIGIN_SLOTS'
ORIGIN_SLOTS = max(1, min(32, int(os.environ.get(ORIGIN_ENV, '12'))))
_thumb_slots = threading.BoundedSemaphore(max(1, THUMB_WORKERS))
_origin_slots = threading.BoundedSemaphore(ORIGIN_SLOTS)
_locks = {}
_locks_guard = threading.Lock()


class _path_lock:
    """同一张图串行、不同图并行。全局单锁会让连翻大图整体排队。"""

    def __init__(self, key):
        self.key = key

    def __enter__(self):
        with _locks_guard:
            self.lock = _locks.setdefault(self.key, threading.Lock())
        self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()
        return False


def library_info(library=DEFAULT_LIBRARY):
    try:
        return LIBRARIES[library]
    except KeyError:
        raise ValueError(f'未知图库：{library}') from None


@lru_cache(maxsize=None)
def records(library=DEFAULT_LIBRARY):
    info = library_info(library)
    source = LIBRARY / 'data' / info['index']
    if not source.is_file():
        raise FileNotFoundError(
            f'{info["label"]}索引缺失：library/data/{info["index"]}，请更新或重新安装完整 comfyui-ref-lookbook 节点。')
    data = json.loads(source.read_text(encoding='utf-8'))
    if not isinstance(data, list) or not data:
        raise ValueError(f'{info["label"]}索引为空或格式错误')
    return data


@lru_cache(maxsize=None)
def index(library=DEFAULT_LIBRARY):
    return {row['id']: row for row in records(library)}


@lru_cache(maxsize=None)
def meta(library=DEFAULT_LIBRARY):
    source = LIBRARY / 'data' / library_info(library)['meta']
    if not source.is_file():
        return {'total': len(records(library))}
    return json.loads(source.read_text(encoding='utf-8'))


def item(library, item_id):
    try:
        return index(library)[item_id]
    except KeyError:
        raise ValueError(f'未知{library_info(library)["label"]} ID：{item_id}') from None


def costume(costume_id):
    return item(DEFAULT_LIBRARY, costume_id)


def describe(row):
    """分类 / 二级分类 / 中文关键词；服装节点输出与旧版保持一致。"""
    head = ' / '.join(part for part in (row.get('分类'), row.get('分类2')) if part)
    words = row.get('关键词') or []
    return head + ' / ' + '、'.join(words) if words else head


def variant_values(library):
    """该库的形态维度取值：姿势与深度姿势是五个机位，二次元是彩图 / 线稿，其余库没有这一维。"""
    if library in ('pose', 'depth'):
        return list(ANGLES)
    if library == 'anime':
        return list(VARIANTS)
    return []


def pick(row, field, angle=None):
    """姿势记录按视角保存素材路径，其余记录是单一路径。"""
    value = row[field]
    if isinstance(value, str):
        return value
    if angle in value:
        return value[angle]
    return next(iter(value.values()))


def _relative(library, kind, filename):
    return f'{library_info(library)["base"]}/{kind}/{filename}'


def _allowlisted(library, relative):
    field = FIELDS[Path(relative).parent.name]
    for row in records(library):
        value = row.get(field)
        if value is None:
            continue
        if relative in value.values() if isinstance(value, dict) else value == relative:
            return True
    return False


def _line_url(library, relative):
    """二次元线稿的源站地址：本地叫 <源ID>_line，源站是 line/<源ID>.png。"""
    info = library_info(library)
    stem = Path(relative).stem
    if not info.get('line_origin') or not stem.endswith('_line'):
        return None
    return info['line_origin'].format(stem=stem[:-len('_line')])


def origin_url(library, relative):
    """上游原图地址：由素材文件名（不含扩展名）拼出，各站点规则不同但都只认文件名。"""
    return _line_url(library, relative) or library_info(library)['origin'].format(stem=Path(relative).stem)


def thumb_url(library, relative):
    """上游缩略图地址。各站点路径各不相同（webp / jpg / img-thumb），缓存到本地后统一成 WebP。

    二次元线稿在源站没有现成缩略图，回退到线稿原图（PNG），由 _write_thumb 现转码。
    """
    return _line_url(library, relative) or library_info(library)['thumb'].format(stem=Path(relative).stem)


def site(library):
    return library_info(library)['site']


def offline():
    return os.environ.get(OFFLINE_ENV, '').strip().lower() in ('1', 'true', 'yes', 'on')


def local_path(relative):
    """素材在图库内的绝对路径，顺带挡住目录穿越。"""
    target = (LIBRARY / relative).resolve()
    if not target.is_relative_to(LIBRARY):
        raise ValueError('图片不在图库中')
    return target


def asset(kind, filename, library=DEFAULT_LIBRARY, remote=False):
    """取素材。remote=False 只读本地；remote=True 时缩略图与原图允许向上游取一次。"""
    if kind not in FIELDS or Path(filename).name != filename or '\\' in filename:
        raise ValueError('无效图片路径')
    relative = _relative(library, kind, filename)
    if not _allowlisted(library, relative):
        raise ValueError('图片不在图库中')
    target = local_path(relative)
    if not target.is_file():
        if remote and kind == 'png':
            return ensure_original(library, relative)
        if remote and kind == 'thumbs':
            return ensure_thumb(library, relative)
        raise FileNotFoundError(
            f'图片缺失：library/{relative}。缩略图（library/*/thumbs）随仓库发行，缺失说明安装不完整；'
            '原图（library/*/png）不随仓库分发，节点出图时会自动从作者站点获取，也可自行下载放入该路径。')
    return target


def asset_by_id(library, item_id, kind='png', angle=None, remote=False):
    """按记录 ID 取素材，供节点预览使用（姿势需要带视角）。"""
    row = item(library, item_id)
    if kind not in FIELDS:
        raise ValueError('无效图片路径')
    return asset(kind, Path(pick(row, FIELDS[kind], angle)).name, library, remote)


def ensure_original(library, relative):
    """本地原图优先；缺失时从上游下载并缓存到 library/{库}/png/，下次直接命中。"""
    target = local_path(relative)
    if target.is_file() and target.stat().st_size > 0:
        return target
    url = origin_url(library, relative)
    hint = (f'缺少原图 library/{relative}。\n'
            f'可手动下载后放到该路径（授权允许个人保存）：{url}\n'
            f'或关闭环境变量 {OFFLINE_ENV} 让节点自动获取。')
    if offline():
        raise FileNotFoundError(hint)
    try:
        _download(url, target)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        raise FileNotFoundError(f'{hint}\n自动获取失败：{exc}') from None
    return target


def _download(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with _path_lock(str(target)):
        if target.is_file() and target.stat().st_size > 0:
            return
        try:
            with _origin_slots:
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(part, 'wb') as handle:
                    shutil.copyfileobj(response, handle)
            magic = _MAGIC.get(target.suffix.lower())
            head = part.read_bytes()[:len(magic)] if magic else None
            if magic and head != magic:
                raise ValueError('上游返回的不是图片，可能被网络劫持或文件已下架')
            if part.stat().st_size < 1024:
                raise ValueError('下载内容过小，疑似失败')
            os.replace(part, target)
        except BaseException:
            part.unlink(missing_ok=True)
            raise


def ensure_thumb(library, relative):
    """缩略图本地优先；缺失时从上游取一次，统一缩放到 THUMB_WIDTH 的 WebP 后缓存。

    上游三个站点的缩略图格式不一样（WebP / JPG / WebP），缓存文件名一律是索引里的 .webp，
    所以这里必须真正转码，不能直接把字节落盘。
    """
    target = local_path(relative)
    if target.is_file() and target.stat().st_size > 0:
        return target
    url = thumb_url(library, relative)
    hint = (f'缺少缩略图 library/{relative}。\n'
            f'联网后打开图库会自动获取并缓存：{url}\n'
            f'也可以手动下载原图放到 library/{_relative(library, "png", Path(relative).stem + ".png")}，'
            f'或关闭环境变量 {OFFLINE_ENV} 让节点自动获取。')
    if offline():
        raise FileNotFoundError(hint)
    with _path_lock(relative):
        if target.is_file() and target.stat().st_size > 0:
            return target
        try:
            with _thumb_slots:
                _fetch_thumb(url, target)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            raise FileNotFoundError(f'{hint}\n自动获取失败：{exc}') from None
    return target


def _fetch_thumb(url, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = response.read()
        if len(payload) < 1024:
            raise ValueError('下载内容过小，疑似失败')
        if not _looks_like_image(payload):
            raise ValueError('上游返回的不是图片，可能被网络劫持或文件已下架')
        _write_thumb(payload, part)
        os.replace(part, target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def _looks_like_image(payload):
    return (payload[:8] == _MAGIC['.png'] or payload[:3] == _MAGIC['.jpg']
            or payload[:4] == _MAGIC['.webp'])


def _write_thumb(payload, part):
    from PIL import Image  # 只有真的需要转码时才用 Pillow，纯读索引的调用方不受影响
    with Image.open(BytesIO(payload)) as source:
        img = source.convert('RGB')
        if img.width > THUMB_WIDTH:
            height = max(1, round(img.height * THUMB_WIDTH / img.width))
            img = img.resize((THUMB_WIDTH, height), Image.LANCZOS)
        img.save(part, 'WEBP', quality=THUMB_QUALITY, method=4)


def missing_originals(library=DEFAULT_LIBRARY):
    """返回该库尚未缓存的原图条数，供设置面板/自检使用。"""
    total = 0
    for row in records(library):
        value = row['原图']
        names = value.values() if isinstance(value, dict) else [value]
        total += sum(1 for name in names if not local_path(name).is_file())
    return total


__all__ = ['ANGLES', 'DEFAULT_LIBRARY', 'FIELDS', 'LIBRARIES', 'LIBRARY', 'ROOT', 'OFFLINE_ENV',
           'THUMB_WIDTH', 'asset', 'asset_by_id', 'costume', 'describe', 'ensure_original',
           'ensure_thumb', 'index', 'item', 'library_info', 'local_path', 'meta', 'missing_originals',
           'offline', 'origin_url', 'pick', 'records', 'site', 'thumb_url']
