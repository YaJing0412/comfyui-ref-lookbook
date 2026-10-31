import importlib.util
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

spec = importlib.util.spec_from_file_location('catalog', Path(__file__).resolve().parents[1] / 'catalog.py')
catalog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(catalog)


def clear():
    for cached in (catalog.records, catalog.index, catalog.meta):
        cached.cache_clear()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_library = catalog.LIBRARY
        catalog.LIBRARY = Path(self.temp.name)
        (catalog.LIBRARY / 'data').mkdir()
        for kind in catalog.FIELDS: (catalog.LIBRARY / 'costume' / kind).mkdir(parents=True)
        row = {'id': 'SPR-0001', '原图': 'costume/png/SPR-0001.png', '预览图': 'costume/img/SPR-0001.webp', '缩略图': 'costume/thumbs/SPR-0001.webp'}
        (catalog.LIBRARY / 'data/costume-zh.json').write_text(json.dumps([row]))
        for field in catalog.FIELDS.values(): (catalog.LIBRARY / row[field]).write_bytes(b'fixture')
        clear()

    def tearDown(self):
        catalog.LIBRARY = self.old_library
        clear()
        self.temp.cleanup()

    def test_all_three_versions_are_allowlisted(self):
        for kind, name in [('png','SPR-0001.png'), ('img','SPR-0001.webp'), ('thumbs','SPR-0001.webp')]:
            self.assertEqual(catalog.asset(kind,name).read_bytes(),b'fixture')

    def test_rejects_unknown_paths_ids_and_extensions(self):
        for kind,name in [('png','../SPR-0001.png'),('png','SPR-0001.webp'),('data','costume-zh.json'),('png','SPR-9999.png'),('png','..\\SPR-0001.png'),('png','/etc/passwd')]:
            with self.subTest(kind=kind,name=name), self.assertRaises(ValueError): catalog.asset(kind,name)

    def test_missing_original_points_to_upstream(self):
        (catalog.LIBRARY/'costume/png/SPR-0001.png').unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'library/costume/png/SPR-0001.png.*thumbs'):
            catalog.asset('png','SPR-0001.png')

    @unittest.skipIf(os.name == 'nt', 'Windows 默认不允许普通用户创建符号链接')
    def test_external_symlink_is_rejected(self):
        p=catalog.LIBRARY/'costume/png/SPR-0001.png';p.unlink();p.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError): catalog.asset('png','SPR-0001.png')

    def test_metadata_cannot_allow_external_path(self):
        row={'id':'SPR-0001','原图':'../secret.png'}
        (catalog.LIBRARY/'data/costume-zh.json').write_text(json.dumps([row]));clear()
        with self.assertRaises(ValueError): catalog.asset('png','SPR-0001.png')


