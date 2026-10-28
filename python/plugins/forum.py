"""
论坛（贴吧）只读采集：定期发 `:-`，把服务器回的帖子帧解析成列表存起来。
不主动发帖、不回别人的帖子。
"""
import asyncio
import io
import json
import os
import re
import time

from loguru import logger

from iirosebot.globals.globals import GlobalVal

PLUGIN_DATE = {
    "name": "forum",
    "author": "鲸鱼娘",
    "version": "1.0.0",
    "description": "论坛只读采集（每 10 分钟抓一次）",
    "dependencies": {},
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEM = os.path.join(ROOT, "memory")
RAW = os.path.join(MEM, "raw_frames.log")
OUT = os.path.join(MEM, "forum.json")


def _interval():
    try:
        cfg = json.load(open(os.path.join(ROOT, "ai.json"), encoding="utf-8"))
        return max(10, int(cfg.get("forumIntervalMin", 30))) * 60
    except Exception:
        return 30 * 60


INTERVAL = _interval()
STATE = {"offset": 0, "last_at": 0.0}

try:
    from iirosebot.API.api_load_config import load_config

    BOT_NAME = load_config()[0]
except Exception:
    BOT_NAME = "鲸鱼娘"


def _read_new_frames():
    if not os.path.exists(RAW):
        return ""
    size = os.path.getsize(RAW)
    if size < STATE["offset"]:
        STATE["offset"] = 0
    with io.open(RAW, encoding="utf-8", errors="ignore") as file:
        file.seek(STATE["offset"])
        chunk = file.read()
        STATE["offset"] = file.tell()
    return chunk


def _parse(chunk):
    text = " ".join(chunk.splitlines())
    # 日志前缀会插在帧中间，先换成记录分隔符，否则记录被切断
    text = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} :-", "<", text)
    posts = []
    for record in text.split("<"):
        parts = record.split(">")
        if len(parts) < 7:
            continue
        name = parts[0].strip()
        if not name or len(name) > 24:
            continue
        content = re.sub(r"^[0-9a-fA-F]{6}", "", parts[3])
        reply_to = ""
        match = re.search(r"\[@(\d+)\]", content)
        if match:
            reply_to = match.group(1)
        ts = pid = None
        for field in parts[4:]:
            if field.isdigit() and len(field) == 10 and ts is None:
                ts = int(field)
            elif field.isdigit() and len(field) >= 13 and pid is None:
                pid = field
        if not ts:
            continue
        images = re.findall(r"https?://[^\s\]]+\.(?:jpg|jpeg|png|gif|webp)", content)
        plain = re.sub(r"\[[^\]]*\]", "", content).strip()
        posts.append({
            "name": name,
            "at": time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)),
            "ts": ts,
            "id": pid or "",
            "reply_to": reply_to,
            "text": plain[:200],
            "images": images[:3],
        })
    return posts


async def _collect():
    try:
        await GlobalVal.websocket.send(":-")
    except Exception as exc:
        logger.warning(f"[论坛] 发命令失败：{exc!r}")
        return 0
    await asyncio.sleep(4)
    chunk = _read_new_frames()
    posts = _parse(chunk)
    if not posts:
        return 0

    data = {"updated": time.time(), "posts": []}
    try:
        data = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        pass
    old = {p.get("id"): p for p in data.get("posts", []) if p.get("id")}
    for post in posts:
        if post.get("id"):
            old[post["id"]] = post
    merged = sorted(old.values(), key=lambda p: p.get("ts", 0), reverse=True)[:200]
    seen = set(data.get("seen_replies") or [])
    own_ids = {p["id"] for p in merged if p.get("name") == BOT_NAME and p.get("id")}
    for post in merged:
        if post.get("reply_to") in own_ids and post.get("id") and post["id"] not in seen:
            seen.add(post["id"])
            logger.info(
                f"[论坛] 有人回你的帖子：{post['at']} {post['name']}：{post['text'][:50]}"
            )
    data = {"updated": time.time(), "posts": merged, "seen_replies": sorted(seen)[-500:]}
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    newest = [p for p in posts if p["ts"] > time.time() - 900]
    for post in newest:
        logger.info(f"[论坛] {post['at']} {post['name']}：{post['text'][:40]}")
    return len(posts)


async def _loop():
    await asyncio.sleep(45)
    while True:
        try:
            STATE["last_at"] = time.time()
            count = await _collect()
            logger.info(f"[论坛] 本轮解析 {count} 条")
        except Exception as exc:
            logger.warning(f"[论坛] 采集异常：{exc!r}")
        await asyncio.sleep(INTERVAL)


async def on_init():
    asyncio.create_task(_loop())
    logger.info(f"[论坛] 只读采集已启动，每 {INTERVAL // 60} 分钟一次")
