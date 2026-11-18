#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
دانلودر تلگرام — اینستاگرام + پورن‌هاب (یوتیوب ندارد).
- پی‌وی و گروه.
- اینستا: دانلود مستقیم؛ کپشن فقط «@<یوزرنیم ربات> ❤️».
- پورن‌هاب: اول منوی انتخاب کیفیت، بعد دانلود با عکس کاور و
  پیشرفت هر ۵ ثانیه؛ ویدیو با کاور (thumbnail) فرستاده می‌شود.
- فایل بزرگ: یک سشن مشترک Telethon برای همه کاربرها
  (/data/telethon_session.txt یا TELETHON_SESSION_STRING) → تا ۲ گیگ
  با MTProto؛ اگر نباشد، تقسیم با ffmpeg.
- دانلودها در پس‌زمینه اجرا می‌شوند تا ربات به دستورهای دیگر
  جواب بدهد.
- BOT_TOKEN از متغیر محیطی.
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Telethon به‌صورت lazy وارد می‌شود تا اگر نصب نبود، ربات باز هم
# با مسیر معمولی Bot API کار کند.
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

# curl-cffi برای impersonation مرورگر در yt-dlp لازم است؛ اگر نصب نباشد،
# yt-dlp بدون impersonation کار می‌کند و پورن‌هاب ممکن است با 403 ردش کند.
try:
    import curl_cffi  # noqa: F401
    CURL_CFFI_AVAILABLE = True
except ImportError:  # pragma: no cover - curl-cffi not installed
    CURL_CFFI_AVAILABLE = False

# yt-dlp از طریق Python API انتظار یک شیء ImpersonateTarget دارد؛
# دادن رشته "chrome" باعث AssertionError می‌شود.
try:
    from yt_dlp.networking.impersonate import (
        ImpersonateTarget as _ImpersonateTarget,
    )
    _CHROME_IMPERSONATE_TARGET = _ImpersonateTarget.from_str("chrome")
except Exception:  # pragma: no cover - old yt-dlp or import failure
    _CHROME_IMPERSONATE_TARGET = None

# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("downloader-bot")

# سقف ارسال فایل با Bot API: ۵۰ مگابایت؛ با حاشیه امن ۴۸ مگ می‌گیریم.
MAX_BYTES = 48 * 1024 * 1024

# سقف ارسال فایل با MTProto (حساب کاربری Telethon): ۲ گیگابایت.
TELETHON_MAX_BYTES = 2 * 1024 * 1024 * 1024

# فقط یک دانلود هم‌زمان؛ بقیه صف می‌کشند.
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(1)


