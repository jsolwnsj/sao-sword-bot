<?php
// ============================================================
// webhook.php — نقطه ورود ربات شمشیر SAO روی Railway
// ============================================================
// این فایل وب‌هوک تلگرام است: تلگرام آپدیت‌ها را با POST به
// همین آدرس می‌فرستد و این فایل آن‌ها را به game_5.php می‌دهد.
//
// توکن و سکرت هیچ‌وقت اینجا نوشته نمی‌شوند؛ هر دو از متغیرهای
// محیطی Railway خوانده می‌شوند (BOT_TOKEN و WEBHOOK_SECRET).
// ============================================================

error_reporting(E_ALL);
ini_set('display_errors', '0');
ini_set('log_errors', '1');

set_time_limit(120);
ignore_user_abort(true);

// ------------------------------------------------------------
// سلامت‌سنجی (Health Check) — Railway با GET چک می‌کند
// ------------------------------------------------------------

if (($_SERVER['REQUEST_METHOD'] ?? '') === 'GET') {
    header('Content-Type: text/plain; charset=utf-8');
    echo 'ok';
    exit;
}

// ------------------------------------------------------------
// خواندن توکن و سکرت از محیط (هرگز اینجا هاردکد نکن)
// ------------------------------------------------------------

$bot_token = (string)(getenv('BOT_TOKEN') ?: '');
$webhook_secret = (string)(getenv('WEBHOOK_SECRET') ?: '');

if ($bot_token === '') {
    error_log('webhook.php: BOT_TOKEN is not set in environment variables.');
    http_response_code(500);
    echo 'ok';
    exit;
}

if (!defined('API_URL')) {
    define(
        'API_URL',
        'https://api.telegram.org/bot' . $bot_token . '/'
    );
}

// ------------------------------------------------------------
// بررسی هدر سکرت تلگرام (جلوی درخواست‌های جعلی را می‌گیرد)
// ------------------------------------------------------------

if ($webhook_secret === '') {
    error_log('webhook.php: WARNING — WEBHOOK_SECRET is empty, secret check skipped.');
} else {
    $incoming_secret = (string)(
        $_SERVER['HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN'] ?? ''
    );

    if (!hash_equals($webhook_secret, $incoming_secret)) {
        error_log('webhook.php: secret token mismatch, request rejected.');
        http_response_code(403);
        echo 'forbidden';
        exit;
    }
}

// ------------------------------------------------------------
// درخواست POST تلگرام را بخوان
// ------------------------------------------------------------

$raw_input = file_get_contents('php://input');

if ($raw_input === false || $raw_input === '') {
    http_response_code(400);
    echo 'ok';
    exit;
}

$update = json_decode($raw_input, true);

if (!is_array($update)) {
    error_log('webhook.php: invalid JSON payload received.');
    echo 'ok';
    exit;
}

// ------------------------------------------------------------
// توابع پایه‌ای که game_5.php و ماژول‌ها لازم دارند
// ------------------------------------------------------------

function makeCurl($url, $data = [])
{
    $ch = curl_init();

    curl_setopt($ch, CURLOPT_URL, $url);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 10);
    curl_setopt($ch, CURLOPT_TIMEOUT, 30);

    if (!empty($data)) {
        // فرم معمولی (application/x-www-form-urlencoded):
        // ماژول‌ها reply_markup را از قبل json_encode کرده‌اند،
        // پس همین شکل برای تلگرام درست است.
        curl_setopt(
            $ch,
            CURLOPT_POSTFIELDS,
            http_build_query($data)
        );
    }

    $response = curl_exec($ch);

    if ($response === false) {
        error_log(
            'makeCurl error: ' . curl_error($ch)
        );
        curl_close($ch);
        return false;
    }

    curl_close($ch);

    $decoded = json_decode($response, true);

    return is_array($decoded) ? $decoded : $response;
}

function answerCallbackQuery($callback_id, $text, $alert = false)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    return makeCurl(
        API_URL . 'answerCallbackQuery',
        [
            'callback_query_id' => (string)$callback_id,
            'text' => (string)$text,
            'show_alert' => $alert ? true : false,
        ]
    );
}

function editMessageText($chat_id, $message_id, $text, $reply_markup = null)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    $post_data = [
        'chat_id' => (int)$chat_id,
        'message_id' => (int)$message_id,
        'text' => (string)$text,
    ];

    if ($reply_markup !== null) {
        $post_data['reply_markup'] = is_string($reply_markup)
            ? $reply_markup
            : json_encode(
                $reply_markup,
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            );
    }

    return makeCurl(API_URL . 'editMessageText', $post_data);
}

// ------------------------------------------------------------
// محل ذخیره دیتا: روی Volume ریلی که به /data وصل شده
// تا با هر ری‌استارت، اطلاعات گروه‌ها از بین نرود.
// این ثابت‌ها باید قبل از require شدن game_5.php تعریف شوند.
// ------------------------------------------------------------

if (!defined('GAME_STATE_FILE')) {
    define('GAME_STATE_FILE', '/data/game_groups.json');
}

if (!defined('GAME_GROUP_DATA_DIR')) {
    define('GAME_GROUP_DATA_DIR', '/data/game_group_databases');
}

if (!is_dir(GAME_GROUP_DATA_DIR)) {
    @mkdir(GAME_GROUP_DATA_DIR, 0750, true);
}

// ------------------------------------------------------------
// پردازش آپدیت با ماژول اصلی بازی
// ------------------------------------------------------------

require_once __DIR__ . '/game_5.php';

try {
    handleGameUpdate($update);
} catch (Throwable $e) {
    error_log('webhook.php: handleGameUpdate error: ' . $e->getMessage());
}

header('Content-Type: text/plain; charset=utf-8');
echo 'ok';
