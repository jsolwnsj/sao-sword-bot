#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
دانلودر تلگرام — اینستاگرام + پورن‌هاب
- هم توی پی‌وی کار می‌کند، هم توی گروه (به شرطی که Privacy Mode ربات خاموش باشد).
- لینک اینستاگرام (ریلز/پست عمومی) یا پورن‌هاب را می‌گیرد،
  با yt-dlp دانلود می‌کند و همان‌جا توی همان چت برمی‌گرداند.
- فقط محتوای عمومی، بدون لاگین و بدون کوکی.
- یوتیوب توی این نسخه نیست.
- محدودیت تلگرام: سقف سخت ۵۰ مگابایت برای ارسال فایل با ربات است و
  با «مستقیم فرستادن» دور زده نمی‌شود. ربات اول کیفیت را پایین می‌آورد
  (۷۲۰p، بعد ۴۸۰p، بعد ۳۶۰p) و اگر باز هم فایل بالای ۵۰ مگ بود،
  با ffmpeg آن را به قسمت‌های زیر ۴۸ مگ تقسیم می‌کند و قسمت‌ها را
  به ترتیب می‌فرستد.
- راه دوم برای فایل بزرگ (اختیاری): MTProto با Telethon. اگر
  TELETHON_API_ID و TELETHON_API_HASH ست باشند و سشن هم از یکی از
  این سه جا بیاید — متغیر TELETHON_SESSION_STRING، فایل
  /data/telethon_session.txt (روی Volume ریل‌وی) یا ساخته‌شده با
  دستور /makesession توی پی‌وی — فایل بزرگ (تا ۲ گیگابایت) مستقیم
  با حساب کاربری تلگرام فرستاده می‌شود و نیازی به تیکه‌تیکه کردن
  نیست. اگر سشن نباشد، همان مسیر پایین آوردن کیفیت + تقسیم استفاده
  می‌شود.
- توکن از متغیر محیطی BOT_TOKEN خوانده می‌شود؛ هیچ‌وقت اینجا هاردکد نکن.
- روش اجرا: polling — نیازی به دامین و وب‌هوک نیست.
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yt_dlp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Telethon به‌صورت lazy وارد می‌شود تا اگر نصب نبود، ربات باز هم
# با مسیر معمولی Bot API کار کند. اگر telethon نصب باشد و متغیرهای
# محیطی‌اش ست شده باشند، مسیر MTProto فعال می‌شود.
try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    from telethon.sessions import StringSession
    TELETHON_AVAILABLE = True
except ImportError:  # pragma: no cover - telethon not installed
    TelegramClient = None  # type: ignore[assignment]
    StringSession = None  # type: ignore[assignment]

    class SessionPasswordNeededError(Exception):  # type: ignore[no-redef]
        """جایگزین ساختگی؛ فقط وقتی Telethon نصب نیست استفاده می‌شود."""

    TELETHON_AVAILABLE = False

# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("downloader-bot")

# سقف سخت تلگرام برای ارسال فایل با ربات: ۵۰ مگابایت.
# با کمی حاشیه امن، ۴۸ مگابایت می‌گیریم.
MAX_BYTES = 48 * 1024 * 1024

# سقف ارسال فایل با MTProto (حساب کاربری Telethon): ۲ گیگابایت.
TELETHON_MAX_BYTES = 2 * 1024 * 1024 * 1024


# سشن Telethon از سه جا می‌تواند بیاید (به ترتیب اولویت):
# ۱) حافظه — ساخته‌شده با /makesession، بدون نیاز به ری‌استارت
# ۲) متغیر محیطی TELETHON_SESSION_STRING
# ۳) فایل /data/telethon_session.txt روی Volume ریل‌وی (بعد از ری‌استارت هم می‌ماند)
# مسیر فایل با TELETHON_SESSION_FILE قابل تغییر است (پیش‌فرض /data/telethon_session.txt).
TELETHON_SESSION_FILE = Path(
    os.environ.get("TELETHON_SESSION_FILE", "/data/telethon_session.txt")
)
_RUNTIME_SESSION_STRING: str | None = None