class ProgressTracker:
    """وضعیت دانلود yt-dlp؛ هوک از توی thread فقط چند عدد را به‌روز
    می‌کند و یک تسک جداگانه پیام پیشرفت را ویرایش می‌کند."""

    def __init__(self) -> None:
        self.downloaded = 0
        self.total = 0
        self.speed = 0.0
        self.eta = 0
        self.started_at = time.monotonic()

    def hook(self, d: dict) -> None:
        if d.get("status") == "downloading":
            self.downloaded = int(d.get("downloaded_bytes") or 0)
            self.total = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
            self.speed = float(d.get("speed") or 0)
            self.eta = int(d.get("eta") or 0)

    def percent(self) -> int:
        if not self.total:
            return 0
        return min(100, self.downloaded * 100 // self.total)


def _progress_text(pct: int) -> str:
    """متن پیام پیشرفت: نوار لودینگ + درصد. کوتاه."""
    pct = max(0, min(100, pct))
    filled = pct // 10
    bar = "▓" * filled + "░" * (10 - filled)
    return f"⏳ {bar} {pct}٪"


# ---------------------------------------------------------------------------
# سشن مشترک Telethon — یکی برای همه کاربرها
# ---------------------------------------------------------------------------
# سشن از سه جا می‌تواند بیاید (به ترتیب اولویت):
# ۱) حافظه — ساخته‌شده با /makesession
# ۲) متغیر محیطی TELETHON_SESSION_STRING
# ۳) فایل /data/telethon_session.txt روی Volume ریل‌وی
# سشن مال یک نفر نیست؛ هر کسی /makesession را بزند، همین یک سشن
# مشترک را می‌سازد/جایگزین می‌کند و همه کاربرها از همان استفاده می‌کنند.
TELETHON_SESSION_FILE = Path(
    os.environ.get("TELETHON_SESSION_FILE", "/data/telethon_session.txt")
)
_RUNTIME_SESSION_STRING: str | None = None


def get_telethon_session_string() -> str:
    """رشته سشن مشترک Telethon؛ خالی اگر هیچ‌جا نباشد."""
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
    """سشن مشترک را توی حافظه و فایل ذخیره می‌کند.
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
    """True اگر API ID/Hash ست باشند و سشن مشترک از حافظه، متغیر
    محیطی یا فایل بیاید و کتابخانه نصب باشد."""
    if not TELETHON_AVAILABLE:
        return False
    if _telethon_api_credentials() is None:
        return False
    return bool(get_telethon_session_string())


async def send_via_telethon(chat_id: int, path: Path, caption: str | None,
                            thumb: str | None = None) -> bool:
    """
    فایل را با MTProto (حساب کاربری، سشن مشترک) به همان چت می‌فرستد.
    سقف ۲ گیگابایت. در صورت هر خطایی False برمی‌گرداند تا مسیر
    تقسیم استفاده شود.
    نکته: حساب کاربری باید عضو گروه باشد (برای ارسال به گروه) یا با
    گیرنده دیالوگ داشته باشد (برای پی‌وی).
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
        kwargs = {"supports_streaming": True}
        if thumb:
            kwargs["thumb"] = thumb
        await client.send_file(
            chat_id,
            str(path),
            caption=caption,
            **kwargs,
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
لینک اینستاگرام یا پورن‌هاب رو بفرست تا دانلودش کنم.
برای پورن‌هاب، بعد از فرستادن لینک کیفیت رو انتخاب می‌کنی.
/makesession — برای فایل‌های بزرگ (فقط پی‌وی)"""

TOO_BIG_TEXT = "ویدیو خیلی بزرگه. 😕"

ERROR_TEXT = "نشد دانلودش کنم. 😕"


def help_text() -> str:
    return START_TEXT


# یوزرنیم ربات (برای کپشن اینستا)؛ یک بار گرفته و کش می‌شود.
_BOT_USERNAME: str | None = None


async def instagram_caption(bot) -> str:
    """کپشن ویدیوهای اینستا: فقط آیدی ربات + قلب."""
    global _BOT_USERNAME
    if _BOT_USERNAME is None:
        username = getattr(bot, "username", None)
        if not username:
            try:
                me = await bot.get_me()
                username = me.username
            except Exception:
                username = None
        _BOT_USERNAME = username or ""
    if _BOT_USERNAME:
        return f"@{_BOT_USERNAME} ❤️"
    return "❤️"


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

CHROME_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

PORNHUB_COOKIES_FILE = Path(
    os.environ.get("PORNHUB_COOKIES_FILE", "/data/cookies.txt")
)
_IMPERSONATION_WARNING_LOGGED = False


def get_pornhub_cookiefile() -> str | None:
    """مسیر فایل کوکی پورن‌هاب؛ None اگر چیزی نباشد.
    اولویت: متغیر PORNHUB_COOKIES (مسیر فایل یا متن خام فایل کوکی)،
    بعد فایل /data/cookies.txt روی Volume ریل‌وی.
    کوکی فقط برای پورن‌هاب استفاده می‌شود، نه اینستاگرام."""
    env_value = os.environ.get("PORNHUB_COOKIES", "").strip()
    if env_value:
        if os.path.isfile(env_value):
            return env_value
        if "\n" in env_value and "pornhub.com" in env_value:
            try:
                target = Path("/data/pornhub_cookies.txt")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(env_value, encoding="utf-8")
                return str(target)
            except OSError:
                try:
                    fd, tmp = tempfile.mkstemp(
                        prefix="ph-cookies-", suffix=".txt"
                    )
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(env_value)
                    return tmp
                except OSError:
                    pass
        logger.warning(
            "PORNHUB_COOKIES is set but is neither an existing file "
            "nor cookie-file text; ignoring it."
        )
        return None
    try:
        if PORNHUB_COOKIES_FILE.is_file():
            return str(PORNHUB_COOKIES_FILE)
    except OSError:
        pass
    return None


def _build_ydl_opts(url: str, height: int, outdir: str, tracker=None) -> dict:
    """تنظیمات yt-dlp: شبیه مرورگر واقعی + ری‌ترای."""
    global _IMPERSONATION_WARNING_LOGGED
    platform = detect_platform(url)
    if platform == "pornhub":
        referer = "https://www.pornhub.com/"
    elif platform == "instagram":
        referer = "https://www.instagram.com/"
    else:
        referer = "https://www.google.com/"

    ydl_opts: dict = {
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
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
        "progress_hooks": [tracker.hook] if tracker is not None else [],
        "http_headers": {
            "User-Agent": CHROME_USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        },
    }

    if CURL_CFFI_AVAILABLE and _CHROME_IMPERSONATE_TARGET is not None:
        ydl_opts["impersonate"] = _CHROME_IMPERSONATE_TARGET
    elif not _IMPERSONATION_WARNING_LOGGED:
        _IMPERSONATION_WARNING_LOGGED = True
        logger.warning(
            "curl-cffi is not installed or ImpersonateTarget could not "
            "be built; yt-dlp will run without browser impersonation "
            "(Pornhub may return 403)."
        )

    if platform == "pornhub":
        cookiefile = get_pornhub_cookiefile()
        if cookiefile:
            ydl_opts["cookiefile"] = cookiefile
            logger.info("Using Pornhub cookiefile: %s", cookiefile)

    return ydl_opts


def _fetch_info_sync(url: str) -> dict | None:
    """اطلاعات ویدیو بدون دانلود فایل (عنوان + آدرس کاور)."""
    try:
        ydl_opts = _build_ydl_opts(url, 720, tempfile.gettempdir())
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return info if isinstance(info, dict) else None
    except Exception:
        logger.exception("yt-dlp info fetch failed for %s", url)
        return None


def _download_cover_sync(thumb_url: str | None, tmpdir: str) -> Path | None:
    """کاور ویدیو را دانلود می‌کند و به JPG تبدیل می‌کند (اگر webp/png
    بود). None اگر نشد."""
    if not thumb_url:
        return None
    try:
        req = urllib.request.Request(
            thumb_url,
            headers={
                "User-Agent": CHROME_USER_AGENT,
                "Referer": "https://www.pornhub.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            ctype = ""
            try:
                ctype = resp.headers.get_content_type()
            except Exception:
                pass
        if not data:
            return None
        low = thumb_url.lower().split("?")[0]
        needs_convert = (
            low.endswith(".webp") or low.endswith(".png")
            or ctype in ("image/webp", "image/png")
        )
        if needs_convert:
            raw_ext = ".webp" if "webp" in (low + ctype) else ".png"
            raw = Path(tmpdir) / f"cover{raw_ext}"
            raw.write_bytes(data)
            jpg = Path(tmpdir) / "cover.jpg"
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", str(raw), str(jpg)],
                capture_output=True, timeout=60,
            )
            if r.returncode == 0 and jpg.is_file() and jpg.stat().st_size > 0:
                return jpg
            return None
        path = Path(tmpdir) / "cover.jpg"
        path.write_bytes(data)
        return path if path.stat().st_size > 0 else None
    except Exception:
        logger.exception("Cover download failed")
        return None


def _probe_height_sync(url: str) -> int | None:
    """بدون دانلود فایل، حجم تقریبی هر کیفیت را می‌پرسد و بالاترین
    کیفیتی که زیر ۴۸ مگ جا می‌شود را برمی‌گرداند. None یعنی حجم
    معلوم نشد."""
    for height in (720, 480, 360):
        try:
            ydl_opts = _build_ydl_opts(url, height, tempfile.gettempdir())
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            logger.exception("yt-dlp probe failed at %dp for %s", height, url)
            return None
        if not isinstance(info, dict):
            return None
        size = info.get("filesize") or info.get("filesize_approx")
        if not size:
            return None
        if int(size) <= MAX_BYTES:
            return height
    return 360


def _download_once(url: str, height: int, outdir: str, tracker=None) -> tuple[str, list[Path]]:
    """یک بار دانلود با سقف کیفیت height. برمی‌گرداند: (عنوان، فهرست فایل‌ها)."""
    ydl_opts = _build_ydl_opts(url, height, outdir, tracker=tracker)

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
        segment_time = max(30, int(duration * MAX_BYTES * 0.92 / size))
    else:
        segment_time = 300

    workdir.mkdir(parents=True, exist_ok=True)

    for _attempt in range(3):
        pattern = str(workdir / f"{path.stem}_part%03d.mp4")
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
        segment_time = max(15, segment_time // 2)

    parts = sorted(workdir.glob(f"{path.stem}_part*.mp4"))
    return [p for p in parts if p.is_file() and p.stat().st_size > 0] or [path]


async def download_best_effort(url: str, tmpdir: str, prefer_telethon: bool = False,
                               tracker=None):
    """
    دانلود با کیفیتی که از قبل اندازه‌اش معلوم شده (probe).
    برمی‌گرداند: (title, files, was_split)
    اگر حجم معلوم نشد، حلقه قدیمی (۷۲۰p، بعد ۴۸۰p، بعد ۳۶۰p) به‌عنوان
    fallback می‌ماند. اگر prefer_telethon=True باشد، مستقیم ۷۲۰p
    دانلود می‌شود تا اول Telethon امتحان شود.
    """
    if prefer_telethon:
        subdir = Path(tmpdir) / "h720"
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            title, files = await asyncio.to_thread(
                _download_once, url, 720, str(subdir), tracker
            )
        except Exception:
            logger.exception("yt-dlp failed at 720p for %s", url)
            return "", [], False
        return title, files, False

    probe_height = await asyncio.to_thread(_probe_height_sync, url)
    if probe_height is not None:
        logger.info("Probe chose %dp for %s", probe_height, url)
        subdir = Path(tmpdir) / f"h{probe_height}"
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            title, files = await asyncio.to_thread(
                _download_once, url, probe_height, str(subdir), tracker
            )
        except Exception:
            logger.exception(
                "yt-dlp failed at %dp for %s", probe_height, url
            )
            return "", [], False
        if not files:
            return "", [], False
        return title, files, False

    logger.info("Probe gave no size for %s; falling back to 720→480→360", url)
    best_candidate: tuple[str, list[Path]] | None = None
    for height in (720, 480, 360):
        subdir = Path(tmpdir) / f"h{height}"
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            title, files = await asyncio.to_thread(
                _download_once, url, height, str(subdir), tracker
            )
        except Exception:
            logger.exception("yt-dlp failed at %dp for %s", height, url)
            continue
        if not files:
            continue
        main = max(files, key=lambda p: p.stat().st_size)
        if main.stat().st_size <= MAX_BYTES:
            return title, files, False
        if best_candidate is None or main.stat().st_size < max(
            p.stat().st_size for p in best_candidate[1]
        ):
            best_candidate = (title, files)

    if best_candidate is None:
        return "", [], False
    title, files = best_candidate
    main = max(files, key=lambda p: p.stat().st_size)
    if main.suffix.lower() not in VIDEO_EXTS:
        return title, files, False
    parts_dir = Path(tmpdir) / "parts"
    parts = await asyncio.to_thread(_split_video_sync, main, parts_dir)
    if len(parts) > 1 and all(p.stat().st_size <= MAX_BYTES for p in parts):
        return title, parts, True
    return title, files, False


# ---------------------------------------------------------------------------
# ارسال فایل به چت
# ---------------------------------------------------------------------------

async def send_files(bot, chat_id: int, files: list[Path],
                     captions: list | None = None,
                     thumb: Path | None = None) -> bool:
    """فایل‌ها را می‌فرستد. captions هم‌طول files است.
    thumb (کاور) فقط برای اولین ویدیو استفاده می‌شود.
    اگر هیچ فایلی قابل ارسال نباشد False برمی‌گرداند."""
    if not files:
        return False

    captions = captions or [None] * len(files)
    sent_any = False
    for i, path in enumerate(files):
        if path.stat().st_size > MAX_BYTES:
            continue
        caption = captions[i] if i < len(captions) else None
        ext = path.suffix.lower()
        try:
            if ext in VIDEO_EXTS:
                thumb_f = None
                if thumb is not None and i == 0 and thumb.is_file():
                    thumb_f = open(thumb, "rb")
                try:
                    with open(path, "rb") as f:
                        await bot.send_video(
                            chat_id=chat_id, video=f,
                            caption=caption, supports_streaming=True,
                            thumb=thumb_f,
                        )
                finally:
                    if thumb_f is not None:
                        thumb_f.close()
            elif ext == ".mp3":
                with open(path, "rb") as f:
                    await bot.send_audio(chat_id=chat_id, audio=f)
            elif ext in (".jpg", ".jpeg", ".png", ".webp"):
                with open(path, "rb") as f:
                    await bot.send_photo(
                        chat_id=chat_id, photo=f, caption=caption,
                    )
            else:
                with open(path, "rb") as f:
                    await bot.send_document(
                        chat_id=chat_id, document=f, caption=caption,
                    )
            sent_any = True
        except Exception:
            logger.exception("send failed for %s", path)

    return sent_any


async def _deliver(bot, chat_id: int, tmpdir: str, title: str,
                   files: list[Path], was_split: bool,
                   caption_mode: str, thumb: Path | None = None) -> bool:
    """فایل‌های دانلودشده را می‌فرستد و True برمی‌گرداند اگر چیزی
    فرستاده شد.
    caption_mode: "instagram" → کپشن همه قسمت‌ها «@ربات ❤️»؛
    "title" → کپشن عنوان (قسمت‌ها با شماره قسمت).
    ترتیب: ۱) فایل‌های کوچک با Bot API؛ ۲) فایل‌های بزرگ اول با
    Telethon (سشن مشترک)، بعد تقسیم با ffmpeg."""
    if not files:
        return False

    async def build_captions(n: int, split: bool) -> list:
        if caption_mode == "instagram":
            ig = await instagram_caption(bot)
            return [ig] * n
        caps = []
        for i in range(n):
            if split and n > 1:
                caps.append(
                    f"{title[:150]}\nقسمت {i + 1} از {n}" if title
                    else f"قسمت {i + 1} از {n}"
                )
            else:
                caps.append(title[:200] if (i == 0 and title) else None)
        return caps

    small = [p for p in files if p.stat().st_size <= MAX_BYTES]
    large = [p for p in files if p.stat().st_size > MAX_BYTES]
    sent = False

    if small:
        small_caps = [
            (await build_captions(len(files), was_split))[files.index(p)]
            for p in small
        ]
        sent = await send_files(bot, chat_id, small, small_caps, thumb=thumb)

    for path in large:
        if path.stat().st_size > TELETHON_MAX_BYTES:
            continue
        caps = await build_captions(len(files), was_split)
        cap = caps[files.index(path)]
        if telethon_configured():
            if await send_via_telethon(
                chat_id, path, cap,
                thumb=str(thumb) if thumb is not None else None,
            ):
                sent = True
                continue
            logger.warning(
                "Telethon send failed for %s; falling back to split",
                path,
            )
        if path.suffix.lower() in VIDEO_EXTS:
            parts_dir = Path(tmpdir) / f"parts-{path.stem}"
            parts = await asyncio.to_thread(
                _split_video_sync, path, parts_dir
            )
            if len(parts) > 1 and all(
                p.stat().st_size <= MAX_BYTES for p in parts
            ):
                part_caps = await build_captions(len(parts), True)
                if await send_files(
                    bot, chat_id, parts, part_caps, thumb=thumb
                ):
                    sent = True
                continue

    return sent


# ---------------------------------------------------------------------------
# دانلود اینستاگرام و پورن‌هاب (در پس‌زمینه اجرا می‌شوند)
# ---------------------------------------------------------------------------

async def do_instagram_download(bot, chat_id: int, url: str) -> str:
    """دانلود اینستا. برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'"""
    status = await bot.send_message(chat_id=chat_id, text="⏳")
    try:
        async with DOWNLOAD_SEMAPHORE:
            with tempfile.TemporaryDirectory(prefix="dl-") as tmpdir:
                try:
                    title, files, was_split = await download_best_effort(
                        url, tmpdir, prefer_telethon=telethon_configured(),
                    )
                except Exception:
                    logger.exception("download failed for %s", url)
                    return "error"
                if not files:
                    return "empty"
                sent = await _deliver(
                    bot, chat_id, tmpdir, title, files, was_split,
                    "instagram",
                )
                if sent:
                    return "ok"
                if all(p.stat().st_size > MAX_BYTES for p in files):
                    return "too_big"
                return "empty"
    finally:
        try:
            await status.delete()
        except Exception:
            pass


