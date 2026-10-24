# IIROSE 机器人

基于 IIROSE（蔷薇花园）WebSocket 协议的独立 Node.js 机器人，不依赖 Koishi，`pnpm install` 之后 `node src/index.js` 就能跑。

## 这个项目是什么

- 一条稳定的 WebSocket 连接：登录、gzip 压包、心跳、断线指数重连
- 一层业务封装：说话、私聊、切房间、点赞/点踩/关注、撤回
- 一个极简命令框架：命令都注册在 `src/plugins/`，加命令就是加一条 `registry.add()`
- 三个脚本：端点探测、登录自检、投递自检

## 快速开始

```bash
pnpm install
cp config.example.json config.json   # 然后填账号
node src/index.js
```

`config.json` 里能直接写明文 `password`（程序自己算 MD5），也可以填 32 位小写 MD5。

拿资料的位置：

| 字段 | 在哪拿 |
|---|---|
| `username` | 游戏里左上角，去掉 `[**]` |
| `uid` | 个人资料 → 唯一标识，13 位 |
| `password` | 密码明文，或者它的 MD5 |
| `roomId` | 房间链接里 `[_ _]` 中间那段 |

## 目录

```
src/
  protocol.js   报文编解码：登录包、聊天包、事件解析、压包
  client.js     连接层：WS、登录、心跳、重连、下行分流
  bot.js        业务层：say / whisper / moveRoom / like / follow
  commands.js   命令注册表
  config.js     配置加载与校验
  plugins/basic.js  内置命令
  index.js      入口
scripts/
  probe.js       探测所有端点，挑最快的
  login-test.js  只登录不发消息，确认账号/房间对不对
  e2e.js         登录后真的说一句话
  verify-send.js 说一句话→重连→在历史里找回来，证明投递成功
```

## 内置命令

默认前缀 `/`，命令名和别名都注册在 `src/plugins/basic.js`：

```
/ping  /help(帮助)  /status(状态)  /say(说)  /like(赞)  /dislike(踩)
/follow(关注)  /move(切)  /recent(最近)
```

`/say` 和 `/move` 受 `ownerUid` 限制：填了只有那个人能用，留空谁都能用。

## 协议实测笔记（和网上流传的文档不一样的地方）

这份项目是照着 `iirose-docs` 写的，但真机联调发现文档有几处过时，代码按实测为准：

1. **端点不是 `ws://m.iirose.com:8777`**。那个端口早就关了，现在网页客户端走 Cloudflare 的 443：
   `wss://m1.iirose.com`、`wss://m8.iirose.com`、`wss://m9.iirose.com`。
2. **登录报文不是 `{username,password,roomId}`**，是短键：
   ```json
   {"r":"房间ID","n":"用户名","p":"md5密码","st":"n","mo":"签名","mb":"","mu":"01","fp":"@md5(用户名)"}
   ```
   `fp` 是客户端指纹，`lr`（上次房间）和 `rp`（房间密码）可选。
3. **登录成功是 `%*"` + 几百 KB 初始化包**，不是 `%*` 之后就结束；失败才是很短的 `%*"2`。所以判定要看长度，不能只看前缀。
4. **下行包前面可能多一个 `"`**，解析前要先削掉。
5. **进/出房事件的标记在第 4 段**（`'1` / `'2`），uid 在第 9 段，文档里的位置偏了一格。
6. **聊天包** `{m,mc,i}` 里的 `mc` 填自己的 uid，`i` 是 12 位随机数字，和网页客户端一致。
7. 自己发的消息服务端不回显，所以 `verify-send.js` 用「重连后翻历史」来验证。

## 加一个命令

```js
registry.add('roll', async ({ bot, message }) => {
  bot.reply(message.name, String(Math.floor(Math.random() * 6) + 1))
}, { aliases: ['骰子'], description: '掷个骰子' })
```

## 注意

- `config.json` 里有账号凭据和模型 key，已经在 `.gitignore` 里，别提交。
- 同一账号别同时开网页和机器人，容易被顶下线；要挂机器人就先把网页关了。
- 平台没有公开的速率限制文档，命令回得太快容易被管理员盯上，`basic.js` 里没有做限流，自己按需加。

## 参考

协议资料来自社区的第三方整理，仓库内容没有随代码一起分发：

- [iirose-docs](https://github.com/XCWQW1/iirose-docs) — 蔷薇花园第三方文档
- [adapter-iirose](https://github.com/iirose-plugins/adapter-iirose) — Koishi 适配器，登录报文和端点以它为准

