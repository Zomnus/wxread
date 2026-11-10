# 更新第三版，提高读书稳定程度，最大限量保持cookie有效时间，欢迎fork！

## 项目介绍 📚

这个脚本主要是为了在微信读书的阅读**挑战赛中刷时长**和**保持天数**。由于本人偶尔看书时未能及时签到，导致入场费打了水漂。网上找了一些，发现高赞的自动阅读需要挂阅读器模拟或者用ADB模拟，实现一点也不优雅。因此，我决定编写一个自动化脚本。通过对官网接口的抓包和JS逆向分析实现。

该脚本具备以下功能：

- **阅读时长调节**：默认计入排行榜和挑战赛，时长可调节，默认为 20 分钟（`READ_NUM=40`，每次 30 秒）。
- **定时运行推送**：可部署在GitHub Action/服务器上，支持每天定时运行并推送结果到微信。
- **Cookie自动更新**：脚本能自动获取并更新Cookie，一次部署后面无需其它操作。
- **轻量化设计**：本脚本实现了轻量化的编写，部署服务器/GIthub action后到点运行，无需额外硬件。
- **反检测增强**：TLS/HTTP2 指纹模拟（curl_cffi）、sentry trace 随机化、阅读行为随机化、启动随机抖动，详见下方【反检测增强】章节。
- **P1 增强**：阅读内容元组一致性（书/章/摘要字段匹配）、失败退避重试、真实计入时长校验（可选）、cookie 自动导出与 Actions 回写，详见【P1 增强】章节。

***

## 反检测增强 🛡️

在原版基础上完成 P0 级反检测改造，收敛可被服务端风控识别的指纹面：

| 改造项 | 说明 | 生效方式 |
| --- | --- | --- |
| TLS/HTTP2 指纹模拟 | 优先使用 `curl_cffi` 模拟 Chrome 的 TLS 握手与 HTTP/2 特征，消除 Python requests 的 JA3 指纹；未安装时自动回退到 requests（功能等价但指纹暴露） | 安装 `curl_cffi` 即生效（Docker 镜像 / Actions 已内置） |
| sentry trace 随机化 | 每次运行随机生成新的 `sentry-trace_id`，不再复用抓包时的固定值（真实浏览器每次会话都会生成新值） | 自动生效 |
| 阅读行为随机化 | 阅读间隔 25–45 秒随机、`rt` 字段上限 90 秒（吸收异常耗时）、阅读次数每日 ±10% 抖动 | 自动生效 |
| 启动随机抖动 | 定时触发后先随机休眠 0–45 分钟，避免每天在固定分钟级时刻运行 | 环境变量 `START_JITTER_MAX`（默认 2700，设 0 禁用） |

> 本地手动测试建议：`START_JITTER_MAX=0 python main.py`，跳过启动抖动立即执行。
> 反检测不等于零风险，建议阅读时长控制在每天 10–30 分钟的自然区间。

## P1 增强 🧩