def get_telethon_session_string() -> str:
    """رشته سشن Telethon؛ خالی اگر هیچ‌جا نباشد."""
    if _RUNTIME_SESSION_STRING:
        return _RUNTIME_SESSION_STRING
    env_session = os.environ.get("TELETHON_SESSION_STRING", "").strip()
    if env_session:
        return env_session
    try:
        if TELETHON_SESSION_FILE.is_file():
            return TELETHON_SESSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""


def _telethon_api_credentials() -> tuple[int, str] | None:
    """(api_id, api_hash) از متغیرهای محیطی؛ اگر نباشند None."""
    if not TELETHON_AVAILABLE:
        return None
    try:
        api_id = int(os.environ.get("TELETHON_API_ID", "").strip())
    except ValueError:
        return None
    api_hash = os.environ.get("TELETHON_API_HASH", "").strip()
    if not api_hash:
        return None
    return api_id, api_hash


def _save_telethon_session(session_str: str) -> bool:
    """سشن را توی حافظه و فایل ذخیره می‌کند.
    True اگر فایل هم ذخیره شد، False اگر فقط حافظه شد."""
    global _RUNTIME_SESSION_STRING
    _RUNTIME_SESSION_STRING = session_str
    try:
        TELETHON_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        TELETHON_SESSION_FILE.write_text(session_str, encoding="utf-8")
        return True
    except OSError:
        logger.exception("Could not save Telethon session file")
        return False


def telethon_configured() -> bool:
    """True اگر API ID/Hash ست باشند و سشن از حافظه، متغیر محیطی
    یا فایل /data/telethon_session.txt بیاید و کتابخانه نصب باشد."""
    if not TELETHON_AVAILABLE:
        return False
    if _telethon_api_credentials() is None:
        return False
    return bool(get_telethon_session_string())


async def send_via_telethon(chat_id: int, path: Path, caption: str | None) -> bool:
    """
    فایل را با MTProto (حساب کاربری Telethon) به همان چت می‌فرستد.
    سقف ۲ گیگابایت است و سقف ۵۰ مگ Bot API را ندارد.
    در صورت هر خطایی False برمی‌گرداند تا مسیر تقسیم استفاده شود.
    نکته: حساب کاربری Telethon باید عضو گروه باشد (برای ارسال به گروه)
    یا با گیرنده دیالوگ داشته باشد (برای پی‌وی)؛ در غیر این صورت
    ارسال ناموفق می‌شود و False برمی‌گردد.
    """
    if not telethon_configured():
        return False
    creds = _telethon_api_credentials()
    session_str = get_telethon_session_string()
    if creds is None or not session_str:
        return False
    api_id, api_hash = creds

    client = None
    try:
        client = TelegramClient(
            StringSession(session_str), api_id, api_hash
        )
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning("Telethon session is not authorized.")
            return False
        await client.send_file(
            chat_id,
            str(path),
            caption=caption,
            supports_streaming=True,
        )
        logger.info(
            "Sent %s (%d bytes) via Telethon MTProto to %s",
            path, path.stat().st_size, chat_id,
        )
        return True
    except Exception:
        logger.exception("Telethon send failed for %s", path)
        return False
    finally:
        if client is not None:
            try:
                await client.disconnect()
            except Exception:
                pass


URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}

