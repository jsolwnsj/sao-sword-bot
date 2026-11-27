#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
دانلودر تلگرام — اینستاگرام + تیک‌تاک + یوتیوب + پورن‌هاب + ساندکلود + پینترست.
- پی‌وی و گروه.
- اینستا، تیک‌تاک و پینترست: دانلود مستقیم؛ کپشن فقط «@<یوزرنیم ربات> ❤️».
- پینترست: پین عکسی با کیفیت اصلی (originals)؛ پین چندعکسی همه عکس‌ها
  را در یک آلبوم می‌فرستد؛ پین ویدیویی مثل تیک‌تاک با yt-dlp دانلود
  می‌شود. لینک pin.it هم باز می‌شود؛ لینک بورد/پروفایل پین تکی نیست.
- یوتیوب و پورن‌هاب: اول منوی انتخاب کیفیت، بعد دانلود با عکس کاور و
  پیشرفت هر ۵ ثانیه؛ ویدیو با کاور (thumbnail) فرستاده می‌شود.
  یوتیوب یک گزینه «صوتی (mp3)» هم دارد.
- ساندکلود: اول کاور آهنگ با اسم آهنگ و خواننده، بعد فایل صوتی
  mp3 با عنوان و خواننده درست.
- فایل بزرگ: اول با کیفیت پایین‌تر مستقیم دانلود می‌شود
  (۷۲۰p، بعد ۴۸۰p، بعد ۳۶۰p). اگر فایل باز هم بالای ۴۸ مگ بود،
  **خود ربات** با Telethon bot client (MTProto با BOT_TOKEN،
  نه سشن حساب کاربری) تا ۲ گیگابایت می‌فرستد — فرستنده خود
  ربات است، نه اکانت؛ نه تقسیم می‌شود، نه فشرده‌سازی. تقسیم
  فقط آخرین راه است و سقف ۱۰ قسمت دارد (قسمت‌ها نزدیک ۴۸ مگ‌اند؛
  باگ ۱۵۲ قسمت که از segment_time خیلی کوچک می‌آمد رفع شده است).
  ارسال با حساب کاربری (سشن Telethon) فقط fallback است و فقط
  وقتی TELETHON_SEND_ENABLED=true ست شده باشد استفاده می‌شود.
- پیام پیشرفت همه فازها را نشان می‌دهد: آماده‌سازی، دانلود،
  ارسال مستقیم، تقسیم و آپلود — هر کدام با نوار،
  درصد، سرعت و ETA؛ هر ۵ ثانیه در همان پیام ویرایش می‌شود.
- تا ۳ دانلود هم‌زمان؛ دانلود چهارم به بعد توی صف می‌ماند.
  هر دانلود پوشه، پیام و ترکر خودش را دارد.
- ارسال سریع پورن‌هاب: اول سعی می‌شود لینک مستقیم mp4 (بدون
  دانلود روی ریل‌وی) مستقیم به تلگرام فرستاده شود؛ اگر نشد
  (لینک IP-bound است یا تلگرام نمی‌تواند بگیرد)، مسیر قدیمی
  دانلود-با-فرگمنت‌های موازی اجرا می‌شود.
- دانلودها در پس‌زمینه اجرا می‌شوند تا ربات به دستورهای دیگر
  جواب بدهد.
- BOT_TOKEN از متغیر محیطی.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, quote, urlencode, urlparse
import uuid
from pathlib import Path

import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
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
    from telethon.sessions import StringSession
    TELETHON_AVAILABLE = True
except ImportError:  # pragma: no cover - telethon not installed
    TelegramClient = None  # type: ignore[assignment]
    StringSession = None  # type: ignore[assignment]
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

# سقف ارسال فایل با Telethon bot client (خود ربات با BOT_TOKEN،
# MTProto): ۲ گیگابایت — همان سقف MTProto، ولی فرستنده خود ربات
# است، نه حساب کاربری. سقف ۵۰ مگ فقط برای Bot API از طریق HTTP
# است؛ MTProto آن را ندارد.
BOT_TELETHON_MAX_BYTES = 2 * 1024 * 1024 * 1024

# سقف تعداد قسمت‌های تقسیم: اگر فایل برای جا شدن زیر ۴۸ مگ به
# بیشتر از ۱۰ قسمت نیاز داشته باشد، اصلاً تقسیم نمی‌شود (به‌جای
# آن کیفیت پایین‌تر دانلود می‌شود یا با bot client فرستاده
# می‌شود). این سقف باگ ۱۵۲ قسمت را رفع می‌کند: قبلاً segment_time
# حداقل ۳۰ ثانیه بود و در retry تا ۱۵ ثانیه نصف می‌شد، پس برای
# ویدیوی طولانی، ده‌ها قسمت خیلی کوچک ساخته می‌شد.
MAX_SPLIT_PARTS = 10

# حداکثر ۳ دانلود هم‌زمان؛ دانلود چهارم به بعد توی صف می‌ماند و
# به کاربر گفته می‌شود. هر دانلود پوشه، پیام پیشرفت و ترکر خودش را
# دارد، پس یک دانلود پورن‌هاب هیچ‌وقت دانلود ریلز کاربر دیگر را
# بلاک نمی‌کند و ربات هم موقع دانلود به دستورها جواب می‌دهد.
MAX_CONCURRENT_DOWNLOADS = 3
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)


def _fmt_speed(bps: float) -> str:
    """سرعت به شکل خوانا: 512KiB/s یا 1.2MiB/s؛ خالی اگر معلوم نیست."""
    if not bps or bps <= 0:
        return ""
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f}MiB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f}KiB/s"
    return f"{bps:.0f}B/s"


