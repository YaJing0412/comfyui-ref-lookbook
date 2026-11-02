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
                         {'costume', 'costume-anime', 'pose', 'face', 'depth', 'anime'})


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
