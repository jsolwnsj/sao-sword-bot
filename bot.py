#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
دانلودر تلگرام — اینستاگرام + یوتیوب (اسلایس ۱)
- هم توی پی‌وی کار می‌کند، هم توی گروه (به شرطی که Privacy Mode ربات خاموش باشد).
- لینک اینستاگرام (ریلز/پست عمومی) یا یوتیوب (ویدیو/شورت/موزیک) را می‌گیرد،
  با yt-dlp دانلود می‌کند و همان‌جا توی همان چت برمی‌گرداند.
- فقط محتوای عمومی، بدون لاگین و بدون کوکی.
- محدودیت تلگرام: فایل بیشتر از ۵۰ مگابایت را نمی‌شود با ربات فرستاد.
- توکن از متغیر محیطی BOT_TOKEN خوانده می‌شود؛ هیچ‌وقت اینجا هاردکد نکن.
- روش اجرا: polling — نیازی به دامین و وب‌هوک نیست.
"""

import asyncio
import logging
import os
import re
import sys
import tempfile
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

# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("downloader-bot")

# سقف تلگرام برای ارسال فایل با ربات: ۵۰ مگابایت.
# با کمی حاشیه امن، ۴۸ مگابایت می‌گیریم.
MAX_BYTES = 48 * 1024 * 1024

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

START_TEXT = """سلام! 👋
من دانلودر اینستا و یوتیوبم.

کافیه لینک رو بفرستی:
• لینک ریلز یا پست اینستاگرام
• لینک ویدیو، شورت یا موزیک یوتیوب

من دانلودش می‌کنم و همین‌جا برات می‌فرستم.

برای یوتیوب، بعد از فرستادن لینک می‌تونی انتخاب کنی ویدیو می‌خوای یا فقط صدا (mp3).

نکته‌ها:
• فقط محتوای عمومی دانلود می‌شه؛ پیج خصوصی و استوری با لاگین، توی این نسخه نیست.
• فایل بیشتر از ۵۰ مگابایت رو تلگرام نمی‌ذاره بفرستم؛ اگه حجمش زیاد بود، می‌گم.
• توی گروه هم کار می‌کنم، فقط باید Privacy Mode ربات خاموش باشه (تو BotFather با /setprivacy).

