"""用桩模块导入节点包，锁定输入定义里容易回归的几个点。

重点是 angle：它必须是 optional，否则 API 调用方（以及省略该键的工作流 JSON）
整条链会被判成 "Required input is missing: angle" 而静默丢弃。
"""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
INPUT_DIR = Path(tempfile.mkdtemp(prefix='ref_gallery_input_'))


def _install_stubs():
    """临时注入桩模块，加载完节点包后立刻还原，避免污染其他测试（例如需要真 PIL 的用例）。"""
    saved = {}
    server = types.ModuleType('server')

    class Routes:
        def get(self, path):
            return lambda fn: fn

        def post(self, path):
            return lambda fn: fn

    class PromptServer:
        instance = types.SimpleNamespace(routes=Routes())

    server.PromptServer = PromptServer
    stubs = {'server': server}

    folder_paths = types.ModuleType('folder_paths')
    folder_paths.get_input_directory = lambda: str(INPUT_DIR)
    stubs['folder_paths'] = folder_paths

    aiohttp = types.ModuleType('aiohttp')
    web = types.ModuleType('aiohttp.web')
    web.json_response = lambda *a, **k: None
    web.FileResponse = lambda path, headers=None: path
    web.HTTPNotFound = type('HTTPNotFound', (Exception,), {})
    aiohttp.web = web
    stubs['aiohttp'] = aiohttp
    stubs['aiohttp.web'] = web

    torch = types.ModuleType('torch')
    torch.from_numpy = lambda array: array
    torch.Tensor = object
    stubs['torch'] = torch

    numpy = types.ModuleType('numpy')
    numpy.array = lambda *a, **k: None
    stubs['numpy'] = numpy

    pil = types.ModuleType('PIL')
    image = types.ModuleType('PIL.Image')
    image.open = lambda *a, **k: None
    image.LANCZOS = 1
    imageops = types.ModuleType('PIL.ImageOps')
    imageops.exif_transpose = lambda im: im
    pil.Image = image
    pil.ImageOps = imageops
    stubs['PIL'] = pil
    stubs['PIL.Image'] = image
    stubs['PIL.ImageOps'] = imageops

    for name, module in stubs.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = module
    return saved


def _restore(saved):
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


