# tests/test_pool_autodetect.py
# 阅读池自动识别测试：直接把 read 请求的 curl 当作池条目来源
# 运行方式：在项目根目录执行  python3 -m unittest discover -s tests -v
import importlib
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ENV_KEYS = ['WXREAD_CURL_BASH', 'WXREAD_CURL_BASH_2', 'WXREAD_CURL_BASH_3',
            'WXREAD_CURL_BASH_4', 'WXREAD_CURL_BASH_5']


def _body(b, c, ci, co, sm, pr):
    return json.dumps(
        {'appId': 'wb1', 'b': b, 'c': c, 'ci': ci, 'co': co, 'sm': sm, 'pr': pr,
         'rt': 30, 'ts': 1744264311434, 'rn': 466, 'sg': 'x', 'ct': 1744264311,
         'ps': 'p', 'pc': 'pc', 's': 'ss'},
        ensure_ascii=False, separators=(',', ':'),
    )


def _curl(url, body, referer=None, quote="'"):
    # Windows "Copy as cURL (cmd)" 用双引号包裹参数，内部引号写成 \"
    body_text = body.replace('"', '\\"') if quote == '"' else body
    parts = [f"curl '{url}'"]
    if referer:
        parts.append(f"-H {quote}referer: {referer}{quote}")
    parts.append(f"-H {quote}accept: application/json{quote}")
    parts.append(f"--data-raw {quote}{body_text}{quote}")
    return ' '.join(parts)


BOOK_A = _body('36d322f07186022636daa5e', 'ecc32f3013eccbc87e4b62e', 3, 120, '第一本书摘要', 8)
BOOK_B = _body('6f932ec05dd9eb6f96f14b9', 'a87322c014a87ff679a21ea', 5, 260, '第二本书摘要', 11)

CURL_A = _curl('https://weread.qq.com/web/book/read', BOOK_A,
               referer='https://weread.qq.com/web/bookDetail/3300060341')
CURL_B = _curl('https://weread.qq.com/web/book/read', BOOK_B,
               referer='https://weread.qq.com/web/bookDetail/4400012345')
# 非 read 报文：renewal 请求没有 b/c 等字段，应被忽略
CURL_RENEW = ("curl 'https://weread.qq.com/web/login/renewal' "
              "-H 'accept: */*' --data-raw '{\"rq\":\"/web/book/read\",\"ql\":false}'")


