# main.py 主逻辑：包括字段拼接、模拟请求
# P0：TLS 指纹模拟 / sentry trace 随机化 / 行为随机化 / 启动抖动
# P1：阅读内容元组一致性 / 失败退避重试 / 真实时长校验（可选）/ cookie 导出回写 / 函数化重构
import json
import re
import time
import random
import logging
import hashlib
import urllib.parse
from datetime import datetime

from push import push
from log_utils import setup_logging
from config import (
    data, headers, cookies, READ_NUM, PUSH_METHOD, START_JITTER_MAX,
    READ_POOL, COOKIE_EXPORT_PATH, WEREAD_API_KEY, curl_str,
)

# ---------------------------------------------------------------------------
# HTTP 后端选择（反检测改造 P0-1）
# 优先使用 curl_cffi：以 libcurl 模拟 Chrome 的 TLS 握手与 HTTP/2 特征，
# 使请求在网络层面与真实浏览器一致；未安装时自动回退到 requests
# （功能等价，但 TLS/JA3 指纹为 Python 默认特征，易被服务端识别）
# ---------------------------------------------------------------------------
try:
    from curl_cffi import requests as http
    from curl_cffi.requests.exceptions import RequestException
    HTTP_CLIENT = "curl_cffi"
except ImportError:
    import requests as http
    from requests.exceptions import RequestException
    HTTP_CLIENT = "requests"

IMPERSONATE_TARGET = "chrome"  # curl_cffi 模拟的浏览器目标


# 加密盐及其它默认值
KEY = "3c5c8717f3daf09iop3423zafeqoi"
READ_URL = "https://weread.qq.com/web/book/read"
RENEW_URL = "https://weread.qq.com/web/login/renewal"
FIX_SYNCKEY_URL = "https://weread.qq.com/web/book/chapterInfos"
COOKIE_DATA_VARIANTS = [{"rq": "%2Fweb%2Fbook%2Fread", "ql": False},{"rq": "%2Fweb%2Fbook%2Fread", "ql": True},{"rq": "%2Fweb%2Fbook%2Fread"},]
REQUEST_TIMEOUT = (10, 30)
SYNCKEY_REPAIR_LIMIT = 3
SYNCKEY_REPAIR_DELAY = 5
AUTH_ERROR_CODES = {-2012, -2013}

# 微信读书官方 Agent Gateway（P1-2：真实时长校验，可选）
READDATA_URL = "https://i.weread.qq.com/api/agent/gateway"
READDATA_API_NAME = "/readdata/detail"
SKILL_VERSION = "1.0.4"

# 阅读行为随机化参数（反检测改造 P0-3）
SLEEP_MIN_SECONDS = 25          # 每次阅读间隔下限（秒）
SLEEP_MAX_SECONDS = 45          # 每次阅读间隔上限（秒）
MAX_RT_SECONDS = 90             # rt 字段上限：吸收异常分支耗时，避免出现超长单次阅读
READ_NUM_JITTER_RATIO = 0.1     # 阅读次数每日 ±10% 抖动

# 失败退避参数（P1-3）
MAX_CONSECUTIVE_FAILURES = 5    # 连续失败达到该次数终止运行
BACKOFF_MIN_SECONDS = 30        # 失败后退避下限（秒）
BACKOFF_MAX_SECONDS = 60        # 失败后退避上限（秒）

# 会话内进度推进参数（P1-1：模拟真实翻页推进，co/pr 缓慢前进）
PROGRESS_MIN_CHARS = 80         # 每次成功上报后 co 前进量下限
PROGRESS_MAX_CHARS = 240        # 每次成功上报后 co 前进量上限
PROGRESS_CAP = 3000             # 单会话总推进量上限（避免超出章节范围）
PROGRESS_PER_PR = 800           # co 每前进该值，pr 前进 1


def http_post(url, **kwargs):
    """统一 POST 入口：curl_cffi 后端自动附加浏览器指纹模拟"""
    if HTTP_CLIENT == "curl_cffi":
        kwargs.setdefault("impersonate", IMPERSONATE_TARGET)
    return http.post(url, **kwargs)


