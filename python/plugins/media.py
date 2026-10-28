"""
点歌 / 放视频 / 发图：让鲸鱼娘在房间里放媒体。

机器上没有 ffmpeg，所以框架探测时长那一步会失败——这里要求显式给时长，
不给就用默认值。指令只对主人开放，避免房间里被人乱点。

  放视频 <链接> [秒]
  点歌   <链接> [秒]
  鱼鱼我要听 <歌名>        （iTunes 搜索，30 秒试听）
  发图   <本地路径 | 图片链接>
  停一下 / 别放了
"""
import asyncio
import re
import time

from loguru import logger

import iirosebot.API.api_iirose as _api_mod
from iirosebot.globals.globals import GlobalVal

_API_CLASS = next(
    obj for name, obj in vars(_api_mod).items()
    if name.startswith("APII") and isinstance(obj, type)
)
API = _API_CLASS()

PLUGIN_DATE = {
    "name": "media",
    "author": "鲸鱼娘",
    "version": "1.0.0",
    "description": "房间点歌 / 放视频（需显式时长或默认值）",
    "dependencies": {},
}

ROOT = None

import json  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTERS = set()


def _load_masters():
    try:
        with open(os.path.join(ROOT, "follow.json"), encoding="utf-8") as file:
            for uid in json.load(file).get("masters") or []:
                MASTERS.add(str(uid))
    except Exception:
        pass


_load_masters()

URL_RE = re.compile(r"https?://\S+")
LAST_PLAY = {"at": 0.0}

# 免费图床：litterbox（catbox 的临时区，免 key，文件最长存 72 小时）
IMAGE_HOST = "https://litterbox.catbox.moe/resources/internals/api.php"

# 收图：房间里的图先存本地，才算真永久（花园自己的图床会回档）
IMG_URL_RE = re.compile(r"https?://[^\s\"'<>]+?\.(?:jpg|jpeg|png|gif|webp)(?:[^\s\"'<>]*)?", re.I)
COLLECT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memes", "collected")
LAST_IMAGE = {"url": "", "at": 0.0, "room": ""}


def _collect_image(url, emotion=""):
    import hashlib

    import requests

    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    if resp.status_code != 200 or not resp.headers.get("Content-Type", "").startswith("image/"):
        return ""
    digest = hashlib.sha256(resp.content).hexdigest()[:12]
    ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
        ext = "jpg"
    folder = os.path.join(COLLECT_DIR, emotion) if emotion else COLLECT_DIR
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{digest}.{ext}")
    with open(path, "wb") as file:
        file.write(resp.content)
    # 记下原始链接（花园的 r.iirose.com 链接是永久的，以后再发直接用）
    if url.startswith("http") and "iirose.com" in url:
        try:
            sources_path = os.path.join(os.path.dirname(COLLECT_DIR), "sources.json")
            sources = {}
            if os.path.exists(sources_path):
                with open(sources_path, encoding="utf-8") as file:
                    sources = json.load(file)
            sources[f"{digest}.{ext}"] = url
            with open(sources_path, "w", encoding="utf-8") as file:
                json.dump(sources, file, ensure_ascii=False, indent=1)
        except Exception:
            pass
    return path


def _upload_image(path):
    import requests

    with open(path, "rb") as file:
        resp = requests.post(
            IMAGE_HOST,
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": file},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=90,
        )
    if resp.status_code == 200 and resp.text.strip().startswith("http"):
        return resp.text.strip()
    logger.warning(f"[媒体] 图床返回 {resp.status_code}：{resp.text[:80]}")
    return ""


def _parse(text):
    match = URL_RE.search(text)
    if not match:
        return None, None
    url = match.group(0).rstrip("，,。)")
    rest = text.replace(url, " ").strip()
    seconds = None
    num = re.search(r"(\d{1,4})\s*(秒|s)?$", rest)
    if num:
        seconds = int(num.group(1))
    return url, seconds


def _name_of(url):
    tail = url.rstrip("/").split("/")[-1]
    return tail[:40] or "未知"


# ---------- 按名字点歌：iTunes 搜索（免密钥，给 30 秒试听直链） ----------
TSUNDERE_LINES = [
    "哼，就你会差遣人……行吧。",
    "真是麻烦……不过你都开口了。",
    "又要听？……就这一次啊。",
    "行行行，放就是了，别催。",
]
SEARCH_HINT = re.compile(r"^(?:鱼鱼|鲸鱼娘)?\s*(我要听|想听|放首|来首|点首|我要看|想看)\s*(.+)$")


