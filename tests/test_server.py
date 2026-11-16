"""独立 HTTP 服务（server.py）的路由与安全测试。

起真实监听（127.0.0.1 随机端口），全部用本地已有的缩略图，不发任何上游请求。
"""
import json
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

from server import WEB_FILES, Handler, Server, export_to_file

ROOT = Path(__file__).resolve().parent.parent


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # 302 就停在 302，别自动跟到 gallery


_opener = urllib.request.build_opener(NoRedirect)


def get(path, method='GET', payload=None):
    url = f'http://127.0.0.1:{SERVER.server_address[1]}{path}'
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    try:
        with _opener.open(request, timeout=30) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


SERVER = Server(('127.0.0.1', 0), Handler)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()


class ServerTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        SERVER.shutdown()
        SERVER.server_close()

    def test_root_redirects_to_gallery(self):
        status, headers, _ = get('/')
        self.assertEqual(status, 302)
        self.assertEqual(headers['Location'], '/ref_lookbook/gallery')

    def test_gallery_page_and_whitelisted_assets(self):
        status, headers, body = get('/ref_lookbook/gallery')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertIn('参考图库', body.decode('utf-8'))
        for name in WEB_FILES:
            status, _, _ = get(f'/ref_lookbook/web/{name}')
            self.assertEqual(status, 200, name)

    def test_web_whitelist_blocks_other_files(self):
        status, _, _ = get('/ref_lookbook/web/server.py')
        self.assertEqual(status, 404)

    def test_catalog_returns_all_records(self):
        for library, count in (('costume', 1407), ('costume-anime', 1320), ('pose', 288),
                               ('face', 1498), ('depth', 288), ('anime', 1027)):
            status, _, body = get(f'/ref_lookbook/catalog/{library}')
            payload = json.loads(body)
            self.assertEqual(status, 200, library)
            self.assertEqual(len(payload['records']), count, library)
        status, _, body = get('/ref_lookbook/catalog/anime')
        self.assertIn('line/', json.loads(body)['origin']['line_template'])

    def test_catalog_unknown_library_is_404(self):
        status, _, _ = get('/ref_lookbook/catalog/nope')
        self.assertEqual(status, 404)

    def test_thumbs_served_with_content_type(self):
        status, headers, body = get('/ref_lookbook/assets/costume-anime/thumbs/SPR-0001.webp')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/webp')
        self.assertEqual(body[:4], b'RIFF')

    def test_asset_by_id_reads_local_thumb(self):
        status, headers, _ = get('/ref_lookbook/asset/costume-anime/thumbs/SPR-0001')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/webp')

    def test_traversal_attempts_do_not_leak_files(self):
        for path in ('/ref_lookbook/assets/costume/thumbs/..%2F..%2Fserver.py',
                     '/ref_lookbook/assets/costume/thumbs/%2e%2e%2fserver.py',
                     '/ref_lookbook/assets/../../../server.py'):
            status, _, _ = get(path)
            self.assertEqual(status, 404, path)

    def test_unknown_route_is_404_json(self):
        status, _, body = get('/ref_lookbook/nothing')
        self.assertEqual(status, 404)
        self.assertIn('error', json.loads(body))

    def test_status_reports_all_libraries(self):
        status, _, body = get('/ref_lookbook/status')
        report = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(set(report['libraries']),
                         {'costume', 'costume-anime', 'pose', 'face', 'depth', 'anime', 'mio'})

    def test_mio_page_is_standalone_and_served(self):
        """mio 有独立页面（不进六库页签）：正反斜杠两种写法都能开，页面引用都是绝对路径。"""
        for path in ('/ref_lookbook/mio', '/ref_lookbook/mio/'):
            status, headers, body = get(path)
            with self.subTest(path=path):
                self.assertEqual(status, 200)
                self.assertIn('text/html', headers['Content-Type'])
                self.assertIn('设计档案', body.decode('utf-8'))
        for name in ('mio.mjs', 'mio.css'):
            self.assertEqual(get(f'/ref_lookbook/web/{name}')[0], 200, name)

    def test_primary_menu_has_two_libraries(self):
        """一级菜单只有日系图库 / 澪图库两项，两个页面各有一份，当前页要标 aria-current。

        菜单靠 HTML 手写（不是 JS 生成），改坏了浏览器也不会报错，这条测试就是防这个。
        """
        cases = (('/ref_lookbook/gallery', '日系图库', '/ref_lookbook/mio'),
                 ('/ref_lookbook/mio', '澪图库', '/ref_lookbook/gallery'))
        for path, current, other in cases:
            status, _, body = get(path)
            text = body.decode('utf-8')
            with self.subTest(path=path):
                self.assertEqual(status, 200)
                self.assertIn('class="lib-nav"', text)
                block = text.split('class="lib-nav"', 1)[1].split('</nav>', 1)[0]
                self.assertEqual(block.count('<a '), 2, block)
                self.assertIn('日系图库', block)
                self.assertIn('澪图库', block)
                self.assertIn(other, block)
                # 当前页的那一项带 aria-current="page"
                items = [item.split('</a>', 1)[0] for item in block.split('<a ')[1:]]
                marked = [item for item in items if 'aria-current="page"' in item]
                self.assertEqual(len(marked), 1, items)
                self.assertIn(current, marked[0])

    def test_mio_catalog_and_jpeg_asset(self):
        status, _, body = get('/ref_lookbook/catalog/mio')
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload['records']), 387)
        self.assertEqual(len(payload['meta']['volumes']), 43)
        status, headers, _ = get('/ref_lookbook/assets/mio/thumbs/hair-01-01.jpg')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/jpeg')

    def test_mio_is_excluded_from_bulk_download(self):
        """mio 的图随仓库内置，整库下载不该把它算进去（否则用户会以为还要下 387 张）。"""
        status, _, body = get('/ref_lookbook/fetch-all')
        plan = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(plan['libraries']), 6)
        self.assertNotIn('mio', plan['libraries'])


class ExportTests(unittest.TestCase):
    """独立模式的「导入」落 exports/，命名规则与 ComfyUI 版一致（同编号跨库不撞名）。"""

    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        patcher = unittest.mock.patch('server.EXPORT_DIR', self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_same_id_from_two_libraries_exports_two_files(self):
        thumb = ROOT / 'library/costume/thumbs/SPR-0001.webp'
        anime_thumb = ROOT / 'library/costume-anime/thumbs/SPR-0001.webp'
        self.assertTrue(thumb.is_file() and anime_thumb.is_file())
        self.assertEqual(export_to_file('costume', 'SPR-0001', None, thumb), 'ref_SPR-0001.webp')
        self.assertEqual(export_to_file('costume-anime', 'SPR-0001', None, anime_thumb),
                         'ref_anime-SPR-0001.webp')

    def test_angle_becomes_suffix(self):
        thumb = ROOT / 'library/pose/thumbs/full_sexy_P001_front.webp'
        if not thumb.is_file():
            self.skipTest('本地缺姿势缩略图')
        name = export_to_file('pose', 'POS-SEXY-P001', '斜45°', thumb)
        self.assertEqual(name, 'ref_POS-SEXY-P001_45deg.webp')

    def test_repeat_export_is_idempotent(self):
        thumb = ROOT / 'library/costume/thumbs/SPR-0001.webp'
        export_to_file('costume', 'SPR-0001', None, thumb)
        name = export_to_file('costume', 'SPR-0001', None, thumb)
        self.assertEqual(name, 'ref_SPR-0001.webp')
        self.assertEqual([p.name for p in self.tmp.iterdir()], ['ref_SPR-0001.webp'])