def encode_data(data):
    """数据编码"""
    return '&'.join(f"{k}={urllib.parse.quote(str(data[k]), safe='')}" for k in sorted(data.keys()))


def cal_hash(input_string):
    """计算哈希值"""
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1

    while _19094e > 0:
        _7032f5 = 0x7fffffff & (_7032f5 ^ ord(input_string[_19094e]) << (length - _19094e) % 30)
        _cc1055 = 0x7fffffff & (_cc1055 ^ ord(input_string[_19094e - 1]) << _19094e % 30)
        _19094e -= 2

    return hex(_7032f5 + _cc1055)[2:].lower()


def effective_read_num(read_num):
    """阅读次数每日抖动（P0-3）：总量恒定同样是统计特征"""
    jitter = max(1, int(read_num * READ_NUM_JITTER_RATIO))
    return max(1, read_num + random.randint(-jitter, jitter))


def get_wr_skey():
    """刷新cookie密钥"""
    for cookie_data in COOKIE_DATA_VARIANTS:
        try:
            response = http_post(
                RENEW_URL,
                headers=headers,
                cookies=cookies,
                data=json.dumps(cookie_data, separators=(',', ':')),
                timeout=REQUEST_TIMEOUT,
            )

            new_skey = response.cookies.get('wr_skey')
            if new_skey:
                return new_skey[:8]
        except RequestException as exc:
            logging.warning(f"refresh_cookie 请求失败，payload={cookie_data}，原因：{exc}")
            continue


    return None