START_TEXT = """سلام! 👋
من دانلودر اینستا و پورن‌هابم.

کافیه لینک رو بفرستی:
• لینک ریلز یا پست اینستاگرام
• لینک ویدیوی پورن‌هاب

من دانلودش می‌کنم و همین‌جا برات می‌فرستم.

نکته‌ها:
• فقط محتوای عمومی دانلود می‌شه؛ محتوای خصوصی و نیازمند لاگین، توی این نسخه نیست.
• یوتیوب توی این نسخه نیست.
• تلگرام سقف سخت ۵۰ مگابایت برای ارسال فایل با ربات داره و با «مستقیم فرستادن» دور زده نمی‌شه. من اول کیفیت رو پایین می‌آرم (۷۲۰p، بعد ۴۸۰p، بعد ۳۶۰p). اگه فایل باز هم بزرگ بود، اگه ارسال با MTProto (Telethon) فعال باشه، مستقیم تا ۲ گیگابایت فرستاده می‌شه؛ اگه فعال نباشه، تیکه‌تیکه‌ش می‌کنم و قسمت‌ها رو به ترتیب می‌فرستم. پس ویدیوهای خیلی طولانی ممکنه چند قسمت بشن.
• توی گروه هم کار می‌کنم، فقط باید Privacy Mode ربات خاموش باشه (تو BotFather با /setprivacy).
• برای فعال کردن ارسال فایل بزرگ (MTProto)، توی پی‌وی /makesession رو بزن و شماره و کد رو بده؛ نیازی به ترمینال نیست.

دستورها:
/start — همین راهنما
/help — همین راهنما
/makesession — ساخت سشن Telethon با چت (فقط پی‌وی)؛ برای فعال کردن ارسال فایل بزرگ با MTProto
"""

TOO_BIG_TEXT = (
    "این ویدیو حتی بعد از کم کردن کیفیت و تیکه‌تیکه کردن هم "
    "برای تلگرام خیلی بزرگه. 😕\n"
    "یه لینک کوتاه‌تر رو امتحان کن."
)

ERROR_TEXT = (
    "نتونستم دانلودش کنم. 😕\n"
    "لینک رو چک کن که عمومی باشه و دوباره بفرست."
    "\nاگه باز هم نشد، شاید اینستا یا پورن‌هاب موقتاً جلوش رو گرفته."
)


def help_text() -> str:
    """متن راهنما + وضعیت مسیر MTProto (فعال/غیرفعال)."""
    if telethon_configured():
        status = "\nارسال فایل بزرگ (MTProto) فعال است؛ ویدیوهای بزرگ تا ۲ گیگابایت مستقیم فرستاده می‌شوند."
    else:
        status = "\nارسال فایل بزرگ (MTProto) فعال نیست؛ ویدیوهای بزرگ تیکه‌تیکه می‌شوند."
    return START_TEXT + status


# ---------------------------------------------------------------------------
# تشخیص لینک
# ---------------------------------------------------------------------------

def find_url(text: str) -> str | None:
    """اولین URL توی متن را برمی‌گرداند (بدون علامت‌های آخر جمله)."""
    if not text:
        return None
    m = URL_RE.search(text)
    if not m:
        return None
    url = m.group(0).rstrip(".,)]}>\"'")
    return url


def detect_platform(url: str) -> str | None:
    low = url.lower()
    if "instagram.com" in low:
        return "instagram"
    if "pornhub.com" in low:
        return "pornhub"
    return None


# ---------------------------------------------------------------------------
# دانلود با yt-dlp (بلوک‌کننده است؛ توی thread اجرا می‌شود)
# ---------------------------------------------------------------------------