async def _watch_pornhub_progress(bot, chat_id: int, message_id: int,
                                  tracker: ProgressTracker,
                                  done: asyncio.Event,
                                  is_photo: bool) -> None:
    """هر ۵ ثانیه پیام پیشرفت را با درصد فعلی ویرایش می‌کند."""
    last_pct = -1
    try:
        while not done.is_set():
            await asyncio.sleep(5)
            pct = tracker.percent()
            if pct == last_pct:
                continue
            last_pct = pct
            try:
                if is_photo:
                    await bot.edit_message_caption(
                        chat_id=chat_id, message_id=message_id,
                        caption=_progress_text(pct),
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=_progress_text(pct),
                    )
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


async def do_pornhub_download(bot, chat_id: int, url: str,
                              height: int) -> str:
    """دانلود پورن‌هاب با کیفیت انتخاب‌شده.
    برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'
    اول اطلاعات + کاور گرفته می‌شود، عکس کاور با نوار پیشرفت
    فرستاده می‌شود و هر ۵ ثانیه ویرایش می‌شود؛ ویدیو با همان کاور
    به‌عنوان thumbnail فرستاده می‌شود. اگر دانلود با کیفیت انتخاب‌شده
    نشد، نردبان کیفیت (probe/720→480→360) به‌عنوان fallback اجرا
    می‌شود."""
    async with DOWNLOAD_SEMAPHORE:
        with tempfile.TemporaryDirectory(prefix="ph-") as tmpdir:
            tracker = ProgressTracker()
            done = asyncio.Event()
            progress_msg = None
            is_photo = False
            watcher = None
            try:
                # ۱) اطلاعات + کاور (بدون دانلود ویدیو)
                info = await asyncio.to_thread(_fetch_info_sync, url)
                title = str((info or {}).get("title") or "")
                cover = None
                if info:
                    cover = await asyncio.to_thread(
                        _download_cover_sync, info.get("thumbnail"), tmpdir
                    )

                # ۲) پیام پیشرفت با کاور
                try:
                    if cover is not None:
                        with open(cover, "rb") as f:
                            progress_msg = await bot.send_photo(
                                chat_id=chat_id, photo=f,
                                caption=_progress_text(0),
                            )
                        is_photo = True
                    else:
                        progress_msg = await bot.send_message(
                            chat_id=chat_id, text=_progress_text(0),
                        )
                except Exception:
                    progress_msg = None
                    logger.exception("Could not send progress message")

                if progress_msg is not None:
                    watcher = asyncio.create_task(
                        _watch_pornhub_progress(
                            bot, chat_id, progress_msg.message_id,
                            tracker, done, is_photo,
                        )
                    )

                # ۳) دانلود با کیفیت انتخاب‌شده
                files: list[Path] = []
                was_split = False
                subdir = Path(tmpdir) / f"h{height}"
                subdir.mkdir(parents=True, exist_ok=True)
                try:
                    dl_title, files = await asyncio.to_thread(
                        _download_once, url, height, str(subdir), tracker
                    )
                    if dl_title:
                        title = dl_title
                except Exception:
                    logger.exception(
                        "yt-dlp failed at %dp for %s", height, url
                    )
                    files = []

                # ۴) اگر نشد، fallback به نردبان کیفیت
                if not files:
                    title, files, was_split = await download_best_effort(
                        url, tmpdir,
                        prefer_telethon=telethon_configured(),
                        tracker=tracker,
                    )
                    if not files:
                        return "error"

                # ۵) ارسال (ویدیو با کاور)
                sent = await _deliver(
                    bot, chat_id, tmpdir, title, files, was_split,
                    "title", thumb=cover,
                )
                if sent:
                    return "ok"
                if all(p.stat().st_size > MAX_BYTES for p in files):
                    return "too_big"
                return "empty"
            finally:
                done.set()
                if watcher is not None:
                    watcher.cancel()
                if progress_msg is not None:
                    try:
                        await progress_msg.delete()
                    except Exception:
                        pass


