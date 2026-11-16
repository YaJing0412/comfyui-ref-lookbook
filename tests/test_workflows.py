"""示例工作流的完整性检查。

工作流 JSON 最容易出的错是连线错位：加了槽位忘了改索引，节点一打开就串图，
而且只有手动拖进 ComfyUI 才会发现。这里把「结构」当成数据来断言，
覆盖不了出图效果，但能保证连线两端都成立。
"""

import json
import unittest
from pathlib import Path

# 节点包在测试环境里需要桩模块才能导入，这里复用 test_nodes 里那套加载器，
# 不再抄一遍——桩一旦分叉，两边断言的就是不同的东西。
from test_nodes import nodes

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / 'example_workflows'
SINGLE = WORKFLOWS / 'ref_gallery_qwen21.json'

# ComfyUI 内置节点：不要求本插件注册，但至少得是认识的类型。
BUILTIN = {'UNETLoader', 'LoraLoaderModelOnly', 'QwenImage21Cache', 'CLIPLoader', 'VAELoader',
           'TextEncodeQwenImage21', 'KSampler', 'VAEDecode', 'SaveImage', 'LoadImage',
           'ImageStitch', 'MarkdownNote'}

# 只有前端、没有 Python 类的节点（web/ref_gallery.js 里 LiteGraph.registerNodeType 注册）。
FRONTEND = {'ref_lookbook/WorkflowSwitch'}

# 开关节点按组标题里的序号找组，标题改了开关就哑了，所以标题当成契约来断言。
SLOT_ONE = '①'
SLOT_TWO = '②'
SLOT_SHARED = '③'


def load(path=SINGLE):
    return json.loads(path.read_text(encoding='utf-8'))


class WorkflowShapeTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load()
        self.nodes = {node['id']: node for node in self.workflow['nodes']}
        self.links = {link[0]: link for link in self.workflow['links']}

    def test_only_one_json_ships(self):
        """只要一个 json：两份分开维护时，改了一边忘了另一边是迟早的事。"""
        files = sorted(path.name for path in WORKFLOWS.glob('*.json'))
        self.assertEqual(files, ['ref_gallery_qwen21.json'])

    def test_node_types_are_known(self):
        known = set(nodes.NODE_CLASS_MAPPINGS) | BUILTIN | FRONTEND
        unknown = sorted({node['type'] for node in self.workflow['nodes']} - known)
        self.assertEqual(unknown, [], f'工作流里有不认识的节点：{unknown}')

    def test_every_link_has_two_live_ends(self):
        for link_id, source, source_slot, target, target_slot, kind in self.workflow['links']:
            with self.subTest(link=link_id):
                self.assertIn(source, self.nodes, f'{link_id} 起点节点不存在')
                self.assertIn(target, self.nodes, f'{link_id} 终点节点不存在')

                outputs = self.nodes[source].get('outputs') or []
                self.assertLess(source_slot, len(outputs), f'{link_id} 起点槽位越界')
                self.assertEqual(outputs[source_slot]['type'], kind)
                self.assertIn(link_id, outputs[source_slot].get('links') or [],
                              f'{link_id} 没登记在起点的输出上')

                inputs = self.nodes[target].get('inputs') or []
                self.assertLess(target_slot, len(inputs), f'{link_id} 终点槽位越界')
                self.assertEqual(inputs[target_slot]['link'], link_id,
                                 f'{link_id} 没写进终点的输入')
                self.assertEqual(inputs[target_slot]['type'], kind)

    def test_no_orphan_link_registered_on_outputs(self):
        for node in self.workflow['nodes']:
            for slot, output in enumerate(node.get('outputs') or []):
                for link_id in output.get('links') or []:
                    self.assertIn(link_id, self.links,
                                  f'{node["id"]} 第 {slot} 个输出登记了不存在的连线 {link_id}')

    def test_widget_values_match_input_types(self):
        """widgets_values 是按位置存的，个数对不上就会整体错位——加槽位时最容易踩。

        只数会变成控件的输入：forceInput 的插槽（提示词拼接节点的 extra）在画布上没有控件，
        存盘时也不会进 widgets_values。
        """
        for node in self.workflow['nodes']:
            kind = node['type']
            if kind not in nodes.NODE_CLASS_MAPPINGS:
                continue
            with self.subTest(node=node['id'], type=kind):
                spec = nodes.NODE_CLASS_MAPPINGS[kind].INPUT_TYPES()
                entries = list((spec.get('required') or {}).values()) + \
                    list((spec.get('optional') or {}).values())
                expected = sum(1 for entry in entries
                               if not (isinstance(entry[1], dict) and entry[1].get('forceInput')))
                self.assertEqual(len(node.get('widgets_values') or []), expected)


class RecipeWiringTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load()
        self.nodes = {node['id']: node for node in self.workflow['nodes']}

    def node_of(self, kind):
        found = [node for node in self.workflow['nodes'] if node['type'] == kind]
        self.assertEqual(len(found), 1, f'{kind} 应该正好一个')
        return found[0]

    def upstream_of(self, node, slot):
        """返回连到某个输入上的 (源节点, 源槽位)。"""
        link_id = (node.get('inputs') or [])[slot]['link']
        self.assertIsNotNone(link_id, f'{node["type"]} 第 {slot} 个输入没接线')
        _, source, source_slot, _, _, _ = next(link for link in self.workflow['links']
                                               if link[0] == link_id)
        return self.nodes[source], source_slot

    def encoder_of(self, image_2_source):
        """按 image_2 的来源认链：配方那条接配方节点，单独节点那条接脸部图库。

        以前靠「prompt 有没有接线」区分，加了提示词拼接之后两条链的 prompt 都接了线，只能换判据。
        """
        for node in self.workflow['nodes']:
            if node['type'] != 'TextEncodeQwenImage21':
                continue
            slot = next(index for index, item in enumerate(node['inputs']) if item['name'] == 'images.image_2')
            source, _ = self.upstream_of(node, slot)
            if source['type'] == image_2_source:
                return node
        self.fail(f'没有 image_2 接 {image_2_source} 的编码器')

    def test_recipe_feeds_four_references_in_order(self):
        """四条参考的顺序是硬约定：姿势 → 脸 → 服装 → 发型，错一格就串身份。"""
        recipe = self.node_of('CharacterRecipe')
        encoder = self.encoder_of('CharacterRecipe')

        expect = {'images.image_1': ('pose_image', 2), 'images.image_2': ('face_image', 0),
                  'images.image_3': ('costume_image', 1), 'images.image_4': ('hair_image', 8)}
        for name, (output_name, output_slot) in expect.items():
            slot = next(index for index, item in enumerate(encoder['inputs']) if item['name'] == name)
            source, source_slot = self.upstream_of(encoder, slot)
            with self.subTest(port=name):
                self.assertEqual(source['id'], recipe['id'])
                self.assertEqual(source_slot, output_slot)
                self.assertEqual(source['outputs'][output_slot]['name'], output_name)

    def test_recipe_prompt_is_linked(self):
        """提示词由节点拼好接进去，用户不用自己写；断掉这条线就等于退回手写。"""
        encoder = self.encoder_of('CharacterRecipe')
        slot = next(index for index, item in enumerate(encoder['inputs']) if item['name'] == 'prompt')
        source, source_slot = self.upstream_of(encoder, slot)
        self.assertEqual(source['type'], 'CharacterRecipe')
        self.assertEqual(source['outputs'][source_slot]['name'], 'prompt_zh')

    def test_single_chain_prompt_is_chinese_and_carries_the_hair_detail(self):
        """单独节点那条链的提示词：中文模板打底，所选发型的描述由拼接节点补进来。

        这一版的核心修复——只给模型看一张白色人台图时，长发选长发会被图 2 自带的头发盖掉。
        """
        encoder = self.encoder_of('FaceGallery')
        slot = next(index for index, item in enumerate(encoder['inputs']) if item['name'] == 'prompt')
        join, _ = self.upstream_of(encoder, slot)
        self.assertEqual(join['type'], 'PromptJoin')

        template = join['widgets_values'][0]
        self.assertIn('图4', template)
        self.assertIn('头发', template)
        self.assertRegex(template, r'[\u4e00-\u9fff]{5,}', '模板必须是中文，方便用户自己改')

        extra_slot = next(index for index, item in enumerate(join['inputs']) if item['name'] == 'extra')
        source, source_slot = self.upstream_of(join, extra_slot)
        self.assertEqual(source['type'], 'HairGallery')
        self.assertEqual(source['outputs'][source_slot]['name'], 'hair_detail')

    def test_single_node_chain_uses_the_hair_library(self):
        """单独节点那条链的 image_4 必须来自发型节点，不然这次新增的节点没被演示到。"""
        library_nodes = {node['type']: node for node in self.workflow['nodes']
                         if node['type'] in ('HairGallery', 'FaceGallery', 'CostumeGallery', 'PoseGallery')}
        self.assertEqual(set(library_nodes), {'HairGallery', 'FaceGallery', 'CostumeGallery', 'PoseGallery'})

        encoder = self.encoder_of('FaceGallery')
        expect = {'images.image_1': 'PoseGallery', 'images.image_2': 'FaceGallery',
                  'images.image_3': 'CostumeGallery', 'images.image_4': 'HairGallery'}
        for name, kind in expect.items():
            slot = next(index for index, item in enumerate(encoder['inputs']) if item['name'] == name)
            source, _ = self.upstream_of(encoder, slot)
            with self.subTest(port=name):
                self.assertEqual(source['type'], kind)


