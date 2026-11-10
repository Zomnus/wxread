# tests/test_wxread.py
# P1-5：单元测试（main.py 已函数化，可安全 import，无网络副作用）
# 运行方式：在项目根目录执行  python3 -m unittest discover -s tests -v
import hashlib
import importlib
import os
import re
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from main import (
    encode_data,
    cal_hash,
    effective_read_num,
    build_curl_with_cookies,
    _extract_today_seconds,
    MAX_RT_SECONDS,
    SLEEP_MIN_SECONDS,
    SLEEP_MAX_SECONDS,
    MAX_CONSECUTIVE_FAILURES,
    PROGRESS_CAP,
)


class TestSignature(unittest.TestCase):
    """签名算法回归：算法本体未改动，行为必须与原版完全一致"""

    def test_encode_data_sorted_and_quoted(self):
        result = encode_data({"b": "x y", "a": 1, "c": "中/文"})
        self.assertEqual(result, "a=1&b=x%20y&c=%E4%B8%AD%2F%E6%96%87")

    def test_cal_hash_regression_golden(self):
        # 黄金基线：用 config.data 模板（剔除 s 自身）计算，值必须恒定
        d = {k: v for k, v in config.data.items() if k != "s"}
        self.assertEqual(cal_hash(encode_data(d)), "b352ad8c")

    def test_cal_hash_deterministic(self):
        self.assertEqual(cal_hash("abc123"), cal_hash("abc123"))

    def test_sg_algorithm_matches_template(self):
        # sg = SHA256(ts + rn + 盐)，模板值自洽（上游抓包未改动 ts/rn）
        KEY = "3c5c8717f3daf09iop3423zafeqoi"
        d = config.data
        computed = hashlib.sha256(f"{d['ts']}{d['rn']}{KEY}".encode()).hexdigest()
        self.assertEqual(computed, d["sg"])


class TestConfig(unittest.TestCase):
    def test_convert_headers_and_cookies(self):
        curl = (
            "curl 'https://weread.qq.com/web/book/read' "
            "-H 'accept: application/json, text/plain, */*' "
            "-H 'user-agent: Mozilla/5.0 Chrome/131' "
            "-H 'cookie: wr_vid=123; wr_skey=abcdef12'"
        )
        headers, cookies = config.convert(curl)
        self.assertEqual(cookies["wr_vid"], "123")
        self.assertEqual(cookies["wr_skey"], "abcdef12")
        self.assertEqual(headers["user-agent"], "Mozilla/5.0 Chrome/131")
        self.assertNotIn("cookie", {k.lower() for k in headers})

    def test_convert_cookie_dash_b(self):
        curl = "curl 'https://weread.qq.com/x' -b 'wr_vid=9; wr_skey=xyz' -H 'accept: */*'"
        headers, cookies = config.convert(curl)
        self.assertEqual(cookies["wr_vid"], "9")
        self.assertEqual(cookies["wr_skey"], "xyz")

    def test_convert_windows_double_quotes(self):
        """P2-3：兼容 Windows "Copy as cURL (cmd)" 双引号格式"""
        curl = ('curl "https://weread.qq.com/web/book/read" '
                '-H "accept: application/json" '
                '-H "cookie: wr_vid=5; wr_skey=k" --compressed')
        headers, cookies = config.convert(curl)
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(cookies, {"wr_vid": "5", "wr_skey": "k"})

    def test_convert_ansi_c_quotes(self):
        """P2-3：兼容新版 Chrome / Git Bash 的 $'...' ANSI-C 引号格式"""
        curl = ("curl 'https://weread.qq.com/x' "
                "-H $'accept: application/json, text/plain, */*' "
                "-H $'cookie: a=1; b=2'")
        headers, cookies = config.convert(curl)
        self.assertEqual(headers["accept"], "application/json, text/plain, */*")
        self.assertEqual(cookies, {"a": "1", "b": "2"})

    def test_convert_no_space_after_colon(self):
        """P2-3：兼容 "name:value" 无空格写法（原正则会漏解析）"""
        curl = "curl 'https://weread.qq.com/x' -H 'content-type:application/json' -b 'c=1'"
        headers, cookies = config.convert(curl)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(cookies, {"c": "1"})

    def test_convert_long_flag_forms(self):
        """P2-3：兼容 --header / --cookie 长参数形式"""
        curl = ("curl 'https://weread.qq.com/x' "
                "--header 'accept: application/json' "
                "--cookie 'wr_vid=7'")
        headers, cookies = config.convert(curl)
        self.assertEqual(headers["accept"], "application/json")
        self.assertEqual(cookies, {"wr_vid": "7"})

    def test_randomize_sentry_trace(self):
        h = {"baggage": "sentry-environment=production,sentry-trace_id=1ff5a0725f8841088b42f97109c45862,sentry-public_key=ed67ed71"}
        out = config.randomize_sentry_trace(dict(h))
        self.assertNotIn("1ff5a0725f8841088b42f97109c45862", out["baggage"])
        self.assertIn("sentry-public_key=ed67ed71", out["baggage"])
        self.assertIn("sentry-environment=production", out["baggage"])
        self.assertRegex(out["baggage"], r"sentry-trace_id=[0-9a-f]{32}")

    def test_randomize_sentry_trace_no_baggage(self):
        h = {"accept": "application/json"}
        out = config.randomize_sentry_trace(dict(h))
        self.assertEqual(out, {"accept": "application/json"})

    def test_read_pool_structure(self):
        """READ_POOL 每个条目必须包含全部一致性字段（P1-1）"""
        required = {"b", "bookId", "c", "ci", "co", "sm", "pr"}
        self.assertGreaterEqual(len(config.READ_POOL), 1)
        for entry in config.READ_POOL:
            self.assertTrue(required.issubset(entry.keys()), f"缺少字段: {required - set(entry.keys())}")