async def _background_download(bot, chat_id: int, url: str,
                               platform: str, height: int | None = None) -> None:
    """دانلود را در پس‌زمینه اجرا می‌کند تا هندلر فوراً برگردد و
    ربات به دستورهای دیگر جواب بدهد. پیام خطا را خودش می‌فرستد."""
    try:
        if platform == "pornhub":
            result = await do_pornhub_download(bot, chat_id, url, height or 720)
        else:
            result = await do_instagram_download(bot, chat_id, url)
    except Exception:
        logger.exception("download task failed for %s", url)
        result = "error"
    try:
        if result == "too_big":
            await bot.send_message(chat_id=chat_id, text=TOO_BIG_TEXT)
        elif result in ("empty", "error"):
            await bot.send_message(chat_id=chat_id, text=ERROR_TEXT)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# منوی انتخاب کیفیت پورن‌هاب
# ---------------------------------------------------------------------------

# دانلودهای پورن‌هاب در انتظار انتخاب کیفیت: key کوتاه → {url, chat_id}
PENDING_PORNHUB: dict[str, dict] = {}


async def _offer_pornhub_quality(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE,
                                 url: str) -> None:
    """منوی شیشه‌ای انتخاب کیفیت: دو ستونه، با ایموجی و برچسب تمیز."""
    key = uuid.uuid4().hex[:8]
    PENDING_PORNHUB[key] = {
        "url": url,
        "chat_id": update.message.chat.id,
    }
    keyboard = [
        [
            InlineKeyboardButton("✨ 1080p", callback_data=f"ph:{key}:1080"),
            InlineKeyboardButton("🎞️ 720p", callback_data=f"ph:{key}:720"),
        ],
        [
            InlineKeyboardButton("📺 480p", callback_data=f"ph:{key}:480"),
            InlineKeyboardButton("📱 360p", callback_data=f"ph:{key}:360"),
        ],
        [InlineKeyboardButton("❌ لغو", callback_data=f"ph:{key}:cancel")],
    ]
    await update.message.reply_text(
        "🎬 کیفیت ویدیو رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def pornhub_quality_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """کلیک روی منوی کیفیت پورن‌هاب: دانلود با همان کیفیت، در پس‌زمینه."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "ph":
        return
    _, key, choice = parts
    pending = PENDING_PORNHUB.pop(key, None)
    if pending is None:
        try:
            await query.edit_message_text("منقضی شده؛ لینک رو دوباره بفرست.")
        except Exception:
            pass
        return
    if choice == "cancel":
        try:
            await query.edit_message_text("لغو شد.")
        except Exception:
            pass
        return
    try:
        height = int(choice)
    except ValueError:
        return
    try:
        await query.delete_message()
    except Exception:
        try:
            await query.edit_message_text("⏳")
        except Exception:
            pass
    asyncio.create_task(
        _background_download(
            context.bot, pending["chat_id"], pending["url"],
            "pornhub", height,
        )
    )


# ---------------------------------------------------------------------------
# هندلرها
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text())


