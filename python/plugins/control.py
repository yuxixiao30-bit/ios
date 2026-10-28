"""
本地控制口：让外部（我）不用进房间、不用重连，就能指挥这具身体。

只监听 127.0.0.1:7790，默认不对外。

  GET  /status                在线状态、房间、模型、插件、今日回复
  POST /say    {"text":""}    让它在当前房间说一句
  POST /room   {"roomId":""}  换房间
  POST /ai     {"enabled":t}  开关 AI（不用重启）
  POST /reload               重载 plugins/ 下的插件（control 自己除外）
"""
import asyncio
import json
import os
import random
import time

from aiohttp import web
from loguru import logger

from iirosebot.API.api_iirose import APIIirose
from iirosebot.globals.globals import GlobalVal
from iirosebot.plugin_system.plugin_manage import reload_plugin

PLUGIN_DATE = {
    "name": "control",
    "author": "鲸鱼娘",
    "version": "1.0.0",
    "description": "本地 HTTP 控制口（7790）",
    "dependencies": {},
}

HOST = "127.0.0.1"
PORT = int(os.environ.get("IIROSE_CTRL_PORT", "7790"))
STARTED_AT = time.time()
API = APIIirose()


def _msg_id():
    return str(random.random())[2:14].ljust(12, "0")[:12]


def _self_uid():
    info = GlobalVal.self_info or {}
    return str(info.get("id") or "")


async def _say(text):
    from bridge import fix_mention

    text = fix_mention(str(text))
    payload = json.dumps({"m": text, "mc": _self_uid(), "i": _msg_id()}, ensure_ascii=False)
    await GlobalVal.websocket.send(payload)


def _ok(data=None):
    return web.json_response({"ok": True, "data": data or {}})


def _bad(message, status=400):
    return web.json_response({"ok": False, "error": message}, status=status)


async def status(request):
    ctl = getattr(GlobalVal, "ai_control", None) or {}
    state = ctl.get("state") or {}
    cfg = ctl.get("cfg") or {}
    plugins = []
    if GlobalVal.plugin_list:
        plugins = [info.get("name") for info in GlobalVal.plugin_list.values()]
    return _ok({
        "name": (GlobalVal.self_info or {}).get("name"),
        "uid": _self_uid(),
        "room": GlobalVal.now_room_id,
        "online": GlobalVal.websocket is not None,
        "uptime_sec": int(time.time() - STARTED_AT),
        "ai": {
            "enabled": ctl.get("enabled"),
            "model": cfg.get("model"),
            "mood": ctl.get("mood"),
            "replies_this_hour": state.get("replies_this_hour"),
            "last_reply_at": state.get("last_reply_at"),
            "follow_window": state.get("follow_window"),
        },
        "plugins": plugins,
    })


async def say(request):
    try:
        body = await request.json()
    except Exception:
        return _bad("body 不是合法 JSON")
    text = str(body.get("text") or "").strip()
    if not text:
        return _bad("缺 text")
    if GlobalVal.websocket is None:
        return _bad("还没连上服务器", 503)
    try:
        await _say(text[:500])
    except Exception as exc:
        return _bad(f"发送失败：{exc}", 500)
    logger.info(f"[控制口] 发话：{text[:60]}")
    return _ok({"sent": text[:500]})


async def room(request):
    try:
        body = await request.json()
    except Exception:
        return _bad("body 不是合法 JSON")
    room_id = str(body.get("roomId") or "").strip()
    if not room_id:
        return _bad("缺 roomId")
    try:
        result = await API.move_room(room_id)
    except Exception as exc:
        return _bad(f"换房失败：{exc}", 400)
    logger.info(f"[控制口] 换房 -> {room_id}")
    return _ok(result)


async def ai_switch(request):
    try:
        body = await request.json()
    except Exception:
        return _bad("body 不是合法 JSON")
    if "enabled" not in body:
        return _bad("缺 enabled")
    ctl = getattr(GlobalVal, "ai_control", None)
    if ctl is None:
        return _bad("AI 插件没在跑", 503)
    ctl["enabled"] = bool(body["enabled"])
    logger.info(f"[控制口] AI 开关 -> {ctl['enabled']}")
    return _ok({"enabled": ctl["enabled"]})


async def send_raw(request):
    """往 WebSocket 里塞一条原始命令（比如论坛 `:-`），用来探测框架没解析的协议。"""
    data = await request.json()
    text = str(data.get("text") or "")
    if not text:
        return _bad("text 不能为空")
    try:
        await GlobalVal.websocket.send(text)
        logger.info(f"[控制口] 原始命令 -> {text!r}")
        return _ok({"sent": text})
    except Exception as exc:
        return _bad(f"发送失败：{exc}")


async def reload_all(request):
    if not GlobalVal.plugin_list:
        return _bad("插件表为空", 503)
    result = {}
    for info in list(GlobalVal.plugin_list.values()):
        name = info.get("name")
        if not name or name == "control":
            continue
        try:
            result[name] = await reload_plugin(name)
        except Exception as exc:
            result[name] = {"code": 500, "error": str(exc)}
    logger.info(f"[控制口] 插件重载：{result}")
    return _ok(result)


async def hard_stop(request):
    """紧急关停：整个进程退出，不会自动重启。"""
    logger.warning("[控制口] 收到紧急关停")
    async def _bye():
        try:
            await APIIirose.send_msg_to_room("好，我关掉了。")
        except Exception:
            pass
        await asyncio.sleep(0.8)
        os._exit(0)
    asyncio.create_task(_bye())
    return _ok({"stopping": True})


app = web.Application()
app.add_routes([
    web.get("/status", status),
    web.post("/say", say),
    web.post("/room", room),
    web.post("/ai", ai_switch),
    web.post("/reload", reload_all),
    web.post("/stop", hard_stop),
    web.post("/raw", send_raw),
])


async def on_init():
    try:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, HOST, PORT)
        await site.start()
        GlobalVal.control_runner = runner
        logger.info(f"[控制口] 监听 http://{HOST}:{PORT}")
    except Exception as exc:
        logger.error(f"[控制口] 启动失败：{exc}")
