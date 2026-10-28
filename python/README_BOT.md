# 鲸鱼娘 · iirosebot 部署说明

这套东西的目标是「两全」：用 iirosebot 当长期底座（插件系统 + OneBot v11），
把 Node 版那套人格和接话策略装进来当脑子。

## 一、文件分工

| 文件 | 作用 |
|---|---|
| `bridge.py` | 连接层。连 `wss://m*.iirose.com`，处理 gzip 压缩帧，断线重连 |
| `run.py` | 启动入口。运行时打三个补丁，不改框架源码 |
| `plugins/ai_chat.py` | AI 插件：双人格、限流、插话、接话窗口 |
| `config/config.yml` | 账号、房间、日志、OneBot 开关 |
| `_probe_*.py` | 自检脚本（登录、历史、模型、OneBot），排查时用 |

## 二、为什么不能直接 `python main.py`

1. **端口没了**。框架连的是 `ws://m*.iirose.com:8777`，现在直接回 404。
   现行入口是 Cloudflare 后的 `wss://m1.iirose.com`（443）。
2. **报文压缩**。上行超过 256 字节、下行的大包都是 `0x01 + gzip`。
   框架的 `process_message` 认得这个头，但连接层不会编码。`bridge.py` 补上了。
3. **插件调度跨线程**。原版把插件丢进独立线程 + 独立事件循环，
   插件里 `await GlobalVal.websocket.send()` 会跨 loop 失败——回复根本发不出去。
4. **身份表是空的**。新版初始化包和老解析条件对不上，`self_info` 为空，
   OneBot 的 `get_login_info` 会 `KeyError`。`run.py` 用配置兜底注入。

## 三、启动与停止

```powershell
cd D:\大肥鱼\iirose-bot\新建文件夹
D:\大肥鱼\iirose-bot\.venv-py\Scripts\python.exe run.py
```

Ctrl+C 正常退出。依赖装在 `D:\大肥鱼\iirose-bot\.venv-py`，不用再装。

## 四、对外插座：OneBot v11

已在 `config/config.yml` 打开 WebSocket 服务：

```
ws://127.0.0.1:9002/onebot/v11      通用（收发都走这条）
ws://127.0.0.1:9002/onebot/v11/api  只发 API 响应
ws://127.0.0.1:9002/onebot/v11/event 只收事件
```

`verify: false`，也就是不校验 token；要校验就改成 `true`，
token 在同文件的 `serve.onebot_v11.token`。

实测可用：`get_login_info` 返回 `鲸鱼娘`，`get_status` 返回 `online: true`。

接 AstrBot（aiocqhttp 适配器）：把反向 WS 地址填 `ws://127.0.0.1:9002/onebot/v11`。
接上之后**建议把 `ai_chat` 关掉**，否则一个消息会被两边各回一次：
在 `config/config.yml` 同级放一个 `ai.json`，写 `{"aiEnabled": false}` 即可。

> AstrBot 那头的具体字段名各版本略有差别，以它界面里的「反向 WebSocket」为准。

## 五、改人格、加插件

人格和参数不用改代码。在 `新建文件夹/ai.json` 里覆盖，键名和根目录
`../config.json` 一致，例如：

```json
{
  "aiEnabled": true,
  "model": "deepseek-chat",
  "temperature": 1.1,
  "family": ["雨雨不吃鱼", "豪德寺 三花"],
  "ambientChance": 0.25,
  "maxRepliesPerHour": 60
}
```

加指令（放 `plugins/` 下任意 `.py`）：

```python
from iirosebot.API.api_iirose import APIIirose
from iirosebot.API.decorator import on_command, MessageType

API = APIIirose()

@on_command('饭', False, command_type=[MessageType.room_chat])
async def rice(Message):
    await API.send_msg_to_room('大白饭，一大碗。')
```