# ---------------------------------------------------------------------------
# ساخت سشن مشترک Telethon با چت (/makesession) — فقط پی‌وی، بدون ترمینال
# ---------------------------------------------------------------------------

def _normalize_phone(raw: str) -> str | None:
    """شماره را به فرمت +کدکشور درمی‌آورد؛ اگر نشد None."""
    phone = re.sub(r"[\s\-()]", "", raw.strip())
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if phone.startswith("0"):
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
    """سشن مشترک را ذخیره می‌کند (حافظه + فایل) و وضعیت را پاک می‌کند.
    رشته سشن هیچ‌وقت توی چت فرستاده نمی‌شود."""
    state = context.user_data.pop("makesession", {})
    client = state.get("client")
    if client is None:
        await update.message.reply_text("دوباره /makesession بزن.")
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
        await update.message.reply_text("ذخیره نشد. دوباره /makesession بزن.")
        return
    saved_to_file = _save_telethon_session(session_str)
    text = "انجام شد. ✅"
    if not saved_to_file:
        text += "\nبعد از ری‌استارت باید دوباره بسازی."
    await update.message.reply_text(text)


async def makesession_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """شروع ساخت سشن مشترک Telethon — فقط پی‌وی."""
    msg = update.message
    if msg is None:
        return
    if msg.chat.type != "private":
        await msg.reply_text("فقط پی‌وی.")
        return
    if not TELETHON_AVAILABLE:
        await msg.reply_text("Telethon نصب نیست.")
        return
    if _telethon_api_credentials() is None:
        await msg.reply_text("API ID و Hash ست نیست.")
        return
    if telethon_configured():
        context.user_data["makesession"] = {"step": "await_overwrite_confirm"}
        await msg.reply_text(
            "از قبل فعاله. جایگزین بشه؟\n«بله» یا «خیر»"
        )
        return
    context.user_data["makesession"] = {"step": "await_phone"}
    await msg.reply_text(
        "شماره‌ت رو با کد کشور بفرست. (مثلاً +98...)\nبرای لغو «لغو» رو بفرست."
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
        await _abort_makesession(update, context, "لغو شد.")
        return True

    if step == "await_overwrite_confirm":
        if text in ("بله", "آره", "yes", "Yes"):
            context.user_data["makesession"] = {"step": "await_phone"}
            await msg.reply_text("شماره‌ت رو با کد کشور بفرست.")
        else:
            await _abort_makesession(update, context, "لغو شد.")
        return True

    if step == "await_phone":
        phone = _normalize_phone(text)
        if phone is None:
            await msg.reply_text("شماره درست نیست. با کد کشور بفرست.")
            return True
        creds = _telethon_api_credentials()
        if creds is None:
            await _abort_makesession(
                update, context, "API ID و Hash ست نیست.",
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
            await msg.reply_text("نتونستم کد بفرستم. دوباره /makesession بزن.")
            return True
        state["step"] = "await_code"
        state["phone"] = phone
        state["client"] = client
        state["phone_code_hash"] = sent.phone_code_hash
        await msg.reply_text("کد ۵ رقمی رو بفرست.")
        return True

    if step == "await_code":
        code = re.sub(r"[\s\-]", "", text)
        if not re.fullmatch(r"\d{5}", code):
            await msg.reply_text("کد باید ۵ رقم باشه.")
            return True
        client = state.get("client")
        if client is None:
            await _abort_makesession(
                update, context, "قطع شد. دوباره /makesession بزن.",
            )
            return True
        try:
            await client.sign_in(
                state.get("phone"), code,
                phone_code_hash=state.get("phone_code_hash"),
            )
        except SessionPasswordNeededError:
            state["step"] = "await_2fa"
            await msg.reply_text("رمز دومرحله‌ای رو بفرست.")
            return True
        except Exception:
            logger.exception("Telethon sign_in failed")
            await _abort_makesession(
                update, context, "کد اشتباهه. دوباره /makesession بزن.",
            )
            return True
        await _finish_makesession(update, context)
        return True

    if step == "await_2fa":
        client = state.get("client")
        if client is None:
            await _abort_makesession(
                update, context, "قطع شد. دوباره /makesession بزن.",
            )
            return True
        try:
            await client.sign_in(password=msg.text)
        except Exception:
            logger.exception("Telethon 2FA sign_in failed")
            await _abort_makesession(
                update, context, "رمز اشتباهه. دوباره /makesession بزن.",
            )
            return True
        await _finish_makesession(update, context)
        return True

    context.user_data.pop("makesession", None)
    return False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هر پیام متنی: لینک اینستا/پورن‌هاب را پردازش کن؛ اگر نه، رد شو.
    دانلود در پس‌زمینه اجرا می‌شود تا ربات به بقیه دستورها جواب بدهد."""
    msg = update.message
    if msg is None or not msg.text:
        return

    if await handle_makesession_step(update, context):
        return

    url = find_url(msg.text)
    if not url:
        if msg.chat.type == "private":
            await msg.reply_text("لینک اینستاگرام یا پورن‌هاب رو بفرست.")
        return

    platform = detect_platform(url)
    if not platform:
        if msg.chat.type == "private":
            await msg.reply_text("فقط اینستاگرام و پورن‌هاب.")
        return

    if platform == "pornhub":
        # پورن‌هاب: اول منوی انتخاب کیفیت، دانلود بعد از انتخاب کاربر.
        await _offer_pornhub_quality(update, context, url)
        return

    # اینستاگرام: دانلود مستقیم، در پس‌زمینه.
    asyncio.create_task(
        _background_download(context.bot, msg.chat.id, url, "instagram")
    )


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

    app = Application.builder().token(token).concurrent_updates(10).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("makesession", makesession_cmd))
    app.add_handler(CallbackQueryHandler(pornhub_quality_callback, pattern=r"^ph:"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(error_handler)

    logger.info("Downloader bot started (polling).")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
