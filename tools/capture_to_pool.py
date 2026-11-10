#!/usr/bin/env python3
# tools/capture_to_pool.py
"""抓包转换工具：把 read 接口的 curl 命令转换为 config.py 的 READ_POOL 条目

用法示例：
  # 从文件读取并打印条目（先打印确认）
  python3 tools/capture_to_pool.py capture.txt --book-id 3300060341

  # 从剪贴板/管道读取并直接追加到 config.py
  pbpaste | python3 tools/capture_to_pool.py --book-id 3300060341 --append
  cat capture.txt | python3 tools/capture_to_pool.py --append

  # 转换后运行测试确认 READ_POOL 结构合法
  python3 -m unittest discover -s tests

说明：
  - bookId 为书籍详情页 URL 末段的数字 ID（如
    https://weread.qq.com/web/bookDetail/3300060341 中的 3300060341），
    read 报文中不含该字段，需通过 --book-id 提供（用于 synckey 修复接口）。
  - 支持单引号 / 双引号 / ANSI-C 引号三种 curl 复制格式。
"""
import argparse
import json
import os
import re
import shlex
import sys

REQUIRED_FIELDS = ('b', 'c', 'ci', 'co', 'sm', 'pr')
FIELD_ORDER = ('b', 'bookId', 'c', 'ci', 'co', 'sm', 'pr')
DATA_FLAGS = ('-d', '--data', '--data-raw', '--data-binary')


def parse_curl(curl_command):
    """从 curl 命令提取 headers 与请求体（--data-raw / -d 等）"""
    try:
        tokens = shlex.split(curl_command, posix=True)
    except ValueError as exc:
        raise SystemExit(f"curl 命令解析失败（引号不配对？）：{exc}")

    # 兼容 ANSI-C 引号 $'...'：shlex 分词后 $ 会残留在 token 开头，统一剥离
    tokens = [t[1:] if t.startswith('$') else t for t in tokens]

    headers = {}
    body = None
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
        if token in DATA_FLAGS and i + 1 < len(tokens):
            body = tokens[i + 1]
            i += 2
            continue
        i += 1
    return headers, body


def build_entry(payload, book_id):
    """从 read 报文中提取 READ_POOL 条目所需字段"""
    missing = [k for k in REQUIRED_FIELDS if k not in payload]
    if missing:
        raise SystemExit(f"请求体缺少字段：{', '.join(missing)}（确认抓的是 /web/book/read 接口）")

    entry = {}
    for key in FIELD_ORDER:
        if key == 'bookId':
            entry[key] = book_id
        else:
            entry[key] = payload[key]
    return entry


def format_entry(entry):
    """格式化为 Python 字面量（与 config.py 现有条目风格一致）"""
    lines = ['    {']
    for key in FIELD_ORDER:
        value = entry[key]
        if isinstance(value, str):
            lines.append(f'        "{key}": {json.dumps(value, ensure_ascii=False)},')
        else:
            lines.append(f'        "{key}": {value},')
    lines.append('    },')
    return '\n'.join(lines)


def append_to_config(entry_text, config_path):
    """把条目追加到 config.py 的 READ_POOL 列表末尾"""
    with open(config_path, encoding='utf-8') as f:
        content = f.read()

    marker = 'READ_POOL = ['
    pos = content.find(marker)
    if pos == -1:
        raise SystemExit(f"{config_path} 中未找到 READ_POOL")

    close = content.find('\n]', pos)
    if close == -1:
        raise SystemExit("未找到 READ_POOL 的结束括号 ]")

    new_content = content[:close] + '\n' + entry_text + content[close:]
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(new_content)


def main():
    parser = argparse.ArgumentParser(
        description='把 read 接口抓包的 curl 命令转换为 READ_POOL 条目',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('用法示例：')[-1] if __doc__ else None,
    )
    parser.add_argument('input', nargs='?', help='保存 curl 命令的文本文件；缺省从 stdin 读取')
    parser.add_argument('--book-id', dest='book_id', help='书籍数字 bookId（书籍详情页 URL 末段，如 3300060341）')
    parser.add_argument('--append', action='store_true', help='直接追加到 config.py 的 READ_POOL 列表末尾')
    parser.add_argument('--config', default='config.py', help='config.py 路径（默认当前目录 config.py）')
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding='utf-8') as f:
            curl_command = f.read()
    else:
        if sys.stdin.isatty():
            raise SystemExit('未提供输入：请传入文件参数，或通过管道输入 curl 命令')
        curl_command = sys.stdin.read()

    if not curl_command.strip():
        raise SystemExit('输入为空')

    headers, body = parse_curl(curl_command)
    if not body:
        raise SystemExit('未在 curl 命令中找到请求体（-d / --data-raw）')

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SystemExit(f'请求体不是合法 JSON：{exc}')

    book_id = args.book_id
    if not book_id:
        # 尝试从 referer 中的 bookDetail 链接推断
        referer = next((v for k, v in headers.items() if k.lower() == 'referer'), '')
        match = re.search(r'bookDetail/(\d+)', referer)
        book_id = match.group(1) if match else None
    if not book_id:
        print(
            '警告：未提供 --book-id，条目中 bookId 置为占位符 TODO_BOOK_ID，'
            '请追加后手动补全（书籍详情页 URL 末段数字，如 3300060341）',
            file=sys.stderr,
        )
        book_id = 'TODO_BOOK_ID'

    entry = build_entry(payload, book_id)
    entry_text = format_entry(entry)

    print('# 转换得到的 READ_POOL 条目：\n')
    print(f'READ_POOL += [\n{entry_text}\n]')
    print(f"# 涉及字段：b={entry['b'][:10]}… ci={entry['ci']} co={entry['co']} pr={entry['pr']}")

    if args.append:
        append_to_config(entry_text, args.config)
        print(f'\n已追加到 {args.config} 的 READ_POOL。')
        print('建议运行  python3 -m unittest discover -s tests  确认结构合法。')


if __name__ == '__main__':
    main()
