# tests/test_runtime.py
# 运行期行为测试：推送编码、会话统计口径、连续失败终止、凭据校验、配置容错
import importlib
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import main
import push as push_module


class FakeResponse:
    """read 接口的假响应：succ + synckey，供会话循环测试使用"""
    status_code = 200
    text = '{"succ": 1, "synckey": 12345}'

    def json(self):
        return {"succ": 1, "synckey": 12345}

    def raise_for_status(self):
        return None


class FakePushResponse:
    """推送渠道的假响应：WxPusher 成功码为 1000"""
    status_code = 200
    text = '{"code":1000}'

    def json(self):
        return {"code": 1000}

    def raise_for_status(self):
        return None


class TestPushEncoding(unittest.TestCase):
    """wxpusher 把内容拼进 URL 路径：必须整体编码，否则 # / 换行会截断内容"""

    def test_wxpusher_content_is_percent_encoded(self):
        notifier = push_module.PushNotification()
        content = "完成 #话题 20/40 分钟\n第二行"
        with mock.patch.object(push_module.requests, "get", return_value=FakePushResponse()) as get:
            self.assertTrue(notifier.push_wxpusher(content, "SPT123"))
        url = get.call_args[0][0]
        self.assertNotIn("#", url)
        self.assertNotIn("\n", url)
        self.assertIn("%23", url)      # #
        self.assertIn("%2F", url)      # /
        self.assertIn("%0A", url)      # 换行

    def test_unknown_method_returns_false(self):
        self.assertFalse(push_module.push("hi", "not-a-channel"))


class TestSessionAccounting(unittest.TestCase):
    """run_session 返回的计入秒数必须等于各次上报 rt 之和（服务端口径）"""

    def _run(self, read_num=3):
        sent = []

        def fake_post(url, **kwargs):
            sent.append(json.loads(kwargs["data"]))
            return FakeResponse()

        with mock.patch.object(main, "http_post", fake_post), \
                mock.patch.object(main.time, "sleep", lambda seconds: None), \
                mock.patch.object(main, "effective_read_num", lambda n: read_num):
            result = main.run_session(lambda message: None)
        return result, sent

    def test_credited_seconds_matches_sum_of_rt(self):
        (completed, credited, elapsed), sent = self._run(read_num=3)
        self.assertEqual(completed, 3)
        self.assertEqual(len(sent), 3)
        self.assertEqual(credited, sum(item["rt"] for item in sent))
        self.assertGreaterEqual(elapsed, 0)
        for item in sent:
            self.assertLessEqual(item["rt"], main.MAX_RT_SECONDS)
            self.assertIn("sg", item)
            self.assertIn("s", item)

    def test_consistency_fields_from_pool(self):
        _, sent = self._run(read_num=2)
        entry = config.READ_POOL[0]
        for item in sent:
            self.assertEqual(item["b"], entry["b"])
            self.assertEqual(item["c"], entry["c"])
            self.assertEqual(item["ci"], entry["ci"])
            self.assertEqual(item["sm"], entry["sm"])


class TestRtBounds(unittest.TestCase):
    """rt 必须落在 [1, MAX_RT_SECONDS]：时钟回拨不能产生负值，异常耗时不能突破上限"""

    class FakeTime:
        def __init__(self, values):
            self._values = list(values)
            self._last = values[-1]

        def time(self):
            return self._values.pop(0) if self._values else self._last

        def sleep(self, seconds):
            return None

    def _rt_values(self, clock_values):
        sent = []

        def fake_post(url, **kwargs):
            sent.append(json.loads(kwargs["data"]))
            return FakeResponse()

        with mock.patch.object(main, "time", self.FakeTime(clock_values)), \
                mock.patch.object(main, "http_post", fake_post), \
                mock.patch.object(main, "effective_read_num", lambda n: 2), \
                mock.patch.object(main, "push", lambda *a, **k: False):
            main.run_session(lambda message: None)
        return [item["rt"] for item in sent]

    def test_clock_rollback_never_produces_negative_rt(self):
        # session_start, lastTime, (MAX check, thisTime) × 2, elapsed
        rts = self._rt_values([1000, 1000, 1030, 1030, 900, 800, 1000])
        self.assertEqual(rts[0], 60)         # 首轮 lastTime = now - 30 → 1030-970
        self.assertEqual(rts[1], 1)          # 800 - 1030 = -230 → 夹到 1
        for rt in rts:
            self.assertGreaterEqual(rt, 1)
            self.assertLessEqual(rt, main.MAX_RT_SECONDS)

    def test_huge_gap_is_clamped(self):
        rts = self._rt_values([1000, 1000, 2000, 9000, 9001, 9800, 9800])
        for rt in rts:
            self.assertLessEqual(rt, main.MAX_RT_SECONDS)


class TestFailureHandling(unittest.TestCase):
    def test_terminates_after_consecutive_failures(self):
        def boom(*args, **kwargs):
            raise main.RequestException("network down")

        with mock.patch.object(main, "http_post", boom), \
                mock.patch.object(main.time, "sleep", lambda seconds: None), \
                mock.patch.object(main, "push", lambda *a, **k: False), \
                mock.patch.object(main, "effective_read_num", lambda n: 2):
            with self.assertRaises(RuntimeError):
                main.run_session(lambda message: None)

    def test_non_json_response_retries_then_terminates(self):
        class Broken(FakeResponse):
            def json(self):
                raise ValueError("not json")

        with mock.patch.object(main, "http_post", lambda *a, **k: Broken()), \
                mock.patch.object(main.time, "sleep", lambda seconds: None), \
                mock.patch.object(main, "push", lambda *a, **k: False), \
                mock.patch.object(main, "effective_read_num", lambda n: 2):
            with self.assertRaises(RuntimeError):
                main.run_session(lambda message: None)