def fix_no_synckey(book_id):
    """synckey 修复（P1-1：bookId 跟随当前会话书籍，不再硬编码三体）"""
    response = http_post(
        FIX_SYNCKEY_URL,
        headers=headers,
        cookies=cookies,
        data=json.dumps({"bookIds": [book_id]}, separators=(',', ':')),
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def refresh_cookie(strict=True):
    logging.info("刷新 cookie")
    new_skey = get_wr_skey()
    if new_skey:
        cookies['wr_skey'] = new_skey
        logging.info(f"密钥刷新成功，新密钥：{new_skey[:2]}***")
        logging.info("重新本次阅读。")
        return True

    ERROR_CODE = "无法获取新密钥，当前登录状态可能已失效，终止运行。"
    if strict:
        logging.error(ERROR_CODE)
        push(ERROR_CODE, PUSH_METHOD, is_success=False)
        raise Exception(ERROR_CODE)

    logging.warning("启动时未获取到新密钥，保留现有 cookie 继续尝试阅读。")
    return False


# ---------------------------------------------------------------------------
# cookie 导出与回写（P1-4）
# 运行结束（无论成败）把内存中最新的 cookie 写为 curl_bash 格式文件，
# Actions 形态可配 PAT 后由 workflow 用 gh secret set 回写仓库 secret；
# 本地/Docker 形态可直接把该文件内容作为 WXREAD_CURL_BASH 复用。
# ---------------------------------------------------------------------------
def build_curl_with_cookies(curl_command, cookies, headers):
    """用最新 cookies 重建 curl_bash 命令（保留原始抓包的其余 headers）"""
    cookie_header = '; '.join(f"{k}={v}" for k, v in cookies.items())

    if curl_command:
        new_command = curl_command
        if re.search(r"-H\s+'[Cc]ookie:[^']*'", new_command):
            new_command = re.sub(
                r"(-H\s+'[Cc]ookie:\s)[^']*'",
                lambda m: m.group(1) + cookie_header + "'",
                new_command,
            )
        elif re.search(r"-b\s+'[^']*'", new_command):
            new_command = re.sub(
                r"(-b\s')[^']*'",
                lambda m: m.group(1) + cookie_header + "'",
                new_command,
            )
        else:
            new_command = new_command.rstrip() + f" \\\n  -H 'cookie: {cookie_header}'"
        return new_command

    # 无原始 curl：用当前 headers 合成一条最小可用命令
    parts = ["curl 'https://weread.qq.com/web/book/read'"]
    for k, v in headers.items():
        parts.append(f"-H '{k}: {v}'")
    parts.append(f"-H 'cookie: {cookie_header}'")
    return ' \\\n  '.join(parts)


def export_cookie_file():
    """导出最新 cookie（含续期后的 wr_skey）到 COOKIE_EXPORT_PATH"""
    if not COOKIE_EXPORT_PATH:
        return
    try:
        content = build_curl_with_cookies(curl_str, cookies, headers)
        with open(COOKIE_EXPORT_PATH, 'w', encoding='utf-8') as f:
            f.write(content)
        logging.info("最新 cookie 已导出到 %s（供 Actions 回写或下次部署复用）", COOKIE_EXPORT_PATH)
    except OSError as exc:
        logging.warning("cookie 导出失败：%s", exc)


# ---------------------------------------------------------------------------
# 真实时长校验（P1-2，可选）
# 通过微信读书官方 Agent Gateway 的 /readdata/detail 查询阅读统计，
# 提取“今日阅读时长”，用于核对本次刷出的时长是否被服务端实际计入。
# 需要环境变量 WEREAD_API_KEY（wrk- 开头，weread.qq.com/r/weread-skills 免费获取）；
# 未配置或查询失败均不影响主流程。
# ---------------------------------------------------------------------------
READDATA_DURATION_KEYS = ("readTime", "readSeconds", "duration", "seconds", "readtime")
READDATA_DATE_KEYS = ("date", "day", "ts", "timestamp")


def _is_today(value):
    today = time.strftime("%Y-%m-%d")
    s = str(value)
    if today in s:
        return True
    try:
        ts = float(s)
        if ts > 1e9:  # Unix 时间戳（秒）
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d") == today
    except (ValueError, OSError, OverflowError):
        pass
    return False


def _extract_today_seconds(payload):
    """从 /readdata/detail 响应中宽松提取今日阅读秒数（字段名不固定，做递归匹配）"""
    candidates = []

    def walk(node):
        if isinstance(node, dict):
            duration = next((node[k] for k in READDATA_DURATION_KEYS if k in node), None)
            date = next((node[k] for k in READDATA_DATE_KEYS if k in node), None)
            if duration is not None and date is not None:
                candidates.append((date, duration))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    for date, duration in candidates:
        if _is_today(date):
            try:
                return int(duration)
            except (TypeError, ValueError):
                continue
    return None


def fetch_read_stats():
    """查询阅读统计，成功时返回今日阅读秒数，否则返回 None"""
    if not WEREAD_API_KEY:
        logging.info("未配置 WEREAD_API_KEY，跳过阅读时长校验（可选功能）。")
        return None
    try:
        response = http_post(
            READDATA_URL,
            headers={
                "Authorization": f"Bearer {WEREAD_API_KEY}",
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {"api_name": READDATA_API_NAME, "skill_version": SKILL_VERSION},
                separators=(',', ':'),
            ),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        logging.info(
            "readdata/detail 响应：%s",
            json.dumps(payload, ensure_ascii=False)[:2000],
        )
        return _extract_today_seconds(payload)
    except Exception as exc:  # noqa: BLE001 校验失败不影响主流程
        logging.warning("阅读时长校验失败（不影响本次运行结果）：%s", exc)
        return None


# ---------------------------------------------------------------------------
# 阅读会话主循环
# ---------------------------------------------------------------------------
def run_session(refresh_print):
    """执行一次完整阅读会话，返回成功上报次数

    P1-1：会话启动时从 READ_POOL 随机选择一个“书页”元组，
    b/c/ci/sm/co/pr 全部来自同一次真实抓包，字段互相一致；
    会话内 co/pr 随成功上报缓慢推进，模拟真实翻页。
    P1-3：请求失败/接口异常进入退避重试，连续失败达上限才终止。
    """
    read_num = effective_read_num(READ_NUM)
    logging.info("配置阅读 %d 次，本次随机化为 %d 次。", READ_NUM, read_num)

    session = random.choice(READ_POOL)
    logging.info(
        "本次会话书籍 bookId=%s（ci=%s，起始 co=%s）",
        session['bookId'], session['ci'], session['co'],
    )
    progress = 0

    index = 1
    lastTime = int(time.time()) - 30
    synckey_repair_attempts = 0
    consecutive_failures = 0

    while index <= read_num:
        data.pop('s', None)
        # P1-1：字段一致性——全部来自同一抓包元组，co/pr 随进度推进
        data['b'] = session['b']
        data['c'] = session['c']
        data['ci'] = session['ci']
        data['sm'] = session['sm']
        data['co'] = session['co'] + progress
        data['pr'] = session['pr'] + progress // PROGRESS_PER_PR
        thisTime = int(time.time())
        data['ct'] = thisTime
        data['rt'] = min(thisTime - lastTime, MAX_RT_SECONDS)
        data['ts'] = int(thisTime * 1000) + random.randint(0, 1000)
        data['rn'] = random.randint(0, 1000)
        data['sg'] = hashlib.sha256(f"{data['ts']}{data['rn']}{KEY}".encode()).hexdigest()
        data['s'] = cal_hash(encode_data(data))

        refresh_print(f"阅读进度: 第 {index}/{read_num} 次，已完成 {(index - 1) * 0.5:.1f} 分钟")
        logging.debug("data: %s", data)
        try:
            response = http_post(
                READ_URL,
                headers=headers,
                cookies=cookies,
                data=json.dumps(data, separators=(',', ':')),
                timeout=REQUEST_TIMEOUT,
            )
        except RequestException as exc:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                ERROR_CODE = f"连续 {consecutive_failures} 次阅读请求失败，终止运行。最后错误：{exc}"
                logging.error(ERROR_CODE)
                push(ERROR_CODE, PUSH_METHOD, is_success=False)
                raise RuntimeError(ERROR_CODE) from exc
            logging.warning(
                "阅读请求失败（%d/%d）：%s，退避后重试",
                consecutive_failures, MAX_CONSECUTIVE_FAILURES, exc,
            )
            time.sleep(random.uniform(BACKOFF_MIN_SECONDS, BACKOFF_MAX_SECONDS))
            continue

        try:
            resData = response.json()
        except ValueError as exc:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                ERROR_CODE = f"连续 {consecutive_failures} 次返回非 JSON（HTTP {response.status_code}），终止运行。"
                logging.error(ERROR_CODE)
                push(ERROR_CODE, PUSH_METHOD, is_success=False)
                raise RuntimeError(ERROR_CODE) from exc
            logging.warning(
                "read 接口返回非 JSON 响应，HTTP %s（%d/%d），退避后重试",
                response.status_code, consecutive_failures, MAX_CONSECUTIVE_FAILURES,
            )
            time.sleep(random.uniform(BACKOFF_MIN_SECONDS, BACKOFF_MAX_SECONDS))
            continue

        logging.debug("response: %s", resData)

        if 'succ' in resData:
            if 'synckey' in resData:
                synckey_repair_attempts = 0
                consecutive_failures = 0
                lastTime = thisTime
                index += 1
                # P1-1：会话内进度推进（有上限，避免超出章节范围）
                progress = min(
                    progress + random.randint(PROGRESS_MIN_CHARS, PROGRESS_MAX_CHARS),
                    PROGRESS_CAP,
                )
                # P0-3：阅读间隔随机化（真实翻页间隔为长尾分布而非恒定 30 秒）
                time.sleep(random.uniform(SLEEP_MIN_SECONDS, SLEEP_MAX_SECONDS))
                refresh_print(f"阅读进度: 第 {min(index, read_num + 1) - 1}/{read_num} 次，已完成 {(index - 1) * 0.5:.1f} 分钟")
            else:
                synckey_repair_attempts += 1
                if synckey_repair_attempts > SYNCKEY_REPAIR_LIMIT:
                    ERROR_CODE = f"连续 {SYNCKEY_REPAIR_LIMIT} 次未恢复 synckey，终止运行。"
                    logging.error(ERROR_CODE)
                    push(ERROR_CODE, PUSH_METHOD, is_success=False)
                    raise RuntimeError(ERROR_CODE)

                logging.warning(
                    "无 synckey，尝试修复（%d/%d）...",
                    synckey_repair_attempts,
                    SYNCKEY_REPAIR_LIMIT,
                )
                try:
                    fix_no_synckey(session['bookId'])
                except RequestException as exc:
                    ERROR_CODE = f"synckey 修复请求失败：{exc}"
                    logging.error(ERROR_CODE)
                    push(ERROR_CODE, PUSH_METHOD, is_success=False)
                    raise RuntimeError(ERROR_CODE) from exc
                time.sleep(SYNCKEY_REPAIR_DELAY)
        else:
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                ERROR_CODE = f"连续 {consecutive_failures} 次 read 接口异常，终止运行。"
                logging.error(ERROR_CODE)
                push(ERROR_CODE, PUSH_METHOD, is_success=False)
                raise RuntimeError(ERROR_CODE)

            err_code = resData.get('errCode')
            err_msg = resData.get('errMsg')
            logging.warning(
                "read 接口返回异常：HTTP %s，errCode=%s，errMsg=%s（连续失败 %d/%d）",
                response.status_code,
                err_code,
                err_msg,
                consecutive_failures,
                MAX_CONSECUTIVE_FAILURES,
            )

            if err_code in AUTH_ERROR_CODES:
                logging.warning("检测到登录/鉴权异常，尝试刷新 cookie...")
            else:
                logging.warning("未识别为已知鉴权错误，保留现有刷新流程尝试恢复...")
            refresh_cookie()
            # P1-3：鉴权刷新成功后退避，避免刷新后立即密集请求
            time.sleep(random.uniform(BACKOFF_MIN_SECONDS, BACKOFF_MAX_SECONDS))

    return index - 1


def main():
    refresh_print = setup_logging()

    if HTTP_CLIENT == "curl_cffi":
        logging.info("HTTP 后端：curl_cffi（已模拟 %s 的 TLS/HTTP2 指纹）", IMPERSONATE_TARGET)
    else:
        logging.warning(
            "HTTP 后端：requests（未安装 curl_cffi，TLS 指纹为 Python 默认特征，"
            "建议 pip install curl_cffi 以启用浏览器指纹模拟）"
        )

    # P0-4：启动随机抖动（START_JITTER_MAX=0 可禁用）
    if START_JITTER_MAX > 0:
        startup_jitter = random.randint(0, START_JITTER_MAX)
        logging.info(
            "启动抖动：休眠 %d 秒（0-%d 随机；手动测试可设 START_JITTER_MAX=0 禁用）",
            startup_jitter, START_JITTER_MAX,
        )
        time.sleep(startup_jitter)

    # renewal 失败不等于当前阅读会话已失效；启动时刷新失败也继续尝试阅读。
    refresh_cookie(strict=False)

    try:
        completed = run_session(refresh_print)
        logging.info("阅读脚本已完成。")

        stats_seconds = fetch_read_stats()

        if PUSH_METHOD not in (None, ''):
            logging.info("开始推送...")
            message = f"微信读书自动阅读完成。\n阅读时长：{completed * 0.5} 分钟。"
            if stats_seconds is not None:
                message += f"\n今日实际计入约 {stats_seconds // 60} 分钟（官方统计接口，供核对）。"
            push(message, PUSH_METHOD, is_success=True)
        else:
            logging.info("未配置推送渠道，跳过推送。")
    finally:
        # P1-4：无论成败都导出最新 cookie（续期后的 wr_skey 不再随进程消失）
        export_cookie_file()


if __name__ == "__main__":
    main()