事件函数按名字注册，插件里定义同名协程就会被调用：
`room_message`、`private_message`、`user_join_room`、`user_leave_room`、
`user_move_room`、`revoke_message`、`on_init`。

## 六、已知坑

- **同一个号只能在线一处**。网页开着、Node 版开着、这个 Python 版开着，
  会互相顶下线。
- `iirosebot/plugins/iirose_flow_master.py` 里 `load_config()` 返回 3 个值，
  却解包成 4 个，用「回到默认房间」会报错。要用先修那一行。
- 框架自带的 `plugins/` 是相对当前工作目录的，所以必须在本目录启动。
- `self_info` 的兜底只填了 id/name/room_id，够 OneBot 用；
  要更多字段得等框架修初始化包解析。

## 七、验证记录（2026-10-24）

- 登录：`wss://m1.iirose.com` 成功，收到 240 KB 初始化包，房间 `65c49a968faef`
- 上行：启动时发「鲸鱼娘自检 778812」，重连翻历史确认已进房间
- 模型：家里人口吻「大白饭呀，别的不想…」，路人「? 就这画质也叫顶…」，
  接话判断正确输出 PASS
- OneBot：`get_login_info` / `get_status` 正常返回
- 控制口：`/status`、`/ai`、`/say`、`/reload` 全部返回 ok，说话进了房间

## 八、常驻与远程指挥

外面一层脚本，让机器人不依赖任何终端窗口：

| 脚本 | 作用 |
|---|---|
| `start-bot.ps1` | 隐藏窗口后台启动，PID 写进 `run.pid`，日志进 `logs\console.*.log` |
| `stop-bot.ps1` | 按 PID 停掉 |
| `status.ps1` | 打印控制口状态 |
| `install-task.ps1` | 注册「登录时自启」计划任务 `iirose-whale`（可能要管理员） |
| `uninstall-task.ps1` | 注销计划任务 |

控制口只监听 `127.0.0.1:7790`，默认不对外：

```
GET  /status                在线、房间、模型、插件、本小时回复数
POST /say    {"text":""}    在当前房间说一句
POST /room   {"roomId":""}  换房
POST /ai     {"enabled":真/假}  开关 AI，不用重启
POST /reload               重载 plugins/（control 自己除外）
```

改完插件直接 `POST /reload` 就生效，不用掐进程重连；想临时让它闭嘴就
`/ai` 关掉。端口可用环境变量 `IIROSE_CTRL_PORT` 覆盖。

## 九、接 AstrBot（v4.29.1）

AstrBot 实例在 `E:\机器人数据包\instances\c78c70f7-…\core`，它自带一个 QQ 平台
（id `大肥鱼`，端口 6199）。为了不互相抢号，另开了一个平台实例：

| 项 | 值 |
|---|---|
| 平台 id | `鲸鱼娘花园` |
| 类型 | `aiocqhttp`（反向 WS 服务端） |
| 端口 | 6299（`ws://127.0.0.1:6299/ws`） |
| self_id | -1722948517505749（鲸鱼娘 uid 的 hex 取负） |
| group_id | -1790321304861423（房间 65c49a968faef 的 hex 取负） |
| 白名单 | `鲸鱼娘花园:GroupMessage:-1790321304861423` |

iirosebot 这边用反向 WS 客户端连过去：

```yaml
serve.onebot_v11.websocket_reverse:
  enabled: true
  url: ws://127.0.0.1:6299/ws
```

AstrBot 的 `wake_prefix` 里补了 `鲸鱼娘`（原本只有 `大肥鱼`），
这样在房间里 @ 它或喊名字都能唤醒。

### 为此修的两个框架 bug

1. **WS API 不回包**：`websocket_utools.api_message` 把 http_server 返回的 dict
   当成 aiohttp 响应去 `.text`，异常被吞，任何 API 调用（AstrBot 取 @ 用户资料）
   都只能超时。→ `run.py` 补丁 2.7。