class PoolTestBase(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        for key in ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import config
        importlib.reload(config)

    def load(self, **env):
        for key, value in env.items():
            os.environ[key] = value
        import config
        return importlib.reload(config)


class TestAutoDetect(PoolTestBase):
    def test_single_curl_becomes_pool_entry(self):
        cfg = self.load(WXREAD_CURL_BASH=CURL_A)
        self.assertEqual(len(cfg.CURL_POOL), 1)
        entry = cfg.CURL_POOL[0]
        self.assertEqual(entry['b'], '36d322f07186022636daa5e')
        self.assertEqual(entry['c'], 'ecc32f3013eccbc87e4b62e')
        self.assertEqual(entry['ci'], 3)
        self.assertEqual(entry['co'], 120)
        self.assertEqual(entry['sm'], '第一本书摘要')
        self.assertEqual(entry['pr'], 8)
        # bookId 从 referer 的 bookDetail 链接推断
        self.assertEqual(entry['bookId'], '3300060341')
        # 有抓包条目时只用抓包条目（不再混入默认三体条目）
        self.assertEqual(len(cfg.READ_POOL), 1)
        self.assertEqual(cfg.READ_POOL[0]['b'], '36d322f07186022636daa5e')

    def test_multiple_curls_separated_by_blank_line(self):
        cfg = self.load(WXREAD_CURL_BASH=CURL_A + '\n\n' + CURL_B)
        self.assertEqual(len(cfg.CURL_POOL), 2)
        self.assertEqual({e['ci'] for e in cfg.CURL_POOL}, {3, 5})
        self.assertEqual(cfg.READ_POOL[0]['b'], '36d322f07186022636daa5e')
        self.assertEqual(cfg.READ_POOL[1]['b'], '6f932ec05dd9eb6f96f14b9')

    def test_multiple_curls_separated_by_comment_line(self):
        cfg = self.load(WXREAD_CURL_BASH=CURL_A + '\n#----\n' + CURL_B)
        self.assertEqual(len(cfg.CURL_POOL), 2)

    def test_extra_env_vars(self):
        cfg = self.load(WXREAD_CURL_BASH=CURL_A, WXREAD_CURL_BASH_2=CURL_B)
        self.assertEqual(len(cfg.CURL_POOL), 2)

    def test_duplicate_curls_are_deduplicated(self):
        cfg = self.load(WXREAD_CURL_BASH=CURL_A + '\n\n' + CURL_A)
        self.assertEqual(len(cfg.CURL_POOL), 2)      # 原始解析保留两条
        self.assertEqual(len(cfg.READ_POOL), 1)      # 合并时按 (b,c,co) 去重

    def test_non_read_request_is_ignored(self):
        cfg = self.load(WXREAD_CURL_BASH=CURL_RENEW)
        self.assertEqual(cfg.CURL_POOL, [])
        self.assertEqual(len(cfg.READ_POOL), len(cfg.DEFAULT_POOL))

    def test_windows_double_quotes(self):
        curl = _curl('https://weread.qq.com/web/book/read', BOOK_A, quote='"')
        cfg = self.load(WXREAD_CURL_BASH=curl)
        self.assertEqual(len(cfg.CURL_POOL), 1)
        self.assertEqual(cfg.CURL_POOL[0]['ci'], 3)

    def test_missing_referer_leaves_book_id_empty(self):
        curl = _curl('https://weread.qq.com/web/book/read', BOOK_A)
        cfg = self.load(WXREAD_CURL_BASH=curl)
        self.assertEqual(cfg.CURL_POOL[0]['bookId'], '')

    def test_no_env_uses_default_pool(self):
        cfg = self.load()
        self.assertEqual(cfg.CURL_POOL, [])
        self.assertEqual(len(cfg.READ_POOL), 1)
        self.assertEqual(cfg.READ_POOL[0]['bookId'], '3300060341')

    def test_cookie_still_parsed_from_multi_curl(self):
        curl = CURL_A.replace("--data-raw", "-H 'cookie: wr_vid=1; wr_skey=abcdef12' --data-raw")
        cfg = self.load(WXREAD_CURL_BASH=curl)
        self.assertEqual(cfg.cookies.get('wr_skey'), 'abcdef12')
        self.assertEqual(len(cfg.CURL_POOL), 1)

    def test_entry_keeps_referer(self):
        cfg = self.load(WXREAD_CURL_BASH=CURL_A + '\n\n' + CURL_B)
        self.assertIn('bookDetail/3300060341', cfg.CURL_POOL[0]['referer'])
        self.assertIn('bookDetail/4400012345', cfg.CURL_POOL[1]['referer'])


class TestApplySessionReferer(unittest.TestCase):
    def test_referer_follows_selected_book(self):
        import main
        headers = {'referer': 'https://weread.qq.com/web/bookDetail/4400012345'}
        with mock.patch.object(main, 'headers', headers):
            main.apply_session_referer(
                {'referer': 'https://weread.qq.com/web/bookDetail/3300060341'})
        self.assertIn('3300060341', headers['referer'])

    def test_case_insensitive_key_and_missing_referer(self):
        import main
        headers = {'Referer': 'https://weread.qq.com/web/bookDetail/4400012345'}
        with mock.patch.object(main, 'headers', headers):
            main.apply_session_referer({'referer': 'https://weread.qq.com/web/bookDetail/3300060341'})
            self.assertIn('3300060341', headers['Referer'])
            main.apply_session_referer({})          # 条目没带 referer：保持原样
            self.assertIn('3300060341', headers['Referer'])


class TestResolveBookId(unittest.TestCase):
    def test_use_session_book_id(self):
        import main
        with mock.patch.object(main, 'READ_POOL', [{'bookId': '3300060341'}]):
            self.assertEqual(main.resolve_book_id({'bookId': '4400012345'}), '4400012345')

    def test_fallback_to_pool(self):
        import main
        with mock.patch.object(main, 'READ_POOL', [{'bookId': ''}, {'bookId': '3300060341'}]):
            self.assertEqual(main.resolve_book_id({'bookId': ''}), '3300060341')

    def test_placeholder_ignored(self):
        import main
        with mock.patch.object(main, 'READ_POOL', [{'bookId': 'TODO_BOOK_ID'}]):
            self.assertEqual(main.resolve_book_id({}), '')

    def test_no_book_id_anywhere(self):
        import main
        with mock.patch.object(main, 'READ_POOL', [{'bookId': ''}]):
            self.assertEqual(main.resolve_book_id({'bookId': ''}), '')


if __name__ == '__main__':
    unittest.main()
