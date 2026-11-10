# tests/test_capture_tool.py
# 抓包转换工具 tests/tools/capture_to_pool.py 的单元测试
# 运行方式：在项目根目录执行  python3 -m unittest discover -s tests -v
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TOOL_PATH = os.path.join(ROOT, 'tools', 'capture_to_pool.py')
spec = importlib.util.spec_from_file_location('capture_to_pool', TOOL_PATH)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

import config

SAMPLE_BODY = (
    '{"appId":"wb1","b":"36d322f07186022636daa5e","c":"ecc32f3013eccbc87e4b62e",'
    '"ci":3,"co":120,"sm":"测试章节摘要","pr":8,"rt":30,"ts":1744264311434,'
    '"rn":466,"sg":"x","ct":1744264311,"ps":"p","pc":"pc","s":"ss"}'
)

SAMPLE_CURL_BASH = (
    "curl 'https://weread.qq.com/web/book/read' "
    "-H 'accept: application/json, text/plain, */*' "
    "-H 'user-agent: Mozilla/5.0 Chrome/131' "
    "--data-raw '" + SAMPLE_BODY + "'"
)

SAMPLE_CURL_WINDOWS = (
    'curl "https://weread.qq.com/web/book/read" '
    '-H "accept: application/json" '
    '--data-raw "' + SAMPLE_BODY.replace('"', '\\"') + '"'
)


class TestParseCurl(unittest.TestCase):
    def test_parse_bash_format(self):
        headers, body = tool.parse_curl(SAMPLE_CURL_BASH)
        self.assertEqual(headers['accept'], 'application/json, text/plain, */*')
        self.assertIn('"b":"36d322f07186022636daa5e"', body)

    def test_parse_windows_double_quotes(self):
        headers, body = tool.parse_curl(SAMPLE_CURL_WINDOWS)
        self.assertEqual(headers['accept'], 'application/json')
        self.assertIn('"ci":3', body)

    def test_parse_unbalanced_quotes_raises(self):
        with self.assertRaises(SystemExit):
            tool.parse_curl("curl 'https://x -H 'accept: */*'")


class TestBuildEntry(unittest.TestCase):
    def test_build_entry_full(self):
        payload = __import__('json').loads(SAMPLE_BODY)
        entry = tool.build_entry(payload, '3300060341')
        self.assertEqual(entry['b'], '36d322f07186022636daa5e')
        self.assertEqual(entry['bookId'], '3300060341')
        self.assertEqual(entry['ci'], 3)
        self.assertEqual(entry['sm'], '测试章节摘要')

    def test_build_entry_missing_field(self):
        payload = __import__('json').loads(SAMPLE_BODY)
        del payload['sm']
        with self.assertRaises(SystemExit):
            tool.build_entry(payload, '1')


class TestFormatAndAppend(unittest.TestCase):
    def test_format_entry_keys_and_types(self):
        entry = tool.build_entry(__import__('json').loads(SAMPLE_BODY), '3300060341')
        text = tool.format_entry(entry)
        for key in tool.FIELD_ORDER:
            self.assertIn(f'"{key}"', text)
        self.assertIn('"ci": 3,', text)          # 数字不加引号
        self.assertIn('"b": "36d3', text)         # 字符串加引号

    def test_append_to_config_and_reload(self):
        """追加到 config.py 副本后，重新加载应得到 2 个结构合法的条目"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_config = os.path.join(tmp, 'config.py')
            shutil.copy(os.path.join(ROOT, 'config.py'), tmp_config)

            entry = tool.build_entry(__import__('json').loads(SAMPLE_BODY), '3300060341')
            tool.append_to_config(tool.format_entry(entry), tmp_config)

            mod_spec = importlib.util.spec_from_file_location('config_tmp', tmp_config)
            cfg = importlib.util.module_from_spec(mod_spec)
            mod_spec.loader.exec_module(cfg)

            self.assertEqual(len(cfg.READ_POOL), 2)
            required = {'b', 'bookId', 'c', 'ci', 'co', 'sm', 'pr'}
            for item in cfg.READ_POOL:
                self.assertTrue(required.issubset(item.keys()))
            self.assertEqual(cfg.READ_POOL[1]['bookId'], '3300060341')

    def test_convert_roundtrip_on_new_entry(self):
        """新条目对应的字段经 config.convert 闭环不受影响（工具产出的 curl 仍可被解析）"""
        headers, cookies = config.convert(SAMPLE_CURL_BASH)
        self.assertEqual(headers['user-agent'], 'Mozilla/5.0 Chrome/131')


if __name__ == '__main__':
    unittest.main()
