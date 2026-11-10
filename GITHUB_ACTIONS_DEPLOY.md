# GitHub Actions 部署指南

本项目唯一的部署形态是 **GitHub Actions**：不需要服务器、不需要常开设备，公共仓库完全免费。
全文约 10 分钟，配置一次后长期自动运行。

---

## 0. 整体流程

```
Fork 仓库 → 启用 Actions → 抓包获取 cURL → 配置 Secrets / Variables
→（可选）时长校验 + cookie 自动回写 → 手动触发验证 → 每天定时运行
```

---

## 1. Fork 并启用 Actions

1. 打开仓库页面，点击右上角 **Fork**，fork 到你自己的账号；
2. 进入你 fork 后的仓库，点 **Actions** 标签页；
3. 如果看到提示 “Workflows aren't being run on this forked repository”，点 **I understand my workflows, go ahead and enable them**。

> ⚠️ 公开仓库 fork 后，**定时（schedule）workflow 默认不会自动启用**，这一步不做就永远不会触发。

---

## 2. 抓包获取 cURL 命令

1. 浏览器登录微信读书网页版 <https://weread.qq.com/>；
2. 按 **F12** 打开开发者工具 → **Network（网络）** 标签；
3. 打开任意一本书（如《三体》），点一下**下一页**；
4. 在请求列表中找到 `read` 请求，URL 为 `https://weread.qq.com/web/book/read`，
   确认响应体正常：

   ```json
   { "succ": 1, "synckey": 564589834 }
   ```

5. 右键该请求 → **Copy** → **Copy as cURL (bash)**。

> 复制下来的命令里包含登录 cookie 与完整浏览器 headers，**等同于账号凭据**，不要发给任何人或提交到仓库。
> `wr_skey` 有效期约几天，脚本运行后会自动续期；配置了第 5 步的 PAT 后会自动回写，无需再抓包。

支持三种复制格式（bash 单引号 / Windows cmd 双引号 / 新版 Chrome 的 `$'...'`），解析器都能处理。

---

## 3. 配置 Secrets 与 Variables

进入 fork 仓库：**Settings → Secrets and variables → Actions**。

### 3.1 Secrets（Repository secrets）