دستورها:
/start — همین راهنما
/help — همین راهنما
"""

TOO_BIG_TEXT = (
    "حجم این فایل بیشتر از ۵۰ مگابایته و تلگرام نمی‌ذاره بفرستمش. 😕\n"
    "یه لینک دیگه یا کیفیت پایین‌تر رو امتحان کن."
)

ERROR_TEXT = (
    "نتونستم دانلودش کنم. 😕\n"
    "لینک رو چک کن که عمومی باشه و دوباره بفرست."
    "\nاگه باز هم نشد، شاید اینستا یا یوتیوب موقتاً جلوش رو گرفته."
)

# لینک‌های در انتظار انتخاب (یوتیوب: ویدیو یا صدا)
# key کوتاه -> {"url": ..., "chat_id": ..., "user_id": ...}
pending: dict[str, dict] = {}


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
    if "youtube.com" in low or "youtu.be" in low:
        return "youtube"
    return None


# ---------------------------------------------------------------------------
# دانلود با yt-dlp (بلوک‌کننده است؛ توی thread اجرا می‌شود)
# ---------------------------------------------------------------------------

def _download_sync(url: str, mode: str, tmpdir: str) -> tuple[str, list[Path]]:
    """mode: 'video' یا 'audio'. برمی‌گرداند: (عنوان، فهرست فایل‌ها)."""
    if mode == "audio":
        ydl_opts = {
            "format": "bestaudio[filesize<=48M]/bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }
    else:
        ydl_opts = {
            # بهترین کیفیت تا ۷۲۰p و زیر ۴۸ مگ؛ اگه نشد، بهترینِ زیر ۴۸ مگ.
            "format": "best[height<=720][filesize<=48M]/best[filesize<=48M]/best",
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
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
        for p in Path(tmpdir).iterdir()
        if p.is_file() and p.suffix.lower() not in skip_exts
    ]
    files.sort(key=lambda p: p.stat().st_size)
    return title, files


async def download_media(url: str, mode: str, tmpdir: str):
    return await asyncio.to_thread(_download_sync, url, mode, tmpdir)


# ---------------------------------------------------------------------------
# ارسال فایل به چت
# ---------------------------------------------------------------------------

async def send_files(bot, chat_id: int, title: str, files: list[Path]) -> bool:
    """فایل‌ها را می‌فرستد. اگر هیچ فایلی قابل ارسال نباشد False برمی‌گرداند."""
    if not files:
        return False

    sent_any = False
    for i, path in enumerate(files):
        # سقف ۵۰ مگ تلگرام
        if path.stat().st_size > MAX_BYTES:
            continue

        caption = title[:200] if (i == 0 and title) else None
        ext = path.suffix.lower()

        try:
            with open(path, "rb") as f:
                if ext == ".mp3":
                    await bot.send_audio(
                        chat_id=chat_id, audio=f,
                        title=title[:100] if title else None,
                    )
                elif ext in (".mp4", ".mov", ".mkv", ".webm"):
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


async def do_download_and_send(bot, chat_id: int, url: str, mode: str) -> str:
    """
    دانلود و ارسال. برمی‌گرداند: 'ok' | 'too_big' | 'empty' | 'error'
    """
    status = await bot.send_message(
        chat_id=chat_id, text="⏳ دارم دانلود می‌کنم، یه کم صبر کن..."
    )
    try:
        with tempfile.TemporaryDirectory(prefix="dl-") as tmpdir:
            try:
                title, files = await download_media(url, mode, tmpdir)
            except Exception:
                logger.exception("yt-dlp failed for %s", url)
                return "error"

            if not files:
                return "empty"

            # اگر حتی یک فایل هم زیر سقف نبود، too_big
            if all(p.stat().st_size > MAX_BYTES for p in files):
                return "too_big"

            sent = await send_files(bot, chat_id, title, files)
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
    """هر پیام متنی: اگر لینک اینستا/یوتیوب داشت، پردازش کن؛ اگر نه، رد شو."""
    msg = update.message
    if msg is None or not msg.text:
        return

    url = find_url(msg.text)
    if not url:
        # توی پی‌وی یک راهنمای کوتاه بده؛ توی گروه ساکت باش تا اسپم نشه.
        if msg.chat.type == "private":
            await msg.reply_text(
                "لینک اینستاگرام یا یوتیوب رو بفرست تا دانلودش کنم. 🙂\n"
                "برای راهنما /start رو بزن."
            )
        return

    platform = detect_platform(url)
    if not platform:
        if msg.chat.type == "private":
            await msg.reply_text(
                "این لینک رو نمی‌شناسم. فقط لینک اینستاگرام و یوتیوب رو می‌تونم دانلود کنم."
            )
        return

    chat_id = msg.chat.id

    if platform == "youtube":
        # انتخاب ویدیو یا صدا با دکمه
        key = uuid.uuid4().hex[:8]
        pending[key] = {"url": url, "chat_id": chat_id}
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🎬 ویدیو", callback_data=f"v:{key}"),
                    InlineKeyboardButton("🎵 فقط صدا (mp3)", callback_data=f"a:{key}"),
                ]
            ]
        )
        await msg.reply_text(
            "لینک یوتیوب رو گرفتم. چی می‌خوای؟",
            reply_markup=keyboard,
        )
        return

    # اینستاگرام: مستقیم دانلود کن
    result = await do_download_and_send(context.bot, chat_id, url, "video")
    if result == "too_big":
        await msg.reply_text(TOO_BIG_TEXT)
    elif result in ("empty", "error"):
        await msg.reply_text(ERROR_TEXT)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دکمه‌های ویدیو / صدا برای یوتیوب."""
    query = update.callback_query
    if query is None:
        return

    await query.answer()

    data = query.data or ""
    kind, _, key = data.partition(":")
    item = pending.pop(key, None)
    if not item:
        await query.edit_message_text(
            "این دکمه دیگه معتبر نیست. لینک رو دوباره بفرست."
        )
        return

    mode = "audio" if kind == "a" else "video"
    chat_id = item["chat_id"]
    url = item["url"]

    try:
        await query.edit_message_text("⏳ دارم دانلود می‌کنم، یه کم صبر کن...")
    except Exception:
        pass

    result = await do_download_and_send(context.bot, chat_id, url, mode)
    if result == "too_big":
        await context.bot.send_message(chat_id=chat_id, text=TOO_BIG_TEXT)
    elif result in ("empty", "error"):
        await context.bot.send_message(chat_id=chat_id, text=ERROR_TEXT)


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
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(error_handler)

    logger.info("Downloader bot started (polling).")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
