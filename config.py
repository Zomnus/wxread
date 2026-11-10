# config.py 自定义配置,包括阅读次数、推送token的填写
import os
import re
import shlex
import sys
import uuid

"""
可修改区域
默认使用本地值如果不存在从环境变量中获取值
"""


def _env_int(name, default, minimum=0):
    """读取整数环境变量：空值/非法值回退默认值，而不是直接抛 ValueError 让任务崩掉"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == '':
        return default
    try:
        return max(minimum, int(str(raw).strip()))
    except ValueError:
        print(f"[config] 环境变量 {name}={raw!r} 不是合法整数，已回退默认值 {default}", file=sys.stderr)
        return default


# 阅读次数 默认40次/20分钟
READ_NUM = _env_int('READ_NUM', 40, minimum=1)

# 启动随机抖动上限（秒，反检测改造 P0-4）
# 定时触发后先随机休眠 0~该值秒，避免每天在固定分钟级时刻运行
# 默认 2700（45 分钟）；本地手动测试可设为 0 禁用
START_JITTER_MAX = _env_int('START_JITTER_MAX', 2700)

# cookie 导出路径（P1-4：运行结束把内存中最新的 cookie 导出为 curl_bash 格式文件）
# GitHub Actions 形态可配 PAT 后用 gh secret set 回写；本地运行直接复用该文件
# 设为空字符串可禁用导出
_cookie_export = os.getenv('WXREAD_COOKIE_EXPORT_PATH')
COOKIE_EXPORT_PATH = _cookie_export if _cookie_export is not None else 'latest_cookie.txt'

# 微信读书官方 Agent Gateway API Key（P1-2：运行后校验真实计入时长，可选）
# wrk- 开头，https://weread.qq.com/r/weread-skills 免费获取；不配置则跳过校验
WEREAD_API_KEY = os.getenv('WEREAD_API_KEY') or ''
# 需要推送时可选，可选pushplus、wxpusher、telegram
PUSH_METHOD = "" or os.getenv('PUSH_METHOD')
# pushplus推送时需填
PUSHPLUS_TOKEN = "" or os.getenv("PUSHPLUS_TOKEN")
# telegram推送时需填
TELEGRAM_BOT_TOKEN = "" or os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = "" or os.getenv("TELEGRAM_CHAT_ID")
# wxpusher推送时需填
WXPUSHER_SPT = "" or os.getenv("WXPUSHER_SPT")
# SeverChan推送时需填
SERVERCHAN_SPT = "" or os.getenv("SERVERCHAN_SPT")


# read接口的bash命令（必填，GitHub Actions 中由 secret WXREAD_CURL_BASH 注入）
curl_str = os.getenv('WXREAD_CURL_BASH')

# headers、cookies 是省略模板；提供了 WXREAD_CURL_BASH 时会被抓包内容整体覆盖
cookies = {
    'RK': 'oxEY1bTnXf',
    'ptcz': '53e3b35a9486dd63c4d06430b05aa169402117fc407dc5cc9329b41e59f62e2b',
    'pac_uid': '0_e63870bcecc18',
    'iip': '0',
    '_qimei_uuid42': '183070d3135100ee797b08bc922054dc3062834291',
    'wr_avatar': 'https%3A%2F%2Fthirdwx.qlogo.cn%2Fmmopen%2Fvi_32%2FeEOpSbFh2Mb1bUxMW9Y3FRPfXwWvOLaNlsjWIkcKeeNg6vlVS5kOVuhNKGQ1M8zaggLqMPmpE5qIUdqEXlQgYg%2F132',
    'wr_gender': '0',
}

headers = {
    'accept': 'application/json, text/plain, */*',
    'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ko;q=0.5',
    'baggage': 'sentry-environment=production,sentry-release=dev-1730698697208,sentry-public_key=ed67ed71f7804a038e898ba54bd66e44,sentry-trace_id=1ff5a0725f8841088b42f97109c45862',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
}


# 阅读内容池（P1-1：书籍/章节字段一致性元组）
# 每个元素对应一次真实抓包的“页面”：b/c/ci/co/sm/pr/bookId 来自同一次请求，字段互相匹配，
# 会话启动时随机选择一本书，会话内 co/pr 随进度缓慢推进（模拟真实翻页）。
# 建议在网页版真实阅读时抓 5-10 条 read 请求，按此格式补充更多条目：
READ_POOL = [
    {
        "b": "ce032b305a9bc1ce0b0dd2a",          # 书籍 ID（三体）
        "bookId": "3300060341",                   # 同一本书的数字 bookId（用于 chapterInfos 修复）
        "c": "7f632b502707f6ffaa6bf2e",          # 章节/内容块 ID
        "ci": 27,                                  # 章节索引
        "co": 389,                                 # 内容起始位置
        "sm": "19聚会《三体》网友的聚会地点是一处僻静",  # 当前页内容摘要
        "pr": 74,                                  # 页码/段落索引
    },
]

"""
建议保留区域|默认读三体，其它书籍自行测试时间是否增加
"""
data = {
    "appId": "wb182564874603h266381671",
    "b": "ce032b305a9bc1ce0b0dd2a",
    "c": "7f632b502707f6ffaa6bf2e",
    "ci": 27,
    "co": 389,
    "sm": "19聚会《三体》网友的聚会地点是一处僻静",
    "pr": 74,
    "rt": 15,
    "ts": 1744264311434,
    "rn": 466,
    "sg": "2b2ec618394b99deea35104168b86381da9f8946d4bc234e062fa320155409fb",
    "ct": 1744264311,
    "ps": "4ee326507a65a465g015fae",
    "pc": "aab32e207a65a466g010615",
    "s": "36cc0815"
}


def _parse_cookie_string(cookie_string, cookies):
    """解析 cookie 字符串到 dict"""
    if cookie_string:
        for cookie in re.split(r';\s*', cookie_string):
            if '=' in cookie:
                key, value = cookie.split('=', 1)
                cookies[key.strip()] = value.strip()


def _extract_by_shlex(curl_command):
    """shlex 分词解析（P2-3）：兼容单引号/双引号/ANSI-C 引号三种 curl 复制格式

    返回 (headers, cookie_b)；-b / --cookie 的 cookie 优先级高于 -H 'cookie: ...'
    """
    try:
        tokens = shlex.split(curl_command, posix=True)
    except ValueError:
        return None, ''

    # 兼容 ANSI-C 引号 $'...'：shlex 分词后 $ 会残留在 token 开头，统一剥离
    tokens = [t[1:] if t.startswith('$') else t for t in tokens]

    headers = {}
    cookie_b = ''
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ('-H', '--header') and i + 1 < len(tokens):
            raw = tokens[i + 1]
            if ':' in raw:
                key, value = raw.split(':', 1)
                headers[key.strip()] = value.strip()
            i += 2
            continue
        if token in ('-b', '--cookie') and i + 1 < len(tokens):
            cookie_b = tokens[i + 1]
            i += 2
            continue
        i += 1
    return headers, cookie_b


def _extract_by_regex(curl_command):
    """正则兜底（shlex 失败时使用，仅支持单引号格式）"""
    headers = {}
    for match in re.findall(r"-H '([^:]+): ([^']+)'", curl_command):
        headers[match[0]] = match[1]
    cookie_b = re.search(r"-b '([^']+)'", curl_command)
    return headers, cookie_b.group(1) if cookie_b else ''


def convert(curl_command):
    """提取 curl 命令中的 headers 与 cookies（P2-3：shlex 健壮化）

    优先 shlex 分词，兼容：
    - bash 单引号（macOS/Linux DevTools "Copy as cURL (bash)"）
    - Windows 双引号（"Copy as cURL (cmd)"）
    - ANSI-C 引号 $'...'（新版 Chrome / Git Bash）
    以及 "name:value" 无空格写法；cookie 支持 -H 'Cookie: xxx' 与 -b 'xxx'
    两种途径（-b 优先）。shlex 解析失败时退回原正则方案。
    """
    headers, cookie_b = _extract_by_shlex(curl_command)
    if not headers:
        headers, cookie_b = _extract_by_regex(curl_command)

    cookie_header = next((v for k, v in headers.items() if k.lower() == 'cookie'), '')
    cookie_string = cookie_b or cookie_header

    cookies = {}
    _parse_cookie_string(cookie_string, cookies)

    # 移除 headers 中的 Cookie/cookie
    headers = {k: v for k, v in headers.items() if k.lower() != 'cookie'}
    return headers, cookies


def randomize_sentry_trace(headers):
    """随机化 baggage 头中的 sentry-trace_id（反检测改造 P0-2）

    真实浏览器每次页面加载都会生成新的 sentry trace_id，
    而抓包复用的 headers 中该值恒定不变，属于明显的非浏览器指纹。
    每次进程启动时调用一次（对应一次"页面会话"）。
    """
    baggage_key = next((k for k in headers if k.lower() == 'baggage'), None)
    if baggage_key:
        headers[baggage_key] = re.sub(
            r'sentry-trace_id=[0-9a-f]+',
            f'sentry-trace_id={uuid.uuid4().hex}',
            headers[baggage_key],
        )
    return headers


if curl_str:
    headers, cookies = convert(curl_str)
headers = randomize_sentry_trace(headers)
