"""整库下载（bulk）的计数、预估与失败处理。

不联网：把 catalog.ensure_original 换成假实现，只验证调度与统计。
"""
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


catalog = _load('catalog')
bulk = _load('bulk')


class BulkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / 'data').mkdir()
        rows = [{'id': 'A-1', '原图': 'costume/png/a1.png'},
                {'id': 'A-2', '原图': 'costume/png/a2.png'},
                {'id': 'A-3', '原图': 'costume/png/a3.png'}]
        (root / 'data/costume-zh.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
        (root / 'costume/png').mkdir(parents=True)
        (root / 'costume/png/a1.png').write_bytes(b'x' * 3000)
        self.saved_library = catalog.LIBRARY
        self.saved_ensure = catalog.ensure_original
        catalog.LIBRARY = root
        for cached in (catalog.records, catalog.index, catalog.meta):
            cached.cache_clear()

    def tearDown(self):
        catalog.LIBRARY = self.saved_library
        catalog.ensure_original = self.saved_ensure
        for cached in (catalog.records, catalog.index, catalog.meta):
            cached.cache_clear()
        self.tmp.cleanup()

    def _fake_ok(self):
        def fake(library, relative):
            path = catalog.local_path(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x' * 1200)
            return path
        catalog.ensure_original = fake

    def _wait(self, seconds=10):
        deadline = time.time() + seconds
        while time.time() < deadline:
            state = bulk.status()
            if not state['running']:
                return state
            time.sleep(0.05)
        self.fail('下载任务没有在预期时间内结束')

    def test_workers_never_exceed_origin_slots(self):
        """并发不能超过原图信号量，否则多出来的线程只会排队等信号量，白占内存。"""
        self.assertLessEqual(bulk.WORKERS, catalog.ORIGIN_SLOTS)
        self.assertEqual(bulk.WORKERS, min(catalog.ORIGIN_SLOTS, bulk.WORKERS))

    def test_origin_slots_default_is_tuned_to_source(self):
        """12 路是实测拐点（1 路 0.6 张/秒、12 路 4.9 张/秒、20 路不再涨）。改这个值要有新的实测。"""
        if 'COMFYUI_REF_LOOKBOOK_ORIGIN_SLOTS' not in os.environ:
            self.assertEqual(catalog.ORIGIN_SLOTS, 12)
        self.assertGreaterEqual(catalog.ORIGIN_SLOTS, 1)

    def test_plan_counts_missing_and_estimates_bytes(self):
        plan = bulk.plan(['costume'])
        info = plan['libraries']['costume']
        self.assertEqual(info['have'], 1)
        self.assertEqual(info['missing'], 2)
        self.assertEqual(plan['missing'], 2)
        # 用本机已有的那一张（3000 字节）估平均体积
        self.assertEqual(info['average_bytes'], 3000)
        self.assertEqual(plan['estimated_bytes'], 6000)
        self.assertEqual(plan['root'], str(catalog.LIBRARY))
        self.assertIsNotNone(plan['free_bytes'])

    def test_plan_reports_nothing_to_do_when_all_cached(self):
        (catalog.LIBRARY / 'costume/png/a2.png').write_bytes(b'x' * 10)
        (catalog.LIBRARY / 'costume/png/a3.png').write_bytes(b'x' * 10)
        self.assertEqual(bulk.plan(['costume'])['missing'], 0)

    def test_start_refuses_when_nothing_missing(self):
        for name in ('a2', 'a3'):
            (catalog.LIBRARY / f'costume/png/{name}.png').write_bytes(b'x' * 10)
        with self.assertRaises(ValueError):
            bulk.start(['costume'])

    def test_start_downloads_remaining_and_reports_progress(self):
        self._fake_ok()
        bulk.start(['costume'])
        state = self._wait()
        self.assertEqual(state['total'], 2)
        self.assertEqual(state['done'], 2)
        self.assertEqual(state['failed'], 0)
        self.assertEqual(state['bytes'], 2400)
        self.assertGreaterEqual(state['elapsed'], 0)
        self.assertTrue((catalog.LIBRARY / 'costume/png/a2.png').is_file())

    def test_failures_are_counted_without_stopping_the_batch(self):
        def fake(library, relative):
            if relative.endswith('a2.png'):
                raise FileNotFoundError('模拟上游 404')
            path = catalog.local_path(relative)
            path.write_bytes(b'x' * 100)
            return path

        catalog.ensure_original = fake
        bulk.start(['costume'])
        state = self._wait()
        self.assertEqual(state['done'], 1)
        self.assertEqual(state['failed'], 1)
        self.assertEqual(state['errors'][0]['file'], 'costume/png/a2.png')

    def test_cancel_stops_scheduling_new_files(self):
        def fake(library, relative):
            time.sleep(0.2)
            path = catalog.local_path(relative)
            path.write_bytes(b'x' * 10)
            return path

        catalog.ensure_original = fake
        bulk.start(['costume'])
        bulk.cancel()
        state = self._wait()
        self.assertFalse(state['running'])
        self.assertTrue(state['cancelled'])


if __name__ == '__main__':
    unittest.main()