class TestSynckeyRotation(unittest.TestCase):
    """缺 synckey 且无法修复时应换书继续，全部条目失败才终止"""

    @staticmethod
    def _resp(payload):
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = payload
        return resp

    def _make_pool(self):
        return [
            {"label": "A", "b": "aaaa", "bookId": "", "c": "ca", "ci": 1, "co": 10, "sm": "甲", "pr": 1},
            {"label": "B", "b": "bbbb", "bookId": "123456", "c": "cb", "ci": 2, "co": 20, "sm": "乙", "pr": 2},
        ]

    def test_rotates_and_terminates_when_all_entries_fail(self):
        """A 无 bookId 且缺 synckey → 立即换到 B；B 修复 3 次无效 → 全部失败终止"""
        pool = self._make_pool()

        with mock.patch.object(main, "READ_POOL", pool), \
                mock.patch.object(main, "http_post", mock.Mock(return_value=self._resp({"succ": 1}))), \
                mock.patch.object(main, "fix_no_synckey", lambda book_id: None), \
                mock.patch.object(main.time, "sleep", lambda s: None), \
                mock.patch.object(main, "push", lambda *a, **k: False), \
                mock.patch.object(main, "effective_read_num", lambda n: 3):
            with self.assertRaises(RuntimeError) as ctx:
                main.run_session(lambda message: None)
        # 终止消息里应包含换书统计与修复建议
        self.assertIn("全部 2 个条目", str(ctx.exception))
        self.assertIn("bookId", str(ctx.exception))

    def test_session_continues_when_other_entry_has_synckey(self):
        """A 缺 synckey 换到 B 后，B 的正常响应让会话继续完成"""
        pool = self._make_pool()

        def fake_post(url, **kwargs):
            payload = json.loads(kwargs["data"])
            if payload["b"] == "aaaa":
                return self._resp({"succ": 1})                      # A 一直缺 synckey
            return self._resp({"succ": 1, "synckey": 1})            # B 正常

        with mock.patch.object(main, "READ_POOL", pool), \
                mock.patch.object(main, "http_post", fake_post), \
                mock.patch.object(main, "fix_no_synckey", lambda book_id: None), \
                mock.patch.object(main.time, "sleep", lambda s: None), \
                mock.patch.object(main, "effective_read_num", lambda n: 2), \
                mock.patch.object(main.random, "choice", lambda seq: seq[0]):
            completed, credited, _ = main.run_session(lambda message: None)
        self.assertEqual(completed, 2)


class TestCredentialValidation(unittest.TestCase):
    def test_missing_skey_raises_fast(self):
        curl = "curl 'https://weread.qq.com/web/book/read' -H 'accept: */*'"
        with mock.patch.object(main, "curl_str", curl), \
                mock.patch.object(main, "cookies", {"wr_vid": "1"}), \
                mock.patch.object(main, "push", lambda *a, **k: False):
            with self.assertRaises(RuntimeError):
                main.validate_credentials()

    def test_valid_cookie_passes(self):
        curl = "curl 'https://weread.qq.com/web/book/read' -H 'cookie: wr_vid=1; wr_skey=abcd1234'"
        with mock.patch.object(main, "curl_str", curl), \
                mock.patch.object(main, "cookies", {"wr_vid": "1", "wr_skey": "abcd1234"}):
            main.validate_credentials()  # 不应抛异常

    def test_no_curl_str_skips_validation(self):
        with mock.patch.object(main, "curl_str", None):
            main.validate_credentials()


class TestCookieExportQuoting(unittest.TestCase):
    def test_replaces_cookie_in_double_quoted_curl(self):
        curl = ('curl "https://weread.qq.com/web/book/read" '
                '-H "cookie: wr_vid=old; wr_skey=old" -H "accept: */*"')
        out = main.build_curl_with_cookies(curl, {"wr_vid": "new", "wr_skey": "fresh"}, {})
        self.assertIn('-H "cookie: wr_vid=new; wr_skey=fresh"', out)
        self.assertNotIn("wr_skey=old", out)

    def test_exported_curl_matches_bash_style(self):
        curl = "curl 'https://weread.qq.com/web/book/read' -H 'cookie: wr_vid=old'"
        out = main.build_curl_with_cookies(curl, {"wr_vid": "new"}, {})
        headers, cookies = config.convert(out)
        self.assertEqual(cookies, {"wr_vid": "new"})


class TestConfigEnvParsing(unittest.TestCase):
    """非法环境变量不应让任务直接崩溃（Actions 里配置手误会很难排查）"""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("READ_NUM", "START_JITTER_MAX")}

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(config)

    def test_invalid_read_num_falls_back(self):
        os.environ["READ_NUM"] = "forty"
        cfg = importlib.reload(config)
        self.assertEqual(cfg.READ_NUM, 40)

    def test_whitespace_read_num_parsed(self):
        os.environ["READ_NUM"] = "  12  "
        cfg = importlib.reload(config)
        self.assertEqual(cfg.READ_NUM, 12)

    def test_zero_read_num_clamped_to_one(self):
        os.environ["READ_NUM"] = "0"
        cfg = importlib.reload(config)
        self.assertEqual(cfg.READ_NUM, 1)

    def test_invalid_jitter_falls_back(self):
        os.environ["START_JITTER_MAX"] = "abc"
        cfg = importlib.reload(config)
        self.assertEqual(cfg.START_JITTER_MAX, 2700)


if __name__ == "__main__":
    unittest.main()