class TestRandomizationBounds(unittest.TestCase):
    def test_effective_read_num_bounds(self):
        for _ in range(200):
            n = effective_read_num(40)
            self.assertGreaterEqual(n, 36)
            self.assertLessEqual(n, 44)

    def test_effective_read_num_minimum_one(self):
        for _ in range(50):
            self.assertGreaterEqual(effective_read_num(1), 1)

    def test_randomization_constants_sane(self):
        self.assertLess(SLEEP_MIN_SECONDS, SLEEP_MAX_SECONDS)
        self.assertGreater(MAX_RT_SECONDS, SLEEP_MAX_SECONDS)
        self.assertGreaterEqual(MAX_CONSECUTIVE_FAILURES, 3)
        self.assertGreater(PROGRESS_CAP, 0)


class TestCookieExport(unittest.TestCase):
    def test_build_curl_replaces_cookie_header(self):
        curl = "curl 'https://weread.qq.com/web/book/read' -H 'accept: */*' -H 'cookie: wr_vid=old; wr_skey=old'"
        out = build_curl_with_cookies(curl, {"wr_vid": "new", "wr_skey": "fresh123"}, {})
        self.assertIn("-H 'cookie: wr_vid=new; wr_skey=fresh123'", out)
        self.assertNotIn("wr_skey=old", out)
        self.assertIn("-H 'accept: */*'", out)

    def test_build_curl_replaces_dash_b(self):
        curl = "curl 'https://weread.qq.com/web/book/read' -b 'wr_vid=old' -H 'accept: */*'"
        out = build_curl_with_cookies(curl, {"wr_vid": "new"}, {})
        self.assertIn("-b 'wr_vid=new'", out)

    def test_build_curl_appends_when_no_cookie(self):
        curl = "curl 'https://weread.qq.com/web/book/read' -H 'accept: */*'"
        out = build_curl_with_cookies(curl, {"wr_vid": "1"}, {})
        self.assertIn("-H 'cookie: wr_vid=1'", out)

    def test_build_curl_synthesizes_from_headers(self):
        out = build_curl_with_cookies(None, {"wr_vid": "1", "wr_skey": "abc"}, {"accept": "application/json", "user-agent": "UA"})
        self.assertTrue(out.startswith("curl 'https://weread.qq.com/web/book/read'"))
        self.assertIn("-H 'accept: application/json'", out)
        self.assertIn("-H 'user-agent: UA'", out)
        self.assertIn("-H 'cookie: wr_vid=1; wr_skey=abc'", out)
        # 合成结果必须能被 convert() 再解析回来（回写闭环校验）
        headers, cookies = config.convert(out)
        self.assertEqual(cookies, {"wr_vid": "1", "wr_skey": "abc"})
        self.assertEqual(headers["user-agent"], "UA")


class TestReadStatsExtraction(unittest.TestCase):
    def test_extract_today_string_date(self):
        today = time.strftime("%Y-%m-%d")
        payload = {"data": {"days": [{"date": today, "readTime": 1234}, {"date": "2000-01-01", "readTime": 99}]}}
        self.assertEqual(_extract_today_seconds(payload), 1234)

    def test_extract_today_unix_timestamp(self):
        today_ts = int(time.time())
        payload = {"list": [{"ts": today_ts, "readSeconds": 600}]}
        self.assertEqual(_extract_today_seconds(payload), 600)

    def test_extract_no_match(self):
        payload = {"data": {"days": [{"date": "2000-01-01", "readTime": 99}]}}
        self.assertIsNone(_extract_today_seconds(payload))

    def test_extract_ignores_non_numeric_duration(self):
        today = time.strftime("%Y-%m-%d")
        payload = {"days": [{"date": today, "readTime": "1小时"}]}
        self.assertIsNone(_extract_today_seconds(payload))


class TestStartJitterParsing(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("START_JITTER_MAX")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("START_JITTER_MAX", None)
        else:
            os.environ["START_JITTER_MAX"] = self._saved
        importlib.reload(config)

    def _reload_with(self, value):
        if value is None:
            os.environ.pop("START_JITTER_MAX", None)
        else:
            os.environ["START_JITTER_MAX"] = value
        return importlib.reload(config)

    def test_default_2700(self):
        cfg = self._reload_with(None)
        self.assertEqual(cfg.START_JITTER_MAX, 2700)

    def test_zero_disables(self):
        cfg = self._reload_with("0")
        self.assertEqual(cfg.START_JITTER_MAX, 0)

    def test_custom_value(self):
        cfg = self._reload_with("600")
        self.assertEqual(cfg.START_JITTER_MAX, 600)


if __name__ == "__main__":
    unittest.main()
