"""独立 HTTP 服务：不起 ComfyUI 也能在浏览器里用图库。

与 ComfyUI 内置路由（__init__.py 里的 /ref_lookbook/*）共用 catalog.py / bulk.py，
页面同样挂在 /ref_lookbook/gallery，前端 gallery.mjs 全部走相对路径 fetch，零改动复用。

用法：
    python server.py                       # http://127.0.0.1:8180/ref_lookbook/gallery
    python server.py --port 9000
    python server.py --host 0.0.0.0        # 允许局域网访问（会打印安全提醒）
    python server.py --library D:/path/to/library

只依赖标准库 + 本插件的 catalog / bulk。缩略图离线可览；原图按「本地优先 →
上游取一次并缓存」获取，与节点内行为一致。GET /ref_lookbook/status 可自检。
"""
import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

# catalog 在 import 时就固化图库根目录，--library 必须在它加载前生效，
# 所以在 import catalog 之前先从 argv 里手动摘出来，不能等 argparse。
if '--library' in sys.argv:
    _i = sys.argv.index('--library')
    if _i + 1 < len(sys.argv):
        os.environ['COMFYUI_REF_LOOKBOOK_LIBRARY'] = str(Path(sys.argv[_i + 1]).resolve())

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from catalog import (LIBRARIES, OFFLINE_ENV, ROOT, asset, asset_by_id, ensure_original, item,
                         meta, missing_originals, offline, pick, records, site, variant_values)
    import bulk
else:  # 被测试以包方式加载
    from .catalog import (LIBRARIES, OFFLINE_ENV, ROOT, asset, asset_by_id, ensure_original, item,
                          meta, missing_originals, offline, pick, records, site, variant_values)
    from . import bulk

