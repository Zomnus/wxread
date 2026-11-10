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

### 2.1 想读多本书？多抓几条就行（不用填任何字段）

脚本会自动从这条请求的**报文**里读出 `b/c/ci/co/sm/pr` 作为阅读池条目（`bookId` 从 `referer` 的 `bookDetail` 链接推断），所以换书/加书只是"多抓一条"：

1. 打开另一本书，翻一页，同样复制它的 `read` 请求；
2. 与原有命令**用空行隔开**，一起粘贴进同一个 secret `WXREAD_CURL_BASH`：

   ```text
   curl 'https://weread.qq.com/web/book/read' ... --data-raw '{"b":"...","c":"...","ci":3,...}'

   curl 'https://weread.qq.com/web/book/read' ... --data-raw '{"b":"...","c":"...","ci":5,...}'
   ```

   也可以分别放进 `WXREAD_CURL_BASH_2`、`_3`、`_4`、`_5`（见 3.1 表格）。

3. 运行后日志会打印 `阅读池：N 条（由抓包报文自动识别，共 N 条抓包）` 并**逐条列出池内容**（标签 / bookId / 章节 / 摘要），确认条数对不对。

**推荐：给每条抓包加个名字**。在每条命令前写一行 `# 书名` 注释，日志里就用这个名字标识，不用去认加密 ID：

```text
# 三体
curl 'https://weread.qq.com/web/book/read' ... --data-raw '{"b":"...","c":"...","ci":4,...}'

# 沙丘
curl 'https://weread.qq.com/web/book/read' ... --data-raw '{"b":"...","c":"...","ci":3,...}'
```

> 只要抓包可用，默认的三体条目就不再参与随机（避免读到与你书架无关的书）；完全没识别到 `read` 报文时才回退默认条目。
> 抓包未带 referer 时日志里 bookId 显示「未知」——只影响极少数情况下的 synckey 自动修复，正常上报不受影响；想知道数字 bookId，去书籍详情页 URL 末尾看（`weread.qq.com/web/bookDetail/3300060341`）。

---

## 3. 配置 Secrets 与 Variables

进入 fork 仓库：**Settings → Secrets and variables → Actions**。

### 3.1 Secrets（Repository secrets）

| Secret | 是否必填 | 说明 |
| --- | --- | --- |
| `WXREAD_CURL_BASH` | ✅ **必填** | 第 2 步复制的完整 cURL 命令，整段粘贴为一个 secret 值；多条可用空行隔开一起放 |
| `WXREAD_CURL_BASH_2` … `_5` | 可选 | 额外的 `read` 抓包（格式同上），用于多本书/多页随机，见 2.1 |
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
| `READ_NUM` | 40 | 阅读次数，每次间隔 25–45 秒随机。40 ≈ 20 分钟；只做每日挑战可设 2；要 60 分钟设 120 |
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
| `阅读池条目 n/N：…` + `阅读池：N 条…` | 识别到的书页条目明细与总数 |
| `本次会话书籍：…` | 本次选中的书页元组（标签/bookId/章节/摘要） |
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
| 想换一本书读 / 读多本书 | 打开那本书翻一页，复制它的 `read` 请求，用空行隔开追加到 `WXREAD_CURL_BASH`（或放 `_2`…`_5`），无需改代码，见 2.1 |
| 日志显示 `阅读池：1 条（…使用默认条目）` | 说明 secret 里没识别到 `read` 报文（可能抓成了别的接口）。重新复制 `/web/book/read` 请求即可 |
| 推送收不到 | 确认 `PUSH_METHOD` 拼写（小写）、对应 token 已填；wxpusher 会用 SPT 直接发消息，需先关注对应应用 |
| 定时任务几天后不再触发 | 仓库 60 天无活动被 GitHub 停用；本项目已内置 keepalive，如仍停用可在 Actions 页面点 “Enable workflow” |
| fork 后一直没有自动运行 | 定时 workflow 在 fork 中默认不启用，需按第 1 步手动启用 |

---

## 9. 安全注意事项

- `WXREAD_CURL_BASH` 等价于账号登录态，**只放在 Secrets**，不要写进代码、issue 或截图；
- 导出的 `latest_cookie.txt` 与抓包文件已加入 `.gitignore`，请勿强制提交；
- 建议为 PAT 设置最小权限（仅该仓库、仅 Secrets 读写），并定期更换；
- 本项目仅用于个人学习与自动化实践，请遵守平台用户协议，风险自负。
