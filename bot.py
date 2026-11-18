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
• تلگرام سقف سخت ۵۰ مگابایت برای ارسال فایل با ربات داره و با «مستقیم فرستادن» دور زده نمی‌شه. من اول کیفیت رو پایین می‌آرم (۷۲۰p، بعد ۴۸۰p، بعد ۳۶۰p) و اگه باز هم ویدیو بزرگ بود، تیکه‌تیکه‌ش می‌کنم و قسمت‌ها رو به ترتیب می‌فرستم. پس ویدیوهای خیلی طولانی ممکنه چند قسمت بشن.
• توی گروه هم کار می‌کنم، فقط باید Privacy Mode ربات خاموش باشه (تو BotFather با /setprivacy).

دستورها:
/start — همین راهنما
/help — همین راهنما
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


async def download_best_effort(url: str, tmpdir: str):
    """
    دانلود با پایین آوردن کیفیت (۷۲۰p، بعد ۴۸۰p، بعد ۳۶۰p) و در صورت نیاز
    تقسیم به قسمت‌ها.
    برمی‌گرداند: (title, files, was_split)
    """
    best_candidate: tuple[str, list[Path]] | None = None

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
    """
    status = await bot.send_message(
        chat_id=chat_id, text="⏳ دارم دانلود می‌کنم، یه کم صبر کن..."
    )
    try:
        with tempfile.TemporaryDirectory(prefix="dl-") as tmpdir:
            try:
                title, files, was_split = await download_best_effort(url, tmpdir)
            except Exception:
                logger.exception("download failed for %s", url)
                return "error"

            if not files:
                return "empty"

            # اگر حتی یک فایل هم زیر سقف نبود (و تقسیم هم نشد)، too_big
            if all(p.stat().st_size > MAX_BYTES for p in files):
                return "too_big"

            sent = await send_files(bot, chat_id, title, files, was_split)
            return "ok" if sent else "empty"
    finally:
        try:
            await status.delete()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# هندلرها
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """هر پیام متنی: اگر لینک اینستا/پورن‌هاب داشت، پردازش کن؛ اگر نه، رد شو."""
    msg = update.message
    if msg is None or not msg.text:
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
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(error_handler)

    logger.info("Downloader bot started (polling).")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
