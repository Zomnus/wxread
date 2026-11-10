# 更新第四版：反检测增强 + 全流程自动化，欢迎 fork！

## 项目介绍 📚

这个脚本主要是为了在微信读书的阅读**挑战赛中刷时长**和**保持天数**。由于本人偶尔看书时未能及时签到，导致入场费打了水漂。网上找了一些，发现高赞的自动阅读需要挂阅读器模拟或者用ADB模拟，实现一点也不优雅。因此，我决定编写一个自动化脚本。通过对官网接口的抓包和JS逆向分析实现。

本 fork 在原版基础上完成了 **P0/P1/P2 三轮反检测与健壮性改造**：

- **阅读时长调节**：默认计入排行榜和挑战赛，时长可调节，默认为 20 分钟（`READ_NUM=40`，每次 30 秒）。
- **定时运行推送**：可部署在 GitHub Actions / 服务器上，每天定时运行并推送结果到微信。
- **Cookie 自动续期与回写**：运行时自动续期 `wr_skey`，结束后导出最新 cookie；Actions 配置 PAT 后自动回写 secret，**一次抓包长期免维护**。
- **反检测增强（P0）**：Chrome TLS/HTTP2 指纹模拟、sentry trace 随机化、阅读行为随机化、启动随机抖动，详见【反检测增强（P0）】章节。
- **行为真实性（P1）**：阅读内容元组一致性（书/章/摘要字段匹配）、失败退避重试、真实计入时长校验（可选），详见【P1 增强】章节。
- **轻量化设计**：部署后到点运行，无需额外硬件；公共仓库 Actions 完全免费。

***

## 快速开始：GitHub Actions 部署（推荐）🚀

全程约 10 分钟，一次配置后无需再管。整体流程：

```
Fork 仓库 → 启用 Actions → 抓包获取 curl 命令 → 配置 Secrets/Variables
→ （可选）配置时长校验与 cookie 回写 → 手动触发验证 → 等待每天定时运行
```

### 步骤 1：Fork 并启用 Actions

1. 点击右上角 **Fork** 按钮将本仓库 fork 到你的账号下；
2. 打开你 fork 仓库的 **Actions** 标签页，若提示 "Workflows aren't being run on this forked repository"，点击 **I understand my workflows, go ahead and enable them** 按钮启用。
   > 公开仓库 fork 后，定时 workflow 默认不会自动启用，**这一步必须手动操作**，否则永远不会触发。

### 步骤 2：抓包获取 curl 命令

