# -*- coding: utf-8 -*-
"""
ربات هوشمند مدیریت کانفیگ و پروکسی  |  مخزن: @MakhZanSam  ->  مقصد: @SamTvVpn
فقط با توکن ربات کار می‌کند (بدون API_ID).

کارکرد:
  1) هر کانفیگ/پروکسی که تو مخزن بذاری شناسایی می‌شود (لینک مخفی، دکمه و فایل txt هم خوانده می‌شود)،
     اسم کانفیگ‌ها به @SamTvVpn عوض می‌شود و تکراری‌ها حذف می‌شوند. همه‌چیز فوری است؛ هیچ تستی ندارد.
  2) چند ثانیه بعد از آخرین پست، «مرکز کنترل» پایین کانال مخزن می‌آید.
  3) مرکز کنترل:
       🚀 ارسال با سرعت دلخواه (۱۰ث / ۳۰ث / ۱د / ۵د)  یا  فقط N تای اول
       📋 صف ارسال: ساعت دقیق هر پست + شمارش معکوس + پیش‌نمایش عین پیام
       ⏸ مکث/ادامه • ⏭ ارسال بعدی همین الان • 🗑 حذف بعدی • 🔀 بُر زدن • ⏱ تغییر سرعت صف
       🤖 حالت خودکار (هر چیز جدید خودش وارد صف می‌شود)
       📈 آمار ۷ روز اخیر • 📤 خروجی استخر و صف به‌صورت فایل txt
  4) همه‌چیز تو state.json ذخیره می‌شود؛ با خاموش/روشن شدن ربات چیزی از دست نمی‌رود.

دستورها (تو مخزن بنویس؛ ربات پاکش می‌کند):  /panel (پنل)   /status (وضعیت)
"""

import asyncio
import base64
import hashlib
import html
import json
import logging
import random
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    MessageEntity,
    Update,
)
from telegram.error import BadRequest, RetryAfter, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ───────────────────────── تنظیمات ─────────────────────────
BOT_TOKEN = "8754381608:AAGcHV7jlnXV8_QbpSDcdMgc76dA5s4SlAo"

SOURCE_ID = -1004489320526   # @MakhZanSam (مخزن)
TARGET_ID = -1001860049855   # @SamTvVpn
TARGET_USERNAME = "@SamTvVpn"

NEW_NAME = "@SamTvVpn"       # اسمی که روی کانفیگ‌ها می‌نشیند
SPEEDS = [10, 30, 60, 300]   # گزینه‌های سرعت ارسال (ثانیه)
COUNTS = [10, 25, 50]        # گزینه‌های «فقط N تای اول»
PAGE_SIZE = 8                # تعداد ردیف هر صفحه صف
MIN_GAP = 3                  # حداقل فاصله دو ارسال پشت‌سرهم (ضد فلود)
PANEL_DELAY = 2              # بعد از آخرین پست چند ثانیه صبر کند تا پنل بیاید
PANEL_MAX_WAIT = 5           # حتی اگر پست‌ها ادامه داشت، حداکثر بعد از این مدت پنل بیاید
LIVE_EVERY = 8               # هر چند ثانیه پنل زنده بروز شود
PREVIEW_TTL = 45             # پیش‌نمایش بعد از چند ثانیه پاک شود
DEFAULT_AUTO_EVERY = 60      # سرعت پیش‌فرض حالت خودکار

TZ = timezone(timedelta(hours=3, minutes=30))   # تهران
BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
STARTED = time.time()

# قالب پیام
EMOJI_HEAD = ("5983154648968598148", "5803378592247190638")
EMOJI_TAIL = "5866283009681921162"
PLACEHOLDER = "⭐"
# False = کدها دقیقاً به‌صورت متن [کد] ارسال می‌شوند (برای رباتی که کد را به ایموجی تبدیل می‌کند)
# True  = کدها به‌صورت ایموجی پریمیوم (custom emoji) ارسال می‌شوند
USE_CUSTOM_EMOJI = False
# ────────────────────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("config-bot")

CONFIG_RE = re.compile(
    r"(?:vmess|vless|trojan|ssr|ss|hysteria2|hysteria|hy2|tuic|wireguard|socks)"
    r"://[^\s<>\"'`]+",
    re.IGNORECASE,
)
PROXY_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(?:proxy|socks)\?[^\s<>\"'`]+"
    r"|tg://(?:proxy|socks)\?[^\s<>\"'`]+",
    re.IGNORECASE,
)

KIND_FA = {"cfg": "کانفیگ", "prx": "پروکسی"}
KIND_ICON = {"cfg": "📦", "prx": "🔌"}
KINDS = ("cfg", "prx")
LINE = "━━━━━━━━━━━━━━"
FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
MONTHS = ["ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
          "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر"]
SPARK = "▁▂▃▄▅▆▇█"


def fa(v) -> str:
    return str(v).translate(FA_DIGITS)


def fmt_clock(ts: float, secs: bool = False) -> str:
    return fa(datetime.fromtimestamp(ts, TZ).strftime("%H:%M:%S" if secs else "%H:%M"))


def fmt_when(ts: float) -> str:
    d = datetime.fromtimestamp(ts, TZ)
    if d.date() == datetime.now(TZ).date():
        return fa(d.strftime("%H:%M:%S"))
    return fa(f"{d.day} {MONTHS[d.month - 1]} {d:%H:%M}")