class SwitchTests(unittest.TestCase):
    """「选一组跑」开关：组标题、组内节点、默认静音状态三边必须对得上。

    `web/ref_gallery.js` 是拿组的 bounding 与节点中心点判断归属的，这里用同一套
    算法在 Python 里复算一遍——两边一旦分叉，用户点开关就会静音到错的节点。
    """

    def setUp(self):
        self.workflow = load()
        self.nodes = {node['id']: node for node in self.workflow['nodes']}

    def group_of(self, key):
        titles = [group for group in self.workflow.get('groups', []) if key in group['title']]
        self.assertEqual(len(titles), 1, f'含「{key}」的分组应该正好一个，实际 {len(titles)}')
        return titles[0]

    def nodes_in(self, key):
        x, y, w, h = self.group_of(key)['bounding']
        inside = []
        for node in self.workflow['nodes']:
            if node['type'] in FRONTEND:
                continue
            size = node.get('size') or [0, 0]
            center_x = node['pos'][0] + size[0] / 2
            center_y = node['pos'][1] + size[1] / 2
            if x <= center_x <= x + w and y <= center_y <= y + h:
                inside.append(node)
        return inside

    def test_switch_node_exists_and_defaults_to_first_group(self):
        switches = [node for node in self.workflow['nodes'] if node['type'] in FRONTEND]
        self.assertEqual(len(switches), 1, '开关应该正好一个')
        switch = switches[0]
        self.assertEqual(switch['properties']['on'], [True, False], '默认只跑 ①')
        self.assertEqual(switch.get('mode', 0), 0, '开关自己不能被静音，否则按钮跟着变灰')

    def test_groups_are_labelled_for_the_switch(self):
        """开关按 ① / ② 认组；标题里的序号改了就点不动，所以把序号当契约。"""
        self.assertEqual(len(self.nodes_in(SLOT_ONE)), 10,
                         '① 组是四个图库节点 + 提示词拼接 + 编码 + 采样 + 解码 + 存图 + 备用 LoadImage')
        self.assertEqual(len(self.nodes_in(SLOT_TWO)), 6, '② 组是配方 + 编码 + 采样 + 解码 + 两张存图')

    def test_default_state_matches_saved_modes(self):
        """json 里就把 ② 组标成静音：前端脚本没跑起来时也不能两条一起跑。"""
        for node in self.nodes_in(SLOT_ONE):
            with self.subTest(node=node['id']):
                self.assertEqual(node.get('mode', 0), 0, '① 组默认要跑')
        for node in self.nodes_in(SLOT_TWO):
            with self.subTest(node=node['id']):
                self.assertEqual(node.get('mode', 0), 2, '② 组默认静音')

    def test_shared_model_group_is_never_switched(self):
        """模型加载两条链共用，被一起静音就两条都跑不了。"""
        shared = self.nodes_in(SLOT_SHARED)
        self.assertGreaterEqual(len(shared), 5, '③ 组应该含整套模型加载')
        for node in shared:
            with self.subTest(node=node['id']):
                self.assertEqual(node.get('mode', 0), 0, '共用的模型节点不该带静音')

    def test_each_node_belongs_to_exactly_one_group(self):
        """一个节点只能落在一个组里，否则两组抢着改它的 mode，状态就打架了。"""
        buckets = {key: {node['id'] for node in self.nodes_in(key)}
                   for key in (SLOT_ONE, SLOT_TWO, SLOT_SHARED)}
        total = sum(len(ids) for ids in buckets.values())
        union = set().union(*buckets.values())
        self.assertEqual(total, len(union), f'有节点落在多个组里：{buckets}')
        note = next(node for node in self.workflow['nodes'] if node['type'] == 'MarkdownNote')
        self.assertNotIn(note['id'], union, '说明节点落在组内，点开关会被一起静音')

    def test_switch_sits_outside_every_group(self):
        """开关自己不能落在某个组里，否则切到那组时它会把自己也静音掉。"""
        switch = next(node for node in self.workflow['nodes'] if node['type'] in FRONTEND)
        size = switch['size']
        center_x = switch['pos'][0] + size[0] / 2
        center_y = switch['pos'][1] + size[1] / 2
        for group in self.workflow.get('groups', []):
            x, y, w, h = group['bounding']
            with self.subTest(group=group['title']):
                self.assertFalse(x <= center_x <= x + w and y <= center_y <= y + h,
                                 f'开关落进了「{group["title"]}」')


if __name__ == '__main__':
    unittest.main()