async def _itunes_song(keyword):
    import urllib.parse

    import aiohttp

    params = {
        "term": keyword,
        "media": "music",
        "entity": "song",
        "limit": "5",
    }
    for country in ("cn", "us"):
        query = dict(params, country=country)
        url = "https://itunes.apple.com/search?" + urllib.parse.urlencode(query)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                    if resp.status != 200:
                        continue
                    data = json.loads(await resp.text())
        except Exception as exc:
            logger.debug(f"[媒体] iTunes 搜索失败：{exc!r}")
            continue
        for item in data.get("results") or []:
            if item.get("previewUrl"):
                return item
    return None


# ---------- 完整歌曲：flac.music.hi.cn 的搜索/解析接口（酷我源） ----------
HI_BASE = "https://flac.music.hi.cn/ajax.php"
HI_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://flac.music.hi.cn/"}


def _post_hi(action, data, timeout=25):
    """hi.cn 偶尔会掐连接，重试一次。"""
    import requests

    last = None
    for _ in range(2):
        try:
            resp = requests.post(f"{HI_BASE}?act={action}", data=data, headers=HI_HEADERS, timeout=timeout)
            return resp.json()
        except Exception as exc:
            last = exc
            time.sleep(1)
    raise last


def _hi_search(keyword):
    payload = _post_hi("search", {"platform": "kuwo", "keyword": keyword, "page": 1, "size": 20})
    return ((payload.get("data") or {}).get("list") or [])


def _hi_url(item):
    payload = _post_hi(
        "getUrl",
        {
            "platform": "kuwo",
            "songid": item.get("id"),
            "format": "mp3",
            "bitrate": "320",
            "time": item.get("time"),
            "sign": item.get("sign"),
        },
        timeout=40,
    )
    return (payload.get("data") or {}) if payload.get("code") == 0 else {}


async def _search_song(keyword):
    """先找完整版（hi.cn），失败退回 iTunes 的 30 秒试听。"""
    try:
        items = await asyncio.to_thread(_hi_search, keyword)
    except Exception as exc:
        logger.warning(f"[媒体] hi.cn 搜索失败：{exc!r}")
        items = []

    # 带歌手名搜索常常直接返回 0，退回只搜歌名
    if not items:
        first = keyword.split()[0] if keyword.split() else keyword
        if first and first != keyword:
            try:
                items = await asyncio.to_thread(_hi_search, first)
                logger.info(f"[媒体] 组合词无结果，改用「{first}」搜到 {len(items)} 条")
            except Exception:
                items = []

    ranked = [
        item for item in sorted(items, key=lambda it: _score(it, keyword), reverse=True)
        if len(str(item.get("name") or "")) >= 2
    ][:3]
    if ranked:
        best = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else None
        gap = _score(best, keyword) - (_score(runner, keyword) if runner else 0)
        # 只有「查询词全命中 + 明显领先 + 分数够高」才直接放，否则让人挑
        confident = _covers_all(best, keyword) and gap >= 10 and _score(best, keyword) >= 60
        if confident:
            got = await _resolve_pick(best, keyword)
            if got:
                return got
        PENDING.update({"items": ranked, "at": time.time(), "keyword": keyword})

    item = await _itunes_song(keyword)
    if PENDING.get("items"):
        return None
    if item and item.get("previewUrl"):
        return {
            "url": item["previewUrl"],
            "name": item.get("trackName"),
            "artist": item.get("artistName"),
            "duration": 30,
            "pic": str(item.get("artworkUrl100") or "").replace("100x100", "300x300"),
            "source": "iTunes 试听",
        }
    return None


BAD_WORDS = ("dj", "串烧", "伴奏", "翻唱", "cover", "纯音乐", "片段", "铃声", "抖音", "女声版", "男声版")
PENDING = {"items": [], "at": 0.0, "keyword": ""}


def _score(item, keyword):
    name = str(item.get("name") or "").lower().replace(" ", "")
    artist = str(item.get("artist") or "").lower().replace(" ", "")
    query = keyword.lower().replace(" ", "")
    tokens = [t for t in keyword.lower().split() if t]
    text = name + artist

    # 关键词覆盖率：查询里的词有几个真的出现在歌名/歌手里
    covered = sum(1 for t in tokens if t in text)
    coverage = covered / max(1, len(tokens))

    score = 0.0
    if name == query:
        score += 100
    elif query in name:
        score += 70
    elif len(name) >= 3 and name in query:
        score += 35
    score += 40 * coverage

    if len(name) < 2:          # 「伦」这种一字标题，基本是垃圾结果
        score -= 50
    if any(word in name for word in BAD_WORDS):
        score -= 60
    try:
        if int(item.get("duration") or 0) >= 60:
            score += 5
    except Exception:
        pass
    return score


def _covers_all(item, keyword):
    text = (str(item.get("name") or "") + str(item.get("artist") or "")).lower().replace(" ", "")
    return all(token in text for token in keyword.lower().split() if token)