def _load_nodes():
    saved = _install_stubs()
    try:
        spec = importlib.util.spec_from_file_location(
            'ref_gallery_nodes', PACKAGE / '__init__.py',
            submodule_search_locations=[str(PACKAGE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules['ref_gallery_nodes'] = module
        spec.loader.exec_module(module)
        return module
    finally:
        _restore(saved)


nodes = _load_nodes()


class InputDefinitionTests(unittest.TestCase):
    def test_variant_is_optional_so_api_callers_can_omit_it(self):
        for cls in (nodes.PoseGallery, nodes.DepthGallery, nodes.AnimeGallery):
            spec = cls.INPUT_TYPES()
            with self.subTest(node=cls.__name__):
                key = cls.VARIANT_WIDGET
                expected = nodes.variant_values(cls.LIBRARY)
                self.assertNotIn(key, spec['required'], f'{key} 放回 required 会让省略该键的 API 调用整条链被丢弃')
                self.assertIn(key, spec.get('optional', {}))
                self.assertEqual(spec['optional'][key][0], expected)
                self.assertEqual(spec['optional'][key][1]['default'], expected[0])

    def test_libraries_without_angles_have_no_angle_input(self):
        for cls in (nodes.FaceGallery, nodes.CostumeGallery, nodes.CostumeAnimeGallery):
            with self.subTest(node=cls.__name__):
                spec = cls.INPUT_TYPES()
                self.assertNotIn('angle', spec['required'])
                self.assertNotIn('angle', spec.get('optional', {}))

    def test_pose_validation_accepts_missing_angle(self):
        for cls, widget, value in ((nodes.PoseGallery, 'pose_id', 'POS-SEXY-P031'),
                                   (nodes.FaceGallery, 'face_id', 'FACE-0001'),
                                   (nodes.CostumeGallery, 'costume_id', 'SPR-0002'),
                                   (nodes.CostumeAnimeGallery, 'costume_anime_id', 'SPR-0002'),
                                   (nodes.DepthGallery, 'depth_id', 'DEP-SEXY-P031'),
                                   (nodes.AnimeGallery, 'anime_id', 'ANE-P001')):
            with self.subTest(node=cls.__name__):
                self.assertIs(cls.VALIDATE_INPUTS(**{widget: value}), True)

    def test_unknown_id_is_rejected_with_a_readable_message(self):
        result = nodes.PoseGallery.VALIDATE_INPUTS(pose_id='NOT-A-POSE')
        self.assertIsInstance(result, str)
        self.assertIn('NOT-A-POSE', result)

    def test_pose_default_angle_falls_back_to_first_viewpoint(self):
        row = nodes.item('pose', 'POS-SEXY-P031')
        self.assertEqual(nodes.pick(row, '原图', None), row['原图'][nodes.ANGLES[0]])


class AnimeVariantTests(unittest.TestCase):
    """二次元的两个形态：彩图 / 线稿。姿势两者都有，其余素材只有彩图。"""

    def test_pose_line_art_resolves_to_its_own_file(self):
        row = nodes.item('anime', 'ANE-P001')
        color = nodes.pick(row, '原图', '彩图')
        line = nodes.pick(row, '原图', '线稿')
        self.assertNotEqual(color, line, '彩图与线稿必须是两个不同文件，否则切了也没用')
        self.assertTrue(line.endswith('_line.png'), line)

    def test_hair_falls_back_to_color_when_asking_for_line(self):
        row = nodes.item('anime', 'ANE-H001')
        self.assertEqual(nodes.pick(row, '原图', '线稿'), nodes.pick(row, '原图', '彩图'))

    def test_variant_values_match_library(self):
        self.assertEqual(nodes.variant_values('anime'), nodes.VARIANTS)
        self.assertEqual(nodes.variant_values('pose'), nodes.ANGLES)
        self.assertEqual(nodes.variant_values('depth'), nodes.ANGLES)
        self.assertEqual(nodes.variant_values('costume'), [], '服装没有形态维度，不该有下拉')
        self.assertEqual(nodes.variant_values('costume-anime'), [], '服装动画与写实版各是独立图库，没有形态维度')

    def test_anime_import_name_keeps_variant(self):
        """导入到 input 目录时彩图/线稿不能撞名，否则后导入的会盖掉前一个。"""
        self.assertNotEqual(nodes.ANGLE_SLUGS['彩图'], nodes.ANGLE_SLUGS['线稿'])


class CostumeAnimeTests(unittest.TestCase):
    """服装动画版与写实服装共用 SPR / SUM … 编号，独立成库，落盘与导入都不能互相盖掉。"""

    def test_same_id_resolves_to_different_files(self):
        real = nodes.pick(nodes.item('costume', 'SPR-0001'), '原图')
        anime = nodes.pick(nodes.item('costume-anime', 'SPR-0001'), '原图')
        self.assertNotEqual(real, anime)
        self.assertTrue(real.startswith('costume/'), real)
        self.assertTrue(anime.startswith('costume-anime/'), anime)

    def test_import_name_is_namespaced_to_avoid_overwriting_realistic(self):
        """同一编号两个库都导入过时，input 目录里必须是两个文件，否则后导入的会盖掉前一个。"""
        self.assertEqual(nodes.import_to_input.__doc__ is not None, True)
        tagged = nodes.LIB_TAG.get('costume-anime')
        self.assertEqual(tagged, 'anime-', '服装动画的导入前缀丢了就会和写实版撞名')
        self.assertNotIn('costume', nodes.LIB_TAG, '写实服装的名字要保持原样，不能打断已有工作流')


class RegistrationTests(unittest.TestCase):
    def test_seven_nodes_are_registered(self):
        self.assertEqual(set(nodes.NODE_CLASS_MAPPINGS),
                         {'CostumeGallery', 'CostumeAnimeGallery', 'PoseGallery', 'FaceGallery', 'DepthGallery',
                          'AnimeGallery', 'CharacterRecipe'})
        for key in nodes.NODE_CLASS_MAPPINGS:
            with self.subTest(node=key):
                self.assertIn(key, nodes.NODE_DISPLAY_NAME_MAPPINGS)

    def test_every_default_id_exists_in_its_library(self):
        for cls in nodes.NODE_CLASS_MAPPINGS.values():
            with self.subTest(node=cls.__name__):
                self.assertEqual(nodes.item(cls.LIBRARY, cls.DEFAULT_ID)['id'], cls.DEFAULT_ID)

    def test_depth_and_pose_share_pose_ids(self):
        """深度节点和姿势节点的 ID 只差前缀，切库时编号规则一致。"""
        for lib in ('pose', 'depth'):
            row = nodes.item(lib, cls_default(lib))
            with self.subTest(library=lib):
                self.assertEqual(len(row['原图']), 5)


class ResizeOptionTests(unittest.TestCase):
    """尺寸与翻转必须是 optional 且默认原图尺寸：升级节点不能改掉老工作流的出图分辨率。"""

    WIDGETS = ('resize_mode', 'width', 'height', 'flip_horizontal')

    def test_resize_options_are_optional_everywhere(self):
        for key, cls in nodes.NODE_CLASS_MAPPINGS.items():
            if key == 'CharacterRecipe':
                continue  # 配方节点的尺寸做在 required 里：它总是要拼图，尺寸是明确必填的
            with self.subTest(node=key):
                optional = cls.INPUT_TYPES()['optional']
                for widget in self.WIDGETS:
                    self.assertIn(widget, optional, f'{widget} 放 required 会让老工作流缺键')

    def test_default_resize_mode_keeps_original_size(self):
        for key, cls in nodes.NODE_CLASS_MAPPINGS.items():
            with self.subTest(node=key):
                default = cls.INPUT_TYPES()['required' if key == 'CharacterRecipe' else 'optional']['resize_mode'][1]['default']
                if key == 'CharacterRecipe':
                    self.assertEqual(default, '指定尺寸（居中裁剪）', '配方节点要拼图，默认统一尺寸')
                else:
                    self.assertEqual(default, '原图尺寸', '默认原图尺寸才不改变已有出图结果')

    def test_resize_changes_cache_key(self):
        """同一张图改成指定尺寸后必须重算，不能命中上一次的原图缓存。"""
        base = {'pose_id': 'POS-SEXY-P001', 'angle': '正面'}
        original = nodes.PoseGallery.IS_CHANGED(**base)
        resized = nodes.PoseGallery.IS_CHANGED(**base, resize_mode='指定尺寸（居中裁剪）', width=512, height=512)
        self.assertNotEqual(original, resized)


class CharacterRecipeTests(unittest.TestCase):
    """三合一配方：三路 ID 都是必填字符串，其余参数可省，校验不触发下载。"""

    def test_three_ids_are_required_and_optional_keys_are_optional(self):
        spec = nodes.CharacterRecipe.INPUT_TYPES()
        for key in ('face_id', 'costume_id', 'pose_id'):
            with self.subTest(key=key):
                self.assertIn(key, spec['required'])
                self.assertEqual(spec['required'][key][0], 'STRING')
        for key in ('pose_angle', 'costume_library', 'use_depth'):
            with self.subTest(key=key):
                self.assertIn(key, spec['optional'], f'{key} 放 required 会让省略它的 API 调用整条链被丢弃')

    def test_validation_accepts_omitted_optional_inputs(self):
        self.assertIs(nodes.CharacterRecipe.VALIDATE_INPUTS(), True)
        self.assertIs(nodes.CharacterRecipe.VALIDATE_INPUTS(
            face_id='FACE-0001', costume_id='SPR-0001', pose_id='POS-SEXY-P001'), True)

    def test_validation_rejects_unknown_ids(self):
        result = nodes.CharacterRecipe.VALIDATE_INPUTS(face_id='NOPE')
        self.assertIsInstance(result, str)
        self.assertIn('NOPE', result)

    def test_validation_rejects_unknown_costume_library(self):
        result = nodes.CharacterRecipe.VALIDATE_INPUTS(costume_library='not-a-library')
        self.assertIsInstance(result, str)
        self.assertIn('not-a-library', result)

    def test_depth_switch_points_at_the_same_pose_by_number(self):
        """深度库与姿势库编号一一对应，只差前缀；换库后必须仍能取到同一动作。"""
        pose = nodes.item('pose', 'POS-SEXY-P001')
        depth = nodes.item('depth', 'POS-SEXY-P001'.replace('POS-', 'DEP-', 1))
        self.assertEqual(pose['分类2'], depth['分类2'])
        self.assertEqual(len(depth['原图']), 5)

    def test_validation_accepts_pose_id_when_depth_is_on(self):
        """打开 use_depth 后 pose_id 仍是 POS- 开头：校验必须自己换前缀，
        否则工作流会因为「未知深度姿势 ID：POS-SEXY-P001」整条被判失败。"""
        self.assertIs(nodes.CharacterRecipe.VALIDATE_INPUTS(
            pose_id='POS-SEXY-P001', use_depth=True), True)
        self.assertIs(nodes.CharacterRecipe.VALIDATE_INPUTS(
            pose_id='DEP-SEXY-P001', use_depth=True), True)

    def test_prompt_helpers_keep_chinese_and_skip_japanese(self):
        face = nodes.item('face', 'FACE-0001')
        self.assertIn('短发', nodes._describe_zh(face))
        # 脸部与姿势索引里没有英文词条：英文 prompt 宁可空着，也别把日文塞进去
        self.assertEqual(nodes._describe_en(face), '')
        costume = nodes.item('costume', 'SPR-0001')
        self.assertIn('ivory', nodes._describe_en(costume))


def cls_default(library):
    return {'pose': nodes.PoseGallery.DEFAULT_ID, 'depth': nodes.DepthGallery.DEFAULT_ID}[library]


class ImportToInputTests(unittest.TestCase):
    """给 LoadImage 之类的节点用时，素材要落成 input 目录里的真实文件。"""

    def _source(self, name='sample.png', payload=b'PNG'):
        path = INPUT_DIR.parent / f'src_{name}'
        path.write_bytes(payload)
        return path

    def test_plain_item_keeps_its_id_as_filename(self):
        name = nodes.import_to_input('costume', 'SPR-0002', None, self._source())
        self.assertEqual(name, 'ref_SPR-0002.png')
        self.assertEqual((INPUT_DIR / name).read_bytes(), b'PNG')

    def test_pose_angle_is_ascii_suffixed(self):
        name = nodes.import_to_input('pose', 'POS-SEXY-P031', '仰视', self._source())
        self.assertEqual(name, 'ref_POS-SEXY-P031_low.png')

    def test_reimport_overwrites_instead_of_piling_up(self):
        source = self._source(payload=b'PNG-v1')
        first = nodes.import_to_input('face', 'FACE-0001', None, source)
        source.write_bytes(b'PNG-v2')
        second = nodes.import_to_input('face', 'FACE-0001', None, source)
        self.assertEqual(first, second)
        self.assertEqual((INPUT_DIR / second).read_bytes(), b'PNG-v2')
        self.assertEqual(len([p for p in INPUT_DIR.iterdir() if p.name.startswith('ref_FACE-0001')]), 1)

    def test_unknown_characters_are_neutralised(self):
        name = nodes.import_to_input('costume', 'SPR 0001/../x', None, self._source())
        self.assertNotIn('/', name)
        self.assertNotIn(' ', name)


class CacheOnDemandTests(unittest.TestCase):
    """浏览时看过的原图必须落进 library/<库>/png/，下次打开与出图都直接命中本地。

    这两条路由一旦把 png 的 remote 参数收回成 False，缺图就只返回 404，
    前端会退到浏览器直连源站——图只会进浏览器缓存，永远不落进插件目录。
    """

    def test_file_route_lets_catalog_fetch_png_and_cache_it(self):
        import asyncio
        seen = []

        def resolver(kind, filename, library, remote):
            seen.append((kind, remote))
            return Path(f'{kind}.bin')

        for kind, expected in (('png', True), ('thumbs', True), ('img', False)):
            seen.clear()
            asyncio.run(nodes._file(resolver, kind, 'a.bin', 'costume'))
            with self.subTest(kind=kind):
                self.assertEqual(seen[0], (kind, expected))

    def test_asset_by_id_route_lets_catalog_fetch_png(self):
        import asyncio
        seen = []
        original = nodes.asset_by_id
        nodes.asset_by_id = lambda lib, iid, kind, angle, remote: (seen.append((kind, remote)) or Path('x.png'))
        try:
            for kind in ('png', 'thumbs', 'img'):
                seen.clear()
                request = types.SimpleNamespace(
                    match_info={'library': 'costume', 'kind': kind, 'item_id': 'SPR-0001'}, query={})
                asyncio.run(nodes.asset_by_id_route(request))
                with self.subTest(kind=kind):
                    self.assertEqual(seen[0], (kind, kind in ('png', 'thumbs')))
        finally:
            nodes.asset_by_id = original


if __name__ == '__main__':
    unittest.main()
