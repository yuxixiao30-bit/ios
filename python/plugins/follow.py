"""
跟随插件：主人换房间，鲸鱼娘跟着走。

iirose 的换房本质是「断线重连 + 带新房间号重新登录」，
所以这里处理：冷却、目标校验、落地确认、失败重试，以及
**重连期间收到的移动事件排队补跟**（防跟丢）。

配置：follow.json
  {
    "masters": ["5d4e559f99e21", "5efc5d6adced4"],
    "home": "65c49a968faef",
    "enabled": true,
    "cooldown_sec": 6,
    "settle_sec": 10
  }
"""
import asyncio
import json
import os
import re
import time

from loguru import logger

from iirosebot.API.api_iirose import APIIirose
from iirosebot.globals.globals import GlobalVal

PLUGIN_DATE = {
    "name": "follow",
    "author": "鲸鱼娘",
    "version": "1.1.0",
    "description": "主人换房自动跟随（双主人、排队补跟、落地重试）",
    "dependencies": {},
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "follow.json")
API = APIIirose()


def _load_config():
    defaults = {
        "masters": [],
        "home": "65c49a968faef",
        "enabled": True,
        "cooldown_sec": 6,
        "settle_sec": 10,
    }
    try:
        with open(CONFIG_PATH, encoding="utf-8") as file:
            defaults.update(json.load(file))
    except Exception as exc:
        logger.warning(f"[跟] 读取 follow.json 失败，用默认值：{exc}")
    return defaults


CFG = _load_config()
MASTERS = {str(i) for i in CFG.get("masters") or []}
HOME = str(CFG.get("home") or "")
COOLDOWN = float(CFG.get("cooldown_sec", 6))
SETTLE = float(CFG.get("settle_sec", 10))

STATE = {
    "enabled": bool(CFG.get("enabled", True)),
    "busy": False,
    "pending": "",
    "last_move_at": 0.0,
}


def _is_master(message):
    return str(getattr(message, "user_id", "")) in MASTERS


def _target_of(message):
    for attr in ("to_room_id", "room_id", "target_room"):
        value = getattr(message, attr, None)
        if value:
            return str(value).strip()
    return ""


def _now():
    return str(GlobalVal.now_room_id or "")


async def _worker(target):
    """真正执行换房：移动 → 等落地 → 没到就重试一次 → 处理排队。"""
    STATE["busy"] = True
    try:
        logger.info(f"[跟] 出发 -> {target}")
        try:
            await API.move_room(target)
        except Exception as exc:
            logger.error(f"[跟] 换房失败：{exc}")
            return

        await asyncio.sleep(SETTLE)
        if _now() != target:
            logger.warning(f"[跟] {SETTLE:g} 秒未落地（当前 {_now()}），重试一次")
            try:
                await API.move_room(target)
                await asyncio.sleep(SETTLE)
            except Exception as exc:
                logger.error(f"[跟] 重试失败：{exc}")
        if _now() == target:
            logger.info(f"[跟] 已到达 {target}")
        else:
            logger.error(f"[跟] 仍未到达 {target}，当前在 {_now()}")
    finally:
        STATE["busy"] = False
        STATE["last_move_at"] = time.time()

        queued = STATE["pending"]
        STATE["pending"] = ""
        if queued and queued != _now():
            logger.info(f"[跟] 补跟排队目标 -> {queued}")
            await _worker(queued)


async def _follow(message):
    if not STATE["enabled"]:
        return
    if not _is_master(message):
        return

    name = str(getattr(message, "user_name", "") or "?")
    target = _target_of(message)
    if not target:
        logger.warning(f"[跟] {name} 移动了，但事件里没有目标房间：{vars(message)}")
        return
    if target == _now():
        return

    if STATE["busy"]:
        STATE["pending"] = target
        logger.info(f"[跟] 正在换房中，{name} -> {target} 已排队")
        return

    if time.time() - STATE["last_move_at"] < COOLDOWN:
        STATE["pending"] = target
        logger.info(f"[跟] 冷却中，{name} -> {target} 已排队")
        return

    logger.info(f"[跟] 跟随 {name}({getattr(message, 'user_id', '')}) -> {target}")
    asyncio.create_task(_worker(target))


async def user_move_room(Message):
    await _follow(Message)


async def user_leave_room(Message):
    # 有些协议版本把「换房」报成「离开」，这里也接一手
    logger.debug(f"[跟] 离开事件：{vars(Message)}")
    await _follow(Message)


async def room_message(Message):
    text = str(getattr(Message, "message", "") or "").strip()
    uid = str(getattr(Message, "user_id", "") or "")
    if not text:
        return

    normalized = re.sub(r"^\[\*[^*]+\*\]\s*", "", text).strip()
    normalized = normalized.rstrip("。！!？? ")

    if normalized in ("跟随", "开始跟随", "跟着我", "跟我走", "/跟随", "跟随我"):
        if uid in MASTERS:
            STATE["enabled"] = True
            await API.send_msg_to_room("好，跟着你走。")
        return
    if normalized in ("别跟", "别跟随", "不要跟随", "停止跟随", "不跟了", "/别跟", "别跟着我"):
        if uid in MASTERS:
            STATE["enabled"] = False
            STATE["pending"] = ""
            await API.send_msg_to_room("行，不跟了。")
        return
    if normalized in ("回家", "回到默认房间", "/回家"):
        if uid in MASTERS and HOME:
            await API.send_msg_to_room("回默认房间。")
            asyncio.create_task(_worker(HOME))


async def on_init():
    logger.info(
        f"[跟] 跟随插件就绪：主人 {sorted(MASTERS)}，默认房间 {HOME}，"
        f"开关 {STATE['enabled']}，冷却 {COOLDOWN:g}s，落地确认 {SETTLE:g}s"
    )