def _download_once(url: str, height: int, outdir: str) -> tuple[str, list[Path]]:
    """یک بار دانلود با سقف کیفیت height. برمی‌گرداند: (عنوان، فهرست فایل‌ها)."""
    ydl_opts = {
        "format": (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={height}][ext=mp4]/"
            f"best[height<={height}]/best"
        ),
        "outtmpl": os.path.join(outdir, "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    title = ""
    if isinstance(info, dict):
        title = str(info.get("title") or "")

    skip_exts = {".part", ".ytdl", ".json", ".description", ".info.json"}
    files = [
        p
        for p in Path(outdir).iterdir()
        if p.is_file() and p.suffix.lower() not in skip_exts
    ]
    files.sort(key=lambda p: p.stat().st_size)
    return title, files


def _probe_duration_seconds(path: Path) -> float | None:
    """مدت ویدیو (ثانیه) با ffprobe؛ اگر نشد None."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def _split_video_sync(path: Path, workdir: Path) -> list[Path]:
    """ویدیو را با ffmpeg به قسمت‌های زیر ۴۸ مگ تقسیم می‌کند (بدون ریکد)."""
    size = path.stat().st_size
    if size <= MAX_BYTES:
        return [path]

    duration = _probe_duration_seconds(path)
    if duration and duration > 0:
        # زمان هر قسمت: طوری که حجم هر قسمت زیر ۴۸ مگ بماند (۸٪ حاشیه امن).
        segment_time = max(30, int(duration * MAX_BYTES * 0.92 / size))
    else:
        segment_time = 300

    workdir.mkdir(parents=True, exist_ok=True)

    for _attempt in range(3):
        pattern = str(workdir / f"{path.stem}_part%03d.mp4")
        # فایل‌های قسمت قبلی را پاک کن تا با تلاش جدید قاطی نشوند.
        for old in workdir.glob(f"{path.stem}_part*.mp4"):
            try:
                old.unlink()
            except OSError:
                pass
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(path),
                    "-c", "copy", "-map", "0",
                    "-f", "segment", "-segment_time", str(segment_time),
                    "-reset_timestamps", "1",
                    pattern,
                ],
                capture_output=True, text=True, timeout=600,
            )
        except Exception:
            logger.exception("ffmpeg split failed for %s", path)
            return [path]

        parts = sorted(workdir.glob(f"{path.stem}_part*.mp4"))
        parts = [p for p in parts if p.is_file() and p.stat().st_size > 0]
        if len(parts) > 1 and all(p.stat().st_size <= MAX_BYTES for p in parts):
            return parts
        if len(parts) <= 1:
            # تقسیم نشد (مثلاً ویدیوی خیلی کوتاه با بیت‌ریت بالا)؛
            # زمان قسمت را نصف کن و دوباره امتحان کن.
            segment_time = max(15, segment_time // 2)
            continue
        # بعضی قسمت‌ها هنوز بزرگ‌اند؛ زمان را نصف کن و دوباره تقسیم کن.
        segment_time = max(15, segment_time // 2)

    # آخرین تلاش: هرچه هست را برگردان؛ فرستنده قسمت‌های بزرگ را رد می‌کند.
    parts = sorted(workdir.glob(f"{path.stem}_part*.mp4"))
    return [p for p in parts if p.is_file() and p.stat().st_size > 0] or [path]


async def download_best_effort(url: str, tmpdir: str, prefer_telethon: bool = False):
    """
    دانلود با پایین آوردن کیفیت (۷۲۰p، بعد ۴۸۰p، بعد ۳۶۰p) و در صورت نیاز
    تقسیم به قسمت‌ها.
    برمی‌گرداند: (title, files, was_split)

    اگر prefer_telethon=True باشد (یعنی MTProto فعال است)، به‌جای تقسیم،
    فایل باکیفیت‌ترین دانلود (۷۲۰p) برگردانده می‌شود تا فرستنده اول
    Telethon را امتحان کند؛ تقسیم فقط وقتی انجام می‌شود که Telethon
    نباشد یا ناموفق باشد (فرستنده خودش آن را انجام می‌دهد).
    """
    best_candidate: tuple[str, list[Path]] | None = None
    results: dict[int, tuple[str, list[Path]]] = {}

    for height in (720, 480, 360):
        subdir = Path(tmpdir) / f"h{height}"
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            title, files = await asyncio.to_thread(
                _download_once, url, height, str(subdir)
            )
        except Exception:
            logger.exception("yt-dlp failed at %dp for %s", height, url)
            continue
        if not files:
            continue

        results[height] = (title, files)

        # فایل اصلی: بزرگ‌ترین فایل دانلودشده.
        main = max(files, key=lambda p: p.stat().st_size)
        if main.stat().st_size <= MAX_BYTES:
            return title, files, False

        # هنوز بزرگ است؛ کوچک‌ترین کاندید را نگه دار و کیفیت را پایین‌تر بیاور.
        if best_candidate is None or main.stat().st_size < max(
            p.stat().st_size for p in best_candidate[1]
        ):
            best_candidate = (title, files)

    if best_candidate is None:
        return "", [], False

    title, files = best_candidate

    # مسیر MTProto: فایل باکیفیت (۷۲۰p) را بدون تقسیم برگردان؛
    # فرستنده اول Telethon را امتحان می‌کند.
    if prefer_telethon:
        if 720 in results:
            hq_title, hq_files = results[720]
            return hq_title, hq_files, False
        return title, files, False

    main = max(files, key=lambda p: p.stat().st_size)

    # اگر فایل اصلی ویدیو نیست (مثلاً عکس)، تقسیم معنا ندارد.
    if main.suffix.lower() not in VIDEO_EXTS:
        return title, files, False

    # آخرین چاره: تقسیم به قسمت‌های زیر ۴۸ مگ.
    parts_dir = Path(tmpdir) / "parts"
    parts = await asyncio.to_thread(_split_video_sync, main, parts_dir)
    if len(parts) > 1 and all(p.stat().st_size <= MAX_BYTES for p in parts):
        # بقیه فایل‌ها (اگر بود) را کنار بگذار؛ فقط قسمت‌های ویدیو را بفرست.
        return title, parts, True

    return title, files, False


# ---------------------------------------------------------------------------
# ارسال فایل به چت
# ---------------------------------------------------------------------------

async def send_files(bot, chat_id: int, title: str, files: list[Path],
                     was_split: bool) -> bool:
    """فایل‌ها را می‌فرستد. اگر هیچ فایلی قابل ارسال نباشد False برمی‌گرداند."""
    if not files:
        return False

    sent_any = False
    total = len(files)
    for i, path in enumerate(files):
        # سقف سخت ۵۰ مگ تلگرام — با مستقیم فرستادن دور زده نمی‌شود.
        if path.stat().st_size > MAX_BYTES:
            continue

        if was_split and total > 1:
            caption = f"{title[:150]}\nقسمت {i + 1} از {total}" if title else (
                f"قسمت {i + 1} از {total}"
            )
        else:
            caption = title[:200] if (i == 0 and title) else None
        ext = path.suffix.lower()

        try:
            with open(path, "rb") as f:
                if ext == ".mp3":
                    await bot.send_audio(
                        chat_id=chat_id, audio=f,
                        title=title[:100] if title else None,
                    )
                elif ext in VIDEO_EXTS:
                    await bot.send_video(
                        chat_id=chat_id, video=f,
                        caption=caption, supports_streaming=True,
                    )
                elif ext in (".jpg", ".jpeg", ".png", ".webp"):
                    await bot.send_photo(
                        chat_id=chat_id, photo=f, caption=caption,
                    )
                else:
                    await bot.send_document(
                        chat_id=chat_id, document=f, caption=caption,
                    )
            sent_any = True
        except Exception:
            logger.exception("send failed for %s", path)

    return sent_any


async def do_download_and_send(bot, chat_id: int, url: str) -> str:
    """
    دانلود و ارسال. برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'
    ترتیب ارسال:
    ۱) فایل زیر ۴۸ مگ: مستقیم با Bot API.
    ۲) فایل بزرگ‌تر: اگر MTProto (Telethon) فعال باشد، مستقیم تا ۲ گیگ
       با حساب کاربری فرستاده می‌شود.
    ۳) اگر Telethon نباشد یا ناموفق باشد: تقسیم به قسمت‌های زیر ۴۸ مگ
       و ارسال قسمت‌ها با Bot API.
    """
    use_telethon = telethon_configured()
    status = await bot.send_message(
        chat_id=chat_id, text="⏳ دارم دانلود می‌کنم، یه کم صبر کن..."
    )
    try:
        with tempfile.TemporaryDirectory(prefix="dl-") as tmpdir:
            try:
                title, files, was_split = await download_best_effort(
                    url, tmpdir, prefer_telethon=use_telethon
                )
            except Exception:
                logger.exception("download failed for %s", url)
                return "error"

            if not files:
                return "empty"

            # فایل‌های کوچک و بزرگ را جدا کن.
            small = [p for p in files if p.stat().st_size <= MAX_BYTES]
            large = [p for p in files if p.stat().st_size > MAX_BYTES]

            # ۱) فایل‌های کوچک: مستقیم با Bot API.
            sent = False
            if small:
                sent = await send_files(bot, chat_id, title, small, was_split)

            # ۲) فایل‌های بزرگ: اول MTProto، بعد تقسیم.
            for path in large:
                if path.stat().st_size > TELETHON_MAX_BYTES:
                    continue
                if use_telethon:
                    caption = title[:200] if title else None
                    if await send_via_telethon(chat_id, path, caption):
                        sent = True
                        continue
                    logger.warning(
                        "Telethon send failed for %s; falling back to split",
                        path,
                    )
                # ۳) تقسیم به قسمت‌ها و ارسال با Bot API.
                if path.suffix.lower() in VIDEO_EXTS:
                    parts_dir = Path(tmpdir) / f"parts-{path.stem}"
                    parts = await asyncio.to_thread(
                        _split_video_sync, path, parts_dir
                    )
                    if len(parts) > 1 and all(
                        p.stat().st_size <= MAX_BYTES for p in parts
                    ):
                        if await send_files(
                            bot, chat_id, title, parts, True
                        ):
                            sent = True
                        continue
                # نه Telethon شد، نه تقسیم؛ این فایل فرستاده نشد.

            if sent:
                return "ok"
            # اگر حتی یک فایل هم زیر سقف نبود (و تقسیم هم نشد)، too_big
            if all(p.stat().st_size > MAX_BYTES for p in files):
                return "too_big"
            return "empty"
    finally:
        try:
            await status.delete()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# هندلرها
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text())


# ---------------------------------------------------------------------------
# ساخت سشن Telethon با چت (/makesession) — فقط پی‌وی، بدون ترمینال
# ---------------------------------------------------------------------------

def _normalize_phone(raw: str) -> str | None:
    """شماره را به فرمت +کدکشور درمی‌آورد؛ اگر نشد None."""
    phone = re.sub(r"[\s\-()]", "", raw.strip())
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if phone.startswith("0"):
        # با ۰ شروع شده (مثل ۰۹۱۲...)؛ کد کشور ندارد.
        return None
    if not phone.startswith("+"):
        phone = "+" + phone
    if not re.fullmatch(r"\+\d{8,15}", phone):
        return None
    return phone


async def _abort_makesession(update, context, text: str) -> None:
    """کلاینت Telethon را قطع و وضعیت /makesession را پاک می‌کند."""
    state = context.user_data.pop("makesession", None)
    client = (state or {}).get("client")
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            pass
    await update.message.reply_text(text)


async def _finish_makesession(update, context) -> None:
    """سشن را از کلاینت ذخیره می‌کند (حافظه + فایل) و وضعیت را پاک می‌کند.
    رشته سشن هیچ‌وقت توی چت فرستاده نمی‌شود."""
    state = context.user_data.pop("makesession", {})
    client = state.get("client")
    if client is None:
        await update.message.reply_text(
            "چیزی برای ذخیره نیست؛ دوباره /makesession را بزن."
        )
        return
    session_str = None
    try:
        session_str = client.session.save()
    except Exception:
        logger.exception("Could not save Telethon session string")
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    if not session_str:
        await update.message.reply_text(
            "ذخیره سشن نشد؛ دوباره /makesession را بزن. 😕"
        )
        return
    saved_to_file = _save_telethon_session(session_str)
    text = (
        "سشن ذخیره شد، MTProto فعال شد. ✅\n"
        "حالا فایل‌های بزرگ تا ۲ گیگابایت مستقیم فرستاده می‌شوند."
    )
    if not saved_to_file:
        text += (
            "\n(نکته: ذخیره فایل سشن نشد؛ بعد از ری‌استارت ربات "
            "باید دوباره بسازی.)"
        )
    await update.message.reply_text(text)


async def makesession_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """شروع ساخت سشن Telethon — فقط پی‌وی."""
    msg = update.message
    if msg is None:
        return
    if msg.chat.type != "private":
        await msg.reply_text(
            "ساخت سشن فقط توی پی‌وی کار می‌کند؛ توی گروه نمی‌شود. 🙂"
        )
        return
    if not TELETHON_AVAILABLE:
        await msg.reply_text(
            "Telethon روی سرور نصب نیست؛ فعلاً نمی‌شود سشن ساخت. 😕"
        )
        return
    if _telethon_api_credentials() is None:
        await msg.reply_text(
            "اول باید TELETHON_API_ID و TELETHON_API_HASH توی "
            "Variables ریل‌وی ست شده باشند."
        )
        return
    if telethon_configured():
        context.user_data["makesession"] = {"step": "await_overwrite_confirm"}
        await msg.reply_text(
            "سشن از قبل ساخته شده و MTProto فعال است. ✅\n"
            "می‌خواهی دوباره بسازی و جایگزینش کنی؟\n"
            "برای تایید «بله» را بفرست، برای لغو «خیر» را بفرست."
        )
        return
    context.user_data["makesession"] = {"step": "await_phone"}
    await msg.reply_text(
        "شماره تلگرامت را با کد کشور بفرست؛ مثلاً +98...\n"
        "تلگرام یک کد ورود برایت می‌فرستد.\n"
        "برای لغو، «لغو» را بفرست."
    )


async def handle_makesession_step(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """یک پیام متنی را در جریان /makesession پردازش می‌کند.
    True اگر پیام مصرف شد (و نباید به‌عنوان لینک پردازش شود)."""
    msg = update.message
    state = context.user_data.get("makesession")
    if not state or msg is None or not msg.text:
        return False
    text = msg.text.strip()
    step = state.get("step")

    if text in ("لغو", "انصراف"):
        await _abort_makesession(update, context, "لغو شد. 🙂")
        return True

    if step == "await_overwrite_confirm":
        if text in ("بله", "آره", "yes", "Yes"):
            context.user_data["makesession"] = {"step": "await_phone"}
            await msg.reply_text(
                "باشه. شماره تلگرامت را با کد کشور بفرست؛ مثلاً +98...\n"
                "برای لغو، «لغو» را بفرست."
            )
        else:
            await _abort_makesession(
                update, context,
                "لغو شد؛ سشن قبلی سر جایش ماند. 🙂",
            )
        return True

    if step == "await_phone":
        phone = _normalize_phone(text)
        if phone is None:
            await msg.reply_text(
                "شماره درست نیست. با کد کشور بفرست؛ مثلاً +98...\n"
                "برای لغو، «لغو» را بفرست."
            )
            return True
        creds = _telethon_api_credentials()
        if creds is None:
            await _abort_makesession(
                update, context,
                "TELETHON_API_ID و TELETHON_API_HASH ست نیستند؛ "
                "اول توی Variables ریل‌وی بذارشان.",
            )
            return True
        api_id, api_hash = creds
        client = TelegramClient(StringSession(), api_id, api_hash)
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
        except Exception:
            logger.exception("Telethon send_code_request failed")
            try:
                await client.disconnect()
            except Exception:
                pass
            context.user_data.pop("makesession", None)
            await msg.reply_text(
                "نتونستم کد بفرستم؛ شماره را چک کن و دوباره /makesession را بزن. 😕"
            )
            return True
        state["step"] = "await_code"
        state["phone"] = phone
        state["client"] = client
        state["phone_code_hash"] = sent.phone_code_hash
        await msg.reply_text(
            "کد ورود ۵ رقمی که تلگرام فرستاد را بفرست.\n"
            "برای لغو، «لغو» را بفرست."
        )
        return True

    if step == "await_code":
        code = re.sub(r"[\s\-]", "", text)
        if not re.fullmatch(r"\d{5}", code):
            await msg.reply_text(
                "کد باید ۵ رقم باشد؛ دوباره بفرست.\n"
                "برای لغو، «لغو» را بفرست."
            )
            return True
        client = state.get("client")
        if client is None:
            await _abort_makesession(
                update, context,
                "ارتباط قطع شد؛ دوباره /makesession را بزن.",
            )
            return True
        try:
            await client.sign_in(
                state.get("phone"), code,
                phone_code_hash=state.get("phone_code_hash"),
            )
        except SessionPasswordNeededError:
            state["step"] = "await_2fa"
            await msg.reply_text("رمز دومرحله‌ای حسابت را بفرست.")
            return True
        except Exception:
            logger.exception("Telethon sign_in failed")
            await _abort_makesession(
                update, context,
                "کد اشتباه بود یا منقضی شد؛ دوباره /makesession را بزن. 😕",
            )
            return True
        await _finish_makesession(update, context)
        return True

    if step == "await_2fa":
        client = state.get("client")
        if client is None:
            await _abort_makesession(
                update, context,
                "ارتباط قطع شد؛ دوباره /makesession را بزن.",
            )
            return True
        try:
            await client.sign_in(password=msg.text)
        except Exception:
            logger.exception("Telethon 2FA sign_in failed")
            await _abort_makesession(
                update, context,
                "رمز دومرحله‌ای اشتباه بود؛ دوباره /makesession را بزن. 😕",
            )
            return True
        await _finish_makesession(update, context)
        return True

    # وضعیت ناشناخته؛ پاکش کن تا گیر نکند.
    context.user_data.pop("makesession", None)
    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هر پیام متنی: اگر لینک اینستا/پورن‌هاب داشت، پردازش کن؛ اگر نه، رد شو."""
    msg = update.message
    if msg is None or not msg.text:
        return

    # اگر کاربر وسط ساخت سشن با /makesession است، پیامش را آن‌جا مصرف کن.
    if await handle_makesession_step(update, context):
        return

    url = find_url(msg.text)
    if not url:
        # توی پی‌وی یک راهنمای کوتاه بده؛ توی گروه ساکت باش تا اسپم نشه.
        if msg.chat.type == "private":
            await msg.reply_text(
                "لینک اینستاگرام یا پورن‌هاب رو بفرست تا دانلودش کنم. 🙂\n"
                "برای راهنما /start رو بزن."
            )
        return

    platform = detect_platform(url)
    if not platform:
        if msg.chat.type == "private":
            await msg.reply_text(
                "این لینک رو نمی‌شناسم. فقط لینک اینستاگرام و پورن‌هاب رو می‌تونم دانلود کنم."
            )
        return

    # اینستاگرام و پورن‌هاب: مستقیم دانلود کن
    result = await do_download_and_send(context.bot, msg.chat.id, url)
    if result == "too_big":
        await msg.reply_text(TOO_BIG_TEXT)
    elif result in ("empty", "error"):
        await msg.reply_text(ERROR_TEXT)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Update failed: %s", context.error)


# ---------------------------------------------------------------------------
# main — polling
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        print(
            "خطا: متغیر محیطی BOT_TOKEN ست نشده. "
            "تو Railway تب Variables مقدارش رو بذار.",
            file=sys.stderr,
        )
        sys.exit(1)

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("makesession", makesession_cmd))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(error_handler)

    logger.info("Downloader bot started (polling).")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
