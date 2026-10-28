"""
启动入口（不改框架源码，只在运行时打补丁）。

跑法：  .venv-py\\Scripts\\python.exe run.py
        或  python run.py

补丁内容：
1. 登录密码允许直接写 32 位 MD5（根目录 config.json 里只有 passwordMd5，没有明文）
2. 插件调度改回主事件循环 —— 原版把插件丢进独立线程 + 独立事件循环，
   插件里 await GlobalVal.websocket.send() 会跨 loop 报错，回复根本发不出去
3. 替换连接层为 bridge.py（wss + gzip）
"""
import asyncio
import os
import sys
import time
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from loguru import logger  # noqa: E402

import iirosebot.ws_iirose.login_bot as login_bot  # noqa: E402

# ---------- 补丁 1：密码支持 MD5 ----------
_original_md5 = login_bot.md5_encrypt


def md5_smart(password):
    text = str(password).strip()
    if len(text) == 32 and all(c in "0123456789abcdefABCDEF" for c in text):
        return text.lower()
    return _original_md5(text)


login_bot.md5_encrypt = md5_smart

# ---------- 补丁 2：插件调度回到主循环 ----------
from iirosebot.globals.globals import GlobalVal  # noqa: E402
from iirosebot.plugin_system.plugin_init import plugin_manage_data  # noqa: E402
from iirosebot.API.api_get_config import get_onebot_v11_serve  # noqa: E402
from iirosebot.serve.webhook import wh_queue  # noqa: E402
from iirosebot.serve.websocket_client import ws_client_queue  # noqa: E402
from iirosebot.serve.websocket_server import ws_server_queue  # noqa: E402

SERVE = get_onebot_v11_serve()


async def plugin_transfer_inloop(function_name, data=None, one_func=False):
    """原版 plugin_transfer 的等价实现，但不再开线程/新事件循环。"""
    if one_func:
        try:
            await function_name(*data) if isinstance(data, (tuple, list)) else await function_name(data)
        except Exception:
            logger.error(f"调用插件函数报错：{traceback.format_exc()}")
        return

    # 把说过话的人记进用户表，否则 OneBot 回 @ 时查不到名字、整条消息解析失败
    if data is not None and getattr(data, "user_id", None) and getattr(data, "user_name", None):
        try:
            _uid = str(data.user_id)
            _name = str(data.user_name)
            _info = {"id": _uid, "name": _name}
            GlobalVal.iirose_date.setdefault("user", {})[_uid] = _info
            GlobalVal.iirose_date.setdefault("user_name", {})[_name] = _info
        except Exception:
            pass

    if GlobalVal.plugin_list is not None:
        for _key, info in GlobalVal.plugin_list.items():
            name = info.get("name")
            defs = info.get("def")
            if not defs or function_name not in defs:
                continue
            if name in plugin_manage_data and not plugin_manage_data[name]["status"]:
                continue
            try:
                if data is None:
                    await defs[function_name]()
                elif isinstance(data, tuple):
                    await defs[function_name](*data)
                else:
                    await defs[function_name](data)
            except Exception:
                logger.error(f"插件 {name} 的 {function_name} 报错：{traceback.format_exc()}")

    # 对外协议（OneBot v11）转发
    try:
        if SERVE["webhook"]["enabled"]:
            await wh_queue.put((function_name, data))
        if SERVE["websocket_server"]["enabled"]:
            await ws_server_queue.put((function_name, data))
        if SERVE["websocket_reverse"]["enabled"]:
            await ws_client_queue.put((function_name, data))
    except Exception:
        logger.error(f"转发到 OneBot 队列失败：{traceback.format_exc()}")


import iirosebot.ws_iirose.transfer_plugin as transfer_plugin  # noqa: E402

transfer_plugin.plugin_transfer = plugin_transfer_inloop
login_bot.plugin_transfer = plugin_transfer_inloop


# ---------- 补丁 2.4：把框架没解析的帧记下来（论坛 `:-`、朋友圈 `:=` 这类） ----------
_orig_process_message = transfer_plugin.process_message


