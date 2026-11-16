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
        known = set(nodes.NODE_CLASS_MAPPINGS) | BUILTIN
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
        """widgets_values 是按位置存的，个数对不上就会整体错位——加槽位时最容易踩。"""
        for node in self.workflow['nodes']:
            kind = node['type']
            if kind not in nodes.NODE_CLASS_MAPPINGS:
                continue
            with self.subTest(node=node['id'], type=kind):
                spec = nodes.NODE_CLASS_MAPPINGS[kind].INPUT_TYPES()
                expected = len(spec.get('required') or {}) + len(spec.get('optional') or {})
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

    def test_recipe_feeds_four_references_in_order(self):
        """四条参考的顺序是硬约定：姿势 → 脸 → 服装 → 发型，错一格就串身份。"""
        recipe = self.node_of('CharacterRecipe')
        texts = [node for node in self.workflow['nodes']
                 if node['type'] == 'TextEncodeQwenImage21' and
                 any((i.get('name') == 'prompt' and i.get('link')) for i in node.get('inputs') or [])]
        self.assertEqual(len(texts), 1)
        encoder = texts[0]

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
        encoder = next(node for node in self.workflow['nodes']
                       if node['type'] == 'TextEncodeQwenImage21' and
                       any(i.get('name') == 'prompt' for i in node.get('inputs') or []))
        slot = next(index for index, item in enumerate(encoder['inputs']) if item['name'] == 'prompt')
        source, source_slot = self.upstream_of(encoder, slot)
        self.assertEqual(source['type'], 'CharacterRecipe')
        self.assertEqual(source['outputs'][source_slot]['name'], 'prompt_zh')

    def test_single_node_chain_uses_the_hair_library(self):
        """单独节点那条链的 image_4 必须来自发型节点，不然这次新增的节点没被演示到。"""
        library_nodes = {node['type']: node for node in self.workflow['nodes']
                         if node['type'] in ('HairGallery', 'FaceGallery', 'CostumeGallery', 'PoseGallery')}
        self.assertEqual(set(library_nodes), {'HairGallery', 'FaceGallery', 'CostumeGallery', 'PoseGallery'})

        encoder = next(node for node in self.workflow['nodes']
                       if node['type'] == 'TextEncodeQwenImage21' and
                       not any(i.get('name') == 'prompt' for i in node.get('inputs') or []))
        expect = {'images.image_1': 'PoseGallery', 'images.image_2': 'FaceGallery',
                  'images.image_3': 'CostumeGallery', 'images.image_4': 'HairGallery'}
        for name, kind in expect.items():
            slot = next(index for index, item in enumerate(encoder['inputs']) if item['name'] == name)
            source, _ = self.upstream_of(encoder, slot)
            with self.subTest(port=name):
                self.assertEqual(source['type'], kind)


if __name__ == '__main__':
    unittest.main()
