import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'library'
LIBS = {'costume': ('costume-zh.json', 1407), 'costume-anime': ('costume-anime-zh.json', 1320),
        'pose': ('pose-zh.json', 288), 'face': ('face-zh.json', 1498),
        'depth': ('depth-zh.json', 288), 'anime': ('anime-zh.json', 1027)}
FIELDS = ('缩略图', '预览图', '原图')


def paths(row, field):
    value = row[field]
    return list(value.values()) if isinstance(value, dict) else [value]


class LibraryIndexTests(unittest.TestCase):
    """仓库随包发行缩略图：索引必须完整可用，内置缩略图必须逐条在仓库、无多余文件。"""

    def test_every_record_points_at_a_local_thumbnail_path(self):
        for library, (index, expected) in LIBS.items():
            rows = json.loads((ROOT / 'data' / index).read_text(encoding='utf-8'))
            with self.subTest(library=library):
                self.assertEqual(len(rows), expected)
                self.assertEqual(len({r['id'] for r in rows}), expected)
            for row in rows:
                for relative in paths(row, '缩略图'):
                    with self.subTest(library=library, id=row['id']):
                        self.assertEqual(relative.split('/')[-2], 'thumbs', relative)
                        self.assertEqual(relative.split('/')[0], library, '路径第一段必须是库名')
                        self.assertTrue(relative.endswith('.webp'), '内置缩略图统一是 WebP')
                        self.assertNotIn('..', relative)

    def test_originals_and_previews_are_not_shipped_only_cached(self):
        """原图与全尺寸 WebP 不进仓库：本机若有缓存必须来自索引，不能有野文件。"""
        for library, (index, _) in LIBS.items():
            rows = json.loads((ROOT / 'data' / index).read_text(encoding='utf-8'))
            base = ROOT / library
            for kind, field in (('img', '预览图'), ('png', '原图')):
                expected = {Path(p).name for row in rows for p in paths(row, field)}
                actual = {p.name for p in (base / kind).iterdir() if p.is_file() and p.name != '.gitkeep'}
                with self.subTest(library=library, kind=kind):
                    self.assertLessEqual(actual, expected, '缓存目录里出现了索引之外的文件')

    def test_bundled_thumbnails_are_complete_and_exact(self):
        """内置缩略图必须与索引一一对应：每条记录的缩略图都在仓库，且没有多余文件。"""
        for library, (index, _) in LIBS.items():
            rows = json.loads((ROOT / 'data' / index).read_text(encoding='utf-8'))
            base = ROOT / library
            expected = {Path(p).name for row in rows for p in paths(row, '缩略图')}
            actual = {p.name for p in (base / 'thumbs').iterdir() if p.is_file() and p.name != '.gitkeep'}
            with self.subTest(library=library):
                self.assertEqual(actual, expected, '内置缩略图与索引不一致')

    def test_pose_records_carry_five_angles(self):
        rows = json.loads((ROOT / 'data/pose-zh.json').read_text(encoding='utf-8'))
        total = 0
        for row in rows:
            with self.subTest(id=row['id']):
                self.assertEqual(row['视角'], list(row['原图']))
                # 上游数据里 P018 缺「仰视」，其余每个动作都是完整五机位
                self.assertIn(len(row['视角']), (4, 5))
                self.assertIn(row['封面'], row['缩略图'].values())
                total += len(row['视角'])
        self.assertEqual(total, 1439)

    def test_depth_mirrors_pose_exactly(self):
        """深度库是姿势库的同一批图：文件名、视角、编号必须逐条对齐，否则 ControlNet 会配错。"""
        pose = json.loads((ROOT / 'data/pose-zh.json').read_text(encoding='utf-8'))
        depth = json.loads((ROOT / 'data/depth-zh.json').read_text(encoding='utf-8'))
        self.assertEqual(len(pose), len(depth))
        for p_row, d_row in zip(pose, depth):
            with self.subTest(id=p_row['id']):
                self.assertEqual(d_row['id'], p_row['id'].replace('POS-', 'DEP-', 1))
                self.assertEqual(list(d_row['原图']), list(p_row['原图']))
                for angle, rel in p_row['原图'].items():
                    self.assertEqual(d_row['原图'][angle], rel.replace('pose/', 'depth/', 1))

    def test_anime_line_art_is_paired_with_color(self):
        """姿势才有线稿；有线稿的必须有彩图，反之彩图不一定有线稿。线稿文件名统一带 _line。"""
        rows = json.loads((ROOT / 'data/anime-zh.json').read_text(encoding='utf-8'))
        with_line = [r for r in rows if r['线稿']]
        self.assertEqual(len(with_line), 281, '姿势 281 条，每个都该有线稿')
        for row in rows:
            with self.subTest(id=row['id']):
                self.assertIsInstance(row['原图'], dict if row['线稿'] else str)
                if not row['线稿']:
                    continue
                self.assertEqual(set(row['原图']), {'彩图', '线稿'})
                self.assertNotIn('_line', row['原图']['彩图'])
                self.assertIn('_line', row['原图']['线稿'])
                for kind in ('原图', '缩略图', '预览图'):
                    self.assertEqual(len(set(row[kind].values())), 2, f'{kind} 两个形态不能指向同一个文件')

    def test_anime_ids_cover_all_three_kinds(self):
        """H=发型与眼睛 / O=服装 / P=姿势，前缀丢了说明转换时截错了 ID。"""
        rows = json.loads((ROOT / 'data/anime-zh.json').read_text(encoding='utf-8'))
        prefixes = {r['id'].split('-')[1][0] for r in rows}
        self.assertEqual(prefixes, {'H', 'O', 'P'})
        for row in rows:
            with self.subTest(id=row['id']):
                self.assertTrue(row['id'].startswith('ANE-'), row['id'])
                self.assertEqual(row['分类'], {'H': '发型与眼睛', 'O': '服装', 'P': '姿势'}[row['id'].split('-')[1][0]])

    def test_costume_anime_shares_ids_with_realistic_but_points_elsewhere(self):
        """动画版与写实版的编号空间是重合的（上游两版各自独立编号），所以：

        ID 允许一样，但路径必须落在各自库目录下，绝不能指向对方的图；分类仍是同一套 8 类。
        """
        real = json.loads((ROOT / 'data/costume-zh.json').read_text(encoding='utf-8'))
        anime = json.loads((ROOT / 'data/costume-anime-zh.json').read_text(encoding='utf-8'))
        self.assertEqual({r['分类'] for r in anime}, {r['分类'] for r in real})
        self.assertEqual(len(anime), 1320)
        overlap = {r['id'] for r in anime} & {r['id'] for r in real}
        self.assertGreater(len(overlap), 1000, '两版编号确实大量重合，这是上游的设计')
        for row in anime:
            with self.subTest(id=row['id']):
                for field in FIELDS:
                    for relative in paths(row, field):
                        self.assertTrue(relative.startswith('costume-anime/'), relative)
        real_paths = {r['原图'] for r in real}
        self.assertFalse({r['原图'] for r in anime} & real_paths, '两库不能共用同一个原图文件')

    def test_face_ids_are_sequential_and_keep_source_id(self):
        rows = json.loads((ROOT / 'data/face-zh.json').read_text(encoding='utf-8'))
        self.assertEqual([row['id'] for row in rows], [f'FACE-{i + 1:04d}' for i in range(len(rows))])
        self.assertEqual(len({row['源ID'] for row in rows}), len(rows))