| 增强项 | 说明 | 配置 |
| --- | --- | --- |
| 阅读内容一致性（READ_POOL） | 每次会话从 `READ_POOL` 随机选一本"书页"元组：`b/c/ci/co/sm/pr` 全部来自同一次真实抓包，字段互相匹配（原版随机换书但摘要恒为三体，存在交叉校验漏洞）；会话内 `co/pr` 随进度缓慢推进模拟翻页 | config.py 中补充抓包条目 |
| 失败退避重试 | 请求失败/返回异常时退避 30–60 秒重试，连续失败 5 次才终止（原版单次失败即终止，Actions 网络抖动易误杀）；synckey 修复的 bookId 跟随当前会话书籍 | 自动生效 |
| 真实计入时长校验（可选） | 运行结束查询官方 Agent Gateway 的阅读统计，推送"今日实际计入约 X 分钟"，**第一时间发现时长被风控折扣** | secrets 添加 `WEREAD_API_KEY`（wrk- 开头，[weread.qq.com/r/weread-skills](https://weread.qq.com/r/weread-skills) 免费获取） |
| cookie 导出与回写 | 运行结束（无论成败）把续期后的最新 cookie 导出到 `latest_cookie.txt`；Actions 配置 `PAT_TOKEN` 后自动回写 `WXREAD_CURL_BASH` secret，延长免重新抓包周期 | `PAT_TOKEN`（需 repo 权限的 PAT，可选）；本地/ Docker 直接复用导出文件 |

**补充 READ_POOL 条目**：在网页版真实阅读时抓几条 `read` 请求，用工具一键转换并追加：

```bash
# 抓包保存到 capture.txt 后（bookId 为书籍详情页 URL 末段数字，如 3300060341）
python3 tools/capture_to_pool.py capture.txt --book-id 3300060341 --append
# 或直接从剪贴板：pbpaste | python3 tools/capture_to_pool.py --book-id 3300060341 --append
```

也可以手动按 `config.py` 中现有格式添加。条目越多（多本书），会话分布越接近真实阅读。

**单元测试**：`python3 -m unittest discover -s tests -v`（23 个用例，覆盖签名回归、curl 解析、cookie 导出闭环、随机化边界等）。
## 操作步骤 🛠️

### 抓包准备

脚本逻辑还是比较简单的，`main.py`与`push.py`代码不需要改动。在微信阅读官网 [微信读书](https://weread.qq.com/) 搜索【三体】点开阅读点击下一页进行抓包，抓到`read`接口 `https://weread.qq.com/web/book/read`，如果返回格式正常（如：

```json
{
  "succ": 1,
  "synckey": 564589834
}
```
右键复制为Bash格式。

### 方法一： GitHub Action部署运行（GitHub运行）


- Fork这个仓库后，先打开 fork 的 **Actions** 页面，启用 `wxread` workflow；公开仓库 fork 后，定时 workflow 默认不会自动启用。
- 在仓库 **Settings** -> 左侧列表中的 **Secrets and variables** -> **Actions**，然后在右侧的 **Repository secrets** 中添加如下值：
  - `WXREAD_CURL_BASH`：上面抓read接口后转换为curl_bash的数据。
  - `PUSH_METHOD`：推送方法，4选1推送方式（pushplus、wxpusher、telegram、serverChan）。
  - `PUSHPLUS_TOKEN` or `WXPUSHER_SPT` or `TELEGRAM_BOT_TOKEN`&`TELEGRAM_CHAT_ID` or `SERVERCHAN_SPT`: 选择推送后填写对应token。
  
- 在 **Variables** 部分，最下方添加变量：
  - `READ_NUM`：设定每次阅读的目标次数。


- 基本释义：

| key                        | Value                               | 说明                                                         | 属性      |
| ------------------------- | ---------------------------------- | ------------------------------------------------------------ | --------- |
| `WXREAD_CURL_BASH`         | `read` 接口 `curl_bash`数据 | **必填**，必须提供有效指令                                   | secrets   |
| `READ_NUM`                 | 阅读次数（每次 30 秒）              | **可选**，阅读时长，默认 20 分钟                           | variables |
| `PUSH_METHOD`              | `pushplus`/`wxpusher`/`telegram`/`serverchan`    | **可选**，推送方式，4选1，默认不推送                                       |    secrets     |
| `PUSHPLUS_TOKEN`           | PushPlus 的 token                   | 当 `PUSH_METHOD=pushplus` 时必填，[获取地址](https://www.pushplus.plus/uc.html) | secrets   |
| `WXPUSHER_SPT`             | WxPusher 的token                    | 当 `PUSH_METHOD=wxpusher` 时必填，[获取地址](https://wxpusher.zjiecode.com/docs/#/?id=获取spt) | secrets   |
| `TELEGRAM_BOT_TOKEN`  <br>`TELEGRAM_CHAT_ID`   <br>`http_proxy`/`https_proxy`（可选）| 群组id以及机器人token                 | 当 `PUSH_METHOD=telegram` 时必填，[配置文档](https://www.nodeseek.com/post-22475-1) | secrets   |
| `SERVERCHAN_SPT`          | serverchan 的 SendKey               | 当 `PUSH_METHOD=serverchan` 时必填，[获取地址](https://sct.ftqq.com/sendkey) | secrets   |
| `START_JITTER_MAX`        | 启动随机抖动上限（秒）              | **可选**，默认 2700（45 分钟）；设 0 禁用（如需固定时刻）                   | variables |
| `WEREAD_API_KEY`          | 官方 Agent Gateway Key（wrk- 开头） | **可选**，配置后推送"今日实际计入时长"，[获取地址](https://weread.qq.com/r/weread-skills) | secrets |
| `PAT_TOKEN`               | GitHub PAT（repo 权限）             | **可选**，配置后每次运行结束自动把最新 cookie 回写 `WXREAD_CURL_BASH`，延长免抓包周期 | secrets |

**重要：除了READ_NUM配置在varables，其它的都配置在secrets里面的；需要推送`PUSH_METHOD`是必填的。**

### 视频教程

[![视频教程](https://github.com/user-attachments/assets/ec144869-3dbb-40fe-9bc5-f8bf1b5fce3c)](https://www.bilibili.com/video/BV1kJ6gY3En3/ "点击查看视频")


### 方法二： 服务器运行（docker部署）

**步骤1：** 创建 docker-compose.yml 文件

```yaml
services:
  wxread:
    image: ghcr.io/findmover/wxread:latest
    container_name: wxread
    restart: unless-stopped

    environment:
      TZ: "Asia/Shanghai"

      # 阅读次数（每次 30 秒），默认40为20分钟
      READ_NUM: 40

      # 启动随机抖动上限（秒）：触发后随机休眠 0~该值秒，避免固定时刻运行；手动测试设为 0
      START_JITTER_MAX: 2700
      
      # 微信读书 curl bash 命令（必需）
      # 使用 | 表示多行字符串，下一行开始粘贴完整的 curl 命令
      WXREAD_CURL_BASH: |
        curl 'https://weread.qq.com/web/book/read' \
        -H 'accept: application/json, text/plain, */*' \
        .....
      
      # 定时任务时间（Cron 表达式）
      CRON_SCHEDULE: "0 1 * * *"
      
      # 可选配置：推送方式 (pushplus/wxpusher/telegram/serverchan)
      PUSH_METHOD: ""
      # PushPlus 推送配置
      PUSHPLUS_TOKEN: ""
      # Telegram 推送配置
      TELEGRAM_BOT_TOKEN: ""
      TELEGRAM_CHAT_ID: ""
      # WxPusher 推送配置
      WXPUSHER_SPT: ""
      # ServerChan 推送配置
      SERVERCHAN_SPT: ""
```

**Cron 定时任务配置：**
- `0 1 * * *` - 每天凌晨1点（默认）
- `0 */6 * * *` - 每6小时
- `30 8 * * *` - 每天早上8:30

**步骤2：** 启动容器

```bash
docker-compose up -d
```

**步骤3：** 查看日志和测试

```bash
# 查看日志
docker-compose logs -f

# 测试运行
docker-compose exec wxread python /app/main.py
```

**Docker 说明：**
- 镜像地址：`ghcr.io/findmover/wxread:latest`
- 支持多架构：linux/amd64 和 linux/arm64
- 推送代码到仓库会自动构建最新镜像

***
## Attention 📢

1. **阅读次数调整**：`READ_NUM` 每次为 30 秒，默认 40（20 分钟）。只需完成挑战赛每日阅读可设为 2（约 1 分钟）；需要 60 分钟设 120。

2. **解决阅读时间问题**：若遇到 issue 中反馈的“阅读时间没有增加”、“增加时间与刷的时间不对等”，建议配置 `WEREAD_API_KEY`（见 P1 增强）核对实际计入时长；`READ_POOL` 默认读三体，其它书籍用 `tools/capture_to_pool.py` 转换抓包后自行测试。

3. **GitHub Action部署/本地部署**：主要配置config.py即可，Action部署使用环境变量，本地部署修改config.py里的阅读次数、READ_POOL、headers、cookies即可。

4. **推送**：pushplus推送偶尔出问题，猜测是GitHub action环境问题，增加重试机制。并增加wxpusher的极简推送方式。

5. **反检测依赖**：`pip install curl_cffi` 后自动启用 Chrome TLS/HTTP2 指纹模拟（Docker/Actions 已内置）；未安装时自动回退到 requests，功能不受影响。手动测试用 `START_JITTER_MAX=0 python main.py` 跳过启动抖动。


***
## 字段解释 🔍

| 字段 | 示例值 | 解释 |
| --- | --- | --- |
| `appId` | `"wbxxxxxxxxxxxxxxxxxxxxxxxx"` | 应用的唯一标识符。 |
| `b` | `"ce032b305a9bc1ce0b0dd2a"` | 书籍或章节的唯一标识符。 |
| `c` | `"0723244023c072b030ba601"` | 内容的唯一标识符，可能是页面或具体段落。 |
| `ci` | `60` | 章节或部分的索引。 |
| `co` | `336` | 内容的具体位置或页码。 |
| `sm` | `"[插图]威慑纪元61年，执剑人在一棵巨树"` | 当前阅读的内容描述或摘要。 |
| `pr` | `65` | 页码或段落索引。 |
| `rt` | `88` | 阅读时长或阅读进度。 |
| `ts` | `1727580815581` | 时间戳，表示请求发送的具体时间（毫秒级）。 |
| `rn` | `114` | 随机数或请求编号，用于标识唯一的请求。 |
| `sg` | `"bfdf7de2fe1673546ca079e2f02b79b937901ef789ed5ae16e7b43fb9e22e724"` | 安全签名，用于验证请求的合法性和完整性。 |
| `ct` | `1727580815` | 时间戳，表示请求发送的具体时间（秒级）。 |
| `ps` | `"xxxxxxxxxxxxxxxxxxxxxxxx"` | 用户标识符或会话标识符，用于追踪用户或会话。 |
| `pc` | `"xxxxxxxxxxxxxxxxxxxxxxxx"` | 设备标识符或客户端标识符，用于标识用户的设备或客户端。 |
| `s` | `"fadcb9de"` | 校验和或哈希值，用于验证请求数据的完整性。 |


