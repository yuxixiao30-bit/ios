"""
iirose 连接层桥接。

原框架 ws.py 连的是 ws://m*.iirose.com:8777，这个端口现在直接 404。
现行入口是 Cloudflare 后面的 wss://m1.iirose.com（443），而且上下行都按
「0x01 前缀 + gzip」压缩长报文 —— 和网页客户端、以及 Node 版机器人的做法一致。

这个文件只做三件事：
1. 连对地址（多端点轮询 + 断线重连）
2. 把收到的二进制帧原样交给框架的 process_message（它自己会解 gzip）
3. 用一个代理包住 websocket，让框架所有 send() 都自动走压缩编码
"""
import asyncio
import gzip
import json
import re
import socket
import traceback

import websockets
from loguru import logger

from iirosebot.globals.globals import GlobalVal

ENDPOINTS = (
    "wss://m1.iirose.com",
    "wss://m8.iirose.com",
    "wss://m9.iirose.com",
)

# 与 Node 版 / 网页客户端一致的压缩阈值
COMPRESS_THRESHOLD = 256

# 艾特标记后必须空一格，否则对方收不到提醒
MENTION_RE = re.compile(r"^(\[\*[^*]+\*\])\s*")


def fix_mention(text):
    """把 '[*名字*]正文' 统一成 '[*名字*] 正文'。"""
    if not isinstance(text, str) or not text.startswith("[*"):
        return text
    return MENTION_RE.sub(r"\1 ", text)


class WSProxy:
    """把「发字符串」翻译成「发 gzip 二进制帧」，并保持 close() 兼容。"""

    def __init__(self, ws):
        self._ws = ws

    async def send(self, data):
        # 所有上行都从这里过，艾特格式在这里兜底，插件和 OneBot 两条路都覆盖
        if isinstance(data, str) and data.startswith("{"):
            try:
                obj = json.loads(data)
                message = obj.get("m")
                if isinstance(message, str):
                    fixed = fix_mention(message)
                    if fixed != message:
                        obj["m"] = fixed
                        data = json.dumps(obj, ensure_ascii=False)
                        logger.debug(f"[发送] 艾特格式已修正：{data}")
            except Exception:
                pass

        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        if len(raw) > COMPRESS_THRESHOLD:
            raw = b"\x01" + gzip.compress(raw, compresslevel=6, mtime=0)
        await self._ws.send(raw)

    async def close(self):
        await self._ws.close()

    async def recv(self):
        return await self._ws.recv()

    def __getattr__(self, item):
        return getattr(self._ws, item)


async def connect_to_iirose_server():
    from iirosebot.ws_iirose.login_bot import login_to_server
    from iirosebot.ws_iirose.ping import ping_iirose
    from iirosebot.ws_iirose.transfer_plugin import process_message

    index = 0
    while not GlobalVal.close_status:
        url = ENDPOINTS[index % len(ENDPOINTS)]
        try:
            logger.info(f"正在连接 {url}")
            async with websockets.connect(
                url,
                max_size=None,
                open_timeout=15,
                close_timeout=5,
                ping_interval=None,
                family=socket.AF_INET,   # 这台机器到 iirose 的 IPv6 不通，锁死 IPv4
            ) as ws:
                proxy = WSProxy(ws)
                GlobalVal.websocket = proxy
                logger.info("连接已建立，发送登录包")

                asyncio.create_task(login_to_server(proxy))
                asyncio.create_task(ping_iirose(proxy))

                async for message in ws:
                    await process_message(message, proxy)

            if GlobalVal.close_status:
                break
            logger.warning("连接已断开，5 秒后重连")
        except Exception:
            if GlobalVal.close_status:
                break
            logger.error(f"连接异常：{traceback.format_exc()}")
        index += 1
        await asyncio.sleep(5)