class MioLibraryTests(unittest.TestCase):
    """澪设计档案是平铺库：源站只有一档图，原图与缩略图是同一个文件，格式是 JPEG。

    这些约束和六库（WebP 缩略图 + 按需取 png 原图）完全相反，所以单独测，不并进 LIBS。
    """

    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads((ROOT / 'data/mio-zh.json').read_text(encoding='utf-8'))
        cls.meta = json.loads((ROOT / 'data/meta-mio.json').read_text(encoding='utf-8'))

    def test_counts_and_id_uniqueness(self):
        self.assertEqual(len(self.rows), 387)
        self.assertEqual(len({row['id'] for row in self.rows}), 387)
        self.assertEqual({row['分类'] for row in self.rows}, {'发型', '服装', '姿势'})

    def test_original_and_thumbnail_are_the_same_file(self):
        """源站没有大图目录：两个字段必须指向同一个文件，否则等于把同一张图存两份。"""
        for row in self.rows:
            with self.subTest(id=row['id']):
                self.assertEqual(row['原图'], row['缩略图'])
                self.assertTrue(row['原图'].startswith('mio/thumbs/'), row['原图'])
                self.assertTrue(row['原图'].endswith('.jpg'), '保持 JPEG，别转 WebP')

    def test_every_tile_is_418_long_edge(self):
        """图是从每卷合集按真实格边界重切的，长边统一 418 px。

        源站的单件图切点偏 4~40 px，会把相邻格标题切进本格（卡片上多出半行黑字），
        所以不能用它。这里钉住"我们自己重切"这个事实：长边必须是 418。
        """
        from PIL import Image

        for row in self.rows:
            path = ROOT / row['缩略图']
            with self.subTest(id=row['id']):
                self.assertEqual(max(Image.open(path).size), 418, row['缩略图'])

    def test_every_file_is_bundled(self):
        missing = [row['id'] for row in self.rows if not (ROOT / row['原图']).is_file()]
        self.assertEqual(missing, [])

    def test_thumbs_directory_has_no_stray_files(self):
        expected = {Path(row['缩略图']).name for row in self.rows}
        actual = {p.name for p in (ROOT / 'mio/thumbs').iterdir() if p.is_file() and p.name != '.gitkeep'}
        self.assertEqual(actual, expected)

    def test_every_item_carries_bilingual_prompts(self):
        """独立页面的核心卖点就是这两个字段，缺一条就等于这条素材废了一半。"""
        for row in self.rows:
            with self.subTest(id=row['id']):
                self.assertTrue(row['提示词'], row['id'])
                self.assertTrue(row['提示词中文'], row['id'])
                self.assertIn('1girl', row['提示词'])

    def test_volumes_cover_every_record(self):
        self.assertEqual(len(self.meta['volumes']), 43)
        self.assertEqual(sum(volume['count'] for volume in self.meta['volumes']), len(self.rows))
        self.assertEqual({row['卷slug'] for row in self.rows}, {volume['slug'] for volume in self.meta['volumes']})
        self.assertEqual({volume['series_zh'] for volume in self.meta['volumes']}, {'发型', '服装', '姿势'})

    def test_ids_encode_series_and_volume(self):
        """H/C/P 前缀 + 卷号 + 序号：编号要能和 slug 对得上，否则页面按卷筛会漏件。"""
        prefixes = {'发型': 'H', '服装': 'C', '姿势': 'P'}
        for row in self.rows:
            with self.subTest(id=row['id']):
                self.assertEqual(row['id'].split('-')[0], prefixes[row['分类']])
                self.assertEqual(row['id'].split('-')[1], f"{int(row['卷号']):02d}")
