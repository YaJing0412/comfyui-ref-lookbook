"""整库原图批量缓存（图库页面右上角那个按钮的后端）。

这是给使用者自己攒离线库用的：下载什么、下载多少，由使用者决定。
  * 并发默认 12 路，与单张看图共用同一套限流信号量（catalog._origin_slots），
    实测源站 12 路刚好到吞吐拐点，再高没有收益；
  * 每下完一张 sleep 一小会儿，避免对源站形成无间隔的脉冲；
  * 串行队列 + 可随时停止，失败重试一次；
  * 已经在本机的图片直接跳过，所以停止、甚至关掉 ComfyUI 之后再点一次就是续传。

任务跑在后台线程里，ComfyUI 进程不退出它就一直在，前端只负责轮询进度。
"""
import os
import queue
import shutil
import threading
import time

if __package__:  # 作为节点包的一部分加载（ComfyUI 运行时）
    from . import catalog
else:  # 被测试或脚本单独加载
    import catalog

# 并发上限跟原图信号量同一个来源，两边不一致会互相等，白白浪费吞吐。
WORKERS = max(1, min(catalog.ORIGIN_SLOTS,
                      int(os.environ.get('COMFYUI_REF_LOOKBOOK_FETCH_WORKERS', catalog.ORIGIN_SLOTS))))
RETRIES = 1
# 每张之间的间隔。12 路下总开销约 1439×0.05/12 ≈ 6 秒，可以忽略，
# 但能避免请求严丝合缝地排成队列。
PAUSE = 0.05
# 一次都没下过原图时（全新安装）用的体积估值，单位字节。
FALLBACK_BYTES = {'costume': 992_000, 'pose': 465_000, 'face': 3_242_000, 'depth': 97_000}

_guard = threading.Lock()
_job = None


def _average_bytes(library):
    """用本机已有原图估平均体积；一张都没有就用内置估值。"""
    base = catalog.LIBRARY / catalog.library_info(library)['base'] / 'png'
    sizes = []
    if base.is_dir():
        for path in base.iterdir():
            if path.suffix.lower() != '.png':
                continue
            try:
                sizes.append(path.stat().st_size)
            except OSError:
                continue
            if len(sizes) >= 64:
                break
    return sum(sizes) // len(sizes) if sizes else FALLBACK_BYTES.get(library, 900_000)


def _paths(row):
    value = row['原图']
    return list(value.values()) if isinstance(value, dict) else [value]


def plan(libraries=None):
    """预估：各库还差多少张、大概占多少空间、会存到哪儿、磁盘还剩多少。"""
    names = [name for name in (libraries or catalog.LIBRARIES) if name in catalog.LIBRARIES]
    detail, missing_total, bytes_total = {}, 0, 0
    for name in names:
        rows = catalog.records(name)
        missing = have = 0
        for row in rows:
            for relative in _paths(row):
                if catalog.local_path(relative).is_file():
                    have += 1
                else:
                    missing += 1
        average = _average_bytes(name)
        detail[name] = {'label': catalog.LIBRARIES[name]['label'], 'records': len(rows),
                        'have': have, 'missing': missing,
                        'average_bytes': average, 'estimated_bytes': missing * average}
        missing_total += missing
        bytes_total += missing * average
    try:
        free = shutil.disk_usage(catalog.LIBRARY).free
    except OSError:
        free = None
    return {'root': str(catalog.LIBRARY), 'libraries': detail, 'missing': missing_total,
            'estimated_bytes': bytes_total, 'free_bytes': free,
            'offline': catalog.offline(), 'workers': WORKERS}


def start(libraries=None):
    """启动后台下载。已在跑就报错，让前端别再点一次。"""
    global _job
    if catalog.offline():
        raise RuntimeError(f'离线模式下不联网下载（环境变量 {catalog.OFFLINE_ENV}）')
    with _guard:
        if _job and _job['running']:
            raise RuntimeError('已有下载任务在进行中')
        names = [name for name in (libraries or catalog.LIBRARIES) if name in catalog.LIBRARIES]
        if not names:
            raise ValueError('没有可下载的图库')
        tasks = queue.Queue()
        per = {}
        for name in names:
            pending = []
            for row in catalog.records(name):
                pending.extend(path for path in _paths(row) if not catalog.local_path(path).is_file())
            per[name] = {'label': catalog.LIBRARIES[name]['label'], 'total': len(pending),
                         'done': 0, 'failed': 0}
            for relative in pending:
                tasks.put((name, relative))
        total = tasks.qsize()
        if not total:
            raise ValueError('这些图库的原图本机都已经有了，不需要下载')
        _job = {'running': True, 'cancelled': False, 'started_at': time.time(), 'finished_at': None,
                'total': total, 'done': 0, 'failed': 0, 'bytes': 0, 'libraries': names,
                'per_library': per, 'errors': [], 'current': '', 'root': str(catalog.LIBRARY)}
        job = _job
    threading.Thread(target=_run, args=(job, tasks), name='ref-lookbook-fetch', daemon=True).start()
    return status()


def _run(job, tasks):
    threads = [threading.Thread(target=_worker, args=(job, tasks), daemon=True) for _ in range(WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    with _guard:
        job['running'] = False
        job['finished_at'] = time.time()
        job['current'] = ''


def _worker(job, tasks):
    while not job['cancelled']:
        try:
            library, relative = tasks.get_nowait()
        except queue.Empty:
            return
        _one(job, library, relative)
        time.sleep(PAUSE)


def _one(job, library, relative):
    """下载单张。先写 .part 再原子替换，中断也不会留下半张图。"""
    last = None
    for attempt in range(RETRIES + 1):
        if job['cancelled']:
            return
        try:
            path = catalog.ensure_original(library, relative)
        except Exception as exc:  # 单张失败不影响整批
            last = exc
            if attempt < RETRIES:
                time.sleep(1.0 + attempt)
                continue
            with _guard:
                job['failed'] += 1
                job['per_library'][library]['failed'] += 1
                if len(job['errors']) < 20:
                    job['errors'].append({'library': library, 'file': relative, 'error': str(last)[:200]})
            return
        size = path.stat().st_size if path.is_file() else 0
        with _guard:
            job['done'] += 1
            job['bytes'] += size
            job['per_library'][library]['done'] += 1
            job['current'] = relative
        return


def status():
    """进度快照，前端每隔一两秒取一次。"""
    with _guard:
        if not _job:
            return {'running': False, 'job': None}
        job = _job
        elapsed = (job['finished_at'] or time.time()) - job['started_at']
        done = job['done']
        rate = done / elapsed if elapsed > 0 and done else 0
        remaining = job['total'] - done - job['failed']
        return {
            'running': job['running'], 'cancelled': job['cancelled'],
            'total': job['total'], 'done': done, 'failed': job['failed'], 'bytes': job['bytes'],
            'elapsed': round(elapsed, 1), 'rate': round(rate, 2),
            'eta': round(remaining / rate, 1) if rate > 0 else None,
            'current': job['current'], 'libraries': job['libraries'],
            'per_library': job['per_library'], 'errors': list(job['errors']),
        }


def cancel():
    """只是让工作线程在下一次取任务前退出，已下完的图都保留。"""
    with _guard:
        if not _job or not _job['running']:
            return {'running': False}
        _job['cancelled'] = True
    return status()


__all__ = ['cancel', 'plan', 'start', 'status']