1. 登录微信读书网页版 [weread.qq.com](https://weread.qq.com/)；
2. 按 **F12** 打开开发者工具，切换到 **Network（网络）** 标签；
3. 打开任意一本书（如《三体》）进行阅读，点击**下一页**；
4. 在请求列表中找到 `read` 请求（URL 为 `https://weread.qq.com/web/book/read`），确认响应格式正常：

   ```json
   { "succ": 1, "synckey": 564589834 }
   ```

5. 右键该请求 → **Copy** → **Copy as cURL (bash)**，得到一条完整的 curl 命令（其中包含你的登录 cookie 与全部浏览器指纹 headers）。

> 抓包后建议尽快完成配置——cookie 中的 `wr_skey` 有效期约几天，脚本运行后会自动续期。

### 步骤 3：配置 Secrets 与 Variables

进入你 fork 仓库的 **Settings** → 左侧 **Secrets and variables** → **Actions**：

**Secrets（敏感信息，添加在 Repository secrets）：**

| Secret | 必填 | 说明 |
| --- | --- | --- |
| `WXREAD_CURL_BASH` | ✅ **必填** | 步骤 2 复制的完整 curl 命令，整个粘贴为一个 secret 值 |
| `PUSH_METHOD` | 推送时必填 | 推送方式 4 选 1：`pushplus` / `wxpusher` / `telegram` / `serverchan` |
| `PUSHPLUS_TOKEN` | 选其一 | PushPlus token，[获取地址](https://www.pushplus.plus/uc.html) |
| `WXPUSHER_SPT` | 选其一 | WxPusher 的 SPT，[获取地址](https://wxpusher.zjiecode.com/docs/#/?id=获取spt) |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | 选其一 | 机器人 token 与会话 id，[配置文档](https://www.nodeseek.com/post-22475-1) |
| `SERVERCHAN_SPT` | 选其一 | ServerChan SendKey，[获取地址](https://sct.ftqq.com/sendkey) |
| `WEREAD_API_KEY` | 可选 | 时长校验，见步骤 4 |
| `PAT_TOKEN` | 可选 | cookie 自动回写，见步骤 5 |

**Variables（非敏感参数，添加在 Repository variables）：**

| Variable | 默认 | 说明 |
| --- | --- | --- |
| `READ_NUM` | 40 | 阅读次数，每次约 30 秒（40 ≈ 20 分钟；完成每日挑战设 2；要 60 分钟设 120） |
| `START_JITTER_MAX` | 2700 | 启动随机抖动上限（秒）。触发后随机休眠 0~45 分钟避免固定时刻运行；设 0 禁用 |

> **除 `READ_NUM` 和 `START_JITTER_MAX` 配置在 Variables，其余全部配置在 Secrets。**

### 步骤 4（可选）：配置真实计入时长校验

部分情况下会出现"刷了时长但服务端没计入"（疑似风控折扣）。配置官方 Agent Gateway Key 后，每次运行结束会查询并推送**「今日实际计入时长」**，让你第一时间发现异常：

1. 访问 [weread.qq.com/r/weread-skills](https://weread.qq.com/r/weread-skills) 免费获取 API Key（`wrk-` 开头）；
2. 添加到 Secrets：`WEREAD_API_KEY = wrk-xxxx`。

不配置则自动跳过该功能，不影响主流程。

### 步骤 5（可选）：配置 cookie 自动回写（强烈推荐）

脚本每次运行都会自动续期 `wr_skey`，运行结束后把最新 cookie 导出到 `latest_cookie.txt`。配置 PAT 后，Actions 会自动把它回写到 `WXREAD_CURL_BASH` secret——**从此不需要每隔几天重新抓包**：

1. GitHub 右上角头像 → **Settings** → 左侧最底 **Developer settings** → **Personal access tokens**；
2. 推荐 **Fine-grained tokens** → Generate new token：
   - **Repository access** 选择你 fork 的 wxread 仓库；
   - **Permissions** 中把 **Secrets** 设为 **Read and write**；
   - 建议过期时间设长一些（如 1 年，到期记得更换）；
3. 复制生成的 token（`github_pat_` 开头），添加到仓库 Secrets：`PAT_TOKEN`。

> 注意：workflow 自带的默认 `GITHUB_TOKEN` **无权修改 secrets**，必须自建 PAT。不配置 PAT 时该步骤自动跳过——本地/Docker 形态可直接复用导出的 `latest_cookie.txt`，纯 Actions 形态建议配置以获得最佳免维护体验。

### 步骤 6：手动触发验证

1. 打开仓库 **Actions** → 左侧选择 **wxread** workflow；
2. 右侧 **Run workflow** → 选择 `main` 分支 → 点击 **Run workflow**；
3. 点击进入本次运行查看日志：
   - 首次运行会先随机休眠 0~45 分钟（启动抖动，属正常现象，耐心等待）；
   - 若想立即验证，可先把 Variables 中 `START_JITTER_MAX` 设为 `0`，验证通过后再改回或删除（恢复默认 2700）；
4. 运行结束后，若配置了推送，微信会收到结果消息；若配置了 `WEREAD_API_KEY`，消息中会包含「今日实际计入时长」。

### 定时运行机制说明

| 机制 | 说明 |
| --- | --- |
| 触发时刻 | 每天北京时间 **01:07**（cron `7 17 * * *` UTC，刻意避开 GitHub Actions 整点高峰，降低排队延迟） |
| 启动抖动 | 触发后随机休眠 0~45 分钟，实际执行时刻每天不同，消除机器人作息特征 |
| 并发控制 | 同一时间只允许一个实例运行（concurrency 取消旧实例，防止重复计时） |
| Keepalive | 每次运行附带 keepalive 任务，自动防止 GitHub 因仓库 60 天无活动停用定时 workflow |
| Environment | workflow 引用 `AutoRead` 环境（不存在时自动创建），需要时可自行添加保护规则或审批 |
| 手动触发 | 始终支持 workflow_dispatch，随时可手动跑一次 |
| 费用 | 公共仓库 Actions 免费；私有仓库每次运行约 25~70 分钟（含抖动），按月估算在免费额度 2000 分钟内 |

***

## 其他部署方式 🐳

### Docker / docker-compose（常驻服务器）

**步骤 1：** 创建 `docker-compose.yml`：

```yaml
services:
  wxread:
    image: ghcr.io/findmover/wxread:latest
    container_name: wxread
    restart: unless-stopped

    environment:
      TZ: "Asia/Shanghai"

      # 阅读次数（每次 30 秒），默认 40 为 20 分钟
      READ_NUM: 40

      # 启动随机抖动上限（秒）：触发后随机休眠 0~该值秒；手动测试设为 0
      START_JITTER_MAX: 2700

      # 微信读书 curl bash 命令（必需）
      WXREAD_CURL_BASH: |
        curl 'https://weread.qq.com/web/book/read' \
        -H 'accept: application/json, text/plain, */*' \
        .....

      # 定时任务时间（Cron 表达式）
      CRON_SCHEDULE: "0 1 * * *"

      # 可选配置：推送方式 (pushplus/wxpusher/telegram/serverchan)
      PUSH_METHOD: ""
      PUSHPLUS_TOKEN: ""
      TELEGRAM_BOT_TOKEN: ""
      TELEGRAM_CHAT_ID: ""
      WXPUSHER_SPT: ""
      SERVERCHAN_SPT: ""

      # 可选：官方 Agent Gateway Key（wrk- 开头），推送今日实际计入时长
      WEREAD_API_KEY: ""
```

**步骤 2：** 启动并验证：

```bash
docker-compose up -d          # 启动
docker-compose logs -f        # 查看日志
docker-compose exec wxread env START_JITTER_MAX=0 python /app/main.py   # 立即手动测试一次
```

- 镜像地址：`ghcr.io/findmover/wxread:latest`（多架构：linux/amd64、linux/arm64）
- 容器内调度由 `scheduler.py` 按 `CRON_SCHEDULE` 驱动；cookie 续期后会写入容器内 `/app/latest_cookie.txt`，如需跨重启保留可挂载卷。

### 本地运行

```bash
pip install requests curl_cffi          # curl_cffi 可选，装上即启用指纹模拟
export WXREAD_CURL_BASH="curl 'https://weread.qq.com/web/book/read' -H 'cookie: ...' -H 'user-agent: ...'"
START_JITTER_MAX=0 python3 main.py      # 手动测试时禁用启动抖动
```

本地部署也可以直接修改 `config.py` 里的 `READ_NUM`、`READ_POOL`、headers、cookies 后运行，或参考 `.env.example` 用环境变量注入。

**单元测试**：`python3 -m unittest discover -s tests -v`（35 个用例，覆盖签名黄金回归、curl 多格式解析、cookie 导出闭环、随机化边界、抓包转换工具端到端）。

***

## 反检测增强（P0）🛡️

在原版基础上收敛可被服务端风控识别的指纹面：

| 改造项 | 说明 | 生效方式 |
| --- | --- | --- |
| TLS/HTTP2 指纹模拟 | 优先使用 `curl_cffi` 模拟 Chrome 的 TLS 握手与 HTTP/2 特征，消除 Python requests 的 JA3 指纹；未安装时自动回退 requests（功能等价但指纹暴露） | 安装 `curl_cffi` 即生效（Actions/Docker 已内置） |
| sentry trace 随机化 | 每次运行随机生成新的 `sentry-trace_id`，不再复用抓包时的固定值 | 自动生效 |
| 阅读行为随机化 | 阅读间隔 25–45 秒随机、`rt` 字段上限 90 秒、阅读次数每日 ±10% 抖动 | 自动生效 |
| 启动随机抖动 | 定时触发后随机休眠 0–45 分钟，避免每天在固定分钟级时刻运行 | `START_JITTER_MAX`（默认 2700，设 0 禁用） |

> 反检测不等于零风险，建议阅读时长控制在每天 10–30 分钟的自然区间。

## P1 增强 🧩

| 增强项 | 说明 | 配置 |
| --- | --- | --- |
| 阅读内容一致性（READ_POOL） | 每次会话从 `READ_POOL` 随机选一本"书页"元组：`b/c/ci/co/sm/pr` 全部来自同一次真实抓包、字段互相匹配（原版随机换书但摘要恒为三体，存在交叉校验漏洞）；会话内 `co/pr` 随进度缓慢推进模拟翻页 | `config.py` 中补充抓包条目 |
| 失败退避重试 | 请求失败/返回异常时退避 30–60 秒重试，连续失败 5 次才终止（原版单次失败即终止，Actions 网络抖动易误杀）；synckey 修复的 bookId 跟随当前会话书籍 | 自动生效 |
| 真实计入时长校验（可选） | 运行结束查询官方 Agent Gateway 的阅读统计，推送"今日实际计入约 X 分钟"，**第一时间发现时长被风控折扣** | Secrets 添加 `WEREAD_API_KEY` |
| cookie 导出与回写 | 运行结束（无论成败）导出续期后的最新 cookie 到 `latest_cookie.txt`；Actions 配置 `PAT_TOKEN` 后自动回写 `WXREAD_CURL_BASH` secret | `PAT_TOKEN`（可选） |

**补充 READ_POOL 条目**（多本书分布更接近真实阅读）：在网页版真实阅读时抓几条 `read` 请求，用自带工具一键转换：

```bash
# 抓包保存到 capture.txt 后（bookId 为书籍详情页 URL 末段数字，如 3300060341）
python3 tools/capture_to_pool.py capture.txt --book-id 3300060341 --append
# 或直接从剪贴板（macOS）
pbpaste | python3 tools/capture_to_pool.py --book-id 3300060341 --append
```

`--book-id` 省略时会从 curl 命令的 referer 中自动推断。也可以手动按 `config.py` 中现有格式添加。

***

## Attention 📢

1. **阅读次数调整**：`READ_NUM` 每次为 30 秒，默认 40（20 分钟）。只需完成挑战赛每日阅读可设为 2（约 1 分钟）；需要 60 分钟设 120。
2. **解决阅读时间问题**：若遇到"阅读时间没有增加"、"增加时间与刷的时间不对等"，先配置 `WEREAD_API_KEY` 核对实际计入时长；`READ_POOL` 默认读三体，其它书籍用 `tools/capture_to_pool.py` 转换抓包后自行测试。
3. **部署形态选择**：Actions 部署只需配置 Secrets/Variables；本地部署修改 `config.py` 即可。出口 IP 画像角度，家用设备 self-hosted runner 或 Docker 常驻最优。
4. **推送**：pushplus 推送偶尔出问题，已内置重试机制；另支持 wxpusher 极简推送。
5. **反检测依赖**：`pip install curl_cffi` 后自动启用 Chrome TLS/HTTP2 指纹模拟（Actions/Docker 已内置）；未安装时自动回退 requests，功能不受影响。手动测试用 `START_JITTER_MAX=0 python main.py` 跳过启动抖动。
6. **首次运行慢**：默认启动抖动 0–45 分钟属于设计行为（反固定作息），不是卡死；验证配置时可临时设 `START_JITTER_MAX=0`。

## 字段解释 🔍

`read` 接口上报报文的各字段含义（脚本会自动重算签名相关字段）：

| 字段 | 示例值 | 解释 |
| --- | --- | --- |
| `appId` | `"wbxxxxxxxxxxxxxxxxxxxxxxxx"` | 应用的唯一标识符。 |
| `b` | `"ce032b305a9bc1ce0b0dd2a"` | 书籍或章节的唯一标识符。 |
| `c` | `"0723244023c072b030ba601"` | 内容的唯一标识符，可能是页面或具体段落。 |
| `ci` | `60` | 章节或部分的索引。 |
| `co` | `336` | 内容的具体位置或页码。 |
| `sm` | `"[插图]威慑纪元61年，执剑人在一棵巨树"` | 当前阅读的内容描述或摘要。 |
| `pr` | `65` | 页码或段落索引。 |
| `rt` | `88` | 距上次上报的阅读时长（秒），服务端按此累计。 |
| `ts` | `1727580815581` | 时间戳（毫秒级）。 |
| `rn` | `114` | 请求编号。 |
| `sg` | `"bfdf7..."` | 安全签名：SHA256(`ts`+`rn`+盐)，验证请求合法性。 |
| `ct` | `1727580815` | 时间戳（秒级）。 |
| `ps` / `pc` | `"xxxx"` | 用户/设备标识。 |
| `s` | `"fadcb9de"` | 报文校验哈希，防篡改。 |

***

## 视频教程 📺

[![视频教程](https://github.com/user-attachments/assets/ec144869-3dbb-40fe-9bc5-f8bf1b5fce3c)](https://www.bilibili.com/video/BV1kJ6gY3En3/ "点击查看视频")