def fmt_dur(sec: float) -> str:
    sec = int(max(0, sec))
    if sec < 60:
        return f"{fa(sec)} ثانیه"
    m = round(sec / 60)
    if m < 60:
        return f"{fa(m)} دقیقه"
    h, m = divmod(m, 60)
    return f"{fa(h)} ساعت" + (f" و {fa(m)} دقیقه" if m else "")


def fmt_cd(sec: float) -> str:
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return fa(f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}")


def bar(frac: float, n: int = 10) -> str:
    k = round(max(0.0, min(1.0, frac)) * n)
    return "▰" * k + "▱" * (n - k)


class Button:
    @staticmethod
    def inline(text: str, data) -> InlineKeyboardButton:
        return InlineKeyboardButton(text, callback_data=data)

    @staticmethod
    def url(text: str, url: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text, url=url)


def markup(rows):
    return InlineKeyboardMarkup(rows) if rows else None


# ═════════════════════ شناسایی کانفیگ و پروکسی ═════════════════════
def _b64decode(s: str) -> bytes:
    s = s.strip()
    s += "=" * (-len(s) % 4)
    try:
        return base64.b64decode(s)
    except Exception:
        return base64.urlsafe_b64decode(s)


def rename_config(link: str) -> str | None:
    link = link.rstrip(".,;)،")
    if link.lower().startswith("vmess://"):
        try:
            data = json.loads(_b64decode(link[len("vmess://"):].split("#", 1)[0]).decode("utf-8"))
        except Exception:
            return None
        data["ps"] = NEW_NAME
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return "vmess://" + base64.b64encode(raw.encode("utf-8")).decode()
    return f"{link.split('#', 1)[0]}#{quote(NEW_NAME, safe='@')}"


def parse_proxy(raw: str) -> dict | None:
    url = html.unescape(raw).rstrip(".,;)،")
    if not re.match(r"(?i)^(https?|tg)://", url):
        url = "https://" + url
    sp = urlsplit(url)
    is_socks = "socks" in (sp.netloc + sp.path).lower()
    q = {k.lower(): v[0] for k, v in parse_qs(sp.query).items() if v}
    server, port = q.get("server", "").strip(), q.get("port", "").strip()
    if not server or not port.isdigit() or not 0 < int(port) < 65536:
        return None
    port = int(port)
    if not is_socks:
        secret = q.get("secret", "").strip()
        if not secret:
            return None
        s = secret.lower()
        ptype = "MTProto • FakeTLS" if s.startswith("ee") else (
            "MTProto • Secure" if s.startswith("dd") else "MTProto")
        return {"kind": "prx", "key": f"prx|{server.lower()}|{port}|{s}", "d": {
            "v": f"https://t.me/proxy?server={server}&port={port}&secret={secret}",
            "type": ptype, "server": server, "port": port, "secret": secret}}
    user, pw = q.get("user", ""), q.get("pass", q.get("password", ""))
    canon = f"https://t.me/socks?server={server}&port={port}"
    if user:
        canon += f"&user={quote(user)}&pass={quote(pw)}"
    return {"kind": "prx", "key": f"prx|{server.lower()}|{port}|socks|{user}", "d": {
        "v": canon, "type": "SOCKS5", "server": server, "port": port, "user": user, "pass": pw}}


def extract_items(text: str) -> list[dict]:
    """همه کانفیگ‌ها و پروکسی‌های یک متن؛ هر آیتم: {kind, key, d}."""
    out, local = [], set()
    text = html.unescape(text or "")
    for m in PROXY_RE.finditer(text):
        it = parse_proxy(m.group(0))
        if it and it["key"] not in local:
            local.add(it["key"])
            out.append(it)
    for raw in CONFIG_RE.findall(text):
        new = rename_config(raw)
        if not new:
            continue
        key = "cfg|" + hashlib.sha256(new.split("#", 1)[0].encode()).hexdigest()
        if key in local:
            continue
        local.add(key)
        out.append({"kind": "cfg", "key": key, "d": {"v": new}})
    return out


def short_label(kind: str, d: dict) -> str:
    """برچسب کوتاه برای نمایش تو صف: پروتکل • سرور."""
    try:
        if kind == "prx":
            return f"{d['type']} • {d['server']}:{d['port']}"
        v = d["v"]
        scheme = v.split("://", 1)[0].lower()
        if scheme == "vmess":
            host = json.loads(_b64decode(v[8:].split("#", 1)[0]).decode())["add"]
        else:
            host = urlsplit(v.split("#", 1)[0]).hostname or "—"
        return f"{scheme.upper()} • {host}"
    except Exception:
        return d.get("v", "؟")[:24]


# ═════════════════════ وضعیت (ذخیره سبک و دسته‌ای) ═════════════════════
STATE: dict = {}
_dirty = False


def load_state() -> None:
    STATE.update({
        "seen": set(), "pool": {"cfg": [], "prx": []}, "plan": [], "panel_id": None,
        "sent": {"cfg": 0, "prx": 0}, "daily": {},
        "run": {k: {"total": 0, "done": 0, "every": 10} for k in KINDS},
        "stats": {"new": 0, "dup": 0},
        "paused": False, "paused_at": 0.0,
        "auto": {"on": False, "every": DEFAULT_AUTO_EVERY},
    })
    if not STATE_FILE.exists():
        return
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        STATE["seen"] = set(data.get("seen", []))
        for k in ("pool", "sent", "stats", "auto", "daily"):
            if isinstance(data.get(k), dict):
                STATE[k].update(data[k])
        for k in KINDS:
            if isinstance(data.get("run", {}).get(k), dict):
                STATE["run"][k].update(data["run"][k])
        STATE["plan"] = [p for p in data.get("plan", []) if isinstance(p, dict) and "d" in p and "kind" in p]
        STATE["panel_id"] = data.get("panel_id")
        STATE["paused"] = bool(data.get("paused"))
        STATE["paused_at"] = float(data.get("paused_at") or 0)
    except Exception:
        log.exception("خواندن state.json ممکن نشد؛ با وضعیت خالی شروع می‌کنم")