async def _process_message_with_raw_log(data, websocket):
    try:
        raw = data
        if isinstance(raw, (bytes, bytearray)) and raw[:1] == b"\x01":
            import gzip as _gzip

            raw = _gzip.decompress(raw[1:])
        text = raw.decode("utf-8", "ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        if text[:2] in (":-", ":=", ":+", "$?", "`#", "g-") or text[:1] in (":", "$", "`"):
            logger.info(f"[原始帧] {text[:300]}")
            try:
                with open(os.path.join(os.path.dirname(__file__), "memory", "raw_frames.log"), "a", encoding="utf-8") as _fh:
                    _fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
            except Exception:
                pass
    except Exception:
        pass
    return await _orig_process_message(data, websocket)


transfer_plugin.process_message = _process_message_with_raw_log

# ---------- 补丁 2.5：把「自己是谁」写进框架状态 ----------
# 新版初始化包的格式和老框架的解析条件对不上，self_info / user_name 表是空的，
# 于是 OneBot 的 get_login_info、事件里的 self_id 全都会 KeyError。这里用配置兜底。


def _seed_identity():
    import json as _json

    import yaml as _yaml

    try:
        with open(os.path.join(BASE, "config", "config.yml"), encoding="utf-8") as file:
            cfg = _yaml.safe_load(file)
        name = str(cfg["bot"]["username"])
        room_id = str(cfg["bot"]["room_id"])
    except Exception:
        return

    uid = ""
    try:
        with open(os.path.join(os.path.dirname(BASE), "config.json"), encoding="utf-8") as file:
            uid = str(_json.load(file).get("uid") or "")
    except Exception:
        pass
    if not name or not uid:
        return

    info = {"id": uid, "name": name, "room_id": room_id, "color": "ffffff"}
    if not GlobalVal.self_info:
        GlobalVal.self_info = info
    GlobalVal.iirose_date.setdefault("user_name", {})[name] = info
    GlobalVal.iirose_date.setdefault("user", {})[uid] = info


_original_init_plugin = login_bot.init_plugin


async def _init_plugin_wrapped():
    _seed_identity()
    await _original_init_plugin()


login_bot.init_plugin = _init_plugin_wrapped

# ---------- 补丁 2.6：房间消息的 mc 字段 ----------
# 新版协议里 mc 是发送者 uid，老框架填的是颜色，发出去服务端不认。
# OneBot 的 send_group_msg 最终会走到这里，所以 AstrBot 想回来必须修这一处。
import json as _json  # noqa: E402
import random as _random  # noqa: E402

import iirosebot.API.api_iirose as _api_module  # noqa: E402


async def _send_msg_to_room(msg, color=None):
    if GlobalVal.websocket is None:
        raise RuntimeError("还没连上服务器")
    uid = str((GlobalVal.self_info or {}).get("id") or "")
    message_id = str(_random.random())[2:14].ljust(12, "0")[:12]
    payload = _json.dumps({"m": msg, "mc": uid, "i": message_id}, ensure_ascii=False)
    await GlobalVal.websocket.send(payload)
    return message_id


_API_CLASS = next(obj for name, obj in vars(_api_module).items() if name.startswith("APII") and isinstance(obj, type))
_API_CLASS.send_msg_to_room = staticmethod(_send_msg_to_room)

# ---------- 补丁 2.7：OneBot WS API 的回包 ----------
# 框架把 http_server 返回的 dict 当成 aiohttp 响应去取 .text，异常被吞掉，
# 于是任何 WS 上的 API 调用（比如 AstrBot 取 @ 用户资料）都等不到回包、只能超时。
import json as _j2  # noqa: E402

import iirosebot.utools.websocket_utools as _ob  # noqa: E402


async def _onebot_api_message(raw, ws):
    request = _j2.loads(raw)
    action = request.get("action")
    table = _ob.onebot_v11_api_list
    if action not in table:
        await ws.send_json({"status": "failed", "retcode": 1404, "data": None, "echo": request.get("echo")})
        return
    try:
        result = await table[action](_ob.QueryParams(request.get("params") or {}))
    except Exception:
        logger.error(f"[onebot|v11|API] {action} 执行失败：{traceback.format_exc()}")
        await ws.send_json({"status": "failed", "retcode": 1400, "data": None, "echo": request.get("echo")})
        return

    payload = dict(result) if isinstance(result, dict) else _j2.loads(result.text)
    payload["echo"] = request.get("echo")
    logger.info(f"[onebot|v11|API] {action} 已回包")
    await ws.send_json(payload)


_ob.api_message = _onebot_api_message
import iirosebot.serve.websocket_client as _ws_client_mod  # noqa: E402
import iirosebot.serve.websocket_server as _ws_server_mod  # noqa: E402

_ws_client_mod.api_message = _onebot_api_message
_ws_server_mod.api_message = _onebot_api_message

# ---------- 补丁 2.8：send_group_msg 的 reply_id ----------
# 原实现只在传数组时才定义 reply_id，传纯字符串会 UnboundLocalError。
import iirosebot.serve.http_server as _http_mod  # noqa: E402


async def _send_group_msg_safe(request):
    data = request.query if request.method == "GET" else await request.json()
    message = data.get("message")
    reply_id = None
    private_id = None
    msg_obj = None
    if not isinstance(message, str):
        parsed = await _http_mod.array2text(message)
        if isinstance(parsed, str):
            return _http_mod.return_data({}, "failed", 400, 200)
        message, reply_id, private_id, msg_obj = parsed
    if not message:
        return _http_mod.return_data({}, "failed", 400, 200)
    if reply_id is not None:
        msg_id = await _http_mod.API.replay_msg(msg_obj, message, private_id=private_id)
    else:
        msg_id = await _http_mod.API.send_msg_to_room(message)
    return _http_mod.return_data({"message_id": msg_id}, "ok", 0, 200)


_http_mod.send_group_msg = _send_group_msg_safe
_ob.onebot_v11_api_list["send_group_msg"] = _send_group_msg_safe


async def _send_msg_safe(request):
    data = request.query if request.method == "GET" else await request.json()
    message_type = data.get("message_type")
    user_id = _http_mod.hex2uid(data.get("user_id"))
    group_id = _http_mod.hex2uid(data.get("group_id"))
    message = data.get("message")
    reply_id = None
    private_id = None
    msg_obj = None
    if not isinstance(message, str):
        parsed = await _http_mod.array2text(message)
        if isinstance(parsed, str):
            return _http_mod.return_data({}, "failed", 400, 200)
        message, reply_id, private_id, msg_obj = parsed
    if not message:
        return _http_mod.return_data({}, "failed", 400, 200)
    if reply_id is not None:
        msg_id = await _http_mod.API.replay_msg(msg_obj, message, private_id=private_id)
    elif message_type == "private":
        msg_id = await _http_mod.API.send_msg_to_private(message, user_id)
    elif message_type == "group":
        msg_id = await _http_mod.API.send_msg_to_room(message)
    elif user_id is not None:
        msg_id = await _http_mod.API.send_msg_to_private(message, user_id)
    elif group_id is not None:
        msg_id = await _http_mod.API.send_msg_to_room(message)
    else:
        return _http_mod.return_data({}, "failed", 400, 200)
    return _http_mod.return_data({"message_id": msg_id}, "ok", 0, 200)


_http_mod.send_msg = _send_msg_safe
_ob.onebot_v11_api_list["send_msg"] = _send_msg_safe

# ---------- 补丁 3：连接层 ----------
import iirosebot.ws_iirose.ws as ws_module  # noqa: E402
import bridge  # noqa: E402

ws_module.connect_to_iirose_server = bridge.connect_to_iirose_server

# ---------- 补丁 4：日志按天切 ----------
# 控制台被 start-bot.ps1 重定向到 logs\console.err.log，会一直长；
# 这里再加一个每天零点切、保留 7 天的文件日志。
try:
    logger.add(
        os.path.join(BASE, "logs", "bot_{time:YYYY-MM-DD}.log"),
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        enqueue=True,
        level="INFO",
    )
except Exception:
    pass


def main():
    from iirosebot.main import main as framework_main

    asyncio.run(framework_main())


if __name__ == "__main__":
    main()
