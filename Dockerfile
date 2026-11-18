FROM python:3.11-slim

# ffmpeg برای تبدیل صدا به mp3 لازم است؛ yt-dlp هم ازش استفاده می‌کند.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py /app/

CMD ["python", "/app/bot.py"]