def _fmt_eta(seconds: int) -> str:
    """ETA به شکل mm:ss؛ خالی اگر معلوم نیست."""
    if not seconds or seconds <= 0:
        return ""
    m, s = divmod(int(seconds), 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _bar(pct: int) -> str:
    pct = max(0, min(100, pct))
    filled = pct // 10
    return "▓" * filled + "░" * (10 - filled)


# فازهای پیام پیشرفت: (آیکون، برچسب کوتاه)
_PHASE_META = {
    "info": ("⏳", "آماده‌سازی"),
    "download": ("📥", "دانلود"),
    "direct": ("🔗", "ارسال مستقیم"),
    "split": ("✂️", "تقسیم"),
    "upload": ("📤", "آپلود"),
    "done": ("✅", "تمام شد"),
}


class ProgressTracker:
    """وضعیت همه فازها: آماده‌سازی، دانلود، ارسال مستقیم،
    تقسیم، آپلود. هوک yt-dlp و ffmpeg و ارسال‌کننده‌ها
    از توی thread فقط چند عدد را به‌روز می‌کنند و یک تسک جداگانه
    پیام پیشرفت را هر ۵ ثانیه ویرایش می‌کند. هیچ فازی ساکت نیست."""

    def __init__(self) -> None:
        self.phase = "info"
        # درصد فاز فعلی؛ None یعنی درصد عددی ندارد (مثلاً آماده‌سازی).
        self.phase_percent: int | None = None
        self.downloaded = 0
        self.total = 0
        self.speed = 0.0
        self.eta = 0
        self.started_at = time.monotonic()
        self.upload_done_parts = 0
        self.upload_total_parts = 0
        self.upload_bytes = 0
        self.upload_total_bytes = 0
        self.upload_started_at: float | None = None

    def set_phase(self, phase: str, percent: int | None = None) -> None:
        self.phase = phase
        self.phase_percent = percent

    def hook(self, d: dict) -> None:
        if d.get("status") == "downloading":
            self.phase = "download"
            self.downloaded = int(d.get("downloaded_bytes") or 0)
            self.total = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
            self.speed = float(d.get("speed") or 0)
            self.eta = int(d.get("eta") or 0)

    def percent(self) -> int:
        if not self.total:
            return 0
        return min(100, self.downloaded * 100 // self.total)

    def begin_upload(self, total_parts: int, total_bytes: int) -> None:
        """شروع فاز آپلود: درصد از اینجا به بعد درصد آپلود است."""
        self.phase = "upload"
        self.phase_percent = 0
        self.upload_total_parts = total_parts
        self.upload_done_parts = 0
        self.upload_total_bytes = total_bytes
        self.upload_bytes = 0
        self.upload_started_at = time.monotonic()

    def mark_upload_part_done(self, size: int) -> None:
        self.upload_done_parts += 1
        self.upload_bytes += int(size)
        self.phase_percent = self.upload_percent()

    def upload_percent(self) -> int:
        if self.upload_total_bytes:
            return min(100, self.upload_bytes * 100 // self.upload_total_bytes)
        if self.upload_total_parts:
            return min(
                100, self.upload_done_parts * 100 // self.upload_total_parts
            )
        return 0

    def _upload_speed(self) -> float:
        if self.upload_started_at is None or self.upload_bytes <= 0:
            return 0.0
        elapsed = time.monotonic() - self.upload_started_at
        if elapsed <= 0:
            return 0.0
        return self.upload_bytes / elapsed

    def _upload_eta(self) -> int:
        speed = self._upload_speed()
        if speed <= 0 or not self.upload_total_bytes:
            return 0
        remaining = self.upload_total_bytes - self.upload_bytes
        return max(0, int(remaining / speed))

    def display_percent(self) -> int:
        if self.phase == "upload":
            return self.upload_percent()
        if self.phase == "download":
            return self.percent()
        return self.phase_percent if self.phase_percent is not None else 0

    def display_text(self) -> str:
        icon, label = _PHASE_META.get(self.phase, ("⏳", ""))
        if self.phase == "download":
            pct = self.percent()
            extra = " • ".join(
                x for x in (_fmt_speed(self.speed), _fmt_eta(self.eta)) if x
            )
            text = f"{icon} {label} {_bar(pct)} {pct}٪"
            return text + (f" • {extra}" if extra else "")
        if self.phase == "upload":
            pct = self.upload_percent()
            extra = " • ".join(
                x
                for x in (
                    _fmt_speed(self._upload_speed()),
                    _fmt_eta(self._upload_eta()),
                )
                if x
            )
            text = f"{icon} {label} {_bar(pct)} {pct}٪"
            return text + (f" • {extra}" if extra else "")
        if self.phase == "split":
            if self.phase_percent is None:
                return f"{icon} {label}…"
            pct = self.phase_percent
            return f"{icon} {label} {_bar(pct)} {pct}٪"
        if self.phase == "done":
            return f"{icon} {label}"
        return f"{icon} {label}…"


def _progress_text(pct: int, phase: str = "download") -> str:
    """متن اولیه پیام پیشرفت (قبل از اینکه ترکر داده داشته باشد)."""
    icon, label = _PHASE_META.get(phase, ("⏳", ""))
    if phase in ("info", "direct"):
        return f"{icon} {label}…"
    return f"{icon} {label} {_bar(pct)} {pct}٪"


# ---------------------------------------------------------------------------
# سشن مشترک Telethon — یکی برای همه کاربرها
# ---------------------------------------------------------------------------
# سشن فقط از دو جا می‌تواند بیاید (به ترتیب اولویت):
# ۱) متغیر محیطی TELETHON_SESSION_STRING
# ۲) فایل /data/telethon_session.txt روی Volume ریل‌وی
# سشن را با get_session.py (روی کامپیوتر) می‌سازی و رشته‌اش را
# توی Variables ریل‌وی می‌گذاری؛ دستور /makesession حذف شده است.
TELETHON_SESSION_FILE = Path(
    os.environ.get("TELETHON_SESSION_FILE", "/data/telethon_session.txt")
)


def get_telethon_session_string() -> str:
    """رشته سشن مشترک Telethon؛ خالی اگر هیچ‌جا نباشد."""
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


def telethon_configured() -> bool:
    """True اگر API ID/Hash ست باشند و سشن مشترک از متغیر
    محیطی یا فایل بیاید و کتابخانه نصب باشد."""
    if not TELETHON_AVAILABLE:
        return False
    if _telethon_api_credentials() is None:
        return False
    return bool(get_telethon_session_string())


def telethon_send_enabled() -> bool:
    """ارسال با Telethon فقط وقتی فعال است که صریحاً
    TELETHON_SEND_ENABLED=true ست شده باشد. پیش‌فرض: خاموش —
    ویدیوها فقط با خود ربات (Bot API) فرستاده می‌شوند، نه با
    حساب کاربری."""
    if os.environ.get(
        "TELETHON_SEND_ENABLED", ""
    ).strip().lower() not in ("true", "1", "yes"):
        return False
    return telethon_configured()


async def send_via_telethon(chat_id: int, path: Path, caption: str | None,
                            thumb: str | None = None,
                            tracker: ProgressTracker | None = None) -> bool:
    """
    فایل را با MTProto (حساب کاربری، سشن مشترک) به همان چت می‌فرستد.
    سقف ۲ گیگابایت. فقط وقتی صدا زده می‌شود که
    TELETHON_SEND_ENABLED=true باشد؛ پیش‌فرض خاموش است و ویدیوها
    فقط با خود ربات فرستاده می‌شوند. در صورت هر خطایی False
    برمی‌گرداند تا مسیر تقسیم استفاده شود.
    نکته: حساب کاربری باید عضو گروه باشد (برای ارسال به گروه) یا با
    گیرنده دیالوگ داشته باشد (برای پی‌وی).
    """
    if not telethon_send_enabled():
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
        if tracker is not None:
            tracker.begin_upload(1, path.stat().st_size)

            def _telethon_progress(current: int, total: int) -> None:
                tracker.upload_bytes = int(current)
                tracker.upload_total_bytes = int(total)

            kwargs["progress_callback"] = _telethon_progress
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


def _bot_telethon_credentials() -> tuple[int, str, str] | None:
    """(api_id, api_hash, bot_token) برای Telethon bot client؛
    اگر هر کدام نباشد None. نیازی به سشن حساب کاربری ندارد —
    ربات با BOT_TOKEN خودش وارد می‌شود."""
    if not TELETHON_AVAILABLE:
        return None
    creds = _telethon_api_credentials()
    if creds is None:
        return None
    bot_token = os.environ.get("BOT_TOKEN", "").strip()
    if not bot_token:
        return None
    api_id, api_hash = creds
    return api_id, api_hash, bot_token


def bot_telethon_available() -> bool:
    """True اگر Telethon bot client قابل ساخت باشد: API ID/Hash و
    BOT_TOKEN ست باشند و کتابخانه نصب باشد."""
    return _bot_telethon_credentials() is not None


async def send_via_telethon_bot(chat_id: int, path: Path, caption: str | None,
                                thumb: str | None = None,
                                tracker: ProgressTracker | None = None,
                                audio_title: str | None = None,
                                audio_performer: str | None = None,
                                audio_duration: int | None = None) -> bool:
    """
    فایل را با MTProto **به‌عنوان خود ربات** می‌فرستد — نه حساب
    کاربری. کلاینت Telethon با BOT_TOKEN وارد می‌شود
    (client.start(bot_token=...))، پس فرستنده خود ربات است و
    سقف ارسال ۲ گیگابایت است، نه ۵۰ مگ Bot API. این همان راهی
    است که ربات‌های دانلودر روی سرور خودشان استفاده می‌کردند:
    سقف ۵۰ مگ فقط برای Bot API از طریق HTTP است؛ MTProto آن را
    ندارد. نیازی به سشن حساب کاربری ندارد و فقط
    به TELETHON_API_ID و TELETHON_API_HASH و BOT_TOKEN نیاز دارد.
    در صورت هر خطایی False برمی‌گرداند تا مسیر بعدی امتحان شود.
    نکته: ربات باید عضو گروه باشد (برای ارسال به گروه) یا کاربر
    ربات را استارت کرده باشد (برای پی‌وی).
    برای فایل صوتی (mp3) می‌توان عنوان، خواننده و مدت را هم داد
    تا توی تلگرام درست نمایش داده شود.
    """
    creds = _bot_telethon_credentials()
    if creds is None:
        return False
    if path.stat().st_size > BOT_TELETHON_MAX_BYTES:
        return False
    api_id, api_hash, bot_token = creds

    client = None
    try:
        # هر ارسال یک کلاینت تازه می‌سازد تا با polling خود
        # python-telegram-bot (که همان BOT_TOKEN را دارد) و با
        # دانلودهای هم‌زمان تداخل نکند.
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.start(bot_token=bot_token)
        kwargs = {"supports_streaming": True}
        if thumb:
            kwargs["thumb"] = thumb
        # فایل صوتی: عنوان و خواننده را توی متادیتای فایل می‌گذاریم
        # تا تلگرام آن را مثل آهنگ نشان بدهد، نه فایل معمولی.
        if path.suffix.lower() == ".mp3" and audio_title:
            try:
                from telethon.tl.types import DocumentAttributeAudio
                kwargs["attributes"] = [
                    DocumentAttributeAudio(
                        duration=int(audio_duration or 0),
                        title=audio_title,
                        performer=audio_performer or "",
                    )
                ]
            except Exception:
                pass
        if tracker is not None:
            tracker.begin_upload(1, path.stat().st_size)

            def _bot_progress(current: int, total: int) -> None:
                tracker.upload_bytes = int(current)
                tracker.upload_total_bytes = int(total)

            kwargs["progress_callback"] = _bot_progress
        await client.send_file(
            chat_id,
            str(path),
            caption=caption,
            **kwargs,
        )
        logger.info(
            "Sent %s (%d bytes) via Telethon bot client (as bot) to %s",
            path, path.stat().st_size, chat_id,
        )
        return True
    except Exception:
        logger.exception("Telethon bot-client send failed for %s", path)
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
لینک بفرست تا دانلودش کنم:
📸 اینستاگرام، تیک‌تاک و پینترست
🎬 یوتیوب و پورن‌هاب — کیفیت رو انتخاب می‌کنی
🎵 ساندکلود و اسپاتیفای"""

TOO_BIG_TEXT = "ویدیو خیلی بزرگه. 😕"

AGE_RESTRICTED_TEXT = "این ویدیو محدودیت سنی یا منطقه‌ای داره. 😕"

# وب‌سرویس یوتیوب (GFw) درست ست نشده یا کلیدش مشکل دارد — کلید
# فقط از متغیر محیطی GFWDEV_API_KEY می‌آید و هیچ‌جا هاردکد
# نمی‌شود.
GFW_KEY_MISSING_TEXT = "کلید وب‌سرویس یوتیوب تنظیم نشده. 😕"
GFW_KEY_BAD_TEXT = "کلید وب‌سرویس یوتیوب مشکل داره. 😕"

# وب‌سرویس می‌گوید ویدیو در دسترس نیست (حذف/خصوصی شده).
YOUTUBE_UNAVAILABLE_TEXT = "این ویدیو در دسترس نیست. 😕"

ERROR_TEXT = "نشد دانلودش کنم. 😕"


def help_text() -> str:
    return START_TEXT


# یوزرنیم ربات (برای کپشن اینستا و تیک‌تاک)؛ یک بار گرفته و کش می‌شود.
_BOT_USERNAME: str | None = None


async def instagram_caption(bot) -> str:
    """کپشن ویدیوهای اینستا و تیک‌تاک: فقط آیدی ربات + قلب."""
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
    if "tiktok.com" in low:
        return "tiktok"
    if "youtube.com" in low or "youtu.be" in low:
        return "youtube"
    if "soundcloud.com" in low:
        return "soundcloud"
    if "spotify.com" in low or "spotify.link" in low:
        return "spotify"
    if "pinterest." in low or "pin.it" in low:
        return "pinterest"
    return None


# Referer هر پلتفرم برای هدرهای yt-dlp و HEAD.
_PLATFORM_REFERERS = {
    "pornhub": "https://www.pornhub.com/",
    "instagram": "https://www.instagram.com/",
    "tiktok": "https://www.tiktok.com/",
    "pinterest": "https://www.pinterest.com/",
    "youtube": "https://www.youtube.com/",
    "soundcloud": "https://soundcloud.com/",
    "spotify": "https://open.spotify.com/",
}


def _referer_for(url: str) -> str:
    return _PLATFORM_REFERERS.get(
        detect_platform(url) or "", "https://www.google.com/"
    )


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
INSTAGRAM_COOKIES_FILE = Path(
    os.environ.get("INSTAGRAM_COOKIES_FILE", "/data/instagram_cookies.txt")
)
YOUTUBE_COOKIES_FILE = Path(
    os.environ.get("YOUTUBE_COOKIES_FILE", "/data/youtube_cookies.txt")
)

# وب‌سرویس یوتیوب (GFw): دانلود یوتیوب دیگر با yt-dlp نیست و
# کلید فقط از متغیر محیطی می‌آید — هیچ‌جا هاردکد نمی‌شود.
GFWDEV_API_BASE = "https://api.gfwdev.ir/youtube"
GFWDEV_API_KEY = os.environ.get("GFWDEV_API_KEY", "").strip()
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


def get_instagram_cookiefile() -> str | None:
    """مسیر فایل کوکی اینستاگرام؛ None اگر چیزی نباشد.
    اینستاگرام IP دیتاسنتر را خیلی وقت‌ها بدون لاگین رد می‌کند؛
    کوکی لاگین‌شده همان راه‌حلی است که برای پورن‌هاب جواب داد.
    اولویت: متغیر INSTAGRAM_COOKIES (مسیر فایل یا متن خام فایل
    کوکی)، بعد فایل /data/instagram_cookies.txt روی Volume ریل‌وی.
    کوکی فقط برای اینستاگرام استفاده می‌شود، نه پورن‌هاب."""
    env_value = os.environ.get("INSTAGRAM_COOKIES", "").strip()
    if env_value:
        if os.path.isfile(env_value):
            return env_value
        if "\n" in env_value and "instagram.com" in env_value:
            try:
                target = Path("/data/instagram_cookies.txt")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(env_value, encoding="utf-8")
                return str(target)
            except OSError:
                try:
                    fd, tmp = tempfile.mkstemp(
                        prefix="ig-cookies-", suffix=".txt"
                    )
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(env_value)
                    return tmp
                except OSError:
                    pass
        logger.warning(
            "INSTAGRAM_COOKIES is set but is neither an existing file "
            "nor cookie-file text; ignoring it."
        )
        return None
    try:
        if INSTAGRAM_COOKIES_FILE.is_file():
            return str(INSTAGRAM_COOKIES_FILE)
    except OSError:
        pass
    return None


def get_youtube_cookiefile() -> str | None:
    """مسیر فایل کوکی یوتیوب؛ None اگر چیزی نباشد.
    یوتیوب IP دیتاسنتر را بدون لاگین رد می‌کند («Sign in to
    confirm you're not a bot»)؛ کوکی لاگین‌شده همان راه‌حلی
    است که برای جستجوی یوتیوب در fallback اسپاتیفای استفاده
    می‌شود. اولویت: متغیر YOUTUBE_COOKIES (مسیر فایل یا متن
    خام فایل کوکی)، بعد فایل /data/youtube_cookies.txt روی
    Volume ریل‌وی. کوکی فقط برای یوتیوب استفاده می‌شود."""
    env_value = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if env_value:
        if os.path.isfile(env_value):
            return env_value
        if "\n" in env_value and "youtube.com" in env_value:
            try:
                target = Path("/data/youtube_cookies.txt")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(env_value, encoding="utf-8")
                return str(target)
            except OSError:
                try:
                    fd, tmp = tempfile.mkstemp(
                        prefix="yt-cookies-", suffix=".txt"
                    )
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        f.write(env_value)
                    return tmp
                except OSError:
                    pass
        logger.warning(
            "YOUTUBE_COOKIES is set but is neither an existing file "
            "nor cookie-file text; ignoring it."
        )
        return None
    try:
        if YOUTUBE_COOKIES_FILE.is_file():
            return str(YOUTUBE_COOKIES_FILE)
    except OSError:
        pass
    return None


def _build_ydl_opts(url: str, height: int, outdir: str, tracker=None,
                    audio_only: bool = False,
                    noplaylist: bool = True) -> dict:
    """تنظیمات yt-dlp: شبیه مرورگر واقعی + ری‌ترای.
    audio_only=True یعنی فقط بهترین صدا و تبدیل به mp3 (ساندکلود).
    noplaylist=False فقط برای اسلایدشوی
    عکس‌های تیک‌تاک استفاده می‌شود. یوتیوب دیگر از yt-dlp
    استفاده نمی‌کند (وب‌سرویس GFw) و اینجا به آن دست نمی‌زنیم."""
    global _IMPERSONATION_WARNING_LOGGED
    platform = detect_platform(url)
    referer = _referer_for(url)

    if audio_only:
        fmt = "bestaudio/best"
    else:
        fmt = (
            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={height}][ext=mp4]/"
            f"best[height<={height}]/best"
        )

    ydl_opts: dict = {
        "format": fmt,
        "outtmpl": os.path.join(outdir, "%(id)s.%(ext)s"),
        "noplaylist": noplaylist,
        "quiet": True,
        "no_warnings": True,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "socket_timeout": 30,
        # دانلود موازی فرگمنت‌ها: پورن‌هاب هر اتصال را حدود ۵۰۰
        # کیلوبایت/ثانیه محدود می‌کند (rate=500k توی لینک)، پس
        # ۸ فرگمنت موازی تا چند برابر سرعت دانلود را بالا می‌برد.
        # برای فایل mp4 مستقیم هم چانک‌های ۱۰ مگی موازی می‌شود.
        "concurrent_fragment_downloads": 8,
        "http_chunk_size": 10 * 1024 * 1024,
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

    if not audio_only:
        ydl_opts["merge_output_format"] = "mp4"
    else:
        # فقط صدا: خروجی mp3 با ffmpeg (اصل فایل حذف می‌شود و
        # فقط mp3 می‌ماند).
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

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

    if platform == "instagram":
        # impersonation کروم + هدرها همین‌طور برای اینستاگرام هم
        # ست شده‌اند (بالا)؛ اینستاگرام IP دیتاسنتر را بدون لاگین
        # رد می‌کند، پس کوکی لاگین‌شده راه‌حل دوم است.
        cookiefile = get_instagram_cookiefile()
        if cookiefile:
            ydl_opts["cookiefile"] = cookiefile
            logger.info("Using Instagram cookiefile: %s", cookiefile)

    if platform == "youtube":
        # یوتیوب با yt-dlp فقط در fallback اسپاتیفای استفاده
        # می‌شود (دانلود مستقیم صدا وقتی کلید GFw نیست)؛ بدون
        # کوکی لاگین‌شده IP دیتاسنتر رد می‌شود.
        cookiefile = get_youtube_cookiefile()
        if cookiefile:
            ydl_opts["cookiefile"] = cookiefile
            logger.info("Using YouTube cookiefile: %s", cookiefile)

    return ydl_opts


def _fetch_info_err_sync(url: str) -> tuple[dict | None, str]:
    """اطلاعات ویدیو بدون دانلود فایل (عنوان + آدرس کاور).
    برمی‌گرداند: (info یا None، متن خطا یا "")."""
    try:
        ydl_opts = _build_ydl_opts(url, 720, tempfile.gettempdir())
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return (info if isinstance(info, dict) else None), ""
    except Exception as e:
        logger.exception("yt-dlp info fetch failed for %s", url)
        return None, str(e)


def _fetch_info_sync(url: str) -> dict | None:
    """اطلاعات ویدیو بدون دانلود فایل (عنوان + آدرس کاور)."""
    info, _err = _fetch_info_err_sync(url)
    return info


def parse_soundcloud_track(info: dict) -> tuple[str, str]:
    """از info ساندکلود، (عنوان تمیز، خواننده) را برمی‌گرداند.
    خواننده به ترتیب از `artist`، بعد `creator`، بعد `uploader`
    می‌آید؛ اگر هیچ‌کدام نبود، از تقسیم عنوان روی اولین " - "
    درمی‌آید. عنوان: اگر `track` باشد، همان است؛ وگرنه عنوان
    روی اولین " - " تقسیم می‌شود (فقط وقتی خواننده از همان
    تقسیم آمده باشد، یا قسمت چپ دقیقاً همان خواننده باشد).
    هیچ‌وقت اسم خواننده دو بار تکرار نمی‌شود."""
    track = str(info.get("track") or "").strip()
    title_raw = str(info.get("title") or "").strip()
    artist = str(
        info.get("artist") or info.get("creator")
        or info.get("uploader") or ""
    ).strip()
    if track:
        if not artist and " - " in title_raw:
            left, _, right = title_raw.partition(" - ")
            if right.strip() == track:
                artist = left.strip()
        return track, artist
    if " - " in title_raw:
        left, _, right = title_raw.partition(" - ")
        if not artist:
            return right.strip(), left.strip()
        if left.strip() == artist:
            return right.strip(), artist
    return title_raw, artist


def _best_thumbnail_url(info: dict | None) -> str | None:
    """بهترین (بزرگ‌ترین) کاور از info؛ اول از لیست thumbnails،
    بعد thumbnail تکی."""
    if not info:
        return None
    best: str | None = None
    best_area = -1
    for t in info.get("thumbnails") or []:
        if not isinstance(t, dict):
            continue
        u = t.get("url")
        if not u:
            continue
        area = (t.get("width") or 0) * (t.get("height") or 0)
        if area >= best_area:
            best_area = area
            best = u
    return best or info.get("thumbnail")


# ---------------------------------------------------------------------------
# ارسال مستقیم با لینک (بدون دانلود روی ریل‌وی) — بهترین تلاش
# ---------------------------------------------------------------------------
# ایده: اگر yt-dlp یک لینک mp4 مستقیم بدهد که تلگرام خودش بتواند
# بگیرد، ریل‌وی اصلاً دانلود/آپلود نمی‌کند و ویدیو در چند ثانیه
# می‌رسد. ولی دو مانع واقعی هست که تست محلی ثابت کرد:
# - پورن‌هاب: لینک mp4 مستقیم به IP قفل شده
#   (…&ip=…&ipa=1&hash=…)؛ تلگرام از IP دیگری می‌گیرد و 410 می‌گیرد.
# - اینستاگرام: CDN حتی به HEAD با impersonation هم 403 می‌دهد و
#   حجم فایل توی info نیست (None)، پس اندازه معلوم نیست.
# پس این مسیر فقط وقتی امتحان می‌شود که (۱) فرمت mp4 مستقیم باشد،
# (۲) لینک به IP قفل نباشد، (۳) حجم معلوم و زیر ۴۸ مگ باشد. اگر هر
# کدام نبود، بدون معطلی برمی‌گردیم به مسیر دانلود-با-فرگمنت-موازی
# اگر هم تلگرام نتوانست بگیرد، همان‌جا fallback می‌شود.
# لاگ مشخص می‌کند کدام مسیر استفاده شد: "direct-url" یا دلیل skip.

def _is_ip_bound_url(url: str) -> bool:
    """True اگر لینک به IP استخراج‌کننده قفل شده باشد
    (پارامترهای ip= و ipa=1 توی کوئری)."""
    try:
        params = parse_qs(urlparse(url).query)
    except Exception:
        return False
    if params.get("ipa") == ["1"]:
        return True
    return "ip" in params and "hash" in params


def _head_content_length_sync(url: str, referer: str) -> int | None:
    """HEAD با همان استک yt-dlp (impersonation کروم)؛
    Content-Length را برمی‌گرداند یا None اگر نشد."""
    try:
        ydl_opts = _build_ydl_opts(
            referer, 720, tempfile.gettempdir()
        )
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            req = yt_dlp.networking.Request(
                url, method="HEAD",
                headers={"Referer": referer},
            )
            resp = ydl.urlopen(req)
            length = resp.headers.get("Content-Length")
            return int(length) if length else None
    except Exception:
        return None


def _pick_direct_format(info: dict, max_height: int) -> dict | None:
    """بهترین فرمت mp4 مستقیم (https) با صدا و تصویر، با ارتفاع
    حداکثر max_height. فرمت‌های فقط-تصویر (dash ویدیویی) و HLS
    (m3u8) را نمی‌خواهد؛ چون تلگرام نه صدای جدا می‌خواهد نه m3u8."""
    best = None
    for f in info.get("formats") or []:
        if f.get("protocol") not in ("https", "http"):
            continue
        if (f.get("ext") or "").lower() != "mp4":
            continue
        if f.get("vcodec") in (None, "none"):
            continue
        if f.get("acodec") in (None, "none"):
            continue
        height = f.get("height") or 0
        if height > max_height:
            continue
        if best is None or height > (best.get("height") or 0):
            best = f
    return best


async def _try_direct_url_send(bot, chat_id: int, info: dict,
                               max_height: int, caption: str | None,
                               thumb: Path | None,
                               tracker: ProgressTracker) -> bool:
    """سعی می‌کند ویدیو را با لینک مستقیم mp4 به تلگرام بفرستد
    (تلگرام خودش فایل را می‌گیرد؛ ریل‌وی دانلود/آپلود نمی‌کند).
    True اگر تلگرام قبول کرد؛ False یعنی باید مسیر دانلود اجرا شود.
    هر دلیل skip/fail توی لاگ می‌آید."""
    fmt = _pick_direct_format(info, max_height)
    if fmt is None:
        logger.info("direct-url skipped: no direct mp4 format with audio")
        return False
    url = fmt.get("url") or ""
    if not url:
        return False
    if _is_ip_bound_url(url):
        logger.info(
            "direct-url skipped: URL is IP-bound (format %s)",
            fmt.get("format_id"),
        )
        return False
    referer = _referer_for(info.get("webpage_url") or "")
    size = fmt.get("filesize") or fmt.get("filesize_approx")
    if not size:
        size = await asyncio.to_thread(
            _head_content_length_sync, url, referer
        )
    if not size or int(size) > MAX_BYTES:
        logger.info(
            "direct-url skipped: size unknown or >48MB (format %s, size %s)",
            fmt.get("format_id"), size,
        )
        return False
    tracker.set_phase("direct")
    try:
        thumb_f = None
        if thumb is not None and thumb.is_file():
            thumb_f = open(thumb, "rb")
        try:
            await bot.send_video(
                chat_id=chat_id, video=url, caption=caption,
                supports_streaming=True, thumbnail=thumb_f,
            )
        finally:
            if thumb_f is not None:
                thumb_f.close()
        logger.info(
            "direct-url send OK: format %s (%d bytes)",
            fmt.get("format_id"), int(size),
        )
        tracker.set_phase("done", 100)
        return True
    except Exception:
        logger.exception(
            "direct-url send failed (format %s); falling back to download",
            fmt.get("format_id"),
        )
        return False


def _download_cover_sync(thumb_url: str | None, tmpdir: str,
                         referer: str = "https://www.pornhub.com/") -> Path | None:
    """کاور ویدیو را دانلود می‌کند و به JPG تبدیل می‌کند (اگر webp/png
    بود). None اگر نشد."""
    if not thumb_url:
        return None
    try:
        req = urllib.request.Request(
            thumb_url,
            headers={
                "User-Agent": CHROME_USER_AGENT,
                "Referer": referer,
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
            ydl_opts = _build_ydl_opts(
                url, height, tempfile.gettempdir(),
            )
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


def _download_once(url: str, height: int, outdir: str, tracker=None,
                   ) -> tuple[str, list[Path]]:
    """یک بار دانلود با سقف کیفیت height. برمی‌گرداند: (عنوان، فهرست فایل‌ها)."""
    ydl_opts = _build_ydl_opts(
        url, height, outdir, tracker=tracker,
    )

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


def _download_audio_once(url: str, outdir: str, tracker=None,
                         ) -> tuple[str, list[Path]]:
    """فقط بهترین صدا را دانلود و به mp3 تبدیل می‌کند (ساندکلود).
    برمی‌گرداند: (عنوان، فهرست فایل‌های mp3)."""
    ydl_opts = _build_ydl_opts(
        url, 720, outdir, tracker=tracker, audio_only=True,
    )
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    title = ""
    if isinstance(info, dict):
        title = str(info.get("title") or "")

    files = [
        p
        for p in Path(outdir).iterdir()
        if p.is_file() and p.suffix.lower() == ".mp3"
    ]
    files.sort(key=lambda p: p.stat().st_size, reverse=True)
    return title, files


def _download_slideshow_sync(url: str, outdir: str,
                             tracker=None) -> tuple[str, list[Path]]:
    """دانلود اسلایدشوی عکس‌های تیک‌تاک (پلی‌لیست عکس‌ها).
    ویدیوها اول می‌آیند، بعد عکس‌ها به ترتیب اسم. فقط وقتی
    استفاده می‌شود که دانلود معمولی فایلی نداد."""
    ydl_opts = _build_ydl_opts(
        url, 720, outdir, tracker=tracker, noplaylist=False
    )
    ydl_opts["format"] = "best"
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    title = ""
    if isinstance(info, dict):
        title = str(info.get("title") or "")

    keep_exts = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".webm"}
    files = [
        p
        for p in Path(outdir).iterdir()
        if p.is_file() and p.suffix.lower() in keep_exts
    ]
    files.sort(key=lambda p: (0 if p.suffix.lower() in VIDEO_EXTS else 1, p.name))
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


def _run_ffmpeg_progress(args: list[str], duration_s: float | None,
                         tracker: ProgressTracker | None,
                         phase: str) -> int:
    """ffmpeg را با ‎-progress اجرا می‌کند و درصد واقعی را توی ترکر
    می‌نویسد (از out_time_ms نسبت به مدت ویدیو). args دستور کامل
    ffmpeg است که آخرین عنصرش فایل خروجی است؛ ‎-progress قبل از
    خروجی اضافه می‌شود. کد بازگشت ffmpeg را برمی‌گرداند."""
    cmd = list(args[:-1]) + ["-progress", "pipe:1", "-nostats", args[-1]]
    if tracker is not None:
        tracker.set_phase(phase, 0)
    # stderr به فایل موقت می‌رود (نه PIPE که ممکن است deadlock بدهد
    # و نه DEVNULL که دلیل واقعی شکست را قایم می‌کند)؛ اگر ffmpeg
    # با خطا برگشت، دنباله خطا لاگ می‌شود.
    err_file = None
    try:
        err_file = tempfile.TemporaryFile()
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=err_file,
            text=True,
        )
    except Exception:
        logger.exception("ffmpeg start failed")
        if err_file is not None:
            try:
                err_file.close()
            except OSError:
                pass
        return 1
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_ms="):
                try:
                    ms = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if tracker is not None and duration_s:
                    pct = min(99, int(ms / 1000 / duration_s * 100))
                    tracker.set_phase(phase, pct)
    except Exception:
        pass
    rc = proc.wait()
    if err_file is not None:
        try:
            err_file.seek(0, os.SEEK_END)
            size = err_file.tell()
            err_file.seek(max(0, size - 2048))
            tail = err_file.read().decode("utf-8", errors="replace")
            if rc != 0 and tail.strip():
                logger.warning(
                    "ffmpeg rc=%d for %s: %s", rc, args[-1],
                    tail.strip()[-2048:],
                )
        except Exception:
            pass
        finally:
            try:
                err_file.close()
            except OSError:
                pass
    return rc


def _split_video_sync(path: Path, workdir: Path,
                      tracker: ProgressTracker | None = None) -> list[Path]:
    """ویدیو را با ffmpeg به قسمت‌های زیر ۴۸ مگ تقسیم می‌کند (بدون ریکد).
    درصد تقسیم توی ترکر می‌آید.
    سقف: اگر برای جا شدن زیر ۴۸ مگ به بیشتر از MAX_SPLIT_PARTS
    (۱۰) قسمت نیاز باشد، اصلاً تقسیم نمی‌شود و فایل اصلی
    برگردانده می‌شود — به‌جای ۱۵۲ قسمت کوچک، بهتر است کیفیت
    پایین‌تر دانلود شود یا فایل با bot client فرستاده شود.
    قسمت‌ها نزدیک ۴۸ مگ‌اند: segment_time حداقل ۶۰ ثانیه است و
    در retry هم کمتر از ۶۰ نمی‌شود (قبلاً تا ۱۵ ثانیه نصف می‌شد
    و برای ویدیوی طولانی ده‌ها قسمت کوچک می‌ساخت — همان باگ
    ۱۵۲ قسمت)."""
    import math

    size = path.stat().st_size
    if size <= MAX_BYTES:
        return [path]

    # برآورد تعداد قسمت‌ها از روی حجم؛ اگر بیشتر از سقف شد، تقسیم نکن.
    estimated_parts = math.ceil(size / (MAX_BYTES * 0.92))
    if estimated_parts > MAX_SPLIT_PARTS:
        logger.warning(
            "Split would need %d parts for %s (%d bytes); "
            "refusing to split (cap %d).",
            estimated_parts, path, size, MAX_SPLIT_PARTS,
        )
        return [path]

    duration = _probe_duration_seconds(path)
    if duration and duration > 0:
        segment_time = max(60, int(duration * MAX_BYTES * 0.92 / size))
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
        rc = _run_ffmpeg_progress(
            [
                "ffmpeg", "-y", "-i", str(path),
                "-c", "copy", "-map", "0",
                "-f", "segment", "-segment_time", str(segment_time),
                "-reset_timestamps", "1",
                pattern,
            ],
            duration, tracker, "split",
        )
        if rc != 0:
            # مثل قبل: اگر قسمتی ساخته نشده باشد، با زمان کمتر
            # دوباره تلاش می‌شود؛ اگر قسمتی ساخته شده باشد، همان
            # پایین بررسی می‌شود.
            logger.warning("ffmpeg split rc=%d for %s", rc, path)

        parts = sorted(workdir.glob(f"{path.stem}_part*.mp4"))
        parts = [p for p in parts if p.is_file() and p.stat().st_size > 0]
        if len(parts) > MAX_SPLIT_PARTS:
            logger.warning(
                "Split produced %d parts for %s; refusing (cap %d).",
                len(parts), path, MAX_SPLIT_PARTS,
            )
            return [path]
        if len(parts) > 1 and all(p.stat().st_size <= MAX_BYTES for p in parts):
            return parts
        segment_time = max(60, segment_time // 2)

    parts = sorted(workdir.glob(f"{path.stem}_part*.mp4"))
    parts = [p for p in parts if p.is_file() and p.stat().st_size > 0]
    if len(parts) > MAX_SPLIT_PARTS:
        return [path]
    return parts or [path]


async def _fit_for_bot_api(path: Path, tmpdir: str,
                           tracker: ProgressTracker | None = None) -> list[Path]:
    """فایل را برای ارسال با Bot API جا می‌کند: اگر زیر ۴۸ مگ است
    همان را برمی‌گرداند؛ وگرنه با ffmpeg -c copy (بدون ریکد،
    سریع) به قسمت‌های زیر ۴۸ مگ تقسیم می‌کند — ولی فقط اگر
    بیشتر از ۱۰ قسمت نشود؛ اگر بیشتر شد، فایل اصلی برگردانده
    می‌شود تا کیفیت پایین‌تر دانلود شود یا با bot client
    فرستاده شود. فشرده‌سازی (ریکد) حذف شده است چون خیلی طول
    می‌کشید. درصد تقسیم توی ترکر می‌آید."""
    if path.stat().st_size <= MAX_BYTES:
        return [path]
    parts_dir = Path(tmpdir) / f"parts-{path.stem}"
    parts = await asyncio.to_thread(
        _split_video_sync, path, parts_dir, tracker
    )
    if len(parts) > 1 and all(p.stat().st_size <= MAX_BYTES for p in parts):
        return parts
    return [path]


async def download_best_effort(url: str, tmpdir: str, prefer_telethon: bool = False,
                               tracker=None):
    """
    دانلود با کیفیتی که از قبل اندازه‌اش معلوم شده (probe).
    برمی‌گرداند: (title, files, was_split)
    اگر حجم معلوم نشد، حلقه قدیمی (۷۲۰p، بعد ۴۸۰p، بعد ۳۶۰p) به‌عنوان
    fallback می‌ماند. اگر prefer_telethon=True باشد، مستقیم ۷۲۰p
    دانلود می‌شود تا اول با Telethon bot client (خود ربات، تا ۲ گیگ)
    فرستاده شود؛ اینجا هیچ تقسیمی انجام نمی‌شود.
    """
    if prefer_telethon:
        subdir = Path(tmpdir) / "h720"
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            title, files = await asyncio.to_thread(
                _download_once, url, 720, str(subdir), tracker,
            )
        except Exception:
            logger.exception("yt-dlp failed at 720p for %s", url)
            return "", [], False
        return title, files, False

    probe_height = await asyncio.to_thread(
        _probe_height_sync, url
    )
    if probe_height is not None:
        logger.info("Probe chose %dp for %s", probe_height, url)
        subdir = Path(tmpdir) / f"h{probe_height}"
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            title, files = await asyncio.to_thread(
                _download_once, url, probe_height, str(subdir), tracker,
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
                _download_once, url, height, str(subdir), tracker,
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
    if main.stat().st_size <= MAX_BYTES:
        return title, files, False
    # بزرگ بود؛ اینجا تقسیم نمی‌کنیم — _deliver اول با Telethon
    # bot client (خود ربات، تا ۲ گیگ) می‌فرستد و تقسیم فقط آخرین
    # راه است (با سقف ۱۰ قسمت). تقسیم کردن همین‌جا بود که ویدیو
    # را بی‌خود تیکه‌تیکه می‌کرد.


# ---------------------------------------------------------------------------
# ارسال فایل به چت
# ---------------------------------------------------------------------------

async def send_files(bot, chat_id: int, files: list[Path],
                     captions: list | None = None,
                     thumb: Path | None = None,
                     tracker: ProgressTracker | None = None,
                     audio_title: str | None = None,
                     audio_performer: str | None = None,
                     audio_duration: int | None = None) -> bool:
    """فایل‌ها را فقط با خود ربات (Bot API) می‌فرستد.
    captions هم‌طول files است. thumb (کاور) فقط برای اولین ویدیو
    استفاده می‌شود. اگر tracker داده شده باشد، قبل و بعد از هر
    قسمت درصد آپلود را به‌روز می‌کند تا پیام پیشرفت آپلود را
    نشان بدهد. اگر هیچ فایلی قابل ارسال نباشد False برمی‌گرداند.
    برای فایل صوتی (mp3) عنوان، خواننده و مدت هم ست می‌شوند و
    کاور به‌عنوان thumbnail آهنگ فرستاده می‌شود."""
    if not files:
        return False

    captions = captions or [None] * len(files)
    if tracker is not None:
        tracker.begin_upload(
            len(files), sum(p.stat().st_size for p in files)
        )
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
                            thumbnail=thumb_f,
                        )
                finally:
                    if thumb_f is not None:
                        thumb_f.close()
            elif ext == ".mp3":
                thumb_f = None
                if thumb is not None and i == 0 and thumb.is_file():
                    thumb_f = open(thumb, "rb")
                try:
                    with open(path, "rb") as f:
                        await bot.send_audio(
                            chat_id=chat_id, audio=f, caption=caption,
                            title=audio_title, performer=audio_performer,
                            duration=audio_duration, thumbnail=thumb_f,
                        )
                finally:
                    if thumb_f is not None:
                        thumb_f.close()
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
            if tracker is not None:
                tracker.mark_upload_part_done(path.stat().st_size)
        except Exception:
            logger.exception("send failed for %s", path)

    return sent_any


async def _deliver(bot, chat_id: int, tmpdir: str, title: str,
                   files: list[Path], was_split: bool,
                   caption_mode: str, thumb: Path | None = None,
                   tracker: ProgressTracker | None = None,
                   audio_title: str | None = None,
                   audio_performer: str | None = None,
                   audio_caption: str | None = None,
                   audio_duration: int | None = None) -> bool:
    """فایل‌های دانلودشده را می‌فرستد و True برمی‌گرداند اگر چیزی
    فرستاده شد. ارسال همیشه با خود ربات (Bot API) است.
    caption_mode: "instagram" → کپشن همه قسمت‌ها «@ربات ❤️»؛
    "title" → کپشن عنوان (قسمت‌ها با شماره قسمت).
    برای فایل صوتی: audio_caption کپشن پیام آهنگ است و
    audio_title/audio_performer عنوان و خواننده‌ای هستند که
    توی خود فایل صوتی نمایش داده می‌شوند.
    ترتیب: ۱) فایل‌های کوچک با Bot API؛ ۲) فایل‌های بزرگ اول با
    Telethon bot client (خود ربات با BOT_TOKEN، تا ۲ گیگ) — بدون
    تقسیم، بدون فشرده‌سازی؛ ۳) اگر آن نشد، با حساب کاربری
    (Telethon) فقط وقتی TELETHON_SEND_ENABLED=true باشد؛
    ۴) فقط به‌عنوان آخرین راه، با ffmpeg -c copy (بدون ریکد)
    تقسیم می‌شوند — با سقف ۱۰ قسمت."""
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
        # فایل صوتی: کپشن پیام آهنگ، جدای از کپشن ویدیوها.
        if audio_caption is not None:
            small_caps = [
                audio_caption if p.suffix.lower() == ".mp3" else c
                for p, c in zip(small, small_caps)
            ]
        sent = await send_files(
            bot, chat_id, small, small_caps, thumb=thumb, tracker=tracker,
            audio_title=audio_title, audio_performer=audio_performer,
            audio_duration=audio_duration,
        )

    for path in large:
        caps = await build_captions(len(files), was_split)
        cap = caps[files.index(path)]
        if audio_caption is not None and path.suffix.lower() == ".mp3":
            cap = audio_caption
        thumb_arg = str(thumb) if thumb is not None else None
        # ۱) اول با خود ربات از طریق Telethon bot client (MTProto
        # با BOT_TOKEN، تا ۲ گیگ) — فرستنده خود ربات است، نه
        # حساب کاربری؛ نه تقسیم می‌شود، نه فشرده‌سازی. نیازی به
        # سشن حساب کاربری ندارد.
        if path.stat().st_size <= BOT_TELETHON_MAX_BYTES:
            if await send_via_telethon_bot(
                chat_id, path, cap, thumb=thumb_arg, tracker=tracker,
                audio_title=audio_title, audio_performer=audio_performer,
                audio_duration=audio_duration,
            ):
                sent = True
                continue
            logger.warning(
                "Telethon bot-client send failed for %s; "
                "trying user-session fallback",
                path,
            )
        # ۲) fallback: ارسال با حساب کاربری فقط وقتی صریحاً فعال
        # شده باشد؛ پیش‌فرض خاموش است.
        if (
            telethon_send_enabled()
            and path.stat().st_size <= TELETHON_MAX_BYTES
        ):
            if await send_via_telethon(
                chat_id, path, cap,
                thumb=thumb_arg,
                tracker=tracker,
            ):
                sent = True
                continue
            logger.warning(
                "Telethon send failed for %s; falling back to split",
                path,
            )
        # ۳) فقط به‌عنوان آخرین راه: تقسیم (سقف ۱۰ قسمت)؛
        # فقط با Bot API فرستاده می‌شود.
        fitted = await _fit_for_bot_api(path, tmpdir, tracker)
        fitted = [p for p in fitted if p.stat().st_size <= MAX_BYTES]
        if fitted:
            part_caps = await build_captions(len(fitted), len(fitted) > 1)
            if await send_files(
                bot, chat_id, fitted, part_caps, thumb=thumb, tracker=tracker
            ):
                sent = True

    return sent


# ---------------------------------------------------------------------------
# دانلود اینستاگرام و پورن‌هاب (در پس‌زمینه اجرا می‌شوند)
# ---------------------------------------------------------------------------

async def do_instagram_download(bot, chat_id: int, url: str) -> str:
    """دانلود اینستا. برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'
    پیام پیشرفت همه فازها را نشان می‌دهد (آماده‌سازی، دانلود،
    ارسال مستقیم، تقسیم، آپلود) و هر ۵ ثانیه ویرایش
    می‌شود. اول لینک مستقیم امتحان می‌شود؛ اگر نشد دانلود معمولی."""
    tracker = ProgressTracker()
    done = asyncio.Event()
    status = await bot.send_message(
        chat_id=chat_id, text=_progress_text(0, "info"),
    )
    watcher = asyncio.create_task(
        _watch_progress(
            bot, chat_id, status.message_id, tracker, done, False,
        )
    )
    try:
        with tempfile.TemporaryDirectory(prefix="dl-") as tmpdir:
            # ۱) اطلاعات + تلاش برای ارسال مستقیم با لینک
            info = await asyncio.to_thread(_fetch_info_sync, url)
            if info:
                caption = await instagram_caption(bot)
                if await _try_direct_url_send(
                    bot, chat_id, info, 720, caption, None, tracker
                ):
                    return "ok"
            # ۲) دانلود معمولی (فرگمنت موازی)
            try:
                title, files, was_split = await download_best_effort(
                    url, tmpdir,
                    prefer_telethon=bot_telethon_available() or telethon_send_enabled(),
                    tracker=tracker,
                )
            except Exception:
                logger.exception("download failed for %s", url)
                return "error"
            if not files:
                return "empty"
            sent = await _deliver(
                bot, chat_id, tmpdir, title, files, was_split,
                "instagram", tracker=tracker,
            )
            if sent:
                return "ok"
            if all(p.stat().st_size > MAX_BYTES for p in files):
                return "too_big"
            return "empty"
    finally:
        done.set()
        watcher.cancel()
        try:
            await status.delete()
        except Exception:
            pass


async def do_tiktok_download(bot, chat_id: int, url: str) -> str:
    """دانلود تیک‌تاک — دقیقاً مثل اینستاگرام: دانلود مستقیم،
    بدون منوی کیفیت، کپشن فقط «@ربات ❤️». برمی‌گرداند:
    'ok' | 'too_big' | 'empty' | 'error'
    اول لینک مستقیم امتحان می‌شود؛ اگر نشد دانلود معمولی.
    اگر پست اسلایدشوی عکس باشد (دانلود معمولی فایلی نداد)،
    عکس‌ها دانلود و به‌عنوان عکس فرستاده می‌شوند."""
    tracker = ProgressTracker()
    done = asyncio.Event()
    status = await bot.send_message(
        chat_id=chat_id, text=_progress_text(0, "info"),
    )
    watcher = asyncio.create_task(
        _watch_progress(
            bot, chat_id, status.message_id, tracker, done, False,
        )
    )
    try:
        with tempfile.TemporaryDirectory(prefix="tt-") as tmpdir:
            # ۱) اطلاعات + تلاش برای ارسال مستقیم با لینک
            info = await asyncio.to_thread(_fetch_info_sync, url)
            if info:
                caption = await instagram_caption(bot)
                if await _try_direct_url_send(
                    bot, chat_id, info, 720, caption, None, tracker
                ):
                    return "ok"
            # ۲) دانلود معمولی (فرگمنت موازی) — yt-dlp برای
            # تیک‌تاک وقتی بتواند، استریم بدون واترمارک را
            # می‌گیرد؛ اگر نشد همان بهترین کیفیت می‌آید.
            try:
                title, files, was_split = await download_best_effort(
                    url, tmpdir,
                    prefer_telethon=bot_telethon_available() or telethon_send_enabled(),
                    tracker=tracker,
                )
            except Exception:
                logger.exception("download failed for %s", url)
                return "error"
            # ۳) اسلایدشوی عکس: اگر دانلود معمولی فایلی نداد،
            # عکس‌ها را جدا دانلود کن و به‌عنوان عکس بفرست.
            if not files:
                try:
                    subdir = Path(tmpdir) / "slideshow"
                    subdir.mkdir(parents=True, exist_ok=True)
                    title, files = await asyncio.to_thread(
                        _download_slideshow_sync, url, str(subdir), tracker
                    )
                except Exception:
                    logger.exception("slideshow download failed for %s", url)
                    return "error"
            if not files:
                return "empty"
            sent = await _deliver(
                bot, chat_id, tmpdir, title, files, was_split,
                "instagram", tracker=tracker,
            )
            if sent:
                return "ok"
            if all(p.stat().st_size > MAX_BYTES for p in files):
                return "too_big"
            return "empty"
    finally:
        done.set()
        watcher.cancel()
        try:
            await status.delete()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# پینترست (بدون لاگین، با API خود پینترست)
# ---------------------------------------------------------------------------
# چرا yt-dlp به‌تنهایی کافی نیست: اکسترکتور پینترست yt-dlp فقط ویدیو
# را می‌فهمد — برای پین عکسی با «No video formats found!» می‌میرد و
# پین چندعکسی (چند صفحه) را اصلاً نمی‌بیند. پس اطلاعات پین مستقیم از
# همان API بدون لاگین پینترست گرفته می‌شود که اکسترکتور yt-dlp هم
# استفاده می‌کند (PinResource/get با field_set_key
# unauth_react_main_pin):
# - پین ویدیویی: videos.video_list فرمت‌های mp4 را می‌دهد؛ دانلودش
#   مثل تیک‌تاک با yt-dlp انجام می‌شود.
# - پین عکسی: images.orig کیفیت اصلی است (گاهی ‎.heic است)؛ پین
#   چندعکسی یا صفحه‌های story_pin_data است (هر صفحه یک عکس دارد،
#   image.images.originals) یا یک carousel است
#   (carousel_data.carousel_slots — هر اسلات یک عکس جدا، بدون
#   orig؛ URL اصلی از روی signature همان عکس ساخته می‌شود و
#   پسوند درست با تلاش به‌ترتیب پیدا می‌شود، چون پسوند نسخه
#   736x با پسوند اصلی یکی نیست). همه عکس‌ها به ترتیب جمع می‌شوند
#   و به‌صورت یک آلبوم فرستاده می‌شوند.
# تست زنده (از همین VM، بدون لاگین): API جواب می‌دهد؛ ویدیوی
# Origami واقعاً دانلود شد (۵٫۲ مگ mp4)؛ عکس اصلی jpg و heic هر دو
# 200 دادند؛ heic با ffmpeg به jpg تبدیل شد؛ pin.it با 308 ریدایرکت
# می‌شود. یک نکته واقعی: آدرس originals با پسوند ‎.jpg گاهی 403
# می‌دهد (وقتی اصل فایل heic است) — پس هر عکس چند آدرس جایگزین
# دارد (اصل، همان هش با ‎.jpg، و نسخه 736x).

PINTEREST_API_URL = "https://www.pinterest.com/resource/PinResource/get/"

# سقف عکس در Bot API برای send_photo / media group: ۱۰ مگ.
PINTEREST_PHOTO_MAX_BYTES = 10 * 1024 * 1024

# سقف عکس‌های یک پین (پین چندصفحه‌ای حداکثر ۲۰ صفحه دارد).
PINTEREST_MAX_IMAGES = 20

_PIN_ID_RE = re.compile(r"/pin/(?:[\w-]+--)?(\d+)", re.IGNORECASE)


def _extract_pinterest_pin_id(url: str) -> str | None:
    """آیدی عددی پین از URL (شامل فرم اسلاگ‌دار
    /pin/<slug>--<id>). None اگر URL پین تکی نباشد (بورد/پروفایل)."""
    m = _PIN_ID_RE.search(url or "")
    return m.group(1) if m else None


def _resolve_pinterest_url_sync(url: str) -> str | None:
    """لینک کوتاه pin.it را باز می‌کند و URL نهایی را برمی‌گرداند؛
    برای لینک معمولی همان URL. None اگر باز نشد."""
    if "pin.it" not in url.lower():
        return url
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": CHROME_USER_AGENT,
                "Referer": "https://www.pinterest.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            try:
                resp.read(1)
            except Exception:
                pass
            return resp.geturl()
    except Exception:
        logger.warning("pin.it resolve failed for %s", url)
        return None


def _fetch_pinterest_pin_sync(pin_id: str) -> dict | None:
    """اطلاعات پین از API بدون لاگین پینترست (PinResource).
    None اگر نشد — پین حذف‌شده/خصوصی 404 می‌دهد."""
    try:
        payload = {
            "options": {
                "field_set_key": "unauth_react_main_pin",
                "id": pin_id,
            }
        }
        q = urlencode({"data": json.dumps(payload)})
        req = urllib.request.Request(
            PINTEREST_API_URL + "?" + q,
            headers={
                "User-Agent": CHROME_USER_AGENT,
                "X-Pinterest-PWS-Handler": "www/[username].js",
                "Referer": f"https://www.pinterest.com/pin/{pin_id}/",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        pin = (data.get("resource_response") or {}).get("data")
        return pin if isinstance(pin, dict) else None
    except Exception:
        logger.warning("Pinterest API failed for pin %s", pin_id)
        return None


def _pinterest_has_video(data: dict) -> bool:
    """True اگر پین ویدیو داشته باشد (video_list پر باشد).
    is_video قابل اعتماد نیست — برای پین ویدیویی هم False می‌آید.
    ویدیو یا توی videos.video_list است یا توی صفحه‌های story
    (استوری‌پین ویدیویی videos خالی دارد ولی بلاک ویدیو دارد —
    اگر این را نگیریم، ربات به‌جای ویدیو فقط کاورش را می‌فرستد)."""
    videos = data.get("videos")
    if isinstance(videos, dict) and videos.get("video_list"):
        return True
    story = data.get("story_pin_data")
    if isinstance(story, dict):
        for page in story.get("pages") or []:
            if not isinstance(page, dict):
                continue
            for block in page.get("blocks") or []:
                if not isinstance(block, dict):
                    continue
                video = block.get("video")
                if isinstance(video, dict) and video.get("video_list"):
                    return True
    return False


def _pinterest_image_signature(url: str) -> str:
    """کلید یکتا برای تشخیص عکس تکراری: نام فایل بدون پسوند.
    یک عکس ممکن است دو آدرس داشته باشد (‎.jpg توی صفحه‌ها و ‎.heic
    توی images اصلی) — هش فایل یکی است."""
    try:
        name = urlparse(url).path.rsplit("/", 1)[-1]
        return name.rsplit(".", 1)[0].lower()
    except Exception:
        return (url or "").lower()


def _largest_image_url(images: dict | None) -> str | None:
    """بزرگ‌ترین ورودی یک دیکشنری images (بر اساس مساحت)."""
    best: str | None = None
    best_area = -1
    for entry in (images or {}).values():
        if not isinstance(entry, dict):
            continue
        u = entry.get("url")
        if not u:
            continue
        area = (entry.get("width") or 0) * (entry.get("height") or 0)
        if area >= best_area:
            best_area = area
            best = u
    return best


def _pinterest_pick_images(data: dict) -> list[list[str]]:
    """عکس‌های پین با کیفیت اصلی؛ هر عکس یک فهرست آدرس جایگزین
    دارد (بهترین اول). ترتیب: اول اسلات‌های carousel (پین
    چندعکسی)، بعد صفحه‌های story، بعد عکس اصلی پین. عکس تکراری
    (یک هش، دو پسوند) فقط یک بار می‌آید — آدرس دومش جایگزین همان
    عکس می‌شود. اسلات carousel نسخه orig ندارد (فقط تا 736x)،
    پس URL اصلی‌اش از روی signature ساخته می‌شود و پسوند درست
    (jpg/png/heic/…) با تلاش به‌ترتیب در دانلود پیدا می‌شود —
    پسوند نسخه کوچک با پسوند اصلی یکی نیست و نمی‌شود از روی آن
    حدس زد."""
    images: list[list[str]] = []
    by_sig: dict[str, list[str]] = {}

    def _add(u: str | None) -> None:
        if not u:
            return
        sig = _pinterest_image_signature(u)
        if sig in by_sig:
            if u not in by_sig[sig]:
                by_sig[sig].append(u)
        else:
            by_sig[sig] = [u]
            images.append(by_sig[sig])

    def _add_carousel_slot(sized_url: str | None) -> None:
        """یک اسلات carousel: اول آدرس‌های originals با پسوندهای
        محتمل (به‌ترتیب)، بعد همان نسخه کوچک به‌عنوان fallback —
        اگر هیچ originals‌ای نشد، همان 736x دانلود می‌شود تا عکس
        از دست نرود."""
        if not sized_url:
            return
        sig = _pinterest_image_signature(sized_url)
        if len(sig) >= 6:
            for ext in ("jpg", "png", "heic", "jpeg", "webp"):
                _add(
                    "https://i.pinimg.com/originals/"
                    f"{sig[0:2]}/{sig[2:4]}/{sig[4:6]}/{sig}.{ext}"
                )
        _add(sized_url)

    carousel = data.get("carousel_data")
    if isinstance(carousel, dict):
        for slot in carousel.get("carousel_slots") or []:
            if not isinstance(slot, dict):
                continue
            _add_carousel_slot(
                _largest_image_url(slot.get("images"))
            )

    story = data.get("story_pin_data")
    if isinstance(story, dict):
        for page in story.get("pages") or []:
            if not isinstance(page, dict):
                continue
            for block in page.get("blocks") or []:
                if not isinstance(block, dict):
                    continue
                img = block.get("image")
                if not isinstance(img, dict):
                    continue
                imgs = img.get("images")
                if not isinstance(imgs, dict) or not imgs:
                    continue
                orig = imgs.get("originals")
                u = orig.get("url") if isinstance(orig, dict) else None
                _add(u or _largest_image_url(imgs))

    main = data.get("images")
    if isinstance(main, dict) and main:
        orig = main.get("orig")
        u = orig.get("url") if isinstance(orig, dict) else None
        _add(u or _largest_image_url(main))

    return images[:PINTEREST_MAX_IMAGES]


def _pinterest_736x_variant(url: str) -> str | None:
    """نسخه 736x همان عکس (i.pinimg.com همیشه این نسخه را دارد).
    None اگر آدرس از اول 736x باشد یا شکلش عادی نباشد."""
    try:
        parts = urlparse(url).path.split("/")
        # /<size>/<h1>/<h2>/<h3>/<file>
        if len(parts) < 3 or parts[1] == "736x":
            return None
        stem = parts[-1].rsplit(".", 1)[0]
        return "https://i.pinimg.com/736x/" + "/".join(
            parts[2:-1] + [stem + ".jpg"]
        )
    except Exception:
        return None


def _pinterest_download_image_sync(candidates: list[str], outdir: str,
                                   index: int) -> Path | None:
    """یک عکس پین را دانلود می‌کند. اول آدرس‌های اصلی (به ترتیب)،
    بعد برای heic نسخه ‎.jpg همان هش، و در آخر نسخه 736x — چون
    آدرس originals با ‎.jpg گاهی 403 می‌دهد (وقتی اصل فایل heic
    است). اصل heic با ffmpeg به jpg تبدیل می‌شود تا تلگرام آن را
    عکس نشان بدهد؛ اگر تبدیل نشد، خود ‎.heic نگه داشته می‌شود
    (به‌عنوان فایل فرستاده می‌شود). None اگر هیچ آدرسی نشد."""
    attempts: list[str] = []
    for u in candidates:
        if u and u not in attempts:
            attempts.append(u)
        if u and u.lower().endswith((".heic", ".heif")):
            jpg = u.rsplit(".", 1)[0] + ".jpg"
            if jpg not in attempts:
                attempts.append(jpg)
    for u in candidates:
        alt = _pinterest_736x_variant(u)
        if alt and alt not in attempts:
            attempts.append(alt)

    for attempt_url in attempts:
        try:
            req = urllib.request.Request(
                attempt_url,
                headers={
                    "User-Agent": CHROME_USER_AGENT,
                    "Referer": "https://www.pinterest.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status != 200:
                    continue
                blob = resp.read()
            if not blob:
                continue
            tail = attempt_url.rsplit("/", 1)[-1]
            ext = tail.rsplit(".", 1)[-1].lower() if "." in tail else "jpg"
            if ext not in ("jpg", "jpeg", "png", "webp", "heic", "heif", "gif"):
                ext = "jpg"
            path = Path(outdir) / f"pin_{index:02d}.{ext}"
            path.write_bytes(blob)
            if ext in ("heic", "heif"):
                jpg = Path(outdir) / f"pin_{index:02d}.jpg"
                r = subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-i", str(path), str(jpg)],
                    capture_output=True, timeout=120,
                )
                if r.returncode == 0 and jpg.is_file() and jpg.stat().st_size > 0:
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    return jpg
                logger.warning(
                    "HEIC convert failed for %s; keeping .heic", attempt_url
                )
            return path
        except Exception:
            logger.warning(
                "Pinterest image download failed: %s", attempt_url
            )
            continue
    return None


async def _send_pinterest_photos(bot, chat_id: int, files: list[Path],
                                 caption: str | None,
                                 tracker: ProgressTracker | None = None) -> bool:
    """عکس‌های پین را می‌فرستد. دو عکس یا بیشتر (هر کدام زیر ۱۰ مگ)
    به‌صورت یک آلبوم (media group، کپشن روی عکس اول) می‌روند —
    کاربر همه را یک‌جا می‌بیند، نه تک‌تک. تک‌عکس، عکس‌های بالای
    ۱۰ مگ و بقیه فایل‌ها (‎.heic تبدیل‌نشده، گیف) با send_files
    معمولی فرستاده می‌شوند؛ اگر آلبوم خطا داد، همان دسته تک‌تک
    فرستاده می‌شود. True اگر چیزی فرستاده شد."""
    photos = [
        p for p in files
        if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
    ]
    groupable = [
        p for p in photos
        if p.stat().st_size <= PINTEREST_PHOTO_MAX_BYTES
    ]
    rest = [p for p in files if p not in groupable]
    sent_any = False

    if len(groupable) >= 2:
        if tracker is not None:
            tracker.begin_upload(
                len(groupable),
                sum(p.stat().st_size for p in groupable),
            )
        for start in range(0, len(groupable), 10):
            chunk = groupable[start:start + 10]
            if len(chunk) < 2:
                # آلبوم تلگرام حداقل ۲ عکس می‌خواهد؛ تک‌عکس باقی‌مانده
                # (مثلاً عکس یازدهم) تک‌تک فرستاده می‌شود.
                caps = [caption if (start == 0) else None]
                if await send_files(
                    bot, chat_id, chunk, caps, tracker=tracker
                ):
                    sent_any = True
                continue
            try:
                media = []
                handles = []
                for i, p in enumerate(chunk):
                    f = open(p, "rb")
                    handles.append(f)
                    media.append(
                        InputMediaPhoto(
                            media=f,
                            caption=caption
                            if (start == 0 and i == 0) else None,
                        )
                    )
                try:
                    await bot.send_media_group(chat_id=chat_id, media=media)
                finally:
                    for f in handles:
                        try:
                            f.close()
                        except Exception:
                            pass
                sent_any = True
                if tracker is not None:
                    for p in chunk:
                        tracker.mark_upload_part_done(p.stat().st_size)
            except Exception:
                logger.exception(
                    "Pinterest media group failed; sending photos one by one"
                )
                caps = [
                    caption if (start == 0 and i == 0) else None
                    for i in range(len(chunk))
                ]
                if await send_files(
                    bot, chat_id, chunk, caps, tracker=tracker
                ):
                    sent_any = True
    else:
        rest = groupable + rest

    if rest:
        caps = [caption if not sent_any else None] + [None] * (len(rest) - 1)
        if await send_files(bot, chat_id, rest, caps, tracker=tracker):
            sent_any = True
    return sent_any


async def do_pinterest_download(bot, chat_id: int, url: str) -> str:
    """دانلود پینترست — مثل اینستاگرام و تیک‌تاک: دانلود مستقیم،
    بدون منوی کیفیت، کپشن فقط «@ربات ❤️».
    برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'
    اول لینک pin.it باز می‌شود و آیدی پین از URL درمی‌آید؛ لینک
    بورد/پروفایل پین تکی نیست و 'empty' برمی‌گرداند.
    پین ویدیویی: مثل تیک‌تاک با yt-dlp دانلود می‌شود.
    پین عکسی: همه عکس‌های پین با کیفیت اصلی (originals) از
    API خود پینترست گرفته می‌شوند — پین چندعکسی همه عکس‌ها را
    می‌فرستد، نه فقط اولی؛ عکس‌ها به‌صورت یک آلبوم (media group)
    فرستاده می‌شوند."""
    tracker = ProgressTracker()
    done = asyncio.Event()
    status = await bot.send_message(
        chat_id=chat_id, text=_progress_text(0, "info"),
    )
    watcher = asyncio.create_task(
        _watch_progress(
            bot, chat_id, status.message_id, tracker, done, False,
        )
    )
    try:
        with tempfile.TemporaryDirectory(prefix="pin-") as tmpdir:
            # ۰) pin.it را باز کن و آیدی پین را بگیر
            resolved = await asyncio.to_thread(
                _resolve_pinterest_url_sync, url
            )
            pin_id = _extract_pinterest_pin_id(resolved or url)
            if not pin_id:
                return "empty"
            # ۱) اطلاعات پین از API پینترست
            data = await asyncio.to_thread(
                _fetch_pinterest_pin_sync, pin_id
            )
            if not data:
                return "empty"
            # ۲) پین ویدیویی: مثل تیک‌تاک (اول لینک مستقیم،
            # بعد دانلود با yt-dlp، بعد ارسال).
            if _pinterest_has_video(data):
                info = await asyncio.to_thread(
                    _fetch_info_sync, resolved or url
                )
                if info:
                    caption = await instagram_caption(bot)
                    if await _try_direct_url_send(
                        bot, chat_id, info, 720, caption, None, tracker
                    ):
                        return "ok"
                try:
                    title, files, was_split = await download_best_effort(
                        resolved or url, tmpdir,
                        prefer_telethon=bot_telethon_available() or telethon_send_enabled(),
                        tracker=tracker,
                    )
                except Exception:
                    logger.exception(
                        "Pinterest video download failed for %s", url
                    )
                    return "error"
                if not files:
                    return "empty"
                sent = await _deliver(
                    bot, chat_id, tmpdir, title, files, was_split,
                    "instagram", tracker=tracker,
                )
                if sent:
                    return "ok"
                if all(p.stat().st_size > MAX_BYTES for p in files):
                    return "too_big"
                return "empty"
            # ۳) پین عکسی: همه عکس‌ها با کیفیت اصلی
            candidates = _pinterest_pick_images(data)
            if not candidates:
                return "empty"
            tracker.set_phase("download")
            tracker.total = len(candidates)
            files: list[Path] = []
            for i, cands in enumerate(candidates):
                try:
                    path = await asyncio.to_thread(
                        _pinterest_download_image_sync, cands, tmpdir, i
                    )
                except Exception:
                    logger.exception(
                        "Pinterest image download failed for %s", url
                    )
                    path = None
                if path is not None:
                    files.append(path)
                tracker.downloaded = len(files)
            if not files:
                return "empty"
            caption = await instagram_caption(bot)
            sent = await _send_pinterest_photos(
                bot, chat_id, files, caption, tracker=tracker
            )
            if sent:
                return "ok"
            if all(p.stat().st_size > MAX_BYTES for p in files):
                return "too_big"
            return "empty"
    finally:
        done.set()
        watcher.cancel()
        try:
            await status.delete()
        except Exception:
            pass


async def _watch_progress(bot, chat_id: int, message_id: int,
                          tracker: ProgressTracker,
                          done: asyncio.Event,
                          is_photo: bool) -> None:
    """هر ۵ ثانیه پیام پیشرفت را با فاز و درصد فعلی ویرایش می‌کند.
    همه فازها را نشان می‌دهد: آماده‌سازی، دانلود، ارسال مستقیم،
    تقسیم و آپلود — با سرعت و ETA هر جا که معلوم باشد."""
    last_text = ""
    try:
        while not done.is_set():
            await asyncio.sleep(5)
            text = tracker.display_text()
            if text == last_text:
                continue
            last_text = text
            try:
                if is_photo:
                    await bot.edit_message_caption(
                        chat_id=chat_id, message_id=message_id,
                        caption=text,
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=message_id,
                        text=text,
                    )
            except Exception:
                pass
    except asyncio.CancelledError:
        pass


async def do_pornhub_download(bot, chat_id: int, url: str,
                              height: int) -> str:
    """دانلود پورن‌هاب با کیفیت انتخاب‌شده.
    برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'
    پیام پیشرفت از همان ثانیه اول (فاز آماده‌سازی) هست و همه
    فازها را نشان می‌دهد؛ اول اطلاعات + کاور گرفته می‌شود و پیام
    متنی به عکس کاور تبدیل می‌شود، بعد لینک مستقیم امتحان می‌شود
    و اگر نشد دانلود با کیفیت انتخاب‌شده شروع می‌شود. اگر دانلود
    با کیفیت انتخاب‌شده نشد، نردبان کیفیت (probe/720→480→360)
    به‌عنوان fallback اجرا می‌شود. ویدیو با همان کاور به‌عنوان
    thumbnail فرستاده می‌شود."""
    with tempfile.TemporaryDirectory(prefix="ph-") as tmpdir:
        tracker = ProgressTracker()
        done = asyncio.Event()
        progress_msg = None
        is_photo = False
        watcher = None

        def _start_watcher() -> None:
            nonlocal watcher
            if progress_msg is not None:
                watcher = asyncio.create_task(
                    _watch_progress(
                        bot, chat_id, progress_msg.message_id,
                        tracker, done, is_photo,
                    )
                )

        try:
            # ۰) پیام پیشرفت از همان اول (فاز آماده‌سازی) تا هیچ
            # مرحله‌ای ساکت نباشد.
            try:
                progress_msg = await bot.send_message(
                    chat_id=chat_id, text=_progress_text(0, "info"),
                )
                _start_watcher()
            except Exception:
                progress_msg = None
                logger.exception("Could not send progress message")

            # ۱) اطلاعات + کاور (بدون دانلود ویدیو)
            info = await asyncio.to_thread(_fetch_info_sync, url)
            title = str((info or {}).get("title") or "")
            cover = None
            if info:
                cover = await asyncio.to_thread(
                    _download_cover_sync, info.get("thumbnail"), tmpdir
                )

            # ۲) اگر کاور هست، پیام متنی را به عکس کاور تبدیل کن
            # (همان پیام پیشرفت، فقط با عکس).
            if cover is not None and progress_msg is not None:
                try:
                    if watcher is not None:
                        watcher.cancel()
                    await progress_msg.delete()
                except Exception:
                    pass
                try:
                    with open(cover, "rb") as f:
                        progress_msg = await bot.send_photo(
                            chat_id=chat_id, photo=f,
                            caption=tracker.display_text(),
                        )
                    is_photo = True
                    _start_watcher()
                except Exception:
                    progress_msg = None
                    logger.exception("Could not send cover progress photo")

            # ۲٫۵) اول لینک مستقیم امتحان می‌شود (بدون دانلود روی
            # ریل‌وی)؛ اگر نشد می‌رویم سراغ دانلود معمولی.
            if info:
                if await _try_direct_url_send(
                    bot, chat_id, info, height,
                    title[:200] if title else None, cover, tracker,
                ):
                    return "ok"

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
                    prefer_telethon=bot_telethon_available() or telethon_send_enabled(),
                    tracker=tracker,
                )
                if not files:
                    return "error"

            # ۵) ارسال (ویدیو با کاور)
            sent = await _deliver(
                bot, chat_id, tmpdir, title, files, was_split,
                "title", thumb=cover, tracker=tracker,
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


# ---------------------------------------------------------------------------
# دانلود یوتیوب با وب‌سرویس GFw (به‌جای yt-dlp)
# ---------------------------------------------------------------------------
# یوتیوب روی IP دیتاسنتر (ریل‌وی) با yt-dlp کامل بلاک بود: همه
# کلاینت‌های پخش‌کننده صفحه «Sign in to confirm you're not a
# bot» می‌دادند و حتی با کوکی هم Shorts خطا می‌داد. پس یوتیوب
# حالا از وب‌سرویس GFw می‌آید: یک GET با quality=best همه
# کیفیت‌ها را برمی‌گرداند و لینک‌های مستقیم googlevideo را
# می‌دهد که به IP قفل نیستند (از IP دیگر هم ۲۰۶ می‌دهند).
# نکته مهم: همه ویدیوها adaptive و فقط-تصویر هستند (itagهای
# ۱۳۶/۱۳۷ و…) — هیچ itag progressive (۱۸/۲۲) با صدا نیست؛ پس
# ویدیو حتماً باید با بهترین صدا میکس شود (ffmpeg -c copy،
# بدون ریکد)، وگرنه ویدیوی بی‌صدا فرستاده می‌شود. اگر دانلود
# صدا یا میکس نشد، خطا برمی‌گردد و ویدیوی بی‌صدا فرستاده
# نمی‌شود. لینک‌های googlevideo حدود ۶ ساعت اعتبار دارند، پس
# دانلود باید همان‌موقع شروع شود.
# کلید فقط از متغیر محیطی GFWDEV_API_KEY می‌آید و هیچ‌جا
# هاردکد یا لاگ نمی‌شود.

# itagهای progressive یوتیوب (صدا+تصویر با هم) — اگر وب‌سرویس
# روزی یکی از این‌ها را برگرداند، ویدیو خودش صدا دارد و نیازی
# به میکس با صدای جدا نیست.
_PROGRESSIVE_ITAGS = {18, 22, 37, 43}


def _gfw_itag(url: str) -> int | None:
    """itag را از کوئری لینک googlevideo می‌خواند؛ None اگر نباشد."""
    try:
        values = parse_qs(urlparse(url or "").query).get("itag")
        return int(values[0]) if values else None
    except (ValueError, TypeError):
        return None


def _gfw_needs_audio_mux(video_entry: dict) -> bool:
    """True اگر ویدیوی انتخاب‌شده صدا ندارد و باید با صدای جدا
    میکس شود. itag معلوم نباشد هم True می‌دهد (محتاطانه: میکس
    با صدای جدا ضرری ندارد)."""
    itag = _gfw_itag(str(video_entry.get("url") or ""))
    return itag not in _PROGRESSIVE_ITAGS


def _gfw_api_error_code(msg: str, http_status: int | None) -> str:
    """پیام خطای وب‌سرویس را به کد کوتاه نتیجه تبدیل می‌کند:
    "age" | "bad_key" | "unavailable" | "error"."""
    low = (msg or "").lower()
    if any(k in low for k in (
        "age-restricted", "age-gated", "age restriction",
        "age limit", "confirm your age", "age verification",
    )):
        return "age"
    if http_status in (401, 403) or any(k in low for k in (
        "api_key", "api key", "invalid key", "invalid api",
        "unauthorized", "license", "expired key", "forbidden",
    )):
        return "bad_key"
    if any(k in low for k in (
        "unavailable", "private", "not found", "removed",
        "deleted", "no longer available", "video not found",
    )):
        return "unavailable"
    return "error"


def _gfw_youtube_info_sync(
    url: str, api_key: str, timeout: int = 60
) -> tuple[dict | None, str]:
    """اطلاعات یوتیوب را از وب‌سرویس GFw می‌گیرد (فقط stdlib).
    برمی‌گرداند: (data یا None، کد خطا یا "").
    کد خطا: "no_key" (کلید ست نشده) | "bad_key" (کلید نامعتبر)
    | "unavailable" (ویدیو در دسترس نیست) | "age" | "error"."""
    if not api_key:
        return None, "no_key"
    api_url = (
        f"{GFWDEV_API_BASE}?url={quote(url, safe='')}"
        f"&api_key={quote(api_key, safe='')}&quality=best"
    )
    req = urllib.request.Request(
        api_url, headers={"User-Agent": CHROME_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        msg = ""
        try:
            body = e.read().decode("utf-8", "replace")
            try:
                msg = str(json.loads(body).get("message") or "")
            except Exception:
                msg = body
        except Exception:
            pass
        logger.warning(
            "GFw YouTube API HTTP %s for %s: %s", e.code, url, msg[:200]
        )
        return None, _gfw_api_error_code(msg, e.code)
    except Exception:
        logger.exception("GFw YouTube API request failed for %s", url)
        return None, "error"
    if status != 200:
        return None, "error"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        logger.warning("GFw YouTube API returned invalid JSON for %s", url)
        return None, "error"
    if not isinstance(payload, dict):
        return None, "error"
    if not payload.get("status"):
        return None, _gfw_api_error_code(
            str(payload.get("message") or ""), None
        )
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(
        data.get("downloads"), dict
    ):
        return None, "error"
    return data, ""


def _gfw_pick_video(entries: list, height: int) -> dict | None:
    """بهترین ویدیوی mp4: اول همان ارتفاع دقیق، بعد بالاترین
    mp4 تا ارتفاع خواسته‌شده، بعد پایین‌ترین mp4. None اگر
    هیچ mp4ای نباشد."""
    mp4s: list[tuple[int, dict]] = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        if (e.get("format") or "").lower() != "mp4":
            continue
        try:
            h = int(str(e.get("quality") or "").strip().rstrip("p"))
        except ValueError:
            continue
        if h > 0 and e.get("url"):
            mp4s.append((h, e))
    if not mp4s:
        return None
    for h, e in mp4s:
        if h == height:
            return e
    below = [(h, e) for h, e in mp4s if h < height]
    if below:
        return max(below, key=lambda t: t[0])[1]
    return min(mp4s, key=lambda t: t[0])[1]


def _gfw_audio_kbps(entry: dict) -> int:
    """بیت‌ریت صدا از quality (مثل "129kbps")؛ ۰ اگر معلوم نباشد."""
    try:
        return int(
            str(entry.get("quality") or "").lower()
            .replace("kbps", "").strip()
        )
    except ValueError:
        return 0


def _gfw_pick_audio(entries: list) -> dict | None:
    """بهترین صدا: اول m4a با بالاترین بیت‌ریت (معمولاً itag 140
    با 129kbps)، وگرنه بالاترین بیت‌ریت webm. None اگر صدایی
    نباشد."""
    best: dict | None = None
    best_key: tuple[int, int] | None = None
    for e in entries or []:
        if not isinstance(e, dict) or not e.get("url"):
            continue
        fmt = (e.get("format") or "").lower()
        key = (1 if fmt == "m4a" else 0, _gfw_audio_kbps(e))
        if best is None or key > best_key:
            best, best_key = e, key
    return best


def _probe_range_support_sync(url: str,
                              error_out: dict | None = None) -> str:
    """می‌پرسد سرور Range را می‌فهمد یا نه (یک درخواست ۱ بایتی).
    برمی‌گرداند: "range" (۲۰۶) | "no_range" (۲۰۰) | "forbidden"
    (۴۰۳) | "gone" (۴۰۴/۴۱۰) | "unknown" (هر خطای دیگر)."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": CHROME_USER_AGENT,
            "Referer": "https://www.youtube.com/",
            "Range": "bytes=0-0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status == 206:
                return "range"
            if resp.status == 200:
                return "no_range"
            return "unknown"
    except urllib.error.HTTPError as e:
        if e.code == 403:
            if error_out is not None:
                error_out["forbidden"] = True
            return "forbidden"
        if e.code in (404, 410):
            return "gone"
        return "unknown"
    except Exception:
        return "unknown"