| Secret | 是否必填 | 说明 |
| --- | --- | --- |
| `WXREAD_CURL_BASH` | ✅ **必填** | 第 2 步复制的完整 cURL 命令，整段粘贴为一个 secret 值 |
| `PUSH_METHOD` | 需要推送时必填 | `pushplus` / `wxpusher` / `telegram` / `serverchan` 四选一 |
| `PUSHPLUS_TOKEN` | 按渠道 | PushPlus token，[获取](https://www.pushplus.plus/uc.html) |
| `WXPUSHER_SPT` | 按渠道 | WxPusher SPT，[获取](https://wxpusher.zjiecode.com/docs/#/?id=获取spt) |
| `TELEGRAM_BOT_TOKEN`<br>`TELEGRAM_CHAT_ID` | 按渠道 | Telegram 机器人 token 与会话 id，[配置文档](https://www.nodeseek.com/post-22475-1) |
| `SERVERCHAN_SPT` | 按渠道 | ServerChan SendKey，[获取](https://sct.ftqq.com/sendkey) |
| `WEREAD_API_KEY` | 可选 | 真实计入时长校验，见第 4 步 |
| `PAT_TOKEN` | 可选（**推荐**） | cookie 自动回写，见第 5 步 |

### 3.2 Variables（Repository variables）

| Variable | 默认 | 说明 |
| --- | --- | --- |
| `READ_NUM` | 40 | 阅读次数，每次约 30 秒。40 ≈ 20 分钟；只做每日挑战可设 2；要 60 分钟设 120 |
| `START_JITTER_MAX` | 2700 | 启动随机抖动上限（秒）。触发后随机休眠 0~45 分钟，避免固定时刻；设 0 禁用 |

> 记忆口诀：**只有 `READ_NUM` 和 `START_JITTER_MAX` 放 Variables，其余全放 Secrets。**

---

## 4. 可选：真实计入时长校验

部分情况会出现“刷了时长但服务端没计入”（疑似风控折扣）。配置官方 Agent Gateway Key 后，
每次运行结束会查询并推送**今日实际计入时长**，异常可第一时间发现：

1. 访问 <https://weread.qq.com/r/weread-skills> 免费获取 Key（`wrk-` 开头）；
2. 添加到 Secrets：`WEREAD_API_KEY = wrk-xxxx`。

不配置则自动跳过，不影响主流程。

---

## 5. 可选（推荐）：cookie 自动回写

脚本每次运行都会续期 `wr_skey`，并把最新 cookie 导出到 `latest_cookie.txt`。
配置 PAT 后，workflow 会自动把它回写到 `WXREAD_CURL_BASH`——**从此不用反复抓包**。

1. 头像 → **Settings** → 左侧最下 **Developer settings** → **Personal access tokens**；
2. 选 **Fine-grained tokens** → **Generate new token**：
   - **Repository access**：仅选择你 fork 的 wxread 仓库；
   - **Permissions → Repository permissions → Secrets**：设为 **Read and write**；
   - 过期时间建议设长（如 1 年，到期更换）；
3. 复制 token（`github_pat_` 或 `ghp_` 开头），添加为 Secret：`PAT_TOKEN`。

> workflow 自带的 `GITHUB_TOKEN` **无权修改 secrets**，必须自建 PAT。
> 未配置时该步骤会打印“未配置 PAT_TOKEN，跳过 cookie 回写”并正常结束。

---

## 6. 手动触发验证

1. 打开仓库 **Actions** → 左侧选中 **wxread**；
2. 右侧 **Run workflow** → 分支选 `main` → **Run workflow**；
3. 点进本次运行查看日志：
   - 首次会先**随机休眠 0~45 分钟**（启动抖动，正常现象）；
   - 想立刻看到结果，可先把变量 `START_JITTER_MAX` 设为 `0`，验证后再删除该变量（恢复默认 2700）；
4. 结束后：配置了推送会收到微信消息；配置了 `WEREAD_API_KEY` 会额外带上「今日实际计入」。

日志里几条关键行：

| 日志 | 含义 |
| --- | --- |
| `HTTP 后端：curl_cffi（已模拟 chrome ...）` | 指纹模拟已生效 |
| `启动抖动：休眠 xxx 秒` | 本次实际随机到的延迟 |
| `本次会话书籍 bookId=...` | 本次选中的书页元组 |
| `阅读进度: 第 n/40 次，已计入 x.x 分钟` | 每条成功上报的累计计入时长 |
| `最新 cookie 已导出到 latest_cookie.txt` | 回写数据已生成 |

---

## 7. 定时运行机制

| 机制 | 说明 |
| --- | --- |
| 触发时刻 | 每天北京时间 **01:07**（cron `7 17 * * *`，刻意避开 Actions 整点高峰，减少排队延迟） |
| 启动抖动 | 触发后随机休眠 0~45 分钟，实际执行时刻每天都不同 |
| 并发控制 | 同一时间只跑一个实例（新触发会取消旧实例），避免重复计时 |
| Keepalive | 每次运行附带 keepalive 任务，防止仓库 60 天无活动导致定时 workflow 被停用 |
| 环境（Environment） | workflow 引用 `AutoRead` 环境，不存在时 GitHub 会自动创建；需要审批/保护规则时可在 Settings → Environments 里配置 |
| 手动触发 | 始终支持 `workflow_dispatch` |
| 超时保护 | 任务级 `timeout-minutes: 240`；会话内部还有 3 小时上限 |

**费用**：公共仓库 Actions 免费；私有仓库每次约 25~70 分钟（含抖动与阅读），按天累计通常仍在免费 2000 分钟/月以内。

---

## 8. 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| workflow 文件报 `Unrecognized named-value: 'secrets'` | 已修复（secrets 不能用于 `if`）。若你改动过 workflow，注意 secrets 只能放在 `env` / `with` 中 |
| 日志提示 `WXREAD_CURL_BASH 解析失败：缺少 cookie 字段 wr_skey` | 抓包命令不完整。重新复制 `/web/book/read` 的 **Copy as cURL (bash)**，确认包含 `-H 'cookie: ...'` |
| 日志 `连续 5 次阅读请求失败，终止运行` | 网络问题或 cookie 失效。检查 cookie；Actions 出口在海外，偶发超时会自动退避重试 4 次 |
| 时长没增加 / 增加得比预期少 | 先配 `WEREAD_API_KEY` 核对“今日实际计入”；再把每日时长降到 10~30 分钟的自然区间 |
| 推送收不到 | 确认 `PUSH_METHOD` 拼写（小写）、对应 token 已填；wxpusher 会用 SPT 直接发消息，需先关注对应应用 |
| 定时任务几天后不再触发 | 仓库 60 天无活动被 GitHub 停用；本项目已内置 keepalive，如仍停用可在 Actions 页面点 “Enable workflow” |
| fork 后一直没有自动运行 | 定时 workflow 在 fork 中默认不启用，需按第 1 步手动启用 |

---

## 9. 安全注意事项

- `WXREAD_CURL_BASH` 等价于账号登录态，**只放在 Secrets**，不要写进代码、issue 或截图；
- 导出的 `latest_cookie.txt` 与抓包文件已加入 `.gitignore`，请勿强制提交；
- 建议为 PAT 设置最小权限（仅该仓库、仅 Secrets 读写），并定期更换；
- 本项目仅用于个人学习与自动化实践，请遵守平台用户协议，风险自负。