def save_state() -> None:
    """فقط علامت می‌زند؛ نوشتن روی دیسک را flush_loop حداکثر ثانیه‌ای یک‌بار انجام می‌دهد."""
    global _dirty
    _dirty = True


def _snapshot() -> str:
    return json.dumps({**STATE, "seen": list(STATE["seen"])}, ensure_ascii=False)


def _write_state(raw: str) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(raw, encoding="utf-8")
    tmp.replace(STATE_FILE)


async def flush_loop() -> None:
    global _dirty
    while True:
        await asyncio.sleep(1)
        if _dirty:
            _dirty = False
            try:
                await asyncio.to_thread(_write_state, _snapshot())
            except Exception:
                _dirty = True
                log.exception("ذخیره state.json ناموفق بود")


def flush_now() -> None:
    global _dirty
    if _dirty:
        _dirty = False
        _write_state(_snapshot())


def clock() -> float:
    """ساعت منطقی صف؛ وقتی مکث فعاله، زمان در لحظه مکث ثابت می‌ماند."""
    return STATE["paused_at"] if STATE["paused"] else time.time()


# ═════════════════════ ساخت پیام ═════════════════════
def u16(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def compose(segments: list[tuple]) -> tuple[str, list]:
    text, ents = "", []
    for seg in segments:
        kind, off = seg[0], u16(text)
        if kind == "t":
            text += seg[1]
        elif kind == "e":
            if USE_CUSTOM_EMOJI:
                text += PLACEHOLDER
                ents.append(MessageEntity(MessageEntity.CUSTOM_EMOJI, offset=off,
                                          length=u16(PLACEHOLDER), custom_emoji_id=seg[1]))
            else:
                text += f"[{seg[1]}]"
        elif kind == "c":
            text += seg[1]
            ents.append(MessageEntity(MessageEntity.CODE, offset=off, length=u16(seg[1])))
        elif kind == "l":
            text += seg[1]
            ents.append(MessageEntity(MessageEntity.TEXT_LINK, offset=off,
                                      length=u16(seg[1]), url=seg[2]))
    return text, ents


def build_message(kind: str, d: dict) -> tuple[str, list, str | None]:
    """خروجی: (متن، entityها، لینک دکمه اتصال برای پروکسی)."""
    head = [("e", EMOJI_HEAD[0]), ("t", "کانفیگ رایگان" if kind == "cfg" else "پروکسی رایگان"),
            ("e", EMOJI_HEAD[1]), ("t", "\n\n")]
    tail = [("t", "\n\n@SamTvVpn"), ("e", EMOJI_TAIL)]
    if kind == "cfg":
        text, ents = compose(head + [("c", d["v"])] + tail)
        return text, ents, None
    body = [
        ("t", f"🔌 پروکسی ({d['type']})\n\n"),
        ("t", "🌐 Server: "), ("c", d["server"]), ("t", "\n"),
        ("t", "🔢 Port: "), ("c", str(d["port"])), ("t", "\n"),
    ]
    if d.get("secret"):
        body += [("t", "🔑 Secret: "), ("c", d["secret"]), ("t", "\n")]
    if d.get("user"):
        body += [("t", "👤 User: "), ("c", d["user"]), ("t", "\n"),
                 ("t", "🔒 Pass: "), ("c", d.get("pass", "")), ("t", "\n")]
    body += [("t", "\n👉 "), ("l", "اتصال با یک کلیک", d["v"])]
    text, ents = compose(head + body + tail)
    return text, ents, d["v"]


# ═════════════════════ ارتباط با تلگرام ═════════════════════
BOT = None   # بعد از راه‌اندازی مقداردهی می‌شود
_bg: set = set()


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


async def tg(fn, *args, **kwargs):
    """اجرای درخواست تلگرام با صبر خودکار در برابر فلود."""
    for _ in range(5):
        try:
            return await fn(*args, **kwargs)
        except RetryAfter as e:
            log.warning("فلود؛ %s ثانیه صبر...", e.retry_after)
            await asyncio.sleep(int(e.retry_after) + 1)
    return await fn(*args, **kwargs)


async def notify(text: str) -> None:
    try:
        await tg(BOT.send_message, SOURCE_ID, text)
    except Exception as e:
        log.warning("پیام به مخزن ارسال نشد: %s", e)


_admin_cache: dict[int, tuple[float, bool]] = {}


async def is_admin(uid: int) -> bool:
    hit = _admin_cache.get(uid)
    if hit and time.time() - hit[0] < 120:
        return hit[1]
    try:
        m = await BOT.get_chat_member(SOURCE_ID, uid)
        ok = m.status in ("administrator", "creator")
    except TelegramError:
        return False
    _admin_cache[uid] = (time.time(), ok)
    return ok


# ═════════════════════ صف ارسال ═════════════════════
def pool_total() -> int:
    return len(STATE["pool"]["cfg"]) + len(STATE["pool"]["prx"])


def sorted_plan() -> list[dict]:
    return sorted(STATE["plan"], key=lambda p: p["at"])


def start_sending(kind: str, every: int, count: int | None) -> int:
    """چند مورد اول استخر را با فاصله `every` ثانیه وارد صف ارسال می‌کند."""
    pool = STATE["pool"][kind]
    take = pool if count is None else pool[:count]
    if not take:
        return 0
    STATE["pool"][kind] = pool[len(take):]
    fresh = not any(p["kind"] == kind for p in STATE["plan"])
    last = max([p["at"] for p in STATE["plan"]] + [clock() + 3 - every])
    for i, d in enumerate(take, 1):
        STATE["plan"].append({"id": uuid.uuid4().hex[:8], "kind": kind, "d": d,
                              "at": int(last + i * every), "bad": 0})
    run = STATE["run"][kind]
    if fresh:
        run["total"], run["done"] = 0, 0
    run["total"] += len(take)
    run["every"] = every
    save_state()
    return len(take)


def rebase_plan() -> None:
    """بعد از خاموشی، فاصله‌ها حفظ می‌شود ولی ارسال از همین الان ادامه پیدا می‌کند."""
    if not STATE["plan"] or STATE["paused"]:
        return
    plan = sorted_plan()
    shift = time.time() + 3 - plan[0]["at"]
    if shift > 0:
        for p in plan:
            p["at"] = int(p["at"] + shift)
        save_state()


def set_pause(on: bool) -> None:
    now = time.time()
    if on and not STATE["paused"]:
        STATE["paused"], STATE["paused_at"] = True, now
    elif not on and STATE["paused"]:
        shift = now - STATE["paused_at"]
        for p in STATE["plan"]:
            p["at"] = int(p["at"] + shift)
        STATE["paused"], STATE["paused_at"] = False, 0.0
    save_state()


def retime(every: int) -> None:
    """سرعت کل صف را عوض می‌کند (ترتیب حفظ می‌شود)."""
    base = clock() + 3
    for kind in KINDS:
        items = sorted((p for p in STATE["plan"] if p["kind"] == kind), key=lambda p: p["at"])
        for i, p in enumerate(items):
            p["at"] = int(base + i * every)
        if items:
            STATE["run"][kind]["every"] = every
    save_state()


def shuffle_queue() -> int:
    n = 0
    for kind in KINDS:
        items = [p for p in STATE["plan"] if p["kind"] == kind]
        ds = [p["d"] for p in items]
        random.shuffle(ds)
        for p, d in zip(sorted(items, key=lambda p: p["at"]), ds):
            p["d"] = d
        n += len(items)
    save_state()
    return n


def stop_all() -> int:
    """ارسال را متوقف می‌کند و باقی‌مانده را (با ترتیب اصلی) به استخر برمی‌گرداند."""
    n = len(STATE["plan"])
    for pl in sorted(STATE["plan"], key=lambda x: x["at"], reverse=True):
        STATE["pool"][pl["kind"]].insert(0, pl["d"])
    STATE["plan"] = []
    STATE["paused"], STATE["paused_at"] = False, 0.0
    for k in KINDS:
        STATE["run"][k].update(total=0, done=0)
    save_state()
    return n


def today_key() -> str:
    return datetime.now(TZ).date().isoformat()


def count_sent(kind: str) -> None:
    STATE["sent"][kind] += 1
    STATE["run"][kind]["done"] += 1
    STATE["daily"][today_key()] = STATE["daily"].get(today_key(), 0) + 1
    for k in sorted(STATE["daily"])[:-14]:
        STATE["daily"].pop(k, None)


# ═════════════════════ نمایش‌ها (متن + دکمه) ═════════════════════
def kind_stats(kind: str, top: int = 4) -> str:
    items = STATE["pool"][kind]
    if kind == "cfg":
        c = Counter(d["v"].split("://", 1)[0].upper() for d in items)
    else:
        c = Counter(d["type"] for d in items)
    return " · ".join(f"{k} {fa(v)}" for k, v in c.most_common(top))


def progress_lines() -> list[str]:
    out, now = [], clock()
    for kind in KINDS:
        left = [p for p in STATE["plan"] if p["kind"] == kind]
        if not left:
            continue
        run = STATE["run"][kind]
        total, done = max(run["total"], len(left) + run["done"]), run["done"]
        out.append(f"{KIND_ICON[kind]} {KIND_FA[kind]}: {fa(done)}/{fa(total)}  "
                   f"{bar(done / total)} {fa(round(100 * done / total))}٪")
        eta = max(p["at"] for p in left)
        out.append(f"   ⏱ هر {fmt_dur(run['every'])} │ 🏁 {fmt_when(eta)} ({fmt_dur(eta - now)} دیگه)")
    return out


def next_line() -> str | None:
    plan = sorted_plan()
    if not plan:
        return None
    p = plan[0]
    if STATE["paused"]:
        return f"⏸ مکث فعاله │ بعدی: {short_label(p['kind'], p['d'])}"
    return f"⏭ بعدی تا {fmt_cd(p['at'] - time.time())}: {short_label(p['kind'], p['d'])}"


def footer_line() -> str:
    t = STATE["daily"].get(today_key(), 0)
    auto = f"🤖 خودکار: {'روشن' if STATE['auto']['on'] else 'خاموش'}"
    return f"{auto} │ ✅ امروز {fa(t)} │ کل {fa(STATE['sent']['cfg'] + STATE['sent']['prx'])}"


def main_view() -> tuple[str, list]:
    lines = ["📡 مرکز کنترل مخزن", LINE]
    rows = []
    for kind in KINDS:
        items = STATE["pool"][kind]
        if items:
            lines += [f"{KIND_ICON[kind]} {KIND_FA[kind]}‌ها: {fa(len(items))}", f"   🧩 {kind_stats(kind)}"]
            rows.append([Button.inline(f"{KIND_ICON[kind]} ارسال {KIND_FA[kind]}‌ها ({fa(len(items))})", f"k:{kind}")])
    st = STATE["stats"]
    if st["new"] or st["dup"]:
        lines.append(f"🆕 جدید {fa(st['new'])} │ ♻️ تکراری {fa(st['dup'])}")
    if STATE["plan"]:
        lines += [LINE, "⏸ ارسال در حالت مکث" if STATE["paused"] else "🚀 ارسال فعال"]
        lines += progress_lines()
        lines.append(next_line())
    elif not pool_total():
        lines.append("📭 استخر خالیه؛ کانفیگ یا پروکسی جدید بذار")
    lines += [LINE, footer_line(), f"📍 {TARGET_USERNAME} │ 🕒 {fmt_clock(time.time(), True)}"]
    if STATE["plan"]:
        rows.append([Button.inline("▶️ ادامه" if STATE["paused"] else "⏸ مکث", "pz"),
                     Button.inline("⏭ بعدی همین الان", "nx")])
        rows.append([Button.inline("📋 صف و تایمر", "qu:0"), Button.inline("⏱ سرعت", "sp"),
                     Button.inline("⏹ توقف", "c")])
    else:
        rows.append([Button.inline("📋 صف", "qu:0")])
    rows.append([Button.inline("📈 آمار", "st"), Button.inline("⚙️ تنظیمات", "se"),
                 Button.inline("🔄 بروزرسانی", "u")])
    return "\n".join(lines), rows


def done_view() -> str:
    parts = [f"{KIND_ICON[k]} {KIND_FA[k]}: {fa(STATE['run'][k]['done'])}"
             for k in KINDS if STATE["run"][k]["total"]]
    return "\n".join(["✅ ارسال تموم شد", LINE] + parts + ["", f"📍 همه به {TARGET_USERNAME} رسیدن."])


def kind_view(kind: str) -> tuple[str, list]:
    n = len(STATE["pool"][kind])
    lines = [f"{KIND_ICON[kind]} {fa(n)} {KIND_FA[kind]} آماده ارسال", LINE,
             f"🧩 {kind_stats(kind)}", LINE, "با چه سرعتی بفرستم؟ 👇"]
    rows = [[Button.inline(f"⚡ هر {fmt_dur(s)}  —  کل کار حدود {fmt_dur(n * s)}", f"n:{kind}:{s}:a")]
            for s in SPEEDS]
    part = [c for c in COUNTS if c < n]
    if part:
        rows.append([Button.inline(f"🎯 فقط {fa(c)} تای اول", f"n:{kind}:10:{c}") for c in part])
    rows.append([Button.inline("🗑 حذف از استخر", f"x:{kind}"), Button.inline("↩️ برگشت", "b")])
    return "\n".join(lines), rows


def queue_view(page: int) -> tuple[str, list]:
    plan = sorted_plan()
    pages = max(1, -(-len(plan) // PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    lines = [f"📋 صف ارسال ({fa(len(plan))} مورد) │ صفحه {fa(page + 1)}/{fa(pages)}", LINE]
    if not plan:
        lines.append("صف خالیه.")
    else:
        lines += [next_line(), ""]
        for i, p in enumerate(plan[page * PAGE_SIZE:(page + 1) * PAGE_SIZE], page * PAGE_SIZE + 1):
            lines.append(f"{fa(i)}) {fmt_when(p['at'])} │ {KIND_ICON[p['kind']]} {short_label(p['kind'], p['d'])}")
    lines += [LINE, f"🕒 {fmt_clock(time.time(), True)}"]
    rows = []
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(Button.inline("◀️ قبلی", f"qu:{page - 1}"))
        nav.append(Button.inline("🔄", f"qu:{page}"))
        if page < pages - 1:
            nav.append(Button.inline("بعدی ▶️", f"qu:{page + 1}"))
        rows.append(nav)
    if plan:
        rows.append([Button.inline("👁 پیش‌نمایش بعدی", "pv"), Button.inline("⏭ همین الان بفرست", "nq")])
        rows.append([Button.inline("🗑 حذف بعدی", "dl"), Button.inline("🔀 بُر زدن", "sh")])
    rows.append([Button.inline("↩️ برگشت", "b")])
    return "\n".join(lines), rows


def speed_view() -> tuple[str, list]:
    n = len(STATE["plan"])
    text = f"⏱ سرعت صف ({fa(n)} مورد)\n{LINE}\nسرعت جدید برای کل صف:"
    rows = [[Button.inline(f"⚡ هر {fmt_dur(s)}  —  پایان حدود {fmt_dur(n * s)}", f"sv:{s}")] for s in SPEEDS]
    rows.append([Button.inline("↩️ برگشت", "b")])
    return text, rows


def stats_view() -> tuple[str, list]:
    days = [(datetime.now(TZ).date() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    vals = [STATE["daily"].get(d, 0) for d in days]
    mx = max(vals) or 1
    spark = "".join(SPARK[min(7, round(v / mx * 7))] if v else SPARK[0] for v in vals)
    lines = ["📈 آمار", LINE,
             f"✅ امروز: {fa(vals[-1])} │ ۷ روز: {fa(sum(vals))}",
             f"📅 {spark}  (کمترین ← بیشترین)",
             f"📦 کل ارسال کانفیگ: {fa(STATE['sent']['cfg'])}",
             f"🔌 کل ارسال پروکسی: {fa(STATE['sent']['prx'])}",
             LINE,
             f"🗂 استخر: {fa(pool_total())} │ 📋 صف: {fa(len(STATE['plan']))}",
             f"🧠 حافظه ضدتکراری: {fa(len(STATE['seen']))}",
             f"⏳ مدت روشن بودن ربات: {fmt_dur(time.time() - STARTED)}"]
    return "\n".join(lines), [[Button.inline("↩️ برگشت", "b")]]


def settings_view() -> tuple[str, list]:
    a = STATE["auto"]
    text = "\n".join([
        "⚙️ تنظیمات", LINE,
        f"🤖 حالت خودکار: {'روشن ✅' if a['on'] else 'خاموش'}",
        f"   هر چیز جدید خودش با سرعت «هر {fmt_dur(a['every'])}» وارد صف می‌شه.",
        f"📍 مقصد: {TARGET_USERNAME}",
    ])
    rows = [
        [Button.inline("🤖 خودکار: خاموش کن" if a["on"] else "🤖 خودکار: روشن کن", "at")],
        [Button.inline(f"⚡ سرعت خودکار: هر {fmt_dur(a['every'])} (تغییر)", "as")],
        [Button.inline("📤 خروجی استخر و صف (txt)", "ex")],
        [Button.inline("↩️ برگشت", "b")],
    ]
    return text, rows


def current_view():
    """چیزی که پنل اصلی باید الان نشان دهد."""
    return main_view()


# ═════════════════════ پنل: همیشه پایین کانال ═════════════════════
_panel_lock = asyncio.Lock()
_panel_deadline, _panel_running, _panel_first = 0.0, False, 0.0
_last_edit: tuple = (None, "")


async def refresh_panel() -> None:
    """پنل قدیمی پاک و پنل تازه «پایین کانال» فرستاده می‌شود تا همیشه جلوی چشم باشد."""
    async with _panel_lock:
        if not (pool_total() or STATE["plan"]):
            return
        old = STATE.get("panel_id")
        text, rows = current_view()
        msg = await tg(BOT.send_message, SOURCE_ID, text, reply_markup=markup(rows))
        STATE["panel_id"] = msg.message_id
        STATE["stats"] = {"new": 0, "dup": 0}
        save_state()
        if old and old != msg.message_id:
            try:
                await BOT.delete_message(SOURCE_ID, old)
            except TelegramError:
                pass


async def _panel_worker() -> None:
    global _panel_running
    try:
        while time.monotonic() < _panel_deadline:
            await asyncio.sleep(0.3)
    finally:
        _panel_running = False
    try:
        await refresh_panel()
    except Exception:
        log.exception("خطا در ساخت پنل")


def request_panel(delay: float = PANEL_DELAY) -> None:
    global _panel_deadline, _panel_running, _panel_first
    now = time.monotonic()
    if not _panel_running:
        _panel_first = now
    _panel_deadline = min(now + delay, _panel_first + PANEL_MAX_WAIT)
    if not _panel_running:
        _panel_running = True
        _spawn(_panel_worker())


async def edit_panel(text: str, rows) -> None:
    global _last_edit
    mid = STATE.get("panel_id")
    if not mid or _last_edit == (mid, text):
        return
    try:
        await tg(BOT.edit_message_text, text, chat_id=SOURCE_ID, message_id=mid, reply_markup=markup(rows))
        _last_edit = (mid, text)
    except BadRequest as e:
        low = str(e).lower()
        if "not modified" in low:
            _last_edit = (mid, text)
        elif "not found" in low or "can't be edited" in low:
            STATE["panel_id"] = None   # پیام پاک شده؛ دفعه بعد پنل جدید می‌آید
            save_state()
            if pool_total() or STATE["plan"]:
                request_panel(delay=0.5)
        else:
            log.warning("ویرایش پنل ممکن نشد: %s", e)


# ═════════════════════ ورود آیتم‌ها از مخزن ═════════════════════
async def message_text(msg) -> str:
    parts = [msg.text or msg.caption or ""]
    for ent in list(msg.entities or []) + list(msg.caption_entities or []):
        if getattr(ent, "url", None):
            parts.append(ent.url)
    if msg.reply_markup and getattr(msg.reply_markup, "inline_keyboard", None):
        for row in msg.reply_markup.inline_keyboard:
            for b in row:
                if b.url:
                    parts.append(b.url)
    doc = msg.document
    if doc:
        name = (doc.file_name or "").lower()
        if ((doc.mime_type or "").startswith("text/") or name.endswith((".txt", ".conf"))) \
                and (doc.file_size or 0) <= 2 * 1024 * 1024:
            try:
                f = await tg(doc.get_file)
                parts.append(bytes(await f.download_as_bytearray()).decode("utf-8", errors="ignore"))
            except Exception:
                log.exception("خواندن فایل متنی ممکن نشد")
    return "\n".join(parts)


def ingest(items: list[dict]) -> dict:
    """بدون هیچ await/تستی؛ فوری به استخر می‌ریزد و تکراری‌ها را می‌شمارد."""
    added = Counter()
    for it in items:
        if it["key"] in STATE["seen"]:
            STATE["stats"]["dup"] += 1
            continue
        STATE["seen"].add(it["key"])
        it["d"]["key"] = it["key"]
        STATE["pool"][it["kind"]].append(it["d"])
        added[it["kind"]] += 1
        STATE["stats"]["new"] += 1
    if items:
        save_state()
    return dict(added)


COMMANDS = {"/panel": "panel", "پنل": "panel", "/status": "status", "وضعیت": "status"}


async def on_source_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return
    cmd = COMMANDS.get((msg.text or "").strip().lower())
    if cmd:
        try:
            await msg.delete()
        except Exception:
            pass
        if cmd == "panel":
            if pool_total() or STATE["plan"]:
                request_panel(delay=0)
            else:
                await notify("📭 استخر و صف خالیه")
        else:
            lines = ["📊 وضعیت", LINE, f"🗂 استخر: {fa(len(STATE['pool']['cfg']))} کانفیگ │ "
                     f"{fa(len(STATE['pool']['prx']))} پروکسی", f"📋 صف: {fa(len(STATE['plan']))}"]
            if STATE["plan"]:
                lines += progress_lines() + [next_line()]
            await notify("\n".join(lines))
        return
    items = extract_items(await message_text(msg))
    if not items:
        return
    added = ingest(items)
    log.info("پست %s: +%s", msg.message_id, added or "0 (همه تکراری)")
    if STATE["auto"]["on"]:
        for kind in added:
            start_sending(kind, STATE["auto"]["every"], None)
    if added:
        request_panel()


# ═════════════════════ دکمه‌های اینلاین ═════════════════════
async def _delete_later(chat_id: int, mid: int, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await BOT.delete_message(chat_id, mid)
    except TelegramError:
        pass


async def handle_cb(data: str):
    """خروجی: (متن پاسخ، alert؟، (متن جدید پیام، دکمه‌ها) یا None)"""
    action, *p = data.split(":")
    kind = p[0] if p and p[0] in KIND_FA else None
    stale = ("📭 این پنل قدیمیه؛ استخر خالیه", True, ("✅ این پنل تموم شده", None))

    if action in ("k", "n", "x") and kind and not STATE["pool"][kind]:
        return stale
    if action in ("b", "u"):
        return ("✅ به‌روز شد" if action == "u" else None), False, main_view()
    if action == "k":
        return None, False, kind_view(kind)
    if action == "x":
        n = len(STATE["pool"][kind])
        for d in STATE["pool"][kind]:
            STATE["seen"].discard(d.get("key"))
        STATE["pool"][kind] = []
        save_state()
        return "🗑 حذف شد", False, main_view() if (pool_total() or STATE["plan"]) else \
            (f"🗑 {fa(n)} {KIND_FA[kind]} نادیده گرفته شد", None)
    if action == "n":
        every = int(p[1])
        n = start_sending(kind, every, None if p[2] == "a" else int(p[2]))
        return f"🚀 {fa(n)} مورد وارد صف شد", False, main_view()
    if action == "pz":
        set_pause(not STATE["paused"])
        return ("⏸ مکث شد" if STATE["paused"] else "▶️ ادامه پیدا کرد"), False, main_view()
    if action in ("nx", "nq"):
        plan = sorted_plan()
        if not plan:
            return "صف خالیه", True, None
        await deliver(plan[0])
        return "⏭ ارسال شد", False, queue_view(0) if action == "nq" else main_view()
    if action == "dl":
        plan = sorted_plan()
        if not plan:
            return "صف خالیه", True, None
        STATE["plan"].remove(plan[0])
        STATE["run"][plan[0]["kind"]]["total"] = max(0, STATE["run"][plan[0]["kind"]]["total"] - 1)
        save_state()
        return "🗑 از صف حذف شد", False, queue_view(0)
    if action == "sh":
        n = shuffle_queue()
        return f"🔀 {fa(n)} مورد بُر خورد", False, queue_view(0)
    if action == "qu":
        return None, False, queue_view(int(p[0]) if p else 0)
    if action == "pv":
        plan = sorted_plan()
        if not plan:
            return "صف خالیه", True, None
        text, ents, url = build_message(plan[0]["kind"], plan[0]["d"])
        btns = [[Button.url("🔌 اتصال به پروکسی", url)]] if url else None
        m = await tg(BOT.send_message, SOURCE_ID, text, entities=ents, reply_markup=markup(btns),
                     link_preview_options=LinkPreviewOptions(is_disabled=True))
        _spawn(_delete_later(SOURCE_ID, m.message_id, PREVIEW_TTL))
        return f"👁 عین پیام بعدی ارسال شد (بعد از {fa(PREVIEW_TTL)} ثانیه پاک می‌شه)", False, None
    if action == "sp":
        return None, False, speed_view() if STATE["plan"] else main_view()
    if action == "sv":
        retime(int(p[0]))
        return f"⏱ سرعت: هر {fmt_dur(int(p[0]))}", False, main_view()
    if action == "st":
        return None, False, stats_view()
    if action == "se":
        return None, False, settings_view()
    if action == "at":
        STATE["auto"]["on"] = not STATE["auto"]["on"]
        save_state()
        return ("🤖 خودکار روشن شد" if STATE["auto"]["on"] else "🤖 خودکار خاموش شد"), False, settings_view()
    if action == "as":
        i = SPEEDS.index(STATE["auto"]["every"]) if STATE["auto"]["every"] in SPEEDS else -1
        STATE["auto"]["every"] = SPEEDS[(i + 1) % len(SPEEDS)]
        save_state()
        return None, False, settings_view()
    if action == "ex":
        lines = [d["v"] for k in KINDS for d in STATE["pool"][k]]
        lines += [p_["d"]["v"] for p_ in sorted_plan()]
        if not lines:
            return "چیزی برای خروجی نیست", True, None
        name = f"export-{datetime.now(TZ):%Y%m%d-%H%M}.txt"
        await tg(BOT.send_document, SOURCE_ID, document="\n".join(lines).encode("utf-8"), filename=name,
                 caption=f"📤 {fa(len(lines))} مورد (استخر + صف)")
        return "📤 فایل ارسال شد", False, None
    if action == "c":
        n = stop_all()
        if not n:
            return "ارسال فعالی نیست", True, None
        return f"⏹ متوقف شد؛ {fa(n)} مورد برگشت به استخر", True, main_view()
    return None, False, None


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    if not q.message or q.message.chat.id != SOURCE_ID:
        await q.answer()
        return
    if not await is_admin(q.from_user.id):
        await q.answer("⛔ فقط ادمین‌های کانال می‌تونن از این دکمه‌ها استفاده کنن", show_alert=True)
        return
    try:
        ans, alert, view = await handle_cb(q.data)
        await q.answer(ans, show_alert=alert)   # اول جواب بده تا دکمه سریع حس بشه
        if view:
            try:
                await tg(q.edit_message_text, view[0], reply_markup=markup(view[1]))
            except BadRequest as e:
                if "not modified" not in str(e).lower():
                    raise
    except Exception:
        log.exception("خطا در دکمه %s", q.data)
        try:
            await q.answer("⚠️ خطایی رخ داد")
        except TelegramError:
            pass


# ═════════════════════ ارسال و پنل زنده ═════════════════════
_deliver_lock = asyncio.Lock()


async def deliver(p: dict) -> None:
    async with _deliver_lock:                       # هیچ‌وقت دو ارسال هم‌زمان نداریم
        if p not in STATE["plan"]:
            return
        text, ents, url = build_message(p["kind"], p["d"])
        btns = [[Button.url("🔌 اتصال به پروکسی", url)]] if url else None
        try:
            await tg(BOT.send_message, TARGET_ID, text, entities=ents, reply_markup=markup(btns),
                     link_preview_options=LinkPreviewOptions(is_disabled=True))
        except TelegramError as e:
            p["bad"] = p.get("bad", 0) + 1
            log.error("ارسال ناموفق (%d/3): %s", p["bad"], e)
            if p["bad"] >= 3:
                STATE["plan"].remove(p)
                STATE["run"][p["kind"]]["done"] += 1
                _spawn(notify(f"⚠️ یک {KIND_FA[p['kind']]} بعد از ۳ بار تلاش ارسال نشد و کنار گذاشته شد:\n"
                              f"{short_label(p['kind'], p['d'])}"))
            else:
                p["at"] = int(time.time()) + 30
            save_state()
            return
        STATE["plan"].remove(p)
        count_sent(p["kind"])
        save_state()
        log.info("ارسال شد (%s) | باقی‌مانده: %d", p["kind"], len(STATE["plan"]))


async def scheduler_loop() -> None:
    last = 0.0
    while True:
        try:
            now = time.time()
            if not STATE["paused"] and now - last >= MIN_GAP:
                due = [p for p in STATE["plan"] if p["at"] <= now]
                if due:
                    await deliver(min(due, key=lambda x: x["at"]))
                    last = time.time()
        except Exception:
            log.exception("خطای غیرمنتظره در ارسال‌کننده")
        await asyncio.sleep(0.5)


_was_active = False


async def live_loop() -> None:
    """پنل را هر چند ثانیه (با شمارش معکوس زنده) بروز می‌کند و در پایان گزارش نهایی می‌دهد."""
    global _was_active
    while True:
        await asyncio.sleep(LIVE_EVERY)
        try:
            active = bool(STATE["plan"])
            if active:
                _was_active = True
                await edit_panel(*current_view())
            elif _was_active:
                _was_active = False
                if pool_total():
                    await edit_panel(*current_view())
                elif STATE.get("panel_id"):
                    await edit_panel(done_view(), None)
                for k in KINDS:
                    STATE["run"][k].update(total=0, done=0)
                save_state()
        except Exception:
            log.exception("خطا در پنل زنده")


# ═════════════════════ راه‌اندازی ═════════════════════
async def post_init(app: Application) -> None:
    global BOT, _was_active
    BOT = app.bot
    rebase_plan()
    _was_active = bool(STATE["plan"])
    app.bot_data["tasks"] = [asyncio.create_task(f()) for f in (scheduler_loop, flush_loop, live_loop)]
    log.info("روشن شد | انتظار: %d کانفیگ، %d پروکسی | در صف ارسال: %d",
             len(STATE["pool"]["cfg"]), len(STATE["pool"]["prx"]), len(STATE["plan"]))
    if pool_total() or STATE["plan"]:
        request_panel(delay=1)


async def post_shutdown(app: Application) -> None:
    for task in app.bot_data.get("tasks", []):
        task.cancel()
    flush_now()


async def on_error(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("خطا: %s", context.error)


def main() -> None:
    load_state()
    app = (Application.builder().token(BOT_TOKEN).concurrent_updates(True)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    app.add_handler(MessageHandler(
        filters.UpdateType.CHANNEL_POST & filters.Chat(SOURCE_ID), on_source_post))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)
    log.info("ربات روشن شد؛ منتظر پست جدید در مخزن...")
    app.run_polling(allowed_updates=["channel_post", "callback_query"])


if __name__ == "__main__":
    main()