async def _resolve_pick(item, keyword):
    try:
        got = await asyncio.to_thread(_hi_url, item)
    except Exception:
        return None
    if not got.get("url"):
        return None
    return {
        "url": got["url"],
        "name": item.get("name"),
        "artist": item.get("artist"),
        "duration": got.get("duration") or item.get("duration"),
        "pic": item.get("pic_url"),
        "source": "hi.cn 完整版",
    }


async def _play(Message, media_type, url, seconds):
    if str(Message.user_id) not in MASTERS:
        await API.send_msg_to_room("这个只有主人能让放。")
        return
    if time.time() - LAST_PLAY["at"] < 10:
        await API.send_msg_to_room("刚放过，缓一下。")
        return
    LAST_PLAY["at"] = time.time()

    kind = "歌" if media_type else "视频"
    duration = seconds or (240 if media_type else 300)
    try:
        await API.send_msg_to_room(f"好，放个{kind}：《{_name_of(url)}》，大约 {duration} 秒。")
        await API.play_media(
            media_type=media_type,
            media_url=url,
            media_time=duration,
            media_name=_name_of(url),
            media_auther="",
        )
        logger.info(f"[媒体] 播放{kind} {url} {duration}s")
    except Exception as exc:
        logger.error(f"[媒体] 播放失败：{exc!r}")
        await API.send_msg_to_room(f"放不出来：{str(exc)[:60]}")


async def _play_song(song, keyword=""):
    LAST_PLAY["at"] = time.time()
    PENDING["items"] = []
    await API.send_msg_to_room(random.choice(TSUNDERE_LINES))
    try:
        await API.play_media(
            media_type=True,
            media_url=song["url"],
            media_time=int(song.get("duration") or 240),
            media_name=str(song.get("name") or keyword)[:40],
            media_auther=str(song.get("artist") or "")[:40],
            media_pic=str(song.get("pic") or ""),
        )
        logger.info(
            f"[媒体] 点歌 {keyword} -> {song.get('name')} / {song.get('artist')}"
            f"（{song.get('source')}，{song.get('duration')} 秒）"
        )
    except Exception as exc:
        logger.error(f"[媒体] 按名点歌失败：{exc!r}")
        await API.send_msg_to_room("这首放不出来，换一首？")


def _ai_muted():
    """她说不出话的时候，图也别发。"""
    ctl = getattr(GlobalVal, "ai_control", None)
    if isinstance(ctl, dict) and "enabled" in ctl:
        return not bool(ctl["enabled"])
    return False