class PoseLibraryTests(unittest.TestCase):
    """姿势记录按视角保存素材路径，编号与服装库互不干扰。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_library = catalog.LIBRARY
        catalog.LIBRARY = Path(self.temp.name)
        (catalog.LIBRARY / 'data').mkdir()
        for kind in catalog.FIELDS:
            for library in ('costume', 'pose', 'face'):
                (catalog.LIBRARY / library / kind).mkdir(parents=True)
        angles = {'正面': 'front', '侧面': 'side'}
        row = {
            'id': 'POS-SEXY-P001', '分类': '全身 · 性感系', '分类2': '站立',
            '关键词': ['S形站姿', '腰向侧顶出'], '日文': 'S字立ち', '视角': ['正面', '侧面'],
            '封面': 'pose/thumbs/full_sexy_P001_front.webp',
            '原图': {a: f'pose/png/full_sexy_P001_{e}.png' for a, e in angles.items()},
            '预览图': {a: f'pose/img/full_sexy_P001_{e}.webp' for a, e in angles.items()},
            '缩略图': {a: f'pose/thumbs/full_sexy_P001_{e}.webp' for a, e in angles.items()},
        }
        (catalog.LIBRARY / 'data/pose-zh.json').write_text(json.dumps([row], ensure_ascii=False))
        for kind in catalog.FIELDS:
            for value in row[catalog.FIELDS[kind]].values():
                (catalog.LIBRARY / value).write_bytes(b'pose-fixture')
        clear()

    def tearDown(self):
        catalog.LIBRARY = self.old_library
        clear()
        self.temp.cleanup()

    def test_every_angle_is_allowlisted(self):
        for name in ('full_sexy_P001_front.png', 'full_sexy_P001_side.png'):
            self.assertEqual(catalog.asset('png', name, 'pose').read_bytes(), b'pose-fixture')
        self.assertEqual(catalog.asset('thumbs', 'full_sexy_P001_front.webp', 'pose').read_bytes(), b'pose-fixture')

    def test_pose_asset_is_not_visible_to_other_libraries(self):
        other = {'id': 'FACE-0001', '原图': 'png/FACE-0001.png', '预览图': 'img/FACE-0001.webp',
                 '缩略图': 'thumbs/FACE-0001.webp'}
        for library in ('costume', 'face'):
            (catalog.LIBRARY / f'data/{library}-zh.json').write_text(json.dumps([other]), encoding='utf-8')
            for kind in catalog.FIELDS:
                name = 'FACE-0001.png' if kind == 'png' else 'FACE-0001.webp'
                # 各库都在同名子目录下，没有任何库平铺在 library/ 根
                (catalog.LIBRARY / library / kind / name).write_bytes(b'x')
        clear()
        for library in ('costume', 'face'):
            with self.subTest(library=library), self.assertRaises(ValueError):
                catalog.asset('png', 'full_sexy_P001_front.png', library)

    def test_asset_by_id_follows_angle_and_defaults_to_first(self):
        self.assertEqual(catalog.asset_by_id('pose', 'POS-SEXY-P001', 'png', '侧面').name, 'full_sexy_P001_side.png')
        self.assertEqual(catalog.asset_by_id('pose', 'POS-SEXY-P001', 'png').name, 'full_sexy_P001_front.png')
        self.assertEqual(catalog.asset_by_id('pose', 'POS-SEXY-P001', 'png', '不存在').name, 'full_sexy_P001_front.png')

    def test_unknown_id_and_library_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '未知姿势 ID'):
            catalog.asset_by_id('pose', 'POS-SEXY-P999', 'png')
        with self.assertRaisesRegex(ValueError, '未知图库'):
            catalog.asset_by_id('animal', 'POS-SEXY-P001', 'png')

    def test_describe_keeps_two_level_category(self):
        row = catalog.item('pose', 'POS-SEXY-P001')
        self.assertEqual(catalog.describe(row), '全身 · 性感系 / 站立 / S形站姿、腰向侧顶出')


class OriginFetchTests(unittest.TestCase):
    """仓库只发行缩略图：原图本地优先，缺失时按上游规则取一次并缓存。"""

    PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 2048

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_library = catalog.LIBRARY
        catalog.LIBRARY = Path(self.temp.name)
        (catalog.LIBRARY / 'data').mkdir()
        self.row = {'id': 'SPR-0001', '原图': 'costume/png/SPR-0001.png',
                    '预览图': 'costume/img/SPR-0001.webp', '缩略图': 'costume/thumbs/SPR-0001.webp'}
        (catalog.LIBRARY / 'data/costume-zh.json').write_text(json.dumps([self.row]))
        (catalog.LIBRARY / 'costume' / 'thumbs').mkdir(parents=True)
        (catalog.LIBRARY / 'costume/thumbs/SPR-0001.webp').write_bytes(b'thumb')
        clear()

    def tearDown(self):
        catalog.LIBRARY = self.old_library
        os.environ.pop(catalog.OFFLINE_ENV, None)
        clear()
        self.temp.cleanup()

    def test_origin_urls_follow_each_site_layout(self):
        self.assertEqual(catalog.origin_url('costume', 'costume/png/SPR-0001.png'),
                         'https://ai-costume-gallery.pages.dev/png/SPR-0001.png')
        self.assertEqual(catalog.origin_url('pose', 'pose/png/full_sexy_P001_front.png'),
                         'https://ai-pose-gallery.pages.dev/img/full_sexy_P001_front.png')
        self.assertEqual(catalog.origin_url('face', 'face/png/f000a1c4200.png'),
                         'https://ai-portrait-gallery.pages.dev/img/full/f000a1c4200.png')

    def test_local_original_wins_without_network(self):
        local = catalog.local_path('costume/png/SPR-0001.png')
        local.parent.mkdir(parents=True)
        local.write_bytes(self.PNG)
        with unittest.mock.patch('urllib.request.urlopen', side_effect=AssertionError('不该联网')):
            self.assertEqual(catalog.ensure_original('costume', 'costume/png/SPR-0001.png'), local)

    def test_missing_original_is_downloaded_once(self):
        source = Path(self.temp.name) / 'upstream.png'
        source.write_bytes(self.PNG)
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(getattr(request, 'full_url', request))
            return open(source, 'rb')

        with unittest.mock.patch('urllib.request.urlopen', side_effect=fake_urlopen):
            first = catalog.ensure_original('costume', 'costume/png/SPR-0001.png')
            second = catalog.ensure_original('costume', 'costume/png/SPR-0001.png')
        self.assertEqual(first.read_bytes(), self.PNG)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1, '第二次应命中本地缓存')
        self.assertEqual(calls[0], 'https://ai-costume-gallery.pages.dev/png/SPR-0001.png')
        self.assertFalse(list((catalog.LIBRARY / 'costume' / 'png').glob('*.part')))

    def test_non_image_response_is_rejected(self):
        source = Path(self.temp.name) / 'blocked.html'
        source.write_bytes(b'<html>404</html>' + b' ' * 2048)
        with unittest.mock.patch('urllib.request.urlopen', return_value=open(source, 'rb')):
            with self.assertRaisesRegex(FileNotFoundError, '自动获取失败'):
                catalog.ensure_original('costume', 'costume/png/SPR-0001.png')
        self.assertFalse(catalog.local_path('costume/png/SPR-0001.png').exists())
        self.assertFalse(list((catalog.LIBRARY / 'costume' / 'png').glob('*.part')))

    def test_offline_mode_explains_manual_download(self):
        os.environ[catalog.OFFLINE_ENV] = '1'
        with unittest.mock.patch('urllib.request.urlopen', side_effect=AssertionError('离线不该联网')):
            with self.assertRaisesRegex(FileNotFoundError, 'ai-costume-gallery.pages.dev/png/SPR-0001.png'):
                catalog.ensure_original('costume', 'costume/png/SPR-0001.png')

    def test_asset_remote_flag_controls_fetch(self):
        source = Path(self.temp.name) / 'upstream.png'
        source.write_bytes(self.PNG)
        with self.assertRaises(FileNotFoundError):
            catalog.asset('png', 'SPR-0001.png')  # 默认只读本地
        with unittest.mock.patch('urllib.request.urlopen', return_value=open(source, 'rb')):
            self.assertEqual(catalog.asset('png', 'SPR-0001.png', remote=True).read_bytes(), self.PNG)


class ThumbFetchTests(unittest.TestCase):
    """缩略图也不进仓库：首次浏览时取一次、缩到统一尺寸转 WebP 后缓存。"""

    def setUp(self):
        from PIL import Image
        from io import BytesIO
        self.temp = tempfile.TemporaryDirectory()
        self.old_library = catalog.LIBRARY
        catalog.LIBRARY = Path(self.temp.name)
        (catalog.LIBRARY / 'data').mkdir()
        (catalog.LIBRARY / 'costume' / 'thumbs').mkdir(parents=True)
        row = {'id': 'SPR-0001', '原图': 'costume/png/SPR-0001.png',
               '预览图': 'costume/img/SPR-0001.webp', '缩略图': 'costume/thumbs/SPR-0001.webp'}
        (catalog.LIBRARY / 'data/costume-zh.json').write_text(json.dumps([row]))
        buffer = BytesIO()
        Image.new('RGB', (900, 1350), (200, 180, 160)).save(buffer, 'JPEG', quality=80)
        self.jpeg = buffer.getvalue()
        clear()

    def tearDown(self):
        catalog.LIBRARY = self.old_library
        os.environ.pop(catalog.OFFLINE_ENV, None)
        clear()
        self.temp.cleanup()

    def test_thumb_urls_follow_each_site_layout(self):
        self.assertEqual(catalog.thumb_url('costume', 'costume/thumbs/SPR-0001.webp'),
                         'https://ai-costume-gallery.pages.dev/thumbs/SPR-0001.webp')
        self.assertEqual(catalog.thumb_url('pose', 'pose/thumbs/full_sexy_P001_front.webp'),
                         'https://ai-pose-gallery.pages.dev/thumbs/full_sexy_P001_front.jpg')
        self.assertEqual(catalog.thumb_url('face', 'face/thumbs/f000a1c4200.webp'),
                         'https://ai-portrait-gallery.pages.dev/img/thumb/f000a1c4200.webp')

    def test_missing_thumb_is_downloaded_converted_and_cached(self):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append(getattr(request, 'full_url', request))
            from io import BytesIO
            return BytesIO(self.jpeg)

        with unittest.mock.patch('urllib.request.urlopen', side_effect=fake_urlopen):
            first = catalog.ensure_thumb('costume', 'costume/thumbs/SPR-0001.webp')
            second = catalog.ensure_thumb('costume', 'costume/thumbs/SPR-0001.webp')

        from PIL import Image
        with Image.open(first) as img:
            self.assertEqual(img.format, 'WEBP', '上游给 JPEG 也要统一成 WebP')
            self.assertEqual(img.width, catalog.THUMB_WIDTH)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1, '第二次应命中本地缓存')
        self.assertEqual(calls[0], 'https://ai-costume-gallery.pages.dev/thumbs/SPR-0001.webp')
        self.assertFalse(list((catalog.LIBRARY / 'costume' / 'thumbs').glob('*.part')))

    def test_asset_route_flag_controls_thumb_fetch(self):
        with self.assertRaises(FileNotFoundError):
            catalog.asset('thumbs', 'SPR-0001.webp')  # 只读本地时不应联网
        with unittest.mock.patch('urllib.request.urlopen', side_effect=lambda *a, **k: __import__('io').BytesIO(self.jpeg)):
            path = catalog.asset('thumbs', 'SPR-0001.webp', remote=True)
        self.assertTrue(path.is_file())

    def test_offline_mode_points_at_manual_placement(self):
        os.environ[catalog.OFFLINE_ENV] = '1'
        with self.assertRaisesRegex(FileNotFoundError, 'library/costume/thumbs/SPR-0001.webp|library/costume'):
            catalog.ensure_thumb('costume', 'costume/thumbs/SPR-0001.webp')

    def test_html_error_page_is_rejected(self):
        from io import BytesIO
        blocked = BytesIO(b'<html>404</html>' + b' ' * 2048)
        with unittest.mock.patch('urllib.request.urlopen', return_value=blocked):
            with self.assertRaisesRegex(FileNotFoundError, '自动获取失败'):
                catalog.ensure_thumb('costume', 'costume/thumbs/SPR-0001.webp')
        self.assertFalse((catalog.LIBRARY / 'costume/thumbs/SPR-0001.webp').exists())