2. **send_group_msg 崩**：传纯字符串时 `reply_id` 未定义，直接 `UnboundLocalError`。
   → `run.py` 补丁 2.8。

### 验证

- 入向：AstrBot 日志能识别 `鲸鱼娘花园(aiocqhttp)`、self_id/group_id 正确、能唤醒并请求模型
- 出向：从 9002 调用 `send_group_msg` 返回 ok，消息 `954306169819` 在房间历史里查到

### 现在谁在回话

**花园走本地 `ai_chat`**（`ai.json` 里 `aiEnabled: true`），AstrBot 的
`鲸鱼娘花园` 平台设为 `enable: false`，只保留 QQ 的 6199。

想换回 AstrBot 接管：把 `cmd_config.json` 里 `鲸鱼娘花园` 的 `enable` 改回 `true`
并重启 AstrBot，再把 `config/config.yml` 的 `websocket_reverse.enabled` 打开、
`ai.json` 的 `aiEnabled` 改 `false`、重启机器人。两边同时开会各回一次。

## 十、跟随主人换房

`plugins/follow.py` + `follow.json`。两个主人：

```json
{"masters": ["5d4e559f99e21", "5efc5d6adced4"], "home": "65c49a968faef", "enabled": true, "cooldown_sec": 6}
```

- 主人换房 → 插件调 `move_room`，**断线重连**，约 5–10 秒后在新房间上线
- 冷却 6 秒，连续切房不会连环重连
- 换房后 10 秒没落地，自动重试一次
- 指令：`跟随` / `别跟` / `回家`（只有主人能用）

**实测（2026-10-24 23:58）**：雨雨从花园到 `6a9647b8b0632`，
13 秒触发、23 秒落地，事件解析正常（框架的 `len==12` + 第 4 段 `'2` 判断对现行协议仍然成立）。

**注意**：重启机器人会回到 `config.yml` 里的 `bot.room_id`（花园），
不会记得跟随后的房间。要常驻别的房间，就改那个字段。

## 十一、艾特格式

**机器人回复一律不艾特人**，要称呼对方就把名字写进句子里（"梦游，晚上好"）。
模型万一自己吐出 `[*名字*]`，`ai_chat._say()` 会把它拆成「名字，」。

确实需要艾特时（控制口、OneBot 转发），iirose 的标记后面**必须空一格**：

```
[*梦游*] 晚上好     ← 对
[*梦游*]晚上好      ← 错，白艾特
```

这条由 `bridge.py` 的 `WSProxy.send()` 兜底，所有上行 JSON 都过一遍归一化。

## 十二、存储与记忆

平台侧不给机器人任何云存储，**所有东西都落在这台机器上**：

| 位置 | 内容 | 说明 |
|---|---|---|
| `memory/<房间id>.json` | 对话上下文（最近 16 条对话 + 12 条房间消息） | 按房间隔离，重启后自动接着聊 |
| `memory/profile.json` | 长期档案：按 uid 记名字、关系、笔记 | 跨房间、跨重启 |
| `logs/bot_YYYY-MM-DD.log` | 每天零点切，保留 7 天 | 下次重启后生效 |
| `logs/console.err.log` | 控制台原样重定向 | 会持续变大，靠上面的按天文件兜底 |
| `config/`、`ai.json`、`follow.json` | 账号、模型、主人、跟随 | 改完重启或 `/reload` 生效 |

长期档案是自动长出来的：谁在房间里说话，就登记 uid 和名字（主人会标成「主人」）。
主人还可以直接说 **「记住 梦游喜欢猫」**，note 会挂到说话人身上，之后每次对话
都会以「你认识的这些人」注入 system prompt（上限 1200 字）。

记忆文件示例：

```json
{"room": "6a9647b8b0632", "history": ["..."], "recent": ["momo：..."], "updated": 1792858980}
```

`memory/` 只在「换房」和「回复成功」时写，不会每条消息都刷盘。