def _refresh_download_tracker(tracker, downloaded: int, t0: float,
                              total: int) -> None:
    """downloaded/speed/ETA ترکر را از مجموع واقعی بایت‌ها می‌سازد."""
    elapsed = time.monotonic() - t0
    tracker.downloaded = downloaded
    tracker.speed = downloaded / elapsed if elapsed > 0 else 0
    if total and tracker.speed > 0:
        tracker.eta = int((total - downloaded) / tracker.speed)


def _download_part_sync(url: str, start: int, end: int, part_path: Path,
                        part_counters: list, part_idx: int,
                        lock: threading.Lock,
                        tracker, t0: float, total: int,
                        attempts: int = 3) -> str:
    """یک بازه بایتی را با Range دانلود می‌کند؛ هر قسمت خودش تا
    ۳ بار امتحان می‌شود (فقط همان قسمت، نه کل فایل).
    شمارنده پیشرفت برای هر قسمت جداست و با شروع هر تلاش دوباره
    صفر می‌شود؛ ترکر همیشه مجموع واقعی بایت‌های دانلودشده را
    نشان می‌دهد و هیچ‌وقت از بایت‌های واقعی جلو نمی‌زند.
    برمی‌گرداند: "ok" | "forbidden" | "gone" | "no_range" | "failed"."""
    size = end - start + 1
    headers = {
        "User-Agent": CHROME_USER_AGENT,
        "Referer": "https://www.youtube.com/",
        "Range": f"bytes={start}-{end}",
    }
    for attempt in range(1, attempts + 1):
        # تلاش دوباره از صفر همین قسمت شروع می‌شود، پس بایت‌های
        # تلاش قبلی نباید دوباره شمرده شوند.
        if tracker is not None:
            with lock:
                part_counters[part_idx] = 0
                _refresh_download_tracker(
                    tracker, sum(part_counters), t0, total
                )
        try:
            if part_path.is_file():
                part_path.unlink()
        except OSError:
            pass
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status == 200:
                    return "no_range"
                if resp.status != 206:
                    raise urllib.error.HTTPError(
                        url, resp.status, "unexpected status", {}, None
                    )
                with open(part_path, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        if tracker is not None:
                            with lock:
                                part_counters[part_idx] += len(chunk)
                                _refresh_download_tracker(
                                    tracker, sum(part_counters), t0, total
                                )
                if part_path.is_file() \
                        and part_path.stat().st_size == size:
                    return "ok"
                logger.warning(
                    "Part %d-%d incomplete (attempt %d/%d)",
                    start, end, attempt, attempts,
                )
        except urllib.error.HTTPError as e:
            if e.code == 403:
                return "forbidden"
            if e.code in (404, 410):
                return "gone"
            logger.warning(
                "Part %d-%d HTTP %s (attempt %d/%d)",
                start, end, e.code, attempt, attempts,
            )
        except Exception:
            logger.warning(
                "Part %d-%d failed (attempt %d/%d)",
                start, end, attempt, attempts, exc_info=True,
            )
    return "failed"


def _download_ranged_sync(url: str, dest: Path, total: int, tracker=None,
                          attempts: int = 3,
                          error_out: dict | None = None) -> bool:
    """فایل را در حداکثر ۸ قسمت موازی با Range دانلود می‌کند
    (هر قسمت حدود ۸ تا ۱۰ مگابایت؛ فایل کوچک یک قسمت دارد)،
    بعد قسمت‌ها را به ترتیب به هم می‌چسباند و اندازه نهایی را
    با total چک می‌کند. True اگر فایل کامل آمد."""
    nparts = max(1, min(8, -(-total // (8 * 1024 * 1024))))
    part_size = -(-total // nparts)
    bounds = []
    for i in range(nparts):
        start = i * part_size
        end = min(start + part_size, total) - 1
        bounds.append((start, end))
    if tracker is not None:
        tracker.set_phase("download", 0)
        tracker.total = total
        tracker.downloaded = 0
        tracker.speed = 0.0
        tracker.eta = 0
    t0 = time.monotonic()
    # شمارنده جدا برای هر قسمت؛ ترکر مجموع آن‌هاست، پس تلاش
    # دوباره یک قسمت، بایت‌های تلاش قبلی را دو بار نمی‌شمارد.
    part_counters = [0] * nparts
    lock = threading.Lock()
    part_paths = [
        dest.parent / f"{dest.name}.part{i}" for i in range(nparts)
    ]
    statuses: dict[int, str] = {}
    try:
        for p in part_paths:
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass
        with ThreadPoolExecutor(max_workers=min(8, nparts)) as ex:
            futs = {
                ex.submit(
                    _download_part_sync, url, s, e, part_paths[i],
                    part_counters, i, lock, tracker, t0, total, attempts,
                ): i
                for i, (s, e) in enumerate(bounds)
            }
            for fut in as_completed(futs):
                idx = futs[fut]
                try:
                    statuses[idx] = fut.result()
                except Exception:
                    statuses[idx] = "failed"
                if statuses[idx] == "forbidden":
                    ex.shutdown(wait=False, cancel_futures=True)
                    break
        if any(s == "forbidden" for s in statuses.values()):
            if error_out is not None:
                error_out["forbidden"] = True
            return False
        if any(s == "gone" for s in statuses.values()):
            return False
        if len(statuses) != nparts \
                or any(s != "ok" for s in statuses.values()):
            logger.warning(
                "Ranged download incomplete for %s: %s", dest, statuses
            )
            return False
        try:
            if dest.is_file():
                dest.unlink()
        except OSError:
            pass
        with open(dest, "wb") as out:
            for p in part_paths:
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
        if dest.is_file() and dest.stat().st_size == total:
            return True
        logger.warning(
            "Ranged download size mismatch for %s: %d of %d",
            dest, dest.stat().st_size if dest.is_file() else -1, total,
        )
        return False
    finally:
        for p in part_paths:
            try:
                if p.is_file():
                    p.unlink()
            except OSError:
                pass


def _download_url_sync(url: str, dest: Path, tracker=None,
                       total_size: int | None = None,
                       attempts: int = 3,
                       error_out: dict | None = None) -> bool:
    """یک فایل را با urllib دانلود می‌کند (لینک مستقیم
    googlevideo)؛ درصد/سرعت/ETA توی ترکر می‌آید (فاز دانلود).
    استریم ساده googlevideo تا حد چند ده کیلوبایت بر ثانیه
    خفه می‌شود و وسط راه timeout می‌خورد، پس وقتی اندازه کل
    معلوم است، فایل در حداکثر ۸ قسمت موازی با Range دانلود
    می‌شود (هر قسمت جدا retry می‌شود)؛ اگر اندازه معلوم نباشد
    یا سرور Range نفهمد، همان استریم ساده قبلی استفاده می‌شود.
    تا ۳ بار دوباره امتحان می‌کند؛ True اگر فایل کامل آمد.
    اگر 403 خورد، error_out["forbidden"]=True می‌شود تا تماس‌گیرنده
    بتواند لینک تازه بگیرد."""
    total = total_size if isinstance(total_size, int) \
        and total_size > 0 else None
    if total is None:
        return _download_single_stream_sync(
            url, dest, tracker, attempts, None, error_out
        )
    probe = _probe_range_support_sync(url, error_out)
    if probe == "forbidden":
        return False
    if probe != "range":
        return _download_single_stream_sync(
            url, dest, tracker, attempts, total, error_out
        )
    return _download_ranged_sync(
        url, dest, total, tracker, attempts, error_out
    )


async def _download_gfw_file(yt_url: str, entry: dict, dest: Path,
                             tracker, kind: str,
                             height: int | None = None) -> bool:
    """یک فایل GFw (ویدیو یا صدا) را دانلود می‌کند؛ اگر 403 خورد،
    لینک‌های تازه را یک بار از وب‌سرویس می‌گیرد و همان فایل را
    یک بار دیگر امتحان می‌کند. True یعنی فایل کامل آمد.
    kind: "video" (با height برای انتخاب دوباره) یا "audio"."""
    size = entry.get("size")
    total = int(size) if isinstance(size, int) else None
    err: dict = {}
    ok = await asyncio.to_thread(
        _download_url_sync, str(entry["url"]), dest, tracker, total,
        error_out=err,
    )
    if ok or not err.get("forbidden"):
        return ok
    logger.warning(
        "GFw download 403 for %s; refreshing links once", yt_url
    )
    data, _ = await asyncio.to_thread(
        _gfw_youtube_info_sync, yt_url, GFWDEV_API_KEY
    )
    if data is None:
        return False
    downloads = data.get("downloads") or {}
    if kind == "video":
        fresh = _gfw_pick_video(
            downloads.get("video") or [], height or 0
        )
    else:
        fresh = _gfw_pick_audio(downloads.get("audio") or [])
    if fresh is None or not fresh.get("url"):
        return False
    fsize = fresh.get("size")
    return await asyncio.to_thread(
        _download_url_sync, str(fresh["url"]), dest, tracker,
        int(fsize) if isinstance(fsize, int) else None,
    )


def _download_single_stream_sync(url: str, dest: Path, tracker=None,
                                 attempts: int = 3,
                                 total_size: int | None = None,
                                 error_out: dict | None = None) -> bool:
    """استریم ساده قبلی (fallback وقتی اندازه معلوم نیست یا
    سرور Range نمی‌فهمد)؛ تا ۳ بار دوباره امتحان می‌کند؛
    True اگر فایل کامل آمد. 403 را در error_out گزارش می‌کند."""
    for attempt in range(1, attempts + 1):
        try:
            if dest.is_file():
                dest.unlink()
        except OSError:
            pass
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": CHROME_USER_AGENT,
                    "Referer": "https://www.youtube.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = total_size or 0
                try:
                    total = total or int(
                        resp.headers.get("Content-Length") or 0
                    )
                except (ValueError, TypeError):
                    total = total_size or 0
                if tracker is not None:
                    tracker.set_phase("download", 0)
                    tracker.total = total
                    tracker.downloaded = 0
                    tracker.speed = 0.0
                    tracker.eta = 0
                start = time.monotonic()
                downloaded = 0
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if tracker is not None:
                            elapsed = time.monotonic() - start
                            tracker.downloaded = downloaded
                            tracker.speed = (
                                downloaded / elapsed if elapsed > 0 else 0
                            )
                            if total and tracker.speed > 0:
                                tracker.eta = int(
                                    (total - downloaded) / tracker.speed
                                )
            if dest.is_file() and dest.stat().st_size > 0:
                if total and dest.stat().st_size < total:
                    logger.warning(
                        "Download incomplete for %s: %d of %d bytes",
                        dest, dest.stat().st_size, total,
                    )
                    continue
                return True
            logger.warning("Download gave empty file for %s", dest)
        except urllib.error.HTTPError as e:
            # لینک منقضی/ردشده (403/404/410) با retry درست نمی‌شود.
            logger.warning(
                "Download HTTP %s for %s (attempt %d/%d)",
                e.code, url, attempt, attempts,
            )
            if e.code == 403 and error_out is not None:
                error_out["forbidden"] = True
            if e.code in (403, 404, 410):
                return False
        except Exception:
            logger.exception(
                "Download failed for %s (attempt %d/%d)",
                url, attempt, attempts,
            )
    return False


def _mux_video_audio_sync(video: Path, audio: Path, out: Path,
                          duration_s: float | None = None,
                          tracker=None) -> int:
    """ویدیوی فقط-تصویر + صدای جدا را با ffmpeg -c copy (بدون
    ریکد، سریع) به یک mp4 میکس می‌کند. کد بازگشت ffmpeg را
    برمی‌گرداند (۰ یعنی موفق)."""
    return _run_ffmpeg_progress(
        [
            "ffmpeg", "-y",
            "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c", "copy", "-movflags", "+faststart",
            str(out),
        ],
        duration_s, tracker, "info",
    )


def _convert_audio_to_mp3_sync(audio_in: Path, out: Path,
                               duration_s: float | None = None,
                               tracker=None) -> int:
    """صدا (m4a/webm) را به mp3 تبدیل می‌کند. کد بازگشت ffmpeg
    را برمی‌گرداند (۰ یعنی موفق)."""
    return _run_ffmpeg_progress(
        [
            "ffmpeg", "-y", "-i", str(audio_in),
            "-codec:a", "libmp3lame", "-q:a", "2",
            str(out),
        ],
        duration_s, tracker, "info",
    )


async def do_youtube_download(bot, chat_id: int, url: str,
                              height: int, audio: bool = False) -> str:
    """دانلود یوتیوب با وب‌سرویس GFw — دقیقاً مثل پورن‌هاب: اول
    اطلاعات + کاور، پیام پیشرفت با عکس کاور که هر ۵ ثانیه
    ویرایش می‌شود، بعد دانلود با کیفیت انتخاب‌شده و ارسال
    ویدیو با همان کاور به‌عنوان thumbnail. اگر audio=True
    باشد، فقط بهترین صدا دانلود و به mp3 تبدیل می‌شود و با
    عنوان ویدیو فرستاده می‌شود.
    وب‌سرویس همه ویدیوها را فقط-تصویر (adaptive) می‌دهد، پس
    ویدیو حتماً با بهترین صدا میکس می‌شود (ffmpeg -c copy،
    بدون ریکد)؛ اگر دانلود صدا یا میکس نشد، خطا برمی‌گردد و
    ویدیوی بی‌صدا فرستاده نمی‌شود. دانلود لینک‌های googlevideo
    با درخواست‌های Range موازی انجام می‌شود (استریم ساده خفه
    می‌شود) و اگر 403 خورد، لینک تازه یک بار گرفته می‌شود.
    برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error' | 'age'
    | 'no_key' | 'bad_key' | 'unavailable'
    ('no_key' یعنی کلید وب‌سرویس ست نشده؛ 'bad_key' یعنی کلید
    مشکل دارد؛ 'unavailable' یعنی ویدیو در دسترس نیست)."""
    if not GFWDEV_API_KEY:
        return "no_key"
    with tempfile.TemporaryDirectory(prefix="yt-") as tmpdir:
        tracker = ProgressTracker()
        done = asyncio.Event()
        progress_msg = None
        is_photo = False
        watcher = None

        def _start_watcher() -> None:
            nonlocal watcher
            if progress_msg is not None:
                watcher = asyncio.create_task(
                    _watch_progress(
                        bot, chat_id, progress_msg.message_id,
                        tracker, done, is_photo,
                    )
                )

        try:
            # ۰) پیام پیشرفت از همان اول (فاز آماده‌سازی).
            try:
                progress_msg = await bot.send_message(
                    chat_id=chat_id, text=_progress_text(0, "info"),
                )
                _start_watcher()
            except Exception:
                progress_msg = None
                logger.exception("Could not send progress message")

            # ۱) اطلاعات + کاور از وب‌سرویس GFw.
            data, err = await asyncio.to_thread(
                _gfw_youtube_info_sync, url, GFWDEV_API_KEY
            )
            if data is None:
                return err
            title = str(data.get("title") or "")
            performer = str(data.get("channel") or "")
            duration_s: float | None = None
            try:
                duration_s = float(data.get("duration") or 0) or None
            except (TypeError, ValueError):
                duration_s = None
            downloads = data.get("downloads") or {}
            cover = None
            thumb_url = data.get("thumbnail")
            if thumb_url:
                cover = await asyncio.to_thread(
                    _download_cover_sync, thumb_url, tmpdir,
                    "https://www.youtube.com/",
                )

            # ۲) اگر کاور هست، پیام متنی را به عکس کاور تبدیل کن.
            if cover is not None and progress_msg is not None:
                try:
                    if watcher is not None:
                        watcher.cancel()
                    await progress_msg.delete()
                except Exception:
                    pass
                try:
                    with open(cover, "rb") as f:
                        progress_msg = await bot.send_photo(
                            chat_id=chat_id, photo=f,
                            caption=tracker.display_text(),
                        )
                    is_photo = True
                    _start_watcher()
                except Exception:
                    progress_msg = None
                    logger.exception("Could not send cover progress photo")

            files: list[Path] = []
            was_split = False
            audio_duration: int | None = None

            if audio:
                # صوتی: بهترین صدا → mp3.
                entry = _gfw_pick_audio(downloads.get("audio") or [])
                if entry is None or not entry.get("url"):
                    return "error"
                subdir = Path(tmpdir) / "audio"
                subdir.mkdir(parents=True, exist_ok=True)
                fmt = (entry.get("format") or "m4a").lower()
                raw = subdir / f"audio.{fmt}"
                ok = await _download_gfw_file(
                    url, entry, raw, tracker, "audio"
                )
                if not ok:
                    return "error"
                mp3 = subdir / "audio.mp3"
                rc = await asyncio.to_thread(
                    _convert_audio_to_mp3_sync, raw, mp3, duration_s,
                    tracker,
                )
                if rc != 0 or not mp3.is_file() or mp3.stat().st_size == 0:
                    logger.warning("Audio mp3 conversion failed for %s", url)
                    return "error"
                files = [mp3]
            else:
                # ویدیو: کیفیت انتخاب‌شده (mp4) + بهترین صدا، میکس‌شده.
                ventry = _gfw_pick_video(downloads.get("video") or [], height)
                if ventry is None or not ventry.get("url"):
                    return "error"
                subdir = Path(tmpdir) / f"h{height}"
                subdir.mkdir(parents=True, exist_ok=True)
                vfmt = (ventry.get("format") or "mp4").lower()
                vpath = subdir / f"video.{vfmt}"
                ok = await _download_gfw_file(
                    url, ventry, vpath, tracker, "video", height
                )
                if not ok:
                    return "error"
                if _gfw_needs_audio_mux(ventry):
                    aentry = _gfw_pick_audio(downloads.get("audio") or [])
                    if aentry is None or not aentry.get("url"):
                        return "error"
                    afmt = (aentry.get("format") or "m4a").lower()
                    apath = subdir / f"audio.{afmt}"
                    ok = await _download_gfw_file(
                        url, aentry, apath, tracker, "audio"
                    )
                    if not ok:
                        return "error"
                    # خروجی میکس حتماً باید اسمش با ورودی فرق کند؛
                    # ffmpeg روی همان فایل ورودی نمی‌نویسد و با
                    # "same as Input" رد می‌کند (قبلاً merged همان
                    # video.mp4 بود و میکس همیشه می‌مرد).
                    merged = subdir / "merged.mp4"
                    rc = await asyncio.to_thread(
                        _mux_video_audio_sync, vpath, apath, merged,
                        duration_s, tracker,
                    )
                    if rc != 0 or not merged.is_file() \
                            or merged.stat().st_size == 0:
                        logger.warning(
                            "Video/audio mux failed for %s", url
                        )
                        return "error"
                    files = [merged]
                else:
                    files = [vpath]

            # ۵) ارسال (ویدیو با کاور / آهنگ با عنوان و خواننده)
            if files and files[0].suffix.lower() == ".mp3":
                dur = await asyncio.to_thread(
                    _probe_duration_seconds, files[0]
                )
                if dur:
                    audio_duration = int(dur)
            sent = await _deliver(
                bot, chat_id, tmpdir, title, files, was_split,
                "title", thumb=cover, tracker=tracker,
                audio_title=title[:200] if (audio and title) else None,
                audio_performer=performer or None,
                audio_caption=f"🎵 {title}" if (audio and title) else None,
                audio_duration=audio_duration,
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


async def do_soundcloud_download(bot, chat_id: int, url: str) -> str:
    """دانلود ساندکلود: اول کاور آهنگ با اسم آهنگ و خواننده،
    بعد فایل صوتی mp3 با عنوان و خواننده درست.
    اگر لینک پلی‌لیست باشد، فقط اولین آهنگ گرفته می‌شود.
    برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'
    پیام پیشرفت هر ۵ ثانیه روی پیام کاور ویرایش می‌شود؛ آخرش
    کپشن کاور به اسم آهنگ و خواننده برمی‌گردد و پیام کاور
    پاک نمی‌شود (برخلاف پورن‌هاب/یوتیوب که عکس پیشرفت موقت است)."""
    with tempfile.TemporaryDirectory(prefix="sc-") as tmpdir:
        tracker = ProgressTracker()
        done = asyncio.Event()
        progress_msg = None
        is_photo = False
        watcher = None

        def _start_watcher() -> None:
            nonlocal watcher
            if progress_msg is not None:
                watcher = asyncio.create_task(
                    _watch_progress(
                        bot, chat_id, progress_msg.message_id,
                        tracker, done, is_photo,
                    )
                )

        try:
            # ۰) پیام پیشرفت از همان اول (فاز آماده‌سازی).
            try:
                progress_msg = await bot.send_message(
                    chat_id=chat_id, text=_progress_text(0, "info"),
                )
                _start_watcher()
            except Exception:
                progress_msg = None
                logger.exception("Could not send progress message")

            # ۱) اطلاعات (تک‌آهنگ؛ اگر پلی‌لیست بود، اولین آهنگ)
            info = await asyncio.to_thread(_fetch_info_sync, url)
            if isinstance(info, dict) and info.get("entries"):
                entries = [e for e in info["entries"] if isinstance(e, dict)]
                info = entries[0] if entries else None
            if not info:
                return "error"
            title, artist = parse_soundcloud_track(info)
            if not title:
                title = str(info.get("title") or "آهنگ")
            final_caption = f"🎵 {title}"
            if artist:
                final_caption += f"\n👤 {artist}"

            # ۲) کاور (بزرگ‌ترین کاور موجود)
            cover = await asyncio.to_thread(
                _download_cover_sync,
                _best_thumbnail_url(info), tmpdir,
                "https://soundcloud.com/",
            )

            # ۳) اگر کاور هست، پیام متنی را به عکس کاور تبدیل کن؛
            # اگر نیست، همان پیام متنی پیشرفت می‌ماند.
            if cover is not None and progress_msg is not None:
                try:
                    if watcher is not None:
                        watcher.cancel()
                    await progress_msg.delete()
                except Exception:
                    pass
                try:
                    with open(cover, "rb") as f:
                        progress_msg = await bot.send_photo(
                            chat_id=chat_id, photo=f,
                            caption=tracker.display_text(),
                        )
                    is_photo = True
                    _start_watcher()
                except Exception:
                    progress_msg = None
                    logger.exception("Could not send cover progress photo")

            # ۴) دانلود صدا → mp3
            subdir = Path(tmpdir) / "audio"
            subdir.mkdir(parents=True, exist_ok=True)
            try:
                dl_title, files = await asyncio.to_thread(
                    _download_audio_once, url, str(subdir), tracker
                )
                if dl_title and not title:
                    title = dl_title
            except Exception:
                logger.exception("yt-dlp audio failed for %s", url)
                return "error"
            if not files:
                return "error"

            # ۵) ارسال آهنگ (با همان کاور به‌عنوان thumbnail)
            audio_duration: int | None = None
            dur = await asyncio.to_thread(
                _probe_duration_seconds, files[0]
            )
            if dur:
                audio_duration = int(dur)
            sent = await _deliver(
                bot, chat_id, tmpdir, title, files, False,
                "title", thumb=cover, tracker=tracker,
                audio_title=title[:200],
                audio_performer=artist or None,
                audio_caption=final_caption,
                audio_duration=audio_duration,
            )
            if not sent:
                return "empty"

            # ۶) کپشن پیام کاور را به اسم آهنگ و خواننده برگردان؛
            # پیام کاور می‌ماند (پاک نمی‌شود).
            done.set()
            if watcher is not None:
                watcher.cancel()
            if progress_msg is not None:
                try:
                    if is_photo:
                        await bot.edit_message_caption(
                            chat_id=chat_id,
                            message_id=progress_msg.message_id,
                            caption=final_caption,
                        )
                    else:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=progress_msg.message_id,
                            text=final_caption,
                        )
                except Exception:
                    pass
                progress_msg = None
            return "ok"
        finally:
            done.set()
            if watcher is not None:
                watcher.cancel()
            if progress_msg is not None:
                try:
                    await progress_msg.delete()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# اسپاتیفای — دقیقاً مثل ساندکلود: اول کاور آهنگ با اسم آهنگ و
# خواننده، بعد فایل صوتی mp3 با عنوان و خواننده درست.
# ---------------------------------------------------------------------------
# صدای اسپاتیفای DRM دارد و دانلود مستقیم از خود اسپاتیفای ممکن
# نیست؛ پس مسیر اصلی حالا وب‌سرویس NestAPI است
# (open.nestapi.ir/apis-1/spotify-download): بدون کلید، متادیتا
# (اسم، خواننده، کاور، مدت) + لینک مستقیم mp3 را می‌دهد؛ اگر
# NestAPI نشد یا لینک دانلود نداد، fallback جستجوی یوتیوب
# (با کوکی لاگین‌شده، اگر باشد) + صدای GFw؛ در آخر yt-dlp
# مستقیم. پری‌ویو ۳۰ ثانیه‌ای اسپاتیفای استفاده نمی‌شود.
NESTAPI_SPOTIFY_URL = "https://open.nestapi.ir/apis-1/spotify-download"
SPOTIFY_REFERER = "https://open.spotify.com/"


def _extract_spotify_kind_and_id(url: str) -> tuple[str, str] | None:
    """(kind, id) لینک اسپاتیفای: kind یکی از
    track | album | playlist | episode است. None اگر لینک آهنگ/
    آلبوم/پلی‌لیست نباشد (مثلاً artist یا صفحه جستجو)."""
    try:
        parts = urlparse(url)
    except Exception:
        return None
    segs = [s for s in (parts.path or "").split("/") if s]
    # /intl-<xx>/track/<id> → سگمنت زبان را رد کن
    if len(segs) >= 3 and segs[0].startswith("intl-"):
        segs = segs[1:]
    if len(segs) < 2:
        return None
    kind, sid = segs[-2], segs[-1]
    if kind not in ("track", "album", "playlist", "episode"):
        return None
    sid = sid.strip()
    if not sid or len(sid) > 64:
        return None
    return kind, sid


def _nestapi_spotify_sync(url: str) -> tuple[dict | None, str]:
    """پاسخ NestAPI برای یک لینک اسپاتیفای (بدون کلید):
    GET open.nestapi.ir/apis-1/spotify-download?url=<link>
    برمی‌گرداند (data, کد خطا): data با tracks (هر کدام
    name/artists/cover/duration_ms/download)؛ کد خطا "" اگر
    موفق بود، وگرنه code از error پاسخ (مثلاً TRACK_NOT_FOUND)
    یا "" اگر معلوم نبود. برای آلبوم/پلی‌لیست همه آهنگ‌ها با
    لینک دانلودشان می‌آیند."""
    try:
        req = urllib.request.Request(
            f"{NESTAPI_SPOTIFY_URL}?url={quote(url, safe='')}",
            headers={"User-Agent": CHROME_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        code = ""
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
            code = str(((body or {}).get("error") or {}).get("code") or "")
        except Exception:
            pass
        logger.warning(
            "NestAPI Spotify HTTP %s (%s) for %s", e.code, code, url
        )
        return None, code
    except Exception:
        logger.warning("NestAPI Spotify fetch failed for %s", url)
        return None, ""
    if not isinstance(payload, dict) or not payload.get("success"):
        err = (payload or {}).get("error") or {}
        code = str(err.get("code") or "") if isinstance(err, dict) else ""
        logger.warning(
            "NestAPI Spotify error for %s: %s", url, code or err
        )
        return None, code
    data = payload.get("data")
    return (data if isinstance(data, dict) else None), ""


def _nestapi_first_track(
    data: dict,
) -> tuple[str, str, str | None, int | None, str | None] | None:
    """(title, artist, cover_url, duration_ms, download_url|None)
    از اولین آهنگ پاسخ NestAPI؛ download_url ممکن است None
    باشد (اگر آن آهنگ لینک دانلود نداشت) — در آن صورت
    do_spotify_download به fallback یوتیوب می‌رود. None فقط
    اگر هیچ آهنگی نبود. برای آلبوم/پلی‌لیست فعلاً فقط اولین
    آهنگ گرفته می‌شود (مثل رفتار قبلی ربات)."""
    for t in data.get("tracks") or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        artists = [
            str(a).strip() for a in (t.get("artists") or [])
            if str(a).strip()
        ]
        cover = str(
            t.get("cover") or data.get("cover") or ""
        ).strip() or None
        dur = t.get("duration_ms")
        duration_ms = int(dur) if isinstance(dur, int) else None
        dl = str(t.get("download") or "").strip() or None
        return name, ", ".join(artists), cover, duration_ms, dl
    return None


def _resolve_spotify_url_sync(url: str) -> str | None:
    """لینک کوتاه spotify.link را باز می‌کند و URL نهایی را
    برمی‌گرداند؛ برای لینک معمولی همان URL. None اگر باز نشد."""
    if "spotify.link" not in url.lower():
        return url
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": CHROME_USER_AGENT,
                "Referer": SPOTIFY_REFERER,
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            try:
                resp.read(1)
            except Exception:
                pass
            return resp.geturl()
    except Exception:
        logger.warning("spotify.link resolve failed for %s", url)
        return None










def _search_youtube_url_sync(query: str) -> str | None:
    """اولین نتیجه جستجوی یوتیوب برای «خواننده - آهنگ» با yt-dlp.
    None اگر جستجو نشد (IP ریل‌وی یوتیوب را بلاک می‌کند). اگر
    کوکی لاگین‌شده یوتیوب باشد، به yt-dlp داده می‌شود — جستجو
    با حساب لاگین‌شده معمولاً از بلاک IP رد می‌شود."""
    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "extract_flat": True,
            "socket_timeout": 30,
            "http_headers": {
                "User-Agent": CHROME_USER_AGENT,
                "Referer": "https://www.youtube.com/",
            },
        }
        cookiefile = get_youtube_cookiefile()
        if cookiefile:
            ydl_opts["cookiefile"] = cookiefile
            logger.info("Using YouTube cookiefile for search: %s", cookiefile)
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    except Exception:
        logger.warning("YouTube search failed for %s", query)
        return None
    if not isinstance(info, dict):
        return None
    entries = [
        e for e in info.get("entries") or [] if isinstance(e, dict)
    ]
    if not entries:
        return None
    vid = entries[0].get("id")
    if not vid:
        return None
    return f"https://www.youtube.com/watch?v={vid}"


def _spotify_audio_to_mp3_sync(
    raw: Path, out: Path, tracker=None,
    duration_ms: int | None = None,
) -> Path | None:
    """فایل صوتی دانلودشده (mp3/ogg/m4a/...) را به mp3 تبدیل
    می‌کند؛ اگر خودش mp3 بود، همان را برمی‌گرداند. None اگر نشد."""
    try:
        if not raw.is_file() or raw.stat().st_size == 0:
            return None
        with open(raw, "rb") as f:
            head = f.read(3)
        if head[:3] == b"ID3" or (
            len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0
        ):
            if raw.suffix.lower() != ".mp3":
                mp3 = raw.with_suffix(".mp3")
                raw.rename(mp3)
                return mp3
            return raw
        duration_s = duration_ms / 1000 if duration_ms else None
        rc = _convert_audio_to_mp3_sync(raw, out, duration_s, tracker)
        if rc == 0 and out.is_file() and out.stat().st_size > 0:
            return out
        return None
    except Exception:
        logger.exception("Spotify audio to mp3 failed")
        return None


async def _download_spotify_audio_via_youtube_gfw(
    yt_url: str, subdir: Path, tracker
) -> Path | None:
    """صدای یک ویدیوی یوتیوب با وب‌سرویس GFw (کیفیت صوتی)؛
    فایل صوتی خام (m4a/webm) را برمی‌گرداند یا None."""
    data, err = await asyncio.to_thread(
        _gfw_youtube_info_sync, yt_url, GFWDEV_API_KEY
    )
    if data is None:
        logger.warning(
            "GFw YouTube info failed for Spotify fallback: %s", err
        )
        return None
    audio_entry = _gfw_pick_audio(
        (data.get("downloads") or {}).get("audio") or []
    )
    if audio_entry is None:
        return None
    fmt = (audio_entry.get("format") or "m4a").lower()
    dest = subdir / f"audio.{fmt}"
    ok = await _download_gfw_file(
        yt_url, audio_entry, dest, tracker, "audio"
    )
    if not ok or not dest.is_file() or dest.stat().st_size == 0:
        return None
    return dest


async def do_spotify_download(bot, chat_id: int, url: str) -> str:
    """دانلود اسپاتیفای — دقیقاً مثل ساندکلود: اول کاور آهنگ با
    اسم آهنگ و خواننده، بعد فایل صوتی mp3 با عنوان و خواننده درست.
    اگر لینک آلبوم/پلی‌لیست باشد، فقط اولین آهنگ گرفته می‌شود.
    مسیر اصلی NestAPI است (متادیتا + لینک مستقیم mp3، بدون
    کلید)؛ اگر NestAPI نشد یا لینک دانلود نداد، fallback
    جستجوی یوتیوب (با کوکی لاگین‌شده، اگر باشد) + صدای GFw.
    برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'
    (خطای کلید یوتیوب اینجا برنمی‌گردد؛ فقط وقتی همه مسیرها
    نشد «error» برمی‌گردد.)
    پیام پیشرفت هر ۵ ثانیه روی پیام کاور ویرایش می‌شود؛ آخرش
    کپشن کاور به اسم آهنگ و خواننده برمی‌گردد و پیام کاور
    پاک نمی‌شود (مثل ساندکلود)."""
    with tempfile.TemporaryDirectory(prefix="sp-") as tmpdir:
        tracker = ProgressTracker()
        done = asyncio.Event()
        progress_msg = None
        is_photo = False
        watcher = None

        def _start_watcher() -> None:
            nonlocal watcher
            if progress_msg is not None:
                watcher = asyncio.create_task(
                    _watch_progress(
                        bot, chat_id, progress_msg.message_id,
                        tracker, done, is_photo,
                    )
                )

        try:
            # ۰) پیام پیشرفت از همان اول (فاز آماده‌سازی).
            try:
                progress_msg = await bot.send_message(
                    chat_id=chat_id, text=_progress_text(0, "info"),
                )
                _start_watcher()
            except Exception:
                progress_msg = None
                logger.exception("Could not send progress message")

            # ۱) لینک → آهنگ (آلبوم/پلی‌لیست → اولین آهنگ)
            resolved = await asyncio.to_thread(
                _resolve_spotify_url_sync, url
            )
            if not resolved:
                return "empty"
            kind_id = _extract_spotify_kind_and_id(resolved)
            if kind_id is None:
                return "empty"
            # ۱) لینک → آهنگ با NestAPI (متادیتا + لینک mp3،
            # بدون کلید)؛ آلبوم/پلی‌لیست → اولین آهنگ.
            # خطای پیدا-نشدن → "empty" (مثلاً آهنگ حذف شده)،
            # هر خطای دیگر NestAPI → "error".
            nestapi_data, nestapi_err = await asyncio.to_thread(
                _nestapi_spotify_sync, resolved
            )
            if nestapi_data is None:
                if nestapi_err in ("TRACK_NOT_FOUND", "NOT_FOUND"):
                    return "empty"
                return "error"
            nestapi_track = _nestapi_first_track(nestapi_data)
            if nestapi_track is None:
                return "empty"
            title, artist, cover_url, duration_ms, nestapi_dl = (
                nestapi_track
            )
            if not title:
                return "error"
            final_caption = f"🎵 {title}"
            if artist:
                final_caption += f"\n👤 {artist}"

            # ۲) کاور (بزرگ‌ترین کاور موجود)
            cover = await asyncio.to_thread(
                _download_cover_sync,
                cover_url, tmpdir, SPOTIFY_REFERER,
            )

            # ۳) اگر کاور هست، پیام متنی را به عکس کاور تبدیل کن؛
            # اگر نیست، همان پیام متنی پیشرفت می‌ماند.
            if cover is not None and progress_msg is not None:
                try:
                    if watcher is not None:
                        watcher.cancel()
                    await progress_msg.delete()
                except Exception:
                    pass
                try:
                    with open(cover, "rb") as f:
                        progress_msg = await bot.send_photo(
                            chat_id=chat_id, photo=f,
                            caption=tracker.display_text(),
                        )
                    is_photo = True
                    _start_watcher()
                except Exception:
                    progress_msg = None
                    logger.exception("Could not send cover progress photo")

            # ۴) دانلود صدا → mp3
            subdir = Path(tmpdir) / "audio"
            subdir.mkdir(parents=True, exist_ok=True)
            audio_mp3: Path | None = None
            query = f"{artist} - {title}" if artist else title

            # ۴) NestAPI: لینک مستقیم mp3 (مسیر اصلی). فایل
            # معمولاً خودش mp3 است (_spotify_audio_to_mp3_sync
            # آن را همان‌طور برمی‌گرداند)؛ اگر mp3 نبود تبدیل
            # می‌شود. اگر دانلودش نشد، به ۴ب می‌رویم.
            if nestapi_dl:
                raw = subdir / "audio.bin"
                ok = await asyncio.to_thread(
                    _download_url_sync, nestapi_dl, raw, tracker
                )
                if ok and raw.is_file() and raw.stat().st_size > 0:
                    audio_mp3 = await asyncio.to_thread(
                        _spotify_audio_to_mp3_sync,
                        raw, subdir / "audio.mp3",
                        tracker, duration_ms,
                    )
                if audio_mp3 is None:
                    logger.warning(
                        "NestAPI download failed for %s; falling "
                        "back to YouTube search", url
                    )

            # ۴ب) یوتیوب با GFw (اگر NestAPI نشد)
            if audio_mp3 is None:
                yt_url = await asyncio.to_thread(
                    _search_youtube_url_sync, query
                )
                if yt_url:
                    if GFWDEV_API_KEY:
                        raw = await _download_spotify_audio_via_youtube_gfw(
                            yt_url, subdir, tracker
                        )
                        if raw is not None:
                            audio_mp3 = await asyncio.to_thread(
                                _spotify_audio_to_mp3_sync,
                                raw, subdir / "audio.mp3",
                                tracker, duration_ms,
                            )
                    else:
                        # بدون کلید GFw: yt-dlp مستقیم (روی ریل‌وی
                        # احتمالاً بلاک است؛ آخرین راه)
                        try:
                            _dl_title, files = await asyncio.to_thread(
                                _download_audio_once,
                                yt_url, str(subdir), tracker,
                            )
                            mp3s = [
                                p for p in files
                                if p.suffix.lower() == ".mp3"
                            ]
                            if mp3s:
                                audio_mp3 = mp3s[0]
                        except Exception:
                            logger.exception(
                                "yt-dlp audio failed for Spotify %s", url
                            )
            if audio_mp3 is None:
                return "error"

            # ۵) ارسال آهنگ (با همان کاور به‌عنوان thumbnail)
            audio_duration: int | None = None
            if duration_ms:
                audio_duration = int(duration_ms / 1000)
            if not audio_duration:
                dur = await asyncio.to_thread(
                    _probe_duration_seconds, audio_mp3
                )
                if dur:
                    audio_duration = int(dur)
            sent = await _deliver(
                bot, chat_id, tmpdir, title, [audio_mp3], False,
                "title", thumb=cover, tracker=tracker,
                audio_title=title[:200],
                audio_performer=artist or None,
                audio_caption=final_caption,
                audio_duration=audio_duration,
            )
            if not sent:
                return "empty"

            # ۶) کپشن پیام کاور را به اسم آهنگ و خواننده برگردان؛
            # پیام کاور می‌ماند (پاک نمی‌شود).
            done.set()
            if watcher is not None:
                watcher.cancel()
            if progress_msg is not None:
                try:
                    if is_photo:
                        await bot.edit_message_caption(
                            chat_id=chat_id,
                            message_id=progress_msg.message_id,
                            caption=final_caption,
                        )
                    else:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=progress_msg.message_id,
                            text=final_caption,
                        )
                except Exception:
                    pass
                progress_msg = None
            return "ok"
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
                               platform: str, height: int | None = None,
                               audio: bool = False) -> None:
    """دانلود را در پس‌زمینه اجرا می‌کند تا هندلر فوراً برگردد و
    ربات به دستورهای دیگر جواب بدهد. پیام خطا را خودش می‌فرستد.
    تا ۳ دانلود هم‌زمان؛ اگر هر ۳ اسلات پر بود، به کاربر می‌گوید
    توی صف مانده و بعد که نوبت شد دانلود شروع می‌شود. هر دانلود
    پوشه، پیام و ترکر خودش را دارد."""
    acquired = False
    try:
        await asyncio.wait_for(DOWNLOAD_SEMAPHORE.acquire(), timeout=1.0)
        acquired = True
    except asyncio.TimeoutError:
        try:
            await bot.send_message(chat_id=chat_id, text="تو صف موندی… ⏳")
        except Exception:
            pass
        await DOWNLOAD_SEMAPHORE.acquire()
        acquired = True
    try:
        if platform == "pornhub":
            result = await do_pornhub_download(bot, chat_id, url, height or 720)
        elif platform == "youtube":
            result = await do_youtube_download(
                bot, chat_id, url, height or 720, audio=audio
            )
        elif platform == "tiktok":
            result = await do_tiktok_download(bot, chat_id, url)
        elif platform == "pinterest":
            result = await do_pinterest_download(bot, chat_id, url)
        elif platform == "soundcloud":
            result = await do_soundcloud_download(bot, chat_id, url)
        elif platform == "spotify":
            result = await do_spotify_download(bot, chat_id, url)
        else:
            result = await do_instagram_download(bot, chat_id, url)
    except Exception:
        logger.exception("download task failed for %s", url)
        result = "error"
    finally:
        if acquired:
            DOWNLOAD_SEMAPHORE.release()
    try:
        if result == "too_big":
            await bot.send_message(chat_id=chat_id, text=TOO_BIG_TEXT)
        elif result == "age":
            await bot.send_message(chat_id=chat_id, text=AGE_RESTRICTED_TEXT)
        elif result == "no_key":
            await bot.send_message(chat_id=chat_id, text=GFW_KEY_MISSING_TEXT)
        elif result == "bad_key":
            await bot.send_message(chat_id=chat_id, text=GFW_KEY_BAD_TEXT)
        elif result == "unavailable":
            await bot.send_message(
                chat_id=chat_id, text=YOUTUBE_UNAVAILABLE_TEXT
            )
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
# منوی انتخاب کیفیت یوتیوب (مثل پورن‌هاب، با گزینه صوتی)
# ---------------------------------------------------------------------------

# دانلودهای یوتیوب در انتظار انتخاب کیفیت: key کوتاه → {url, chat_id}
# پیشوند callback جدا است (`yt:` در برابر `ph:`) تا هیچ‌وقت با
# منوی پورن‌هاب قاطی نشود.
PENDING_YOUTUBE: dict[str, dict] = {}


async def _offer_youtube_quality(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE,
                                 url: str) -> None:
    """منوی شیشه‌ای انتخاب کیفیت یوتیوب: دو ستونه، با ایموجی و
    برچسب تمیز + گزینه صوتی (mp3)."""
    key = uuid.uuid4().hex[:8]
    PENDING_YOUTUBE[key] = {
        "url": url,
        "chat_id": update.message.chat.id,
    }
    keyboard = [
        [
            InlineKeyboardButton("✨ 1080p", callback_data=f"yt:{key}:1080"),
            InlineKeyboardButton("🎞️ 720p", callback_data=f"yt:{key}:720"),
        ],
        [
            InlineKeyboardButton("📺 480p", callback_data=f"yt:{key}:480"),
            InlineKeyboardButton("📱 360p", callback_data=f"yt:{key}:360"),
        ],
        [InlineKeyboardButton("🎵 صوتی (mp3)", callback_data=f"yt:{key}:audio")],
        [InlineKeyboardButton("❌ لغو", callback_data=f"yt:{key}:cancel")],
    ]
    await update.message.reply_text(
        "🎬 کیفیت ویدیو رو انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def youtube_quality_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """کلیک روی منوی کیفیت یوتیوب: دانلود با همان کیفیت (یا صوتی)،
    در پس‌زمینه."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    parts = (query.data or "").split(":")
    if len(parts) != 3 or parts[0] != "yt":
        return
    _, key, choice = parts
    pending = PENDING_YOUTUBE.pop(key, None)
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
        await query.delete_message()
    except Exception:
        try:
            await query.edit_message_text("⏳")
        except Exception:
            pass
    if choice == "audio":
        asyncio.create_task(
            _background_download(
                context.bot, pending["chat_id"], pending["url"],
                "youtube", None, audio=True,
            )
        )
        return
    try:
        height = int(choice)
    except ValueError:
        return
    asyncio.create_task(
        _background_download(
            context.bot, pending["chat_id"], pending["url"],
            "youtube", height,
        )
    )


# ---------------------------------------------------------------------------
# هندلرها
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text())


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هر پیام متنی: لینک اینستا/تیک‌تاک/یوتیوب/پورن‌هاب/ساندکلود/
    اسپاتیفای/پینترست را پردازش کن؛ اگر نه، رد شو.
    دانلود در پس‌زمینه اجرا می‌شود تا ربات به بقیه دستورها جواب بدهد."""
    msg = update.message
    if msg is None or not msg.text:
        return

    url = find_url(msg.text)
    if not url:
        if msg.chat.type == "private":
            await msg.reply_text("لینک بفرست.")
        return

    platform = detect_platform(url)
    if not platform:
        if msg.chat.type == "private":
            await msg.reply_text(
                "فقط اینستاگرام، تیک‌تاک، یوتیوب، پورن‌هاب، ساندکلود، اسپاتیفای و پینترست."
            )
        return

    if platform == "pornhub":
        # پورن‌هاب: اول منوی انتخاب کیفیت، دانلود بعد از انتخاب کاربر.
        await _offer_pornhub_quality(update, context, url)
        return

    if platform == "youtube":
        # یوتیوب: مثل پورن‌هاب — اول منوی انتخاب کیفیت (با گزینه صوتی).
        await _offer_youtube_quality(update, context, url)
        return

    # اینستاگرام، تیک‌تاک، ساندکلود، اسپاتیفای و پینترست: دانلود مستقیم، در پس‌زمینه.
    asyncio.create_task(
        _background_download(context.bot, msg.chat.id, url, platform)
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
    app.add_handler(CallbackQueryHandler(pornhub_quality_callback, pattern=r"^ph:"))
    app.add_handler(CallbackQueryHandler(youtube_quality_callback, pattern=r"^yt:"))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(error_handler)

    logger.info("Downloader bot started (polling).")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
