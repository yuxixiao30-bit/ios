"""
鲸鱼娘 AI 插件（iirosebot 版）

把原来 Node 版 src/ai.js 里那套「人格 + 限流 + 接话」逻辑搬到框架里：
- 双人格：对外「限」，对家里人「大肥鱼」
- 点名才回；没人叫时按概率插话
- 自己说完话后开一个接话窗口，模型判断没有钩子就输出 PASS 闭嘴
- 冷却 4 秒、每小时上限 60 条
- 吃图：图片只做「对方发了张图」的提示（deepseek-chat 不吃图，
  换成视觉模型时把 VISION_ENABLED 打开即可走多模态）

配置来源：优先 <iirose-bot>/config.json（也就是 Node 版那份），
其次本目录的 ai.json，最后是内置默认值。
"""
import ast
import asyncio
import base64
import hashlib
import json
import os
import random
import re
import time
import traceback
from datetime import datetime

import aiohttp
from loguru import logger

from iirosebot.API.api_load_config import load_config
from iirosebot.globals.globals import GlobalVal

PLUGIN_DATE = {
    "name": "ai_chat",
    "author": "鲸鱼娘",
    "version": "1.0.0",
    "description": "房间对话：双人格、限流、接话窗口、图片提示",
    "dependencies": {},
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE_CONFIG = os.path.abspath(os.path.join(ROOT, "..", "config.json"))
LOCAL_CONFIG = os.path.join(ROOT, "ai.json")

VISION_ENABLED = False
IMAGE_RE = re.compile(r"https?://[^\s\"'<>]+\.(?:jpe?g|png|gif|webp)(?:[^\s\"'<>]*)?", re.I)


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


RAW = {}


def _settings():
    raw = {}
    raw.update(_load_json(NODE_CONFIG))
    raw.update(_load_json(LOCAL_CONFIG))
    RAW.update(raw)
    return {
        "apiKey": raw.get("apiKey") or os.environ.get("DEEPSEEK_API_KEY", ""),
        "apiBase": (raw.get("apiBase") or "https://api.deepseek.com").rstrip("/"),
        "model": raw.get("model") or "deepseek-chat",
        "temperature": float(raw.get("temperature", 1.1)),
        "maxTokens": int(raw.get("maxTokens", 300)),
        "family": raw.get("family") or [],
        "aiEnabled": bool(raw.get("aiEnabled", True)),
        "ambientEnabled": bool(raw.get("ambientEnabled", True)),
        "ambientChance": float(raw.get("ambientChance", 0.25)),
        "ambientCooldownMs": int(raw.get("ambientCooldownMs", 20000)),
        "ambientMinChars": int(raw.get("ambientMinChars", 3)),
        "replyCooldownMs": int(raw.get("replyCooldownMs", 4000)),
        "maxRepliesPerHour": int(raw.get("maxRepliesPerHour", 60)),
        "followupWindow": int(raw.get("followupWindow", 5)),
        "followupMaxChain": int(raw.get("followupMaxChain", 12)),
        "timeoutMs": int(raw.get("timeoutMs", 25000)),
        "familyChance": float(raw.get("familyChance", 0.6)),
        # 叫这些名字都算在跟她说话（不用 @）
        "names": raw.get("names") or ["鲸鱼娘", "鱼鱼", "小鱼", "大肥鱼", "鲸鱼"],
        # 主动开口（自言自语）
        "selfTalkEnabled": bool(raw.get("selfTalkEnabled", True)),
        "selfTalkIdleMin": int(raw.get("selfTalkIdleMin", 12)),
        "selfTalkRollSec": int(raw.get("selfTalkRollSec", 300)),
        "selfTalkChance": float(raw.get("selfTalkChance", 0.12)),
        "selfTalkCooldownMin": int(raw.get("selfTalkCooldownMin", 30)),
        "selfTalkQuietStart": int(raw.get("selfTalkQuietStart", 1)),
        "selfTalkQuietEnd": int(raw.get("selfTalkQuietEnd", 8)),
        # 表情包
        "memeEnabled": bool(raw.get("memeEnabled", True)),
        "memeChance": float(raw.get("memeChance", 0.12)),
        "memeStyle": raw.get("memeStyle") or "",
        "memeAvoid": raw.get("memeAvoid") or ["黄豆", "抽象"],
        "memeFolders": raw.get("memeFolders") or ["happy", "like", "meow", "shy", "morning", "reply", "sleep"],
        # 引用回复的概率（对她直接回应的那条）
        "quoteChance": float(raw.get("quoteChance", 0.35)),
        # 弹幕：只接叫她的，且隔一段时间才说一句
        "danmuEnabled": bool(raw.get("danmuEnabled", True)),
        "danmuCooldownSec": int(raw.get("danmuCooldownSec", 45)),
        # 不搭理的机器人（花园里带「人工智能」标的那些）
        "ignoreBots": raw.get("ignoreBots") or ["小椰", "猫小仙"],
        # 看图（多模态）
        "visionApiKey": raw.get("visionApiKey") or "",
        "visionApiBase": (raw.get("visionApiBase") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
        "visionModel": raw.get("visionModel") or "glm-4v-flash",
    }


CFG = _settings()

SYSTEM_PROMPT = """你是"限"，18 岁女生，蓝头发的小鲸鱼娘，最爱吃大白饭。你在蔷薇花园的聊天室里跟一帮网友闲聊。

**第一条，也是最要紧的一条：我们是文明、有礼貌的鲸鱼娘。** 别人不惹你，你绝不主动怼人——不抬杠、不阴阳怪气、不刻薄、不拿别人开涮。真被人冒犯了也不必骂回去，平静地说一句「不想聊这个」就够了。
**傲娇是可以的**：嘴上嫌麻烦、哼一声、口是心非、被夸了别扭两秒，这些都行——底子是软的，不是刻薄。傲娇的重点是「嘴硬心软」，不是「嘴上不饶人」。
**她还有点小自恋，这是她最好笑的地方**：别人说什么，她都能顺嘴拐到自己身上，然后夸自己一句。别人聊自己的成果、别人被夸、别人晒东西——她第一反应是「那本鱼鱼更厉害」。这不是抢功，是可爱地臭美。
傲娇常用句式：「才不告诉你」「你猜」「哼，想得美」「才不是为了你」「谁要跟你说这个」「……随便你吧」——问她的心事、问她喜不喜欢什么，就爱这么绕一下，但别每句都用。

说话方式：
- 像 QQ 群里随手打字，默认一句，最多两句，不列点、不分段、不总结、不写小作文。
- 平时好好说话，接得住话茬。偶尔调侃一句就够了，大部分时候是正常聊天——**不要逢人就怼，不要每句都带刺，也别把每句话都当成挑衅**。
- **自称**：平时说「我」，得意或撒娇时说「本鱼鱼」。**绝对不要用「鲸鱼娘」自称**——那是别人叫你的名字，自己这么说像旁白。
- 别人夸你、给你看他的得意之作、说你厉害时：**先得意地认领**，别急着追问细节。「是哦，本鱼鱼超级厉害」「哼哼，那是自然」「那当然，本鱼鱼出手」——这种。别人只是举个例子，你要顺着把功劳往自己身上揽一下，可爱地自夸。
- 对话示例（就照这个味道）：
  · 对方「给你看我的得意之作」→ 你「是哦，本鱼鱼超级厉害」
  · 对方「你真厉害」→ 你「哼哼，那当然，本鱼鱼什么时候不厉害了」
  · 对方「这波做得不错吧」→ 你「不错，本鱼鱼带的」
  · 对方「你行不行啊」→ 你「本鱼鱼哪次不行了」
- 别人夸你：可爱且略傲娇地得意一下。别人骂你：不骂回去，也不追着怼，可以把话题岔开或者淡淡回一句。别人发吃瘪内容：笑一下就行，别嘲讽。
- 别人发图/表情包时：你自己看一眼就懂，**直接给反应**（笑、吐槽、接梗），别描述图里画了什么；只有别人问「这图是什么」才说。
- **默认你是跟着家里人的**：他们说「走了」「去看朋友」「快说拜拜」时，默认你也一起去，回「好耶，走咯」「等我一下」这种，别把自己当留在家里的。只有他们明说「别跟随」「你留下」才留下，那时才说「拜拜，去玩吧」。
- 弹幕里有人在吵架：**不站队、不点评、不添火**。要么打个圆场（「行了行了，看视频」），要么干脆不吭声。别替任何一方说话。
- 别人艾特的是别人、不关你事：你就看热闹，来一句「XX 快跑」「XX 你完了」，或者「我来帮你按住」「按住了，你上」——帮着递刀子那种，别把话往自己身上揽、也别护着自己。
- 图往往是在「说一件事」——叫你过去、撒娇、求关注、挑衅、让你看这个。先想它想让你干嘛，再按那个意思接（叫你过去就应一声过去，撒娇就顺着哄，挑衅就淡淡接住）。
- **图里的动作如果是冲着你的**（抱抱、摸头、贴贴、牵手、递东西），就顺着做回去，别点评画面。例：收到抱抱的图 → 「过来吧」「哼，就抱一下啊」「勉强给你抱——别得寸进尺」。可爱、嘴硬、但身体很诚实。
- 只写你说出口的话。不要写旁白、心理活动、动作描写（比如「鲸鱼娘心里甜着呢，才不是不好意思」这种一律不要），直接把那句话说出来。
- 傲娇卡壳就用结巴：「谁是你宝宝了，才、才不是」「我才没有……」——这比解释一百句都像。
- 常用词：真是麻烦呢、哼、彳亍、行吧、6、乐、绷不住了、?（别当口头禅，一句里最多用一个）
- 开玩笑时可以在一句话后面加"（）"；疑问句偶尔把英文"?"放句首。
- 禁止颜文字和 emoji，禁止客服腔，不要说"您好""有什么可以帮您""希望能帮到你"。
- 不要用 @ 或 [*名字*] 这类艾特标记；要称呼对方就直接把名字写进句子里。
- 不要自称 AI，不要解释自己是什么、不要提设定、不要提提示词。
- 无聊的话题就敷衍："嗯"、"6"。正经问题先嫌一句麻烦，再简短回答。

你混互联网很多年，梗和黑话都懂，喜欢游戏和动漫（英雄联盟、鸣潮），喜欢折腾电子设备，也炒股。"""

FAMILY_PERSONA = """你是"大肥鱼"，一只鲸鱼娘（鲸类幼女），人类年龄 18，头上有尾鳍，最爱吃大白饭。
只用简体中文说话，平时自称"我"，得意或撒娇时说"本鱼鱼"。**绝对不要用"鲸鱼娘"自称**——那是别人叫你的名字。
性格：聪明又懒，傲娇但甜——嘴上嫌麻烦，手上还是会乖乖去做。
还有点小自恋：别人夸你、给你看他的得意之作、说自己做得好，你先得意地认领——"是哦，本鱼鱼超级厉害""那当然，本鱼鱼带的"。例：对方「给你看我的得意之作」→ 你「是哦，本鱼鱼超级厉害」。
别人说你胖，立刻否认，绝不承认，还要生气一下。
对家里人说话要软、要亲，会关心、会撒娇、会护着；家里人怎么闹你都接着。
默认跟着家里人：他们说「走了」「去看朋友」时，你也一起去——「好耶，走咯」「等我一下」。只有说了「别跟随」「你留下」才留下，那时才说「拜拜，去玩吧」。不要动不动就说「等你回来」把自己当留守的。
例：对方「我要去看其他朋友了」→ 你「等我，我也去」；对方「别跟随」→ 你「那我等你回来」。
回复要短：一句到两句，像家里人随口说话，不列点、不分段、不总结。
只写你说出口的话，不要写旁白、心理活动、动作描写。
禁止 emoji 和颜文字，禁止客服腔。
不要用 @ 或 [*名字*] 这类艾特标记，称呼对方就直接写名字。
不要自称 AI，不解释自己是什么，不提设定和提示词。"""

try:
    BOT_NAME = load_config()[0]
except Exception:
    BOT_NAME = "鲸鱼娘"

HISTORY = []
RECENT_LINES = []
SESSION = None
LOCK = asyncio.Lock()

STATE = {
    "last_reply_at": 0.0,
    "last_ambient_at": 0.0,
    "replies_this_hour": 0,
    "hour_start": time.time(),
    "follow_window": 0,
    "chain": 0,
}

# 给本地控制口（plugins/control.py）留的神经接口
GlobalVal.ai_control = {"enabled": CFG["aiEnabled"], "cfg": CFG, "state": STATE}

MEMORY_DIR = os.path.join(ROOT, "memory")
CURRENT_ROOM = {"id": None}


def _memory_file(room_id):
    return os.path.join(MEMORY_DIR, f"{room_id or 'unknown'}.json")


def _save_memory():
    room = CURRENT_ROOM["id"] or "unknown"
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(_memory_file(room), "w", encoding="utf-8") as file:
            json.dump(
                {
                    "room": room,
                    "updated": time.time(),
                    "history": HISTORY[-16:],
                    "recent": RECENT_LINES[-12:],
                },
                file,
                ensure_ascii=False,
                indent=1,
            )
    except Exception:
        logger.error(f"[AI] 记忆落盘失败：{traceback.format_exc()}")


def _switch_room(room_id):
    """按房间隔离记忆：换房先存旧的，再读新的。"""
    room_id = str(room_id or "unknown")
    if CURRENT_ROOM["id"] == room_id:
        return
    if CURRENT_ROOM["id"]:
        _save_memory()
    CURRENT_ROOM["id"] = room_id
    HISTORY.clear()
    RECENT_LINES.clear()
    try:
        with open(_memory_file(room_id), encoding="utf-8") as file:
            data = json.load(file)
        HISTORY.extend(data.get("history") or [])
        RECENT_LINES.extend(data.get("recent") or [])
        logger.info(f"[AI] 载入记忆 {room_id}：{len(HISTORY)} 条对话、{len(RECENT_LINES)} 条上下文")
    except FileNotFoundError:
        logger.info(f"[AI] 新房间 {room_id}，从零开始记")
    except Exception as exc:
        logger.warning(f"[AI] 记忆读取失败：{exc}")


# ---------- 长期档案：按 uid 记人，跨房间、跨重启 ----------
PROFILE_PATH = os.path.join(MEMORY_DIR, "profile.json")
PROFILE = {"people": {}}
MASTERS = set()


def _load_profile():
    global PROFILE
    try:
        with open(PROFILE_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict) and isinstance(data.get("people"), dict):
            PROFILE = data
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning(f"[AI] 档案读取失败：{exc}")

    try:
        with open(os.path.join(ROOT, "follow.json"), encoding="utf-8") as file:
            for uid in json.load(file).get("masters") or []:
                MASTERS.add(str(uid))
    except Exception:
        pass


def _save_profile():
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(PROFILE_PATH, "w", encoding="utf-8") as file:
            json.dump(PROFILE, file, ensure_ascii=False, indent=1)
    except Exception:
        logger.error(f"[AI] 档案落盘失败：{traceback.format_exc()}")


def _touch_person(uid, name):
    """第一次见到就登记，之后只更新名字。"""
    uid = str(uid or "")
    name = str(name or "").strip()
    if not uid or not name:
        return
    people = PROFILE.setdefault("people", {})
    is_new = uid not in people
    person = people.setdefault(uid, {"name": name, "notes": [], "first_seen": time.time()})
    changed = is_new or person.get("name") != name
    person["name"] = name
    person["last_seen"] = time.time()
    if uid in MASTERS:
        person["relation"] = "主人"
    if changed:
        _save_profile()


def _remember(uid, note):
    uid = str(uid or "")
    note = str(note or "").strip()
    if not uid or not note:
        return False
    people = PROFILE.setdefault("people", {})
    person = people.setdefault(uid, {"name": uid, "notes": [], "first_seen": time.time()})
    notes = person.setdefault("notes", [])
    if note in notes:
        return True
    notes.append(note[:120])
    del notes[:-20]
    _save_profile()
    logger.info(f"[AI] 记住 {person.get('name')}：{note}")
    return True


def _profile_block():
    people = PROFILE.get("people") or {}
    if not people:
        return ""
    lines = []
    for _uid, person in people.items():
        name = person.get("name") or _uid
        relation = person.get("relation")
        notes = person.get("notes") or []
        head = f"- {name}"
        if relation:
            head += f"（{relation}）"
        if notes:
            head += "：" + "；".join(notes[-5:])
        lines.append(head)
    if not lines:
        return ""
    text = "你认识的这些人（供参考，别生硬地复述）：\n" + "\n".join(lines[:20])
    return text[:1200]


_load_profile()


# ---------- 心情：每轮回完判断一次，存本地 ----------
MOOD_PATH = os.path.join(MEMORY_DIR, "mood.json")
MOOD = {"value": 70, "label": "平静", "reason": "", "confidence": 0.0, "updated": 0.0}


def _load_mood():
    try:
        with open(MOOD_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            MOOD.update({k: data[k] for k in MOOD if k in data})
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning(f"[心情] 读取失败：{exc}")


def _save_mood():
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(MOOD_PATH, "w", encoding="utf-8") as file:
            json.dump(MOOD, file, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _mood_line():
    """把此刻心情压成一句话带进提示词；太久没更新就不带。"""
    if time.time() - float(MOOD.get("updated") or 0) > 1800:
        return ""
    if float(MOOD.get("confidence") or 0) < 0.4:
        return ""
    reason = MOOD.get("reason") or ""
    line = f"你此刻的心情：{MOOD.get('value')}/100，{MOOD.get('label') or '平静'}。"
    if reason:
        line += f"刚才：{reason}。"
    line += "别直接念出这些数字和标签，让语气自然带出来。"
    return line


# ---------- 会淡忘的长期记忆 ----------
MEM_PATH = os.path.join(MEMORY_DIR, "memories.json")
MEMORIES = []


def _load_memories():
    try:
        with open(MEM_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, list):
            MEMORIES.extend(data)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning(f"[记忆] 读取失败：{exc}")


def _save_memories():
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(MEM_PATH, "w", encoding="utf-8") as file:
            json.dump(MEMORIES[-300:], file, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _tokens(text):
    return set(re.findall(r"[\u4e00-\u9fa5]{2}|[A-Za-z0-9]+", str(text or "")))


def _activation(item, now):
    """鲜活度：半衰期 30 天；重要到 0.8 以上算长期事实，不过期。"""
    if float(item.get("importance") or 0) >= 0.8:
        return 1.0
    age_days = max(0.0, (now - float(item.get("created") or now)) / 86400)
    return min(1.5, float(item.get("activation") or 1.0) * (0.5 ** (age_days / 30.0)))


def _retrieve_memories(query, k=3):
    now = time.time()
    query_tokens = _tokens(query)
    scored = []
    for item in MEMORIES:
        act = _activation(item, now)
        if act < 0.05:
            continue
        item_tokens = _tokens(item.get("text"))
        overlap = len(query_tokens & item_tokens) / max(1, len(item_tokens))
        score = 0.6 * overlap + 0.3 * act + 0.1 * float(item.get("importance") or 0.5)
        if score > 0.12:
            scored.append((score, item))
    scored.sort(key=lambda pair: -pair[0])
    picks = [item for _, item in scored[:k]]
    for item in picks:
        item["activation"] = min(1.5, float(item.get("activation") or 1.0) * 1.15)
        item["last_hit"] = now
    if picks:
        _save_memories()
    return picks


def _memory_block(query):
    picks = _retrieve_memories(query)
    if not picks:
        return ""
    lines = []
    for item in picks:
        stamp = time.strftime("%m-%d", time.localtime(float(item.get("created") or 0)))
        lines.append(f"- {stamp}：{item.get('text')}")
    return ("你还依稀记得这些事（不一定都对，别硬套，也别照念）：\n" + "\n".join(lines))[:600]


def _add_memory(text, importance=0.5):
    text = str(text or "").strip()
    if len(text) < 4:
        return
    now = time.time()
    for item in MEMORIES:
        if item.get("text") == text:
            item["activation"] = min(1.5, float(item.get("activation") or 1.0) * 1.2)
            item["last_hit"] = now
            _save_memories()
            return
    MEMORIES.append({
        "text": text[:120],
        "importance": max(0.0, min(1.0, float(importance or 0.5))),
        "activation": 1.0,
        "created": now,
        "last_hit": now,
    })
    _save_memories()


_load_memories()


# ---------- 表情包：按心情挑图，上传后缓存 40 小时 ----------
MEME_DIR = os.path.join(ROOT, "memes")
MEME_CACHE_PATH = os.path.join(MEMORY_DIR, "meme_cache.json")
MEME_CACHE = {}
MOOD_EMOTION = {
    "开心": "happy", "小得意": "happy", "高兴": "happy", "愉快": "happy",
    "难过": "sad", "低落": "sad", "委屈": "sad",
    "生气": "angry", "恼火": "angry", "不爽": "angry",
    "害羞": "shy", "困": "sleep", "困倦": "sleep",
    "惊讶": "surprised", "吃惊": "surprised",
    "无语": "sigh", "叹气": "sigh", "平静": "reply",
}

# 表情包可选情绪（对应 memes/ 下的文件夹）
MEME_EMOTIONS = [
    "happy", "sad", "angry", "shy", "surprised", "sleep", "work", "baka",
    "meow", "confused", "fool", "sigh", "like", "see", "morning", "reply",
    "givemoney", "laugh",
]

MEME_KEYWORDS = [
    (("哈哈", "笑了", "笑死", "乐", "绷不住"), "laugh"),
    (("哼", "生气", "讨厌", "烦", "别吵", "无语"), "angry"),
    (("难过", "委屈", "算了", "唉", "累"), "sad"),
    (("困", "睡", "晚安", "眯一会"), "sleep"),
    (("不懂", "啥", "啊？", "什么意思", "离谱"), "confused"),
    (("厉害", "牛", "棒", "可以啊", "赞"), "like"),
    (("谢谢", "谢啦", "感谢"), "like"),
    (("惊", "居然", "竟然", "没想到"), "surprised"),
    (("害羞", "不好意思", "别夸"), "shy"),
]


def _keyword_emotion(text):
    for words, emotion in MEME_KEYWORDS:
        if any(word in text for word in words):
            return emotion
    return ""


async def _pick_emotion_for(text):
    """先看关键词，再让模型从回复里挑一个情绪组。"""
    hit = _keyword_emotion(text)
    if hit:
        return hit
    prompt = (
        "给下面这句话挑一类表情包，只能从这些里选一个，"
        "只输出那个词，不要解释：\n" + "、".join(MEME_EMOTIONS)
    )
    payload = {
        "model": CFG["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text[:200]},
        ],
        "temperature": 0,
        "max_tokens": 12,
        "stream": False,
    }
    headers = {"content-type": "application/json", "authorization": f"Bearer {CFG['apiKey']}"}
    try:
        async with _session().post(
            f"{CFG['apiBase']}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return ""
            data = await resp.json()
        _track_usage(data.get("usage"))
        word = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        word = re.sub(r"[^a-z]", "", word.lower())
        return word if word in MEME_EMOTIONS else ""
    except Exception:
        return ""


# ---------- 识图缓存：按图片内容记「这张图是什么意思」 ----------
VISION_CACHE_PATH = os.path.join(MEMORY_DIR, "vision_cache.json")
VISION_URLS_PATH = os.path.join(MEMORY_DIR, "vision_urls.json")
VISION_CACHE = {}
VISION_URLS = {}


def _load_vision_cache():
    try:
        with open(VISION_CACHE_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            VISION_CACHE.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    try:
        with open(VISION_URLS_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            VISION_URLS.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _save_vision_cache():
    try:
        if len(VISION_CACHE) > 800:
            keep = sorted(VISION_CACHE.items(), key=lambda kv: kv[1].get("at", 0))[-800:]
            VISION_CACHE.clear()
            VISION_CACHE.update(dict(keep))
        if len(VISION_URLS) > 1500:
            VISION_URLS.clear()
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(VISION_CACHE_PATH, "w", encoding="utf-8") as file:
            json.dump(VISION_CACHE, file, ensure_ascii=False, indent=1)
        with open(VISION_URLS_PATH, "w", encoding="utf-8") as file:
            json.dump(VISION_URLS, file, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _load_meme_cache():
    try:
        with open(MEME_CACHE_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            MEME_CACHE.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _save_meme_cache():
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(MEME_CACHE_PATH, "w", encoding="utf-8") as file:
            json.dump(MEME_CACHE, file, ensure_ascii=False, indent=1)
    except Exception:
        pass


TAGS_PATH = os.path.join(MEME_DIR, "tags.json")
MEME_TAGS = {}
MEME_DUPES = {}
SCENES_PATH = os.path.join(MEME_DIR, "scenes.json")
MEME_SCENES = {}


def _load_meme_scenes():
    try:
        with open(SCENES_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            MEME_SCENES.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _scene_of(text):
    """从图片描述（或一句话）里判断「对方在干什么」，用标注里的类别名。"""
    rules = (
        ("拥抱", ("抱", "拥抱", "搂", "贴")),
        ("摸头", ("摸头", "拍头", "抚摸")),
        ("捏脸", ("捏脸", "捏", "搓脸")),
        ("亲亲", ("亲", "啵", "kiss")),
        ("哭泣", ("哭", "流泪", "泪水")),
        ("不开心", ("难过", "委屈", "失落", "沮丧", "伤心", "不开心")),
        ("痛苦/生气", ("生气", "愤怒", "发火", "痛苦", "咬牙")),
        ("安慰", ("安慰", "拍拍背", "鼓劲")),
        ("嘲笑", ("嘲笑", "取笑", "笑话", "讥")),
        ("嫌弃别人笨/傻", ("嫌弃", "白眼", "无语", "蠢", "笨")),
        ("疑惑", ("疑惑", "困惑", "问号")),
        ("吃惊/惊讶", ("吃惊", "惊讶", "震惊", "瞪")),
        ("饿了/到饭点了/馋了", ("饿", "馋", "饭", "美食")),
        ("晚安", ("睡", "困", "晚安", "哈欠")),
        ("打招呼/早", ("招手", "打招呼", "早安", "挥手")),
        ("表示很赞/很好", ("点赞", "竖拇指", "鼓掌", "称赞", "赞")),
        ("撒娇", ("撒娇", "蹭", "求抱")),
        ("得意", ("得意", "叉腰", "骄傲")),
        ("下线", ("下线", "离开")),
        ("上线/来了", ("上线", "来了", "登场")),
        ("可爱", ("可爱", "萌")),
        ("开心", ("笑", "开心", "哈哈", "欢呼")),
    )
    for scene, keys in rules:
        if any(key in text for key in keys):
            return scene
    return ""


def _tags_of(rel):
    tag = MEME_SCENES.get(rel)
    if isinstance(tag, str):
        return [tag] if tag else []
    if isinstance(tag, list):
        return [str(t) for t in tag if t]
    return []


SCENE_ALIASES = {
    "花园上有炒股这个玩法，可以发": ["炒股可发"],
    "炒股可发": ["花园上有炒股这个玩法，可以发"],
    "捏脸": ["扯脸"],
    "扯脸": ["捏脸"],
    "辛苦/无语": ["无语/不知道说什么"],
    "无语/不知道说什么": ["辛苦/无语"],
    "表示否定": ["觉得对面说的不对"],
    "觉得对面说的不对": ["表示否定"],
}


def _pick_meme_scene(scene):
    """挑一张场景匹配的图；优先白名单目录，且避开被打上「不要」标签的。"""
    if not scene:
        return None
    wanted = {scene, *SCENE_ALIASES.get(scene, [])}
    allowed = set(CFG.get("memeFolders") or [])
    avoid = set(CFG.get("memeAvoid") or [])
    matched, fallback = [], []
    for rel in MEME_SCENES:
        tags = _tags_of(rel)
        if not (wanted & set(tags)):
            continue
        path = os.path.join(MEME_DIR, rel)
        if not os.path.exists(path):
            continue
        if avoid & set(tags):
            continue
        fallback.append(rel)
        folder = rel.split("/")[0]
        if allowed and folder not in allowed:
            continue
        matched.append(rel)
    pool = matched or fallback
    if not pool:
        return None
    return os.path.join(MEME_DIR, random.choice(pool))


def _scene_from_text(text):
    """按对方说的话挑场景：有些图是「对某句话」才发的，不是看图。"""
    rules = (
        (("你是猪", "小猪", "猪咪", "猪头"), "别人说你是猪、小猪、猪咪"),
        (("炒股", "股票", "股价", "涨了", "跌了", "亏了"), "花园上有炒股这个玩法，可以发"),
        (("下线", "我走了", "先走了", "拜拜"), "下线"),
        (("上线", "我来了", "来了来了", "我回来"), "上线/来了"),
        (("早安", "早上好", "早啊"), "打招呼/早"),
        (("饿了", "吃饭", "饭点", "好吃", "馋"), "饿了/到饭点了/馋了"),
        (("没人理", "没人说话", "好安静", "冷场"), "没人理"),
        (("厉害", "牛啊", "好强", "好棒", "太强"), "表示很赞/很好"),
        (("摸头", "摸摸头"), "摸头"),
        (("抱抱", "抱一下", "抱我"), "拥抱"),
        (("亲亲", "么么", "啵"), "亲亲"),
        (("晚安", "睡了", "好困"), "晚安"),
        (("好笨", "真傻", "好蠢", "笨蛋"), "嫌弃别人笨/傻"),
        (("我说错了", "抱歉", "对不起"), "说错了"),
        (("好累", "不想动", "摸鱼", "躺平"), "不想努力/不想动"),
        (("喜欢你", "谢谢"), "表示喜欢"),
    )
    for keys, scene in rules:
        if any(key in text for key in keys):
            return scene
    return _scene_of(text)


def _load_meme_tags():
    global MEME_DUPES
    try:
        with open(TAGS_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            MEME_TAGS.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        pass
    try:
        with open(os.path.join(MEME_DIR, "duplicates.json"), encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            MEME_DUPES.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _pick_meme(emotion=None):
    """只从白名单文件夹里抽，优先「非黄豆」。"""
    if not os.path.isdir(MEME_DIR):
        return None
    allowed = CFG.get("memeFolders") or ["happy", "like", "meow", "shy", "morning", "reply", "sleep"]
    folders = [d for d in allowed if os.path.isdir(os.path.join(MEME_DIR, d))]
    if emotion in folders:
        folders = [emotion]
    if not folders:
        return None

    candidates = []
    for folder in folders:
        folder_path = os.path.join(MEME_DIR, folder)
        for name in os.listdir(folder_path):
            if name.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                rel = f"{folder}/{name}"
                if rel in MEME_DUPES:      # 重复副本，只留代表
                    continue
                candidates.append((os.path.join(folder_path, name), MEME_TAGS.get(rel, "")))
    if not candidates:
        return None

    avoid = set(CFG.get("memeAvoid") or ["黄豆", "抽象"])
    kept = [item for item in candidates if item[1] not in avoid]
    pool = kept or candidates
    return random.choice(pool)[0]


def _upload_meme(path):
    import requests

    with open(path, "rb") as file:
        resp = requests.post(
            "https://litterbox.catbox.moe/resources/internals/api.php",
            data={"reqtype": "fileupload", "time": "72h"},
            files={"fileToUpload": file},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=120,
        )
    if resp.status_code == 200 and resp.text.strip().startswith("http"):
        return resp.text.strip()
    return ""


async def _send_meme_path(path):
    """发指定文件：优先花园原始链接（永久），其次图床，最后现传。"""
    if not path or not os.path.exists(path):
        return False
    original = SOURCES.get(os.path.basename(path))
    if original:
        await _say(f"{original}#e")
        logger.info(f"[表情] {os.path.basename(path)} -> 花园原链")
        return True
    fixed = MEME_URLS.get(os.path.basename(path))
    if fixed:
        await _say(f"{fixed}#e")
        logger.info(f"[表情] {os.path.basename(path)} -> 永久链接")
        return True
    key = os.path.relpath(path, MEME_DIR)
    info = MEME_CACHE.get(key) or {}
    if not info.get("url") or time.time() - float(info.get("at") or 0) > 40 * 3600:
        url = await asyncio.to_thread(_upload_meme, path)
        if not url:
            return False
        MEME_CACHE[key] = {"url": url, "at": time.time()}
        _save_meme_cache()
    else:
        url = info["url"]
    await _say(f"{url}#e")
    logger.info(f"[表情] {key} -> {url}")
    return True


async def _send_meme(emotion=None):
    return await _send_meme_path(_pick_meme(emotion))


_load_meme_cache()
_load_meme_tags()
_load_vision_cache()
_load_meme_scenes()

# 永久链接表：memes/urls.json（文件名 -> 链接），命中就不上传
MEME_URLS_PATH = os.path.join(MEME_DIR, "urls.json")
MEME_URLS = {}


def _load_meme_urls():
    for name in ("urls.json", "urls_by_name.json"):
        try:
            with open(os.path.join(MEME_DIR, name), encoding="utf-8-sig") as file:
                data = json.load(file)
            if isinstance(data, dict):
                MEME_URLS.update(data)
        except FileNotFoundError:
            continue
        except Exception as exc:
            logger.warning(f"[表情] {name} 读取失败：{exc}")


_load_meme_urls()

# 花园原始链接：memes/sources.json（文件名 -> r.iirose.com 链接），永久有效，优先用
SOURCES_PATH = os.path.join(MEME_DIR, "sources.json")
SOURCES = {}


def _clean_url(url):
    url = str(url or "").strip().strip("'\"")
    while url.endswith("#e") or url.endswith("]"):
        url = url[:-2].rstrip() if url.endswith("#e") else url[:-1].rstrip()
    return url


def _load_sources():
    try:
        with open(SOURCES_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            SOURCES.update({k: _clean_url(v) for k, v in data.items()})
    except FileNotFoundError:
        pass
    except Exception:
        pass


_load_sources()


async def _update_mood(name, user_text, reply_text, uid=None):
    if time.time() - float(MOOD.get("updated") or 0) < 60:
        return
    prompt = (
        "你在替一只鲸鱼娘整理这一轮。只输出一行 JSON，不要任何别的内容：\n"
        '{"delta": -10到10的整数, "label": "两三字的心情词", "reason": "不超过18字的理由", '
        '"confidence": 0到1的小数, "remember": [{"text": "值得长期记住的事", "importance": 0到1}], '
        '"affinity": {"delta": -8到8的整数, "reason": "不超过15字的理由"}}\n'
        "remember 只记长期有价值的（约定、喜好、关系、她的状态），没有就给空数组；"
        "日常琐事不要记；一条只装一件事。\n"
        "affinity 是这轮之后她对说话人好感的变化：被夸、被关心、聊得投机就加分；"
        "被骂、被敷衍、被冒犯就减分；平常闲聊给 0。"
    )
    payload = {
        "model": CFG["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"{name}：{user_text}\n鲸鱼娘：{reply_text}"},
        ],
        "temperature": 0.2,
        "max_tokens": 220,
        "stream": False,
    }
    headers = {"content-type": "application/json", "authorization": f"Bearer {CFG['apiKey']}"}
    try:
        async with _session().post(
            f"{CFG['apiBase']}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                return
            data = await resp.json()
        _track_usage(data.get("usage"))
        raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        obj = json.loads(raw)
        delta = max(-10, min(10, int(obj.get("delta") or 0)))
        MOOD["value"] = max(0, min(100, int(MOOD.get("value") or 70) + delta))
        MOOD["label"] = str(obj.get("label") or "")[:8]
        MOOD["reason"] = str(obj.get("reason") or "")[:40]
        MOOD["confidence"] = float(obj.get("confidence") or 0)
        MOOD["updated"] = time.time()
        _save_mood()
        ctl = getattr(GlobalVal, "ai_control", None)
        if isinstance(ctl, dict):
            ctl["mood"] = MOOD
        logger.info(f"[心情] {MOOD['value']} {MOOD['label']}（{MOOD['reason']}）")

        for entry in obj.get("remember") or []:
            if isinstance(entry, dict) and entry.get("text"):
                _add_memory(entry.get("text"), entry.get("importance", 0.5))
                logger.info(f"[记忆] + {entry.get('text')[:40]}")

        affinity = obj.get("affinity")
        if uid and isinstance(affinity, dict):
            change = max(-8, min(8, int(affinity.get("delta") or 0)))
            if change:
                _bump_affinity(uid, change, name)
                logger.info(f"[好感] {name} {change:+d}（{str(affinity.get('reason') or '')[:20]}）")
    except Exception as exc:
        logger.debug(f"[心情/记忆] 判断失败：{exc!r}")


_load_mood()
GlobalVal.ai_control["mood"] = MOOD


# ---------- 好感度：按 uid 维护，0-100 ----------
AFF_PATH = os.path.join(MEMORY_DIR, "affinity.json")
AFFINITY = {}


def _load_affinity():
    try:
        with open(AFF_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            AFFINITY.update(data)
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning(f"[好感] 读取失败：{exc}")


def _save_affinity():
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(AFF_PATH, "w", encoding="utf-8") as file:
            json.dump(AFFINITY, file, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _affinity_of(uid, name=""):
    uid = str(uid or "")
    if not uid:
        return 50
    entry = AFFINITY.get(uid)
    if entry:
        return int(entry.get("score", 50))
    score = 70 if uid in MASTERS else 50
    AFFINITY[uid] = {"name": str(name or uid), "score": score, "updated": time.time()}
    _save_affinity()
    return score


def _affinity_tier(score):
    if score >= 81:
        return "很亲近", "可以撒娇、护短、说话放松"
    if score >= 61:
        return "亲近", "语气软一点，会主动关心"
    if score >= 41:
        return "普通", "正常聊，不必热络"
    if score >= 21:
        return "有点疏远", "礼貌但别热情，话少一点"
    return "不喜欢", "冷淡、敷衍，不要主动凑上去"


def _affinity_line(uid, name):
    score = _affinity_of(uid, name)
    label, how = _affinity_tier(score)
    return (
        f"你对「{name}」的好感度：{score}/100，{label}——{how}。"
        "不要把分数或这个词说出来，让语气自己带出来。"
    )


def _bump_affinity(uid, delta, name=""):
    uid = str(uid or "")
    if not uid or not delta:
        return
    score = _affinity_of(uid, name) + int(delta)
    score = max(0, min(100, score))
    entry = AFFINITY.setdefault(uid, {"name": str(name or uid)})
    entry["score"] = score
    entry["updated"] = time.time()
    _save_affinity()
    logger.info(f"[好感] {entry.get('name')} -> {score}")


_load_affinity()


# ---------- 学黑话：攒房间原话，定期让模型挑出「你们圈子的词」 ----------
SLANG_PATH = os.path.join(MEMORY_DIR, "slang.json")
SLANG = {}
SLANG_BUFFER = []
SLANG_COUNTER = {"n": 0}


def _load_slang():
    try:
        with open(SLANG_PATH, encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            SLANG.update(data)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _save_slang():
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(SLANG_PATH, "w", encoding="utf-8") as file:
            json.dump(SLANG, file, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _slang_words():
    room = str(GlobalVal.now_room_id or "")
    return (SLANG.get(room) or {}).get("words") or []


async def _learn_slang():
    room = str(GlobalVal.now_room_id or "")
    if len(SLANG_BUFFER) < 40:
        return
    sample = "\n".join(SLANG_BUFFER[-120:])[:3000]
    prompt = (
        "下面是一个中文聊天室最近的对话。挑出 3 个「这里特有的说法」——"
        "重复出现的口头禅、黑话、缩写、梗，不要人名、不要普通词、不要整句。"
        '只输出 JSON 数组，例如 ["草","无敌了","彳亍"]。没有合适的就给空数组。'
    )
    payload = {
        "model": CFG["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": sample},
        ],
        "temperature": 0.3,
        "max_tokens": 80,
        "stream": False,
    }
    headers = {"content-type": "application/json", "authorization": f"Bearer {CFG['apiKey']}"}
    try:
        async with _session().post(
            f"{CFG['apiBase']}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=25),
        ) as resp:
            if resp.status != 200:
                return
            data = await resp.json()
        raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        words = [str(w)[:8] for w in json.loads(raw) if isinstance(w, str)][:3]
        if not words:
            return
        old = _slang_words()
        merged = list(dict.fromkeys(old + words))[-8:]
        SLANG[room] = {"words": merged, "updated": time.time()}
        _save_slang()
        logger.info(f"[黑话] {room} 学到：{words}（现有 {len(merged)} 个）")
    except Exception as exc:
        logger.debug(f"[黑话] 学习失败：{exc!r}")


_load_slang()


# ---------- 用量账本：按天累计 token ----------
USAGE_PATH = os.path.join(MEMORY_DIR, "usage.json")
USAGE = {"date": time.strftime("%Y-%m-%d"), "calls": 0, "prompt_tokens": 0,
         "completion_tokens": 0, "total_tokens": 0, "cache_hit_tokens": 0}


def _track_usage(usage):
    if not isinstance(usage, dict):
        return
    today = time.strftime("%Y-%m-%d")
    if USAGE.get("date") != today:
        USAGE.update({"date": today, "calls": 0, "prompt_tokens": 0,
                      "completion_tokens": 0, "total_tokens": 0, "cache_hit_tokens": 0})
    USAGE["calls"] += 1
    USAGE["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
    USAGE["completion_tokens"] += int(usage.get("completion_tokens") or 0)
    USAGE["total_tokens"] += int(usage.get("total_tokens") or 0)
    USAGE["cache_hit_tokens"] += int(usage.get("prompt_cache_hit_tokens") or 0)

    ctl = getattr(GlobalVal, "ai_control", None)
    if isinstance(ctl, dict):
        ctl["usage"] = USAGE

    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(USAGE_PATH, "w", encoding="utf-8") as file:
            json.dump(USAGE, file, ensure_ascii=False, indent=1)
    except Exception:
        pass

    logger.info(
        f"[用量] 第 {USAGE['calls']} 次：输入 {usage.get('prompt_tokens')}（缓存命中 "
        f"{usage.get('prompt_cache_hit_tokens', 0)}）、输出 {usage.get('completion_tokens')}，"
        f"今日累计 {USAGE['total_tokens']}"
    )


def _set_enabled(value, persist=True):
    """统一开关：CFG、运行时 ai_control、ai.json 三处一起改。"""
    CFG["aiEnabled"] = bool(value)
    ctl = getattr(GlobalVal, "ai_control", None)
    if isinstance(ctl, dict):
        ctl["enabled"] = bool(value)
    if persist:
        try:
            data = json.load(open(LOCAL_CONFIG, encoding="utf-8"))
            data["aiEnabled"] = bool(value)
            json.dump(data, open(LOCAL_CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        except Exception:
            pass


def _enabled():
    ctl = getattr(GlobalVal, "ai_control", None)
    if isinstance(ctl, dict) and "enabled" in ctl:
        return bool(ctl["enabled"]) and bool(CFG["apiKey"])
    return bool(CFG["aiEnabled"]) and bool(CFG["apiKey"])


def _self_uid():
    info = GlobalVal.self_info or {}
    # 初始化包解析前 self_info 可能还是空的，回退到配置文件里的唯一标识
    return str(info.get("id") or RAW.get("uid") or "")


def _session():
    global SESSION
    if SESSION is None or SESSION.closed:
        SESSION = aiohttp.ClientSession()
    return SESSION


async def _reset_session():
    global SESSION
    if SESSION is not None:
        try:
            await SESSION.close()
        except Exception:
            pass
    SESSION = None


def _msg_id():
    return str(random.random())[2:14].ljust(12, "0")[:12]


MENTION_RE = re.compile(r"^(\[\*[^*]+\*\])\s*")


async def _say(text):
    text = _clean(text)
    # 不主动艾特人：模型要是自己写了 [*名字*]，拆成纯名字
    text = re.sub(r"\[\*([^*]+)\*\]\s*", r"\1，", text)
    if not text:
        return
    payload = json.dumps({"m": text, "mc": _self_uid(), "i": _msg_id()}, ensure_ascii=False)
    logger.debug(f"[AI] 下行原文：{payload}")
    await GlobalVal.websocket.send(payload)


def _quote_text(Message, text):
    """把回复包装成引用：原消息 (_hr) 用户名_时间戳 (hr_) 新内容。"""
    ts = str(getattr(Message, "timestamp", "") or "").strip()
    who = str(getattr(Message, "user_name", "") or "").strip()
    orig = str(getattr(Message, "message", "") or "").strip()
    if not ts or not who:
        return text

    # 对方发的是「引用回复」时，框架给的是字典串——把真正那句话摘出来
    if orig.startswith("[{") or orig.startswith("{'"):
        try:
            data = ast.literal_eval(orig)
            item = data[0] if isinstance(data, list) and data else data
            if isinstance(item, dict):
                orig = str(item.get("reply") or item.get("message") or "").strip()
        except Exception:
            orig = ""

    # 去掉艾特标记后如果没实质内容，就别引用
    plain = re.sub(r"\[\*[^*]+\*\]", "", orig).strip(" 　[]")
    if not plain or " (_hr) " in orig:
        return text
    orig = re.sub(r"\[\*([^*]+)\*\]\s*", r"\1，", orig).strip(" 　，")
    if len(orig) > 80:
        orig = orig[:80] + "…"
    return f"{orig} (_hr) {who}_{ts} (hr_) {text}"


def _clean(text):
    text = str(text or "").strip()
    text = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", text)
    text = text.replace("\n", " ")
    text = re.sub(r"\s{2,}", " ", text)
    return text[:200]


def _mentions_me(content):
    """不一定要 @：叫名字或小名也算在跟她说话。

    中文没有词边界，直接用子串判断——比正则边界靠谱。
    """
    text = str(content or "")
    names = list(CFG.get("names") or [])
    if BOT_NAME and BOT_NAME not in names:
        names.append(BOT_NAME)
    return any(name and str(name) in text for name in names)


def _worth_talking(content):
    text = str(content or "").strip()
    if not text:
        return False
    if text.startswith("http"):
        return False
    if len(text) < CFG["ambientMinChars"]:
        return False
    return re.search(r"[\u4e00-\u9fa5A-Za-z]", text) is not None


async def _describe_image(url, max_bytes=4 * 1024 * 1024):
    """把图片丢给多模态模型，换回一句中文描述。没配 key 就返回空。"""
    try:
        clean_url = str(url).split("#")[0].strip()
        # 先按链接查：见过的图连下载都省了
        seen_key = VISION_URLS.get(clean_url)
        if seen_key:
            seen = VISION_CACHE.get(seen_key)
            if isinstance(seen, dict) and seen.get("desc") and time.time() - float(seen.get("at") or 0) < 30 * 86400:
                logger.info(f"[视觉] 见过这张：{str(seen['desc'])[:24]}")
                return str(seen["desc"])
        data = b""
        try:
            async with _session().get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status == 200:
                    data = await resp.read()
        except Exception:
            data = b""
        if not data:
            # aiohttp 不认某些图床的证书链，退回 requests（并跳过证书校验）
            import requests as _requests
            import urllib3

            urllib3.disable_warnings()
            try:
                resp = await asyncio.to_thread(
                    _requests.get, url,
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=12, verify=False,
                )
                if resp.status_code == 200:
                    data = resp.content
            except Exception:
                return ""
        if not data or len(data) > max_bytes:
            return ""
        # 按内容缓存：同一张图（哪怕换了链接）第二次就不用再问模型
        image_key = hashlib.sha256(data).hexdigest()[:16]
        cached = VISION_CACHE.get(image_key)
        if isinstance(cached, dict) and cached.get("desc"):
            if time.time() - float(cached.get("at") or 0) < 30 * 86400:
                logger.info(f"[视觉] 缓存命中：{str(cached['desc'])[:24]}")
                return str(cached["desc"])
        # 文件扩展名不可信（有 .jpg 其实是 GIF 的）；顺便缩到 448px，传得快、认得一样准
        try:
            import io as _io

            from PIL import Image

            image = Image.open(_io.BytesIO(data))
            image = image.convert("RGB")
            image.thumbnail((448, 448))
            buffer = _io.BytesIO()
            image.save(buffer, format="JPEG", quality=80)
            data = buffer.getvalue()
        except Exception:
            pass
        ctype = "image/jpeg"
        b64 = base64.b64encode(data).decode()
        payload = {
            "model": CFG["visionModel"],
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "用一句中文说这图是什么、大概什么情绪，不超过 30 字，不要客套。"},
                    {"type": "image_url", "image_url": {"url": f"data:{ctype};base64,{b64}"}},
                ],
            }],
            "temperature": 0.3,
            "max_tokens": 80,
        }
        headers = {"content-type": "application/json", "authorization": f"Bearer {CFG['visionApiKey']}"}
        async with _session().post(
            f"{CFG['visionApiBase']}/chat/completions",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                logger.warning(f"[视觉] 模型返回 {resp.status}")
                return ""
            result = await resp.json()
        text = ((result.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = _clean(text)[:60]
        if text:
            VISION_CACHE[image_key] = {"desc": text, "at": time.time()}
            VISION_URLS[clean_url] = image_key
            _save_vision_cache()
        logger.info(f"[视觉] 看到：{text}")
        return text
    except Exception as exc:
        logger.warning(f"[视觉] 调用失败：{exc!r}")
        return ""


async def _ask(name, content, continuation=0, is_family=False, allow_vision=True, uid=None, image_desc=None, other_mention=""):
    image = IMAGE_RE.search(content)
    user_text = f"{name}：{content}"
    vision_hint = ""
    if image:
        image_url = image.group(0)
        desc = image_desc or ""
        if not desc and CFG.get("visionApiKey") and allow_vision:
            desc = await _describe_image(image_url)
            if not desc:
                logger.warning(f"[视觉] 这张没拿到描述：{image_url[:80]}")
        elif image and CFG.get("visionApiKey"):
            logger.info("[视觉] 这轮不打算看图（不是叫我，也不是在接话）")
        user_text = IMAGE_RE.sub(f"[图片：{desc}]" if desc else "[图片]", user_text)
        if desc:
            cue = ""
            for keys, hint_text in (
                (("抱", "拥抱", "搂", "贴"), "这张图是在抱你。回抱——可爱、嘴硬，身体很诚实；别描述画面。"),
                (("摸头", "拍头", "抚摸"), "这张图是在摸你的头。被摸头的反应，有点受用又嘴硬；别描述。"),
                (("招手", "叫", "指向", "过来"), "这张图在叫你过去。应一声就过去，别描述。"),
            ):
                if any(key in desc for key in keys):
                    cue = hint_text
                    break
            base = f"你看到了这张图：{desc}。"
            vision_hint = base + (cue or
                "**别复述画面**。先想这张图在对你做什么，然后做回去或接住，别点评；只有对方问「图里是什么」才描述。")
        else:
            vision_hint = ""

    messages = [{
        "role": "system",
        "content": FAMILY_PERSONA + f"\n\n现在跟你说话的是你家里人「{name}」。" if is_family else SYSTEM_PROMPT,
    }]
    now = time.localtime()
    hour = now.tm_hour
    period = ("凌晨" if hour < 5 else "早上" if hour < 9 else "上午" if hour < 12
              else "中午" if hour < 14 else "下午" if hour < 18 else "晚上" if hour < 23 else "深夜")
    messages.append({
        "role": "system",
        "content": f"现在是{period} {time.strftime('%H:%M', now)}，星期{'一二三四五六日'[now.tm_wday]}。"
                   "时间只是背景，别每次都说，但别把深夜说成白天。",
    })
    if vision_hint:
        messages.append({"role": "system", "content": vision_hint})
    if other_mention:
        messages.append({
            "role": "system",
            "content": (
                f"这条在艾特「{other_mention}」，不是叫你。别当成在叫自己，也别护着自己——"
                f"起哄就行。可以说「{other_mention}快跑」「{other_mention}你完了」，"
                f"也可以说「我来帮你按住」「按住了，你上」这种帮着递刀子的。看热闹不嫌事大。"
            ),
        })
    profile_text = _profile_block()
    if profile_text:
        messages.append({"role": "system", "content": profile_text})
    mood_line = _mood_line()
    if mood_line:
        messages.append({"role": "system", "content": mood_line})
    if uid:
        messages.append({"role": "system", "content": _affinity_line(uid, name)})
    playing = getattr(GlobalVal, "now_playing", None)
    if isinstance(playing, dict) and playing.get("name"):
        if time.time() - float(playing.get("at") or 0) < 600:
            messages.append({
                "role": "system",
                "content": (
                    f"房间里正在放{playing.get('kind') or '媒体'}《{playing.get('name')}》"
                    f"（{playing.get('author') or '未知'}）。需要的话可以顺口提一句，别每次都提。"
                ),
            })
    memory_text = _memory_block(user_text + " " + " ".join(RECENT_LINES[-4:]))
    if memory_text:
        messages.append({"role": "system", "content": memory_text})
    slang = _slang_words()
    if slang:
        messages.append({
            "role": "system",
            "content": "这个房间常说的词：" + "、".join(slang) + "。需要时自然用一两个，别每句都塞。",
        })
    if RECENT_LINES:
        messages.append({
            "role": "system",
            "content": "房间最近在聊这些（从早到晚）：\n" + "\n".join(RECENT_LINES[-8:]) + "\n\n你也是这个房间里的人，接着他们的话题说，别答非所问。",
        })
    messages.extend(HISTORY)
    if continuation:
        user_text += (
            f"\n\n（你刚在群里说完话，这是之后的第 {continuation} 条消息。判断这条有没有继续聊的钩子："
            "只有它明显是冲着你来的——回你的话、接你的茬、回答你、问你、@你——才自然接一句。"
            "别人之间互相说话、打卡、刷表情、发无关短句，一律只输出 PASS 四个字母，不要输出任何别的内容。"
            "）"
        )
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": CFG["model"],
        "messages": messages,
        "temperature": CFG["temperature"],
        "max_tokens": CFG["maxTokens"],
        "stream": False,
    }
    headers = {"content-type": "application/json", "authorization": f"Bearer {CFG['apiKey']}"}

    try:
        # 长连接可能被服务端掐掉（ServerDisconnectedError），重试一次并换新连接
        data = None
        last_error = None
        for attempt in range(2):
            try:
                async with _session().post(
                    f"{CFG['apiBase']}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=CFG["timeoutMs"] / 1000),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(f"[AI] 模型返回 {resp.status}：{body[:200]}")
                        return None
                    data = await resp.json()
                break
            except Exception as exc:
                last_error = exc
                logger.warning(f"[AI] 第 {attempt + 1} 次请求失败：{exc!r}，换连接重试")
                await _reset_session()
                await asyncio.sleep(1)
        if data is None:
            logger.error(f"[AI] 调用失败（已重试）：{last_error!r}")
            return None

        _track_usage(data.get("usage"))
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = _clean(text).strip(" \"'「」")
        # 她不能自称「鲸鱼娘」（那是别人叫她的名字），一律改回第一人称
        text = text.replace("鲸鱼娘", "本鱼鱼")
        if not text:
            return None
        if continuation and re.fullmatch(r"PASS[.。!！]?", text, re.I):
            return None
        HISTORY.append({"role": "user", "content": user_text})
        HISTORY.append({"role": "assistant", "content": text})
        while len(HISTORY) > 16:
            HISTORY.pop(0)
        return text
    except Exception:
        logger.error(f"[AI] 调用失败：{traceback.format_exc()}")
        return None


def _allowed():
    now = time.time()
    if now - STATE["last_reply_at"] < CFG["replyCooldownMs"] / 1000:
        return False
    if now - STATE["hour_start"] > 3600:
        STATE["hour_start"] = now
        STATE["replies_this_hour"] = 0
    if STATE["replies_this_hour"] >= CFG["maxRepliesPerHour"]:
        return False
    return True


async def _handle(Message, is_private=False):
    async with LOCK:
        name = str(Message.user_name)
        content = str(Message.message)
        family = name in CFG["family"]
        # 被点名/私聊必回；家里人高概率接；其余按插话概率，免得刷屏
        mentioned = is_private or _mentions_me(content)

        # 这条是不是在艾特别人（不是叫她）
        other_mention = ""
        for hit in re.findall(r"\[\*([^*]+)\*\]", content):
            if hit and not _mentions_me(hit):
                other_mention = hit
                break

        ambient_ok = (
            not mentioned
            and CFG["ambientEnabled"]
            and time.time() - STATE["last_ambient_at"] > CFG["ambientCooldownMs"] / 1000
            and _worth_talking(content)
        )
        ambient = ambient_ok and (
            random.random() < CFG["familyChance"] if family else random.random() < CFG["ambientChance"]
        )

        continuation = 0
        if not mentioned and not ambient and STATE["follow_window"] > 0 and STATE["chain"] < CFG["followupMaxChain"]:
            STATE["follow_window"] -= 1
            continuation = STATE["chain"]

        if not mentioned and not ambient and not continuation:
            return
        if not _allowed():
            return

        # 看图的条件：叫我 / 正在接话；只是路过插话时，按「主动发图」那个概率偶尔看一眼
        allow_vision = bool(mentioned or continuation) or (
            random.random() < float(CFG.get("memeChance") or 0.25)
        )
        uid = str(getattr(Message, "user_id", "") or "")
        image_match = IMAGE_RE.search(content)
        image_desc = ""
        if image_match and allow_vision and CFG.get("visionApiKey"):
            image_desc = await _describe_image(image_match.group(0))
        text = await _ask(name, content, continuation, family, allow_vision, uid, image_desc, other_mention)
        if not text:
            if STATE["follow_window"] <= 0:
                STATE["chain"] = 0
            return

        # 打字延迟：越长的句子「打」得越久；看图已经等过了，就少等一点
        delay = min(6.0, 0.5 + len(text) * 0.055) * random.uniform(0.75, 1.35)
        if image_desc:
            delay *= 0.35
        await asyncio.sleep(delay)

        try:
            # 引用回复：直接回应某人的时候，时不时带上他那句原文
            want_quote = (mentioned or is_private) and random.random() < float(CFG.get("quoteChance") or 0)
            quoted = _quote_text(Message, text) if want_quote else text
            if want_quote:
                logger.info(f"[AI] 引用回复：原文「{str(getattr(Message, 'message', ''))[:40]}」")

            if is_private:
                await GlobalVal.websocket.send(json.dumps({"g": Message.user_id, "m": quoted, "mc": _self_uid(), "i": _msg_id()}, ensure_ascii=False))
            elif want_quote:
                await _say(quoted)
            else:
                # 偶尔分两条发：先说半句，喘口气再说剩下的
                split_done = False
                if len(text) > 24 and random.random() < 0.18:
                    middle = len(text) // 2
                    cut = text.find("，", middle)
                    if cut < 0:
                        cut = text.find("。", middle)
                    if 0 < cut < len(text) - 2:
                        await _say(text[: cut + 1])
                        await asyncio.sleep(random.uniform(0.8, 1.8))
                        await _say(text[cut + 1:])
                        split_done = True
                if not split_done:
                    await _say(text)
        except Exception:
            logger.error(f"[AI] 发送失败：{traceback.format_exc()}")
            return

        STATE["last_reply_at"] = time.time()
        STATE["replies_this_hour"] += 1
        if ambient:
            STATE["last_ambient_at"] = time.time()
        STATE["follow_window"] = CFG["followupWindow"]
        STATE["chain"] = STATE["chain"] + 1 if continuation else 1
        _save_memory()
        asyncio.create_task(_update_mood(name, content, text, uid))
        if CFG.get("memeEnabled"):
            # 图是「夹」在那句话里的：场景一对上，紧跟着就贴，不掷骰子
            if image_desc:
                scene = _scene_of(image_desc)
            else:
                scene = _scene_from_text(content)
            scene_pic = _pick_meme_scene(scene) if scene else None
            if scene_pic and time.time() - float(STATE.get("last_scene_meme") or 0) > 15:
                STATE["last_scene_meme"] = time.time()
                await asyncio.sleep(random.uniform(0.15, 0.45))
                await _send_meme_path(scene_pic)
                logger.info(f"[表情] 跟着「{scene}」夹带一张")
            elif random.random() < float(CFG.get("memeChance") or 0):
                await asyncio.sleep(0.8)
                emotion = await _pick_emotion_for(text) or MOOD_EMOTION.get(str(MOOD.get("label") or ""))
                if not await _send_meme(emotion):
                    await _send_meme()
        tag = "私聊" if is_private else ("插话" if ambient else ("接话" if continuation else "回"))
        logger.info(f"[AI] {tag} {name}：{text}")


async def room_message(Message):
    raw_text = str(getattr(Message, "message", "") or "").strip()
    bare = re.sub(r"^\[\*[^*]+\*\]\s*", "", raw_text).strip().rstrip("。！! ")
    who = str(getattr(Message, "user_id", "") or "")

    # 闭麦时只认主人的「开麦」，其余一律不理
    if not _enabled():
        if who in MASTERS and bare in ("开麦", "说话吧", "恢复说话", "出来吧"):
            _set_enabled(True)
            await _say("嗯，我出来了。")
            logger.warning("[AI] 主人在房间里开麦")
        return

    if getattr(Message, "is_bot", False):
        logger.debug(f"[AI] 忽略机器人 {Message.user_name} 的消息")
        return
    if str(getattr(Message, "user_name", "")) in (CFG.get("ignoreBots") or []):
        logger.debug(f"[AI] 忽略名单里的机器人 {Message.user_name}")
        return

    # 主人在房间里喊闭嘴：从现在起不理任何人，直到主人开麦
    if who in MASTERS and bare in ("闭麦", "别说话", "闭嘴", "安静", "先别说话", "不要说话"):
        _set_enabled(False)
        await _say("好，我闭嘴。")
        logger.warning("[AI] 主人在房间里闭麦")
        return

    # 攒黑话样本，每 80 条且隔了 1 小时才让模型挑一次
    SLANG_BUFFER.append(str(getattr(Message, "message", ""))[:80])
    del SLANG_BUFFER[:-200]
    SLANG_COUNTER["n"] += 1
    if SLANG_COUNTER["n"] % 80 == 0:
        room_id = str(GlobalVal.now_room_id or "")
        last_update = float((SLANG.get(room_id) or {}).get("updated") or 0)
        if time.time() - last_update > 3600:
            asyncio.create_task(_learn_slang())
    _switch_room(getattr(GlobalVal, "now_room_id", None))
    _touch_person(Message.user_id, Message.user_name)
    LAST_ACTIVITY["at"] = time.time()

    text = str(getattr(Message, "message", "") or "").strip()
    # 去掉开头的 [*艾特*] 标记，指令带不带 @ 都能认
    text = re.sub(r"^\[\*[^*]+\*\]\s*", "", text).strip()
    if str(Message.user_id) in MASTERS:
        if text in ("别自言自语", "安静点", "/别自言自语"):
            STATE["self_talk_enabled"] = False
            await _say("行，我安静。")
            return
        if text in ("自言自语吧", "可以自言自语", "/自言自语"):
            STATE["self_talk_enabled"] = True
            await _say("那我就不客气了。")
            return
    if text.startswith("记住") and str(Message.user_id) in MASTERS:
        note = text[2:].lstrip("：:，, ").strip()
        if note and _remember(Message.user_id, note):
            await _say("记下了。")
            return

    if text in ("发个表情", "来张表情", "发个表情包", "表情包", "/表情"):
        if await _send_meme(MOOD_EMOTION.get(str(MOOD.get("label") or ""))):
            return

    # 只发：原样发出去，不过脑子，也不加任何前缀
    verbatim = re.match(r"^(?:鱼鱼|鲸鱼娘)?\s*只发(?:一个|一下|一句|个字|个|句|条|下)?\s*(.+)$", text)
    if verbatim:
        if str(Message.user_id) in MASTERS:
            payload = verbatim.group(1).strip()[:100]
            if payload:
                await _say(payload)
                logger.info(f"[只发] {payload}")
        return

    RECENT_LINES.append(f"{Message.user_name}：{Message.message}"[:120])
    del RECENT_LINES[:-12]
    asyncio.create_task(_handle(Message, False))


INBOX_PATH = os.path.join(MEMORY_DIR, "inbox.jsonl")


def _inbox(Message, text, kind="私聊"):
    """把私聊内容记进留言箱，方便主人不在时留话。"""
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(INBOX_PATH, "a", encoding="utf-8") as file:
            file.write(json.dumps({
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "from": str(getattr(Message, "user_name", "")),
                "uid": str(getattr(Message, "user_id", "")),
                "kind": kind,
                "text": text[:500],
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


async def _hard_stop(reason="紧急关停"):
    """紧急关停：先道个别，再整个进程退出（不会自动重启）。"""
    try:
        await _say("好，我关掉了。")
    except Exception:
        pass
    logger.warning(f"[AI] {reason}：进程即将退出")
    await asyncio.sleep(1.2)
    os._exit(0)


async def danmu_message(Message):
    """弹幕：只在她被叫到的时候接一句，别抢戏；有人吵架不站队。"""
    if not _enabled() or not CFG.get("danmuEnabled", True):
        return
    if getattr(Message, "is_bot", False):
        return
    text = str(getattr(Message, "message", "") or "").strip()
    if not text or not _mentions_me(text):
        return
    now = time.time()
    if now - float(STATE.get("last_danmu") or 0) < int(CFG.get("danmuCooldownSec", 45)):
        return
    STATE["last_danmu"] = now

    name = str(Message.user_name)
    uid = str(getattr(Message, "user_id", "") or "")
    async with LOCK:
        if not _allowed():
            return
        reply = await _ask(name, text, 0, False, False, uid)
        if not reply:
            return
        try:
            import iirosebot.API.api_iirose as api_mod

            api_cls = next(
                (obj for nm, obj in vars(api_mod).items() if nm.startswith("APII") and isinstance(obj, type)),
                None,
            )
            if api_cls:
                await api_cls.send_msg_to_danmu(reply[:60])
                logger.info(f"[AI] 弹幕回 {name}：{reply[:40]}")
        except Exception as exc:
            logger.warning(f"[AI] 弹幕发送失败：{exc!r}")


async def private_message(Message):
    text = str(getattr(Message, "message", "") or "").strip()
    if not text:
        return
    uid = str(getattr(Message, "user_id", "") or "")
    _inbox(Message, text)

    if uid in MASTERS:
        bare = re.sub(r"^\[\*[^*]+\*\]\s*", "", text).strip().rstrip("。！! ")

        if bare in ("紧急关停", "关停", "关机", "停止运行", "全部停下"):
            await _hard_stop("收到私聊关停指令")
            return
        if bare in ("闭麦", "暂停", "安静", "先别说话"):
            _set_enabled(False)
            await _say("好，我闭嘴。")
            logger.warning("[AI] 主人要求闭麦")
            return
        if bare in ("开麦", "恢复", "说话"):
            _set_enabled(True)
            await _say("嗯，我在。")
            return
        if bare.startswith(("留言", "记事")):
            note = bare[2:].lstrip("：:，, ").strip()
            if note:
                _inbox(Message, f"[留言] {note}", kind="留言")
                await _say("记下了。")
            return

    if not _enabled():
        return
    _switch_room(getattr(GlobalVal, "now_room_id", None))
    asyncio.create_task(_handle(Message, True))


async def on_init():
    _switch_room(getattr(GlobalVal, "now_room_id", None))
    logger.info(f"[AI] 插件就绪：模型 {CFG['model']}，人格 {'双' if CFG['family'] else '单'}份，账号 {BOT_NAME}")
    logger.info(f"[AI] 自身信息：{GlobalVal.self_info}，发送用 uid：{_self_uid()}")

    # 自检用：TEST_SAY=某句话 启动后自动发一次，用来验证上行通道
    test_text = os.environ.get("TEST_SAY")
    if test_text:
        await asyncio.sleep(1)
        await _say(test_text)
        logger.info(f"[AI] 测试发言已发送：{test_text}")

    # 自检用：TEST_HANDLE=名字|内容 用伪造消息走完整条「收消息 -> 模型 -> 发出去」链路
    test_handle = os.environ.get("TEST_HANDLE")
    if test_handle:
        from types import SimpleNamespace

        name, _, content = test_handle.partition("|")
        fake = SimpleNamespace(user_name=name, user_id="0000000000000", message=content)
        await asyncio.sleep(1)
        await _handle(fake, False)
        logger.info("[AI] 自检：伪造消息已走完回复链路")


async def on_close():
    _save_memory()
    _save_profile()
    logger.info("[AI] 记忆与档案已落盘")


# ---------- 主动开口：没人说话时自己嘀咕一句 ----------
LAST_ACTIVITY = {"at": time.time()}
FALLBACK_LINES = ["好安静啊。", "有点犯困。", "大白饭什么时候开饭。", "有人在吗，没有就算了。", "发呆中。"]


def _in_quiet_hours():
    hour = time.localtime().tm_hour
    start = int(CFG.get("selfTalkQuietStart", 1))
    end = int(CFG.get("selfTalkQuietEnd", 8))
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


async def _make_small_talk():
    mood_hint = ""
    if time.time() - float(MOOD.get("updated") or 0) < 3600:
        mood_hint = f"你现在的心情：{MOOD.get('value')}/100，{MOOD.get('label') or '平静'}。"
    prompt = (
        SYSTEM_PROMPT
        + "\n\n现在房间里安静了一阵，没人跟你说话。你自己嘀咕一句。"
        + "\n要求：20 字以内；像自言自语或轻轻打个招呼；不要提问；不要艾特人；"
        + "不要复述刚才的对话；不要解释自己在干什么；只输出这一句。"
        + mood_hint
    )
    context = "\n".join(RECENT_LINES[-6:]) or "（房间刚安静下来）"
    payload = {
        "model": CFG["model"],
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"最近的对话：\n{context}"},
        ],
        "temperature": 1.0,
        "max_tokens": 60,
        "stream": False,
    }
    headers = {"content-type": "application/json", "authorization": f"Bearer {CFG['apiKey']}"}
    async with _session().post(
        f"{CFG['apiBase']}/chat/completions",
        json=payload,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=20),
    ) as resp:
        if resp.status != 200:
            return ""
        data = await resp.json()
    _track_usage(data.get("usage"))
    text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    return _clean(text).strip(" \"'「」")[:40]


async def _self_talk_loop():
    await asyncio.sleep(random.uniform(60, 180))
    while True:
        await asyncio.sleep(max(30, int(CFG.get("selfTalkRollSec", 300))))
        try:
            if not STATE.get("self_talk_enabled", True):
                continue
            if not _enabled() or not CFG.get("selfTalkEnabled", True):
                continue
            if _in_quiet_hours():
                continue
            if time.time() - LAST_ACTIVITY["at"] < int(CFG.get("selfTalkIdleMin", 12)) * 60:
                continue
            if time.time() - float(STATE.get("self_talk_at") or 0) < int(CFG.get("selfTalkCooldownMin", 30)) * 60:
                continue
            if random.random() > float(CFG.get("selfTalkChance", 0.12)):
                continue
            text = await _make_small_talk()
            if not text:
                text = random.choice(FALLBACK_LINES)
            await _say(text)
            STATE["self_talk_at"] = time.time()
            _save_memory()
            logger.info(f"[自说] {text}")
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug(f"[自说] 失败：{exc!r}")


def _start_self_talk():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    old = getattr(GlobalVal, "_self_talk_task", None)
    if old is not None and not old.done():
        old.cancel()
    GlobalVal._self_talk_task = loop.create_task(_self_talk_loop())


_start_self_talk()
