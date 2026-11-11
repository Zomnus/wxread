import json
import logging
import os
import random
import time
import urllib.parse

import requests

from config import (
    PUSHPLUS_TOKEN,
    SERVERCHAN_SPT,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    WXPUSHER_SPT,
)

logger = logging.getLogger(__name__)

PUSH_ATTEMPTS = 3                      # 单个渠道最多尝试次数
PUSH_RETRY_MIN_SECONDS = 5             # 重试退避下限
PUSH_RETRY_MAX_SECONDS = 15            # 重试退避上限


class PushNotification:
    def __init__(self):
        self.pushplus_url = "https://www.pushplus.plus/send"
        self.telegram_url = "https://api.telegram.org/bot{}/sendMessage"
        self.server_chan_url = "https://sctapi.ftqq.com/{}.send"
        self.wxpusher_simple_url = "https://wxpusher.zjiecode.com/api/send/message/{}/{}"
        self.headers = {"Content-Type": "application/json"}
        # 同时兼容小写与大写代理环境变量（Actions 里常写成 HTTPS_PROXY）
        self.proxies = {
            key: value
            for key, value in {
                "http": os.getenv("http_proxy") or os.getenv("HTTP_PROXY"),
                "https": os.getenv("https_proxy") or os.getenv("HTTPS_PROXY"),
            }.items()
            if value
        }

    @staticmethod
    def _check_business_code(channel, response, hints):
        """HTTP 200 不代表推送成功——各渠道用业务码表示配置/参数错误。

        配置类错误重试也不会成功，识别到后直接给出修复提示并放弃重试。
        返回 True 表示业务成功。
        """
        try:
            result = response.json()
        except ValueError:
            return True  # 非 JSON 响应交由 HTTP 状态码判断
        code = result.get('code')
        success_codes = {'wxpusher': 1000, 'serverchan': 0, 'pushplus': 200}
        if code == success_codes.get(channel):
            return True
        msg = result.get('msg') or result.get('message') or response.text[:120]
        logger.error("%s 推送被拒绝：code=%s，msg=%s", channel, code, msg)
        if hints:
            logger.error("排查提示：%s", hints)
        return False

    def push_pushplus(self, content, token, is_success):
        attempts = PUSH_ATTEMPTS
        title = f"微信阅读-{'成功' if is_success else '失败'}"
        for attempt in range(attempts):
            try:
                response = requests.post(
                    self.pushplus_url,
                    data=json.dumps({"token": token, "title": title,"content": content,}).encode("utf-8"),headers=self.headers,timeout=10,)
                response.raise_for_status()
                if not self._check_business_code(
                    'pushplus', response,
                    "检查 PUSHPLUS_TOKEN 是否正确（pushplus.hxtrip.com 后台获取）",
                ):
                    return False
                logger.info("PushPlus 响应: %s", response.text)
                return True
            except requests.exceptions.RequestException as exc:
                logger.error("PushPlus 推送失败: %s", exc)
                if attempt < attempts - 1:
                    sleep_time = random.randint(PUSH_RETRY_MIN_SECONDS, PUSH_RETRY_MAX_SECONDS)
                    logger.info("%d 秒后重试...", sleep_time)
                    time.sleep(sleep_time)
        return False

    def push_telegram(self, content, bot_token, chat_id):
        url = self.telegram_url.format(bot_token)
        payload = {"chat_id": chat_id, "text": content}

        try:
            response = requests.post(url, json=payload, proxies=self.proxies, timeout=30)
            logger.info("Telegram 响应: %s", response.text)
            response.raise_for_status()
            return True
        except Exception as exc:
            logger.error("Telegram 代理发送失败: %s", exc)
            try:
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
                return True
            except Exception as inner_exc:
                logger.error("Telegram 发送失败: %s", inner_exc)
                return False

    def push_wxpusher(self, content, spt):
        attempts = PUSH_ATTEMPTS
        # content 直接拼进 URL 路径，必须整体百分号编码：
        # 否则内容中的换行、#、/ 会截断或破坏请求（# 之后的内容根本不会发送）
        safe_content = urllib.parse.quote(str(content), safe='')
        url = self.wxpusher_simple_url.format(spt, safe_content)

        for attempt in range(attempts):
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                if not self._check_business_code(
                    'wxpusher', response,
                    "code=1000/spt格式错误 通常是 WXPUSHER_SPT 不对：应为 wxpusher.zjiecode.com"
                    "「极简推送」页面给出的完整 spt（SPT 开头），检查是否混入空格或引号",
                ):
                    return False
                logger.info("WxPusher 响应: %s", response.text)
                return True
            except requests.exceptions.RequestException as exc:
                logger.error("WxPusher 推送失败: %s", exc)
                if attempt < attempts - 1:
                    sleep_time = random.randint(PUSH_RETRY_MIN_SECONDS, PUSH_RETRY_MAX_SECONDS)
                    logger.info("%d 秒后重试...", sleep_time)
                    time.sleep(sleep_time)
        return False

    def push_serverChan(self, content, spt, is_success):
        attempts = PUSH_ATTEMPTS
        url = self.server_chan_url.format(spt)

        title = f"微信阅读-{'成功' if is_success else '失败'}"

        for attempt in range(attempts):
            try:
                response = requests.post(
                    url,
                    data=json.dumps({"title": title, "desp": content}).encode("utf-8"),
                    headers=self.headers,
                    timeout=10,
                )
                response.raise_for_status()
                if not self._check_business_code(
                    'serverchan', response,
                    "检查 SERVERCHAN_SPT 是否正确（sct.ftqq.com 的 SendKey）",
                ):
                    return False
                logger.info("ServerChan 响应: %s", response.text)
                return True
            except requests.exceptions.RequestException as exc:
                logger.error("ServerChan 推送失败: %s", exc)
                if attempt < attempts - 1:
                    sleep_time = random.randint(PUSH_RETRY_MIN_SECONDS, PUSH_RETRY_MAX_SECONDS)
                    logger.info("%d 秒后重试...", sleep_time)
                    time.sleep(sleep_time)
        return False


def push(content, method, is_success = True):
    notifier = PushNotification()

    if method in (None, ""):
        logger.warning("未配置推送渠道，跳过推送。")
        return False

    method = str(method).lower()

    if method == "pushplus":
        return notifier.push_pushplus(content, PUSHPLUS_TOKEN, is_success)
    if method == "telegram":
        return notifier.push_telegram(content, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    if method == "wxpusher":
        return notifier.push_wxpusher(content, WXPUSHER_SPT)
    if method == "serverchan":
        return notifier.push_serverChan(content, SERVERCHAN_SPT, is_success)

    logger.warning("无效的通知渠道 '%s'，已跳过推送。支持：pushplus、telegram、wxpusher、serverchan", method)
    return False