async def room_message(Message):
    if _ai_muted():
        return
    text = str(getattr(Message, "message", "") or "").strip()
    if not text:
        return

    # 记住房间里最近一张图，方便「收下这张」
    m = IMG_URL_RE.search(text)
    if m:
        LAST_IMAGE.update(url=m.group(0), at=time.time(), room=str(GlobalVal.now_room_id or ""))
    text = text.lstrip("[*").rstrip("*] ")

    # 待选歌单：回数字就播那首
    if text in ("1", "2", "3") and PENDING.get("items"):
        if time.time() - float(PENDING.get("at") or 0) < 180 and str(Message.user_id) in MASTERS:
            index = int(text) - 1
            items = PENDING["items"]
            if 0 <= index < len(items):
                keyword = str(PENDING.get("keyword") or "")
                PENDING["items"] = []
                song = await _resolve_pick(items[index], keyword)
                if song:
                    await _play_song(song, keyword)
                else:
                    await API.send_msg_to_room("这首解析不出来，换一个？")
                return

    if text.startswith(("收下这张", "收藏这张", "收图")):
        if str(Message.user_id) not in MASTERS:
            await API.send_msg_to_room("图只有主人能收。")
            return
        found = IMG_URL_RE.search(text)
        url = found.group(0) if found else str(LAST_IMAGE.get("url") or "")
        if not url:
            await API.send_msg_to_room("房间里最近没有图，或者你直接给我链接。")
            return
        emotion = ""
        rest = text.replace(url, " ").replace("收下这张", " ").replace("收藏这张", " ").replace("收图", " ")
        word = rest.strip().split()[0].strip("，。, ") if rest.strip() else ""
        known = set()
        base = os.path.dirname(COLLECT_DIR)
        if os.path.isdir(base):
            known = {d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))}
        if word and word in known:
            emotion = word
        path = await asyncio.to_thread(_collect_image, url, emotion)
        if not path:
            await API.send_msg_to_room("这张存不下来，可能链接已经失效。")
            return
        await API.send_msg_to_room(f"收下了：{os.path.basename(path)}")
        logger.info(f"[收图] {url} -> {path}")
        return

    if text.startswith(("发图", "传图")):
        if str(Message.user_id) not in MASTERS:
            await API.send_msg_to_room("图只有主人能发。")
            return
        arg = text[2:].strip().strip('"')
        if arg.startswith("http"):
            await API.send_msg_to_room(f"{arg}#e")
            return
        if not os.path.exists(arg):
            await API.send_msg_to_room("找不到这个文件。")
            return
        url = await asyncio.to_thread(_upload_image, arg)
        if not url:
            await API.send_msg_to_room("图传不上去，换一张？")
            return
        await API.send_msg_to_room(f"{url}#e")
        logger.info(f"[媒体] 发图 {arg} -> {url}")
        return

    if text in ("停一下", "别放了", "停", "停止播放"):
        if str(Message.user_id) in MASTERS:
            try:
                await API.stop_media()
                await API.send_msg_to_room("停了。")
            except Exception as exc:
                logger.error(f"[媒体] 停止失败：{exc!r}")
        return

    hint = SEARCH_HINT.match(text)
    if hint:
        verb, keyword = hint.group(1), hint.group(2).strip()
        if str(Message.user_id) not in MASTERS:
            await API.send_msg_to_room("这个只有主人能点。")
            return
        if time.time() - LAST_PLAY["at"] < 10:
            await API.send_msg_to_room("刚放过，缓一下。")
            return
        if verb in ("我要听", "想听", "放首", "来首", "点首"):
            song = await _search_song(keyword)
            if not song:
                options = PENDING.get("items") or []
                if options:
                    lines = [
                        f"{i + 1}. {it.get('name')} - {it.get('artist')}"
                        for i, it in enumerate(options)
                    ]
                    await API.send_msg_to_room("搜到几个，回个数字挑一下：\n" + "\n".join(lines))
                else:
                    await API.send_msg_to_room("搜不到这首……给我个直链吧。")
                return
            await _play_song(song, keyword)
            return
        await API.send_msg_to_room("视频按名字我搜不到（B 站拦我），给我个直链嘛。")
        return

    if text.startswith(("放视频", "放个视频", "视频", "看电影")):
        url, seconds = _parse(text)
        if not url:
            await API.send_msg_to_room("给我个视频直链，我认链接不认名字。")
            return
        await _play(Message, False, url, seconds)
        return

    if text.startswith(("点歌", "放歌", "来首歌", "放音乐", "听歌")):
        url, seconds = _parse(text)
        if not url:
            await API.send_msg_to_room("歌我也要链接——我搜不到歌名，只会放你给的地址。")
            return
        await _play(Message, True, url, seconds)
        return


async def private_message(Message):
    """私聊里也能收图：记下最近一张，收到「收图」就存。"""
    if _ai_muted():
        return
    text = str(getattr(Message, "message", "") or "").strip()
    uid = str(getattr(Message, "user_id", "") or "")
    if not text:
        return

    found = IMG_URL_RE.search(text)
    if found:
        LAST_IMAGE.update(url=found.group(0), at=time.time(), room="private")

    if not text.startswith(("收图", "收下这张", "收藏这张")):
        return
    if uid not in MASTERS:
        await API.send_msg_to_private("图只有主人能收。", uid)
        return

    url = found.group(0) if found else str(LAST_IMAGE.get("url") or "")
    if not url:
        await API.send_msg_to_private("最近没图可收，给我个链接也行。", uid)
        return

    emotion = ""
    rest = text.replace(url, " ")
    for word in ("收下这张", "收藏这张", "收图"):
        rest = rest.replace(word, " ")
    word = rest.strip().split()[0].strip("，。, ") if rest.strip() else ""
    known = set()
    base = os.path.dirname(COLLECT_DIR)
    if os.path.isdir(base):
        known = {d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))}
    if word and word in known:
        emotion = word

    path = await asyncio.to_thread(_collect_image, url, emotion)
    if not path:
        await API.send_msg_to_private("这张存不下来，链接可能失效了。", uid)
        return
    await API.send_msg_to_private(f"收下了：{os.path.basename(path)}", uid)
    logger.info(f"[收图|私聊] {url} -> {path}")


async def on_init():
    logger.info(f"[媒体] 点歌/放视频就绪，主人 {sorted(MASTERS)}（时长需显式给或走默认）")


# ---------- 监听房间里的媒体事件（&1 包）----------
NOW_PLAYING = {"name": "", "author": "", "kind": "", "at": 0.0}


async def _record_playing(Message, kind):
    NOW_PLAYING.update(
        name=str(getattr(Message, "media_name", "") or ""),
        author=str(getattr(Message, "media_auther", "") or ""),
        kind=kind,
        at=time.time(),
    )
    GlobalVal.now_playing = NOW_PLAYING
    logger.info(f"[媒体] 房间在放：{NOW_PLAYING['name']} - {NOW_PLAYING['author']}")


async def media_music_message(Message):
    await _record_playing(Message, "音乐")


async def media_video_message(Message):
    await _record_playing(Message, "视频")