# 允许直接下发的静态文件：与 ComfyUI 版路由同一份白名单，外加页面本体。
WEB_FILES = ('gallery.mjs', 'style.css', 'icon.svg', 'ref_gallery.js')
CONTENT_TYPES = {'.webp': 'image/webp', '.svg': 'image/svg+xml', '.mjs': 'text/javascript; charset=utf-8',
                 '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
                 '.html': 'text/html; charset=utf-8', '.json': 'application/json; charset=utf-8',
                 '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}

# 独立模式下没有 ComfyUI 的 input 目录：导入落到插件旁的 exports/，可 --export-dir 改。
EXPORT_DIR = Path(__file__).resolve().parent / 'exports'

ANGLE_SLUGS = {'正面': 'front', '俯视': 'high', '仰视': 'low', '侧面': 'side', '斜45°': '45deg',
               '彩图': 'color', '线稿': 'line'}
# 与 __init__.py 同一份规则：服装动画与写实服装共用编号，导入文件名带库前缀防覆盖。
LIB_TAG = {'costume-anime': 'anime-'}


def export_to_file(library, item_id, angle, source, export_dir=None):
    """独立模式版的 import_to_input：落到导出目录，返回文件名。"""
    suffix = f'_{ANGLE_SLUGS.get(angle, re.sub(r"[^0-9A-Za-z]", "", str(angle or "")))}'
    stem = LIB_TAG.get(library, '') + re.sub(r'[^0-9A-Za-z._-]', '_', item_id)
    target = Path(export_dir or EXPORT_DIR) / f'ref_{stem}{suffix if angle else ""}{source.suffix or ".png"}'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == source.stat().st_size:
        return target.name
    # 先写临时文件再原子替换：避免浏览器或后续处理读到写了一半的图。
    staging = target.with_name(target.name + '.part')
    shutil.copyfile(source, staging)
    staging.replace(target)
    return target.name


class Handler(BaseHTTPRequestHandler):
    server_version = 'RefLookbook/1.0'
    protocol_version = 'HTTP/1.1'   # 配合 Content-Length 复用连接
    # 闲置连接 60 秒后回收：防系统休眠唤醒后的半开连接把线程越积越多
    timeout = 60

    def log_message(self, fmt, *args):  # 一行一条，别刷屏
        print(f'[{self.log_date_time_string()}] {fmt % args}')

    # ---------- 基础 ----------
    def _send(self, body, status=200, content_type='application/json; charset=utf-8', cache=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        if cache:
            self.send_header('Cache-Control', cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, status=200, cache=None):
        self._send(json.dumps(payload, ensure_ascii=False).encode('utf-8'), status, cache=cache)

    def _file(self, path, cache='private, max-age=3600'):
        try:
            data = path.read_bytes()
        except OSError:
            return self._json({'error': f'文件不可读：{path.name}'}, 404)
        ctype = CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        self._send(data, 200, ctype, cache=cache)

    def _body(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return {}
        if length <= 0 or length > 1_000_000:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---------- 路由 ----------
    def do_GET(self):
        self._dispatch('GET')

    def do_POST(self):
        self._dispatch('POST')

    def _dispatch(self, method):
        path = unquote(urlsplit(self.path).path)
        query = parse_qs(urlsplit(self.path).query)
        try:
            if method == 'GET' and path in ('/', '/index.html'):
                self.send_response(302)
                self.send_header('Location', '/ref_lookbook/gallery')
                self.send_header('Content-Length', '0')
                self.end_headers()
            elif method == 'GET' and path == '/ref_lookbook/gallery':
                self._file(ROOT / 'web' / 'gallery.html', cache='no-cache')
            elif method == 'GET' and path.startswith('/ref_lookbook/web/'):
                name = path.rsplit('/', 1)[-1]
                if name not in WEB_FILES:
                    self._json({'error': '文件不在白名单内'}, 404)
                else:
                    self._file(ROOT / 'web' / name, cache='no-cache')
            elif method == 'GET' and path == '/ref_lookbook/catalog':
                self._catalog('costume')
            elif method == 'GET' and path.startswith('/ref_lookbook/catalog/'):
                self._catalog(path.rsplit('/', 1)[-1])
            elif method == 'GET' and path == '/ref_lookbook/status':
                self._status()
            elif method == 'GET' and path == '/ref_lookbook/fetch-all':
                self._json(bulk.plan())
            elif method == 'GET' and path == '/ref_lookbook/fetch-all/status':
                self._json(bulk.status())
            elif method == 'POST' and path == '/ref_lookbook/fetch-all/start':
                self._fetch_start(self._body())
            elif method == 'POST' and path == '/ref_lookbook/fetch-all/stop':
                self._json(bulk.cancel())
            elif method == 'GET' and path.startswith('/ref_lookbook/assets/'):
                self._assets(path)
            elif method == 'GET' and path.startswith('/ref_lookbook/asset/'):
                self._asset_by_id(path, query)
            elif method == 'POST' and path == '/ref_lookbook/import':
                self._import(self._body())
            else:
                self._json({'error': f'未知的接口：{method} {path}'}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # 浏览器取消图片加载、提前断开很常见，不值得一条 traceback
        except (ValueError, FileNotFoundError, KeyError) as exc:
            self._json({'error': str(exc) or exc.__class__.__name__}, 404)
        except OSError:
            pass  # 写响应时连接已死：同上，静默即可
        except Exception as exc:  # 兜底：别让一个坏请求带死线程
            self._json({'error': f'{exc.__class__.__name__}: {exc}'}, 500)

    # ---------- 各接口 ----------
    def _catalog(self, library):
        if library not in LIBRARIES:
            return self._json({'error': f'未知图库：{library}'}, 404)
        try:
            self._json({'library': library, 'meta': meta(library),
                        'origin': {'site': site(library), 'template': LIBRARIES[library]['origin'],
                                   'line_template': LIBRARIES[library].get('line_origin', ''),
                                   'offline': offline(), 'env': OFFLINE_ENV},
                        'records': records(library)})
        except (ValueError, FileNotFoundError) as exc:
            self._json({'error': str(exc)}, 503)

    def _status(self):
        network = 'only-local' if offline() else 'upstream-on-demand'
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
        self._json(report)

    def _fetch_start(self, payload):
        libraries = payload.get('libraries') if isinstance(payload, dict) else None
        try:
            self._json({'job': bulk.start(libraries)})
        except ValueError as exc:
            self._json({'error': str(exc)}, 400)
        except RuntimeError as exc:
            self._json({'error': str(exc)}, 409)

    def _assets(self, path):
        rest = path.split('/')[3:]  # ['', 'ref_lookbook', 'assets', ...]
        if len(rest) == 2:
            kind, filename, library = rest[0], rest[1], 'costume'
        elif len(rest) == 3:
            library, kind, filename = rest
        else:
            return self._json({'error': '路径格式：/ref_lookbook/assets/<库>/<类型>/<文件>'}, 404)
        # 缩略图与原图都允许联网补一次，语义与 ComfyUI 版一致。
        self._file(Path(asset(kind, filename, library, kind in ('thumbs', 'png'))))

    def _asset_by_id(self, path, query):
        parts = path.split('/')
        if len(parts) != 6:
            return self._json({'error': '路径格式：/ref_lookbook/asset/<库>/<类型>/<编号>'}, 404)
        _, _, _, library, kind, item_id = parts
        angle = (query.get('angle') or [None])[0]
        self._file(Path(asset_by_id(library, item_id, kind, angle, kind in ('thumbs', 'png'))))

    def _import(self, payload):
        library = str(payload.get('library') or '')
        item_id = str(payload.get('id') or '')
        angle = payload.get('angle') or None
        if library not in LIBRARIES:
            return self._json({'error': f'未知图库：{library}'}, 404)
        try:
            relative = pick(item(library, item_id), '原图', angle)
            source = ensure_original(library, relative)
            name = export_to_file(library, item_id, angle if angle in variant_values(library) else None, source)
        except ValueError as exc:
            return self._json({'error': str(exc)}, 400)
        except FileNotFoundError as exc:
            return self._json({'error': str(exc)}, 503)
        self._json({'name': name, 'path': str(EXPORT_DIR / name), 'library': library,
                    'id': item_id, 'angle': angle, 'bytes': source.stat().st_size})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # 默认实现会打整段 traceback：浏览器掐断连接在这里很常见，一行带过
        print('一个请求处理线程异常退出（通常是客户端提前断开），服务继续运行。')


def _disable_quick_edit():
    """关掉 Windows 控制台的 QuickEdit：用户鼠标一划窗口就进入选择模式，
    print 全部阻塞，服务看起来像卡死。关掉后日志永远不堵请求线程。"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        handle = ctypes.windll.kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint()
        if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_QUICK_EDIT_MODE(0x40) 关闭，同时必须带 ENABLE_EXTENDED_FLAGS(0x80)
            ctypes.windll.kernel32.SetConsoleMode(handle, (mode.value & ~0x0040) | 0x0080)
    except Exception:
        pass  # 不在真实控制台里（重定向/服务方式运行）就无所谓


def main():
    parser = argparse.ArgumentParser(description='参考图库独立 HTTP 服务')
    parser.add_argument('--host', default='127.0.0.1', help='监听地址，默认 127.0.0.1（仅本机）')
    parser.add_argument('--port', type=int, default=8180, help='监听端口，默认 8180')
    parser.add_argument('--library', default=None, help='图库根目录（默认插件内 library/）')
    parser.add_argument('--export-dir', default=None, help='「导入」落盘目录（默认插件内 exports/）')
    args = parser.parse_args()

    _disable_quick_edit()

    if args.export_dir:
        global EXPORT_DIR
        EXPORT_DIR = Path(args.export_dir).resolve()

    if args.host not in ('127.0.0.1', 'localhost'):
        print('=' * 62)
        print('  安全提醒：服务绑定在非本机回环地址，局域网内任何人都能访问，')
        print('  且「整库下载」会以你的 IP 向上游站点批量抓图。确认你了解风险。')
        print('=' * 62)

    try:
        httpd = Server((args.host, args.port), Handler)
    except OSError:
        print(f'[!] 端口 {args.port} 无法监听：多半已经有一个图库服务在跑（或端口被其他程序占用）。')
        print('    可以换一个端口启动：python server.py --port 8181')
        sys.exit(1)

    total = sum(len(records(name)) for name in LIBRARIES)
    print(f'参考图库已启动：http://{args.host}:{args.port}/ref_lookbook/gallery')
    print(f'共 {len(LIBRARIES)} 个库、{total:,} 条记录。原图按需从上游取一次并缓存到本机。')
    print('保持这个窗口开着即可；关闭窗口服务就停。Ctrl+C 也可以停止。')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止。')
    except Exception:
        # 任何意外都把原因留在窗口里：启动脚本检测到非零退出码会暂停窗口，不至于一闪而过
        import traceback
        print('\n服务因异常退出，原因如下：')
        traceback.print_exc()
        sys.exit(1)
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
