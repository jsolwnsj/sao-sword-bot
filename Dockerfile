FROM php:8.2-cli

# curl برای ارتباط با تلگرام لازم است؛ صریح نصب می‌شود.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libcurl4-openssl-dev \
    && docker-php-ext-install curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . /app

RUN chmod +x /app/start.sh

CMD ["sh", "/app/start.sh"]
