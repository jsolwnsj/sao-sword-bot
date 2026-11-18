<?php

// ============================================================
// بازی سنگ کاغذ قیچی — دو نفره، بهترین از ۳ راند
// هر کس زودتر ۲ راند ببرد، برنده بازی است.
// برنده بازی ۱۰ امتیاز می‌گیرد (rps_leaderboard).
//
// نسخه: 2.4 — 2026-11-11
// اصلاح: صفحه بازی دقیقاً مثل بمب با makeCurl ویرایش می‌شود
// (نه با editMessageText) و اگر ویرایش نشد، به‌صورت پیام جدید فرستاده می‌شود.
// اصلاح 2.2: استایل نامعتبر secondary حذف شد؛ تلگرام فقط
// primary و success و danger را قبول می‌کند.
// اصلاح 2.3: بردهای کل (همه بازی‌ها) از rps_leaderboard خوانده
// و جلوی اسم هر بازیکن نشان داده می‌شود.
// اصلاح 2.4: قبل از شروع فقط کل بردها، بعد از شروع فقط بردهای همین بازی.
// ============================================================

function handleGameRpsUpdate($update, $group)
{
    if (!is_array($update) || !is_array($group)) {
        return false;
    }

    if (!function_exists('gameGroupDataTransaction')) {
        error_log('Game RPS: gameGroupDataTransaction is missing.');
        return false;
    }

    if (!isset($update['callback_query'])) {
        return false;
    }

    $callback = $update['callback_query'];
    $callback_id = (string)($callback['id'] ?? '');
    $data = (string)($callback['data'] ?? '');
    $message = $callback['message'] ?? [];
    $chat = $message['chat'] ?? [];

    $chat_id = (int)($chat['id'] ?? 0);
    $message_id = (int)($message['message_id'] ?? 0);
    $user_id = (int)($callback['from']['id'] ?? 0);
    $chat_type = (string)($chat['type'] ?? '');

    if (
        $callback_id === '' ||
        $chat_id === 0 ||
        $message_id === 0 ||
        $user_id === 0 ||
        !in_array($chat_type, ['group', 'supergroup'], true)
    ) {
        return false;
    }

    if ($data === 'game_rps') {
        return gameRpsStartNewGame($callback, $group);
    }

    if (preg_match('/^rps_join:([a-f0-9]{12})$/', $data, $matches)) {
        return gameRpsHandleJoin(
            $callback,
            $matches[1],
            $chat_id,
            $message_id,
            $user_id
        );
    }

    if (preg_match('/^rps_back:([a-f0-9]{12})$/', $data, $matches)) {
        return gameRpsHandleBack(
            $callback,
            $matches[1],
            $chat_id,
            $message_id,
            $user_id
        );
    }

    if (preg_match('/^rps_exit:([a-f0-9]{12})$/', $data, $matches)) {
        return gameRpsHandleExit(
            $callback,
            $matches[1],
            $chat_id,
            $message_id,
            $user_id
        );
    }

    if (preg_match('/^rps_pick:([a-f0-9]{12}):(rock|paper|scissors)$/', $data, $matches)) {
        return gameRpsHandlePick(
            $callback,
            $matches[1],
            $matches[2],
            $chat_id,
            $message_id,
            $user_id
        );
    }

    return false;
}

function gameRpsAnswer($callback_id, $text, $show_alert = false)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    return makeCurl(
        API_URL . 'answerCallbackQuery',
        [
            'callback_query_id' => $callback_id,
            'text' => $text,
            'show_alert' => $show_alert
        ]
    );
}

function gameRpsResponseOk($response)
{
    if (is_array($response)) {
        return !empty($response['ok']);
    }

    if (is_string($response)) {
        $decoded = json_decode($response, true);
        return is_array($decoded) && !empty($decoded['ok']);
    }

    return false;
}

function gameRpsResponseDescription($response)
{
    if (is_array($response)) {
        return (string)($response['description'] ?? 'unknown error');
    }

    if (is_string($response)) {
        $decoded = json_decode($response, true);

        if (is_array($decoded)) {
            return (string)($decoded['description'] ?? 'unknown error');
        }
    }

    return 'unknown error';
}

function gameRpsDecodeResponse($response)
{
    if (is_array($response)) {
        return $response;
    }

    if (is_string($response)) {
        $decoded = json_decode($response, true);
        return is_array($decoded) ? $decoded : [];
    }

    return [];
}

function gameRpsGetIdentity($user)
{
    $first_name = trim((string)($user['first_name'] ?? ''));
    $last_name = trim((string)($user['last_name'] ?? ''));
    $user_id = (int)($user['id'] ?? 0);

    $name = trim($first_name . ' ' . $last_name);

    if ($name === '') {
        $name = 'بازیکن ' . $user_id;
    }

    return [
        'name' => $name,
        'first_name' => $first_name
    ];
}

function gameRpsPlayerHtml($user_id, $name)
{
    $user_id = (int)$user_id;
    $safe_name = htmlspecialchars(
        (string)$name,
        ENT_QUOTES | ENT_SUBSTITUTE,
        'UTF-8'
    );

    if ($safe_name === '') {
        $safe_name = 'بازیکن';
    }

    if ($user_id > 0) {
        return '<a href="tg://user?id=' . $user_id . '">' . $safe_name . '</a>';
    }

    return $safe_name;
}

// جلوی اسم بازیکن، امتیاز کل را داخل پرانتز می‌نویسد.
// مثال: gameRpsPlayerLabel(123, 'علی', 10) => 'علی (10 ⭐)'
function gameRpsPlayerLabel($user_id, $name, $total_points)
{
    return gameRpsPlayerHtml($user_id, $name) .
        ' (' . (int)$total_points . ' ⭐)';
}

// امتیاز کل یک بازیکن در یک گروه را از rps_leaderboard می‌خواند.
function gameRpsLeaderboardPoints($group_id, $user_id)
{
    $key = (string)(int)$user_id;

    if ($key === '0') {
        return 0;
    }

    $result = gameGroupDataTransaction(
        (int)$group_id,
        function ($state) use ($key) {
            return (int)(
                $state['rps_leaderboard'][$key]['points'] ?? 0
            );
        }
    );

    return (int)($result['result'] ?? 0);
}

// تعداد بردهای کل یک بازیکن (همه بازی‌ها) را از rps_leaderboard می‌خواند.
function gameRpsLeaderboardWins($group_id, $user_id)
{
    $key = (string)(int)$user_id;

    if ($key === '0') {
        return 0;
    }

    $result = gameGroupDataTransaction(
        (int)$group_id,
        function ($state) use ($key) {
            return (int)(
                $state['rps_leaderboard'][$key]['wins'] ?? 0
            );
        }
    );

    return (int)($result['result'] ?? 0);
}

function gameRpsGetGame($game_id, $group_id)
{
    $transaction = gameGroupDataTransaction((int)$group_id);

    if (empty($transaction['ok']) || !is_array($transaction['state'] ?? null)) {
        return null;
    }

    $state = $transaction['state'];

    if (!isset($state['rps_games']) || !is_array($state['rps_games'])) {
        return null;
    }

    if (!isset($state['rps_games'][$game_id]) || !is_array($state['rps_games'][$game_id])) {
        return null;
    }

    return $state['rps_games'][$game_id];
}

function gameRpsNewPlayer($user_id, $name, $total_points = 0, $total_wins = 0)
{
    return [
        'user_id' => (int)$user_id,
        'name' => (string)$name,
        'status' => 'active', // active | exited
        'choice' => '', // '' | rock | paper | scissors
        'round_wins' => 0, // بردهای همین بازی
        'total_points' => (int)$total_points,
        'total_wins' => (int)$total_wins, // بردهای کل همه بازی‌ها
        'joined_at' => time()
    ];
}

// برچسب و ایموجی هر انتخاب
function gameRpsChoiceLabel($choice)
{
    $labels = [
        'rock' => 'سنگ ✊',
        'paper' => 'کاغذ ✋',
        'scissors' => 'قیچی ✌️'
    ];

    return $labels[$choice] ?? '؟';
}

// چه کسی راند را می‌برد؟ 0 یعنی مساوی، 1 یعنی بازیکن اول، 2 یعنی بازیکن دوم
function gameRpsRoundWinner($choice1, $choice2)
{
    if ($choice1 === $choice2) {
        return 0;
    }

    $beats = [
        'rock' => 'scissors',
        'scissors' => 'paper',
        'paper' => 'rock'
    ];

    if (($beats[$choice1] ?? '') === $choice2) {
        return 1;
    }

    return 2;
}

function gameRpsAddEvent(&$game, $event)
{
    if (!isset($game['events']) || !is_array($game['events'])) {
        $game['events'] = [];
    }

    $game['events'][] = (string)$event;

    if (count($game['events']) > 8) {
        $game['events'] = array_slice($game['events'], -8);
    }
}

// نتیجه بازی را در rps_leaderboard ثبت می‌کند:
// برنده ۱۰ امتیاز و یک برد می‌گیرد، هر دو بازیکن یک بازی به حسابشان می‌آید.
// امتیاز کل جدید برنده را برمی‌گرداند.
function gameRpsRecordGameResult(&$state, $winner_id, $winner_name, $loser_id, $loser_name)
{
    if (!isset($state['rps_leaderboard']) || !is_array($state['rps_leaderboard'])) {
        $state['rps_leaderboard'] = [];
    }

    $winner_key = (string)(int)$winner_id;
    $loser_key = (string)(int)$loser_id;

    if ($winner_key !== '0') {
        $record = $state['rps_leaderboard'][$winner_key] ?? [];
        if (!is_array($record)) {
            $record = [];
        }

        $record['user_id'] = (int)$winner_id;
        $record['name'] = (string)$winner_name;
        $record['points'] = max(0, (int)($record['points'] ?? 0)) + 10;
        $record['wins'] = (int)($record['wins'] ?? 0) + 1;
        $record['games'] = (int)($record['games'] ?? 0) + 1;
        $record['updated_at'] = time();

        $state['rps_leaderboard'][$winner_key] = $record;
    }

    if ($loser_key !== '0') {
        $record = $state['rps_leaderboard'][$loser_key] ?? [];
        if (!is_array($record)) {
            $record = [];
        }

        $record['user_id'] = (int)$loser_id;
        $record['name'] = (string)$loser_name;
        $record['points'] = max(0, (int)($record['points'] ?? 0));
        $record['wins'] = (int)($record['wins'] ?? 0);
        $record['games'] = (int)($record['games'] ?? 0) + 1;
        $record['updated_at'] = time();

        $state['rps_leaderboard'][$loser_key] = $record;
    }

    return (int)($state['rps_leaderboard'][$winner_key]['points'] ?? 0);
}

function gameRpsStartNewGame($callback, $group)
{
    $message = $callback['message'] ?? [];
    $chat = $message['chat'] ?? [];
    $user = $callback['from'] ?? [];

    $chat_id = (int)($chat['id'] ?? 0);
    $message_id = (int)($message['message_id'] ?? 0);
    $user_id = (int)($user['id'] ?? 0);
    $callback_id = (string)($callback['id'] ?? '');
    $invoker_id = (int)($group['invoker_id'] ?? 0);

    if ($chat_id === 0 || $message_id === 0 || $user_id === 0) {
        gameRpsAnswer($callback_id, 'اطلاعات شروع بازی معتبر نیست.', true);
        return true;
    }

    if ($invoker_id <= 0 || $user_id !== $invoker_id) {
        gameRpsAnswer(
            $callback_id,
            'فقط سازنده این منو می‌تواند بازی را انتخاب کند.',
            true
        );
        return true;
    }

    try {
        $game_id = bin2hex(random_bytes(6));
    } catch (Throwable $e) {
        error_log('Game RPS random ID error: ' . $e->getMessage());
        gameRpsAnswer($callback_id, 'خطا در ساخت بازی؛ دوباره امتحان کنید.', true);
        return true;
    }

    $identity = gameRpsGetIdentity($user);
    $now = time();

    // امتیاز کل و تعداد بردهای کل بازیکن از بازی‌های قبلی در همین گروه،
    // تا از همان اول جلوی اسمش نشان داده شود.
    $player1_total = gameRpsLeaderboardPoints($chat_id, $user_id);
    $player1_wins = gameRpsLeaderboardWins($chat_id, $user_id);

    $game = [
        'game_id' => $game_id,
        'group_id' => $chat_id,
        'message_id' => $message_id,
        'owner_id' => $invoker_id,

        'player1' => gameRpsNewPlayer($user_id, $identity['name'], $player1_total, $player1_wins),
        'player2' => null,

        'round' => 1,
        'status' => 'waiting', // waiting | playing | finished | returned
        'created_at' => $now,
        'joined_at' => 0,
        'finished_at' => 0,

        'winner_id' => 0,
        'events' => [],
        'finish_reason' => '' // win | forfeit
    ];

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $game) {
            if (!isset($state['rps_games']) || !is_array($state['rps_games'])) {
                $state['rps_games'] = [];
            }

            if (isset($state['rps_games'][$game_id])) {
                return false;
            }

            $state['rps_games'][$game_id] = $game;
            return true;
        }
    );

    if (empty($transaction['ok']) || ($transaction['result'] ?? false) !== true) {
        gameRpsAnswer($callback_id, 'ذخیره اطلاعات بازی ناموفق بود.', true);
        return true;
    }

    gameRpsAnswer($callback_id, 'بازی سنگ کاغذ قیچی ساخته شد؛ منتظر بازیکن دوم باشید.');

    $response = gameRpsEditBoard($chat_id, $message_id, $game);

    if (!gameRpsResponseOk($response)) {
        error_log('Game RPS start edit error: ' . gameRpsResponseDescription($response));

        gameGroupDataTransaction(
            $chat_id,
            function (&$state) use ($game_id) {
                if (isset($state['rps_games'][$game_id])) {
                    $state['rps_games'][$game_id]['status'] = 'error';
                }
                return true;
            }
        );
    }

    return true;
}

function gameRpsBuildText($game)
{
    $status = (string)($game['status'] ?? 'waiting');
    $p1 = $game['player1'] ?? [];
    $p2 = $game['player2'] ?? null;

    $p1_id = (int)($p1['user_id'] ?? 0);
    $p1_name_raw = (string)($p1['name'] ?? 'بازیکن اول');
    $p1_total = (int)($p1['total_points'] ?? 0);
    $p1_name = gameRpsPlayerLabel($p1_id, $p1_name_raw, $p1_total);
    $p1_wins = (int)($p1['round_wins'] ?? 0);
    $p1_total_wins = (int)($p1['total_wins'] ?? 0);

    // قبل از شروع بازی فقط کل بردها نشان داده می‌شود؛
    // بعد از شروع فقط بردهای همین بازی.
    $p1_wins_text = ($status === 'waiting')
        ? " | کل بردها: {$p1_total_wins} 👑"
        : " | بردها: {$p1_wins} 🏆";

    $text = "<b>🎮 بازی سنگ کاغذ قیچی</b>\n";
    $text .= "بهترین از ۳ راند — هر کس ۲ راند ببرد، برنده است.\n\n";
    $text .= "🔴 بازیکن اول: {$p1_name}{$p1_wins_text}\n";

    if (is_array($p2)) {
        $p2_id = (int)($p2['user_id'] ?? 0);
        $p2_name_raw = (string)($p2['name'] ?? 'بازیکن دوم');
        $p2_total = (int)($p2['total_points'] ?? 0);
        $p2_name = gameRpsPlayerLabel($p2_id, $p2_name_raw, $p2_total);
        $p2_wins = (int)($p2['round_wins'] ?? 0);
        $p2_total_wins = (int)($p2['total_wins'] ?? 0);
        $p2_wins_text = ($status === 'waiting')
            ? " | کل بردها: {$p2_total_wins} 👑"
            : " | بردها: {$p2_wins} 🏆";
        $text .= "🔵 بازیکن دوم: {$p2_name}{$p2_wins_text}\n\n";
    } else {
        $text .= "🔵 بازیکن دوم: <i>در انتظار ورود حریف...</i>\n\n";
    }

    if ($status === 'waiting') {
        $text .= "⏱ منتظر بازیکن دوم باشید.";
    } elseif ($status === 'playing') {
        $round = (int)($game['round'] ?? 1);
        $text .= "🎲 راند {$round} از ۳\n";

        $p1_picked = !empty($p1['choice']);
        $p2_picked = is_array($p2) && !empty($p2['choice']);

        if ($p1_picked && $p2_picked) {
            $text .= "هر دو انتخاب کردند...";
        } elseif ($p1_picked) {
            $text .= "✅ بازیکن اول انتخاب کرد — منتظر بازیکن دوم...";
        } elseif ($p2_picked) {
            $text .= "✅ بازیکن دوم انتخاب کرد — منتظر بازیکن اول...";
        } else {
            $text .= "✊✋✌️ هر دو بازیکن یکی را انتخاب کنید!";
        }
    } elseif ($status === 'finished') {
        $winner_id = (int)($game['winner_id'] ?? 0);
        $winner_name = 'بازیکن';

        if ($winner_id === $p1_id) {
            $winner_name = gameRpsPlayerHtml($p1_id, $p1_name_raw);
        } elseif (is_array($p2) && $winner_id === (int)($p2['user_id'] ?? 0)) {
            $winner_name = gameRpsPlayerHtml(
                (int)($p2['user_id'] ?? 0),
                (string)($p2['name'] ?? 'بازیکن دوم')
            );
        }

        $text .= "🏆 برنده: {$winner_name}!\n";
    }

    $events = $game['events'] ?? [];
    if (is_array($events) && !empty($events)) {
        $text .= "\n\n" . implode("\n", $events);
    }

    // جمله پایان بازی فقط یک بار اینجا نوشته می‌شود.
    if ($status === 'finished') {
        $text .= "\n<b>🏁 بازی به پایان رسید!</b>";
    }

    return $text;
}

function gameRpsBuildKeyboard($game)
{
    $status = (string)($game['status'] ?? 'waiting');
    $game_id = (string)($game['game_id'] ?? '');

    if ($status === 'waiting') {
        return [
            'inline_keyboard' => [
                [
                    [
                        'text' => '👋 ورود به بازی',
                        'callback_data' => 'rps_join:' . $game_id,
                        'style' => 'success'
                    ]
                ],
                [
                    [
                        'text' => '🔙 بازگشت',
                        'callback_data' => 'rps_back:' . $game_id,
                        'style' => 'danger'
                    ]
                ]
            ]
        ];
    }

    if ($status === 'playing') {
        return [
            'inline_keyboard' => [
                [
                    [
                        'text' => '✊ سنگ',
                        'callback_data' => 'rps_pick:' . $game_id . ':rock',
                        'style' => 'primary'
                    ],
                    [
                        'text' => '✋ کاغذ',
                        'callback_data' => 'rps_pick:' . $game_id . ':paper',
                        'style' => 'primary'
                    ],
                    [
                        'text' => '✌️ قیچی',
                        'callback_data' => 'rps_pick:' . $game_id . ':scissors',
                        'style' => 'primary'
                    ]
                ],
                [
                    [
                        'text' => '🚪 خروج از بازی',
                        'callback_data' => 'rps_exit:' . $game_id,
                        'style' => 'danger'
                    ]
                ]
            ]
        ];
    }

    if ($status === 'finished') {
        return [
            'inline_keyboard' => [
                [
                    [
                        'text' => '🔙 بازگشت به منو',
                        'callback_data' => 'rps_back:' . $game_id,
                        'style' => 'danger'
                    ]
                ]
            ]
        ];
    }

    return [
        'inline_keyboard' => []
    ];
}

function gameRpsEditBoard($chat_id, $message_id, $game)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    // دقیقاً مثل بمب: مستقیم با makeCurl ویرایش می‌کنیم،
    // نه با editMessageText که در فایل‌های بازی تعریف نشده است.
    $response = makeCurl(
        API_URL . 'editMessageText',
        [
            'chat_id' => (int)$chat_id,
            'message_id' => (int)$message_id,
            'text' => gameRpsBuildText($game),
            'parse_mode' => 'HTML',
            'reply_markup' => json_encode(
                gameRpsBuildKeyboard($game),
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            )
        ]
    );

    if (gameRpsResponseOk($response)) {
        return $response;
    }

    // اگر ویرایش پیام نشد (مثلاً پیام منو قدیمی است یا تلگرام خطا داد)،
    // صفحه بازی را به‌صورت پیام جدید می‌فرستیم و شناسه پیام جدید را
    // در بازی ذخیره می‌کنیم تا دکمه‌های بعدی روی پیام جدید کار کنند.
    error_log(
        'Game RPS edit board failed: ' .
        gameRpsResponseDescription($response) .
        ' — sending board as new message.'
    );

    $send = makeCurl(
        API_URL . 'sendMessage',
        [
            'chat_id' => (int)$chat_id,
            'text' => gameRpsBuildText($game),
            'parse_mode' => 'HTML',
            'reply_markup' => json_encode(
                gameRpsBuildKeyboard($game),
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            )
        ]
    );

    if (!gameRpsResponseOk($send)) {
        error_log('Game RPS send board failed: ' . gameRpsResponseDescription($send));
        return $send;
    }

    $sent = gameRpsDecodeResponse($send);
    $new_message_id = (int)($sent['result']['message_id'] ?? 0);

    if ($new_message_id > 0 && !empty($game['game_id'])) {
        $game_id = (string)$game['game_id'];

        gameGroupDataTransaction(
            (int)$chat_id,
            function (&$state) use ($game_id, $new_message_id) {
                if (isset($state['rps_games'][$game_id])) {
                    $state['rps_games'][$game_id]['message_id'] = $new_message_id;
                }
                return true;
            }
        );
    }

    return $send;
}

function gameRpsRestoreGameMenu($chat_id, $message_id)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    $text = function_exists('gameGroupCommandMenuText')
        ? gameGroupCommandMenuText()
        : 'لطفا یک گزینه را انتخاب کنید.';

    $keyboard = function_exists('gameGroupGameKeyboard')
        ? gameGroupGameKeyboard()
        : [
            'inline_keyboard' => [
                [
                    ['text' => '💣💎', 'callback_data' => 'game_bm', 'style' => 'success'],
                    ['text' => '❌⭕️', 'callback_data' => 'game_dz', 'style' => 'success']
                ],
                [
                    ['text' => '✊✋✌️ سنگ کاغذ قیچی', 'callback_data' => 'game_rps', 'style' => 'danger']
                ]
            ]
        ];

    return makeCurl(
        API_URL . 'editMessageText',
        [
            'chat_id' => (int)$chat_id,
            'message_id' => (int)$message_id,
            'text' => $text,
            'reply_markup' => json_encode(
                $keyboard,
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            )
        ]
    );
}

function gameRpsHandleJoin($callback, $game_id, $chat_id, $message_id, $user_id)
{
    $callback_id = (string)($callback['id'] ?? '');
    $identity = gameRpsGetIdentity($callback['from'] ?? []);

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $chat_id, $message_id, $user_id, $identity) {
            if (!isset($state['rps_games'][$game_id]) || !is_array($state['rps_games'][$game_id])) {
                return ['ok' => false, 'reason' => 'not_found'];
            }

            $game = &$state['rps_games'][$game_id];

            if (
                (int)($game['group_id'] ?? 0) !== $chat_id ||
                (int)($game['message_id'] ?? 0) !== $message_id
            ) {
                return ['ok' => false, 'reason' => 'wrong_context'];
            }

            if (($game['status'] ?? '') !== 'waiting') {
                return ['ok' => false, 'reason' => 'already_started'];
            }

            if (!empty($game['player2'])) {
                return ['ok' => false, 'reason' => 'game_full'];
            }

            if ((int)($game['player1']['user_id'] ?? 0) === $user_id) {
                return ['ok' => false, 'reason' => 'already_joined'];
            }

            $player2_total = (int)(
                $state['rps_leaderboard'][(string)$user_id]['points'] ?? 0
            );
            $player2_wins = (int)(
                $state['rps_leaderboard'][(string)$user_id]['wins'] ?? 0
            );

            $game['player2'] = gameRpsNewPlayer(
                $user_id,
                $identity['name'],
                $player2_total,
                $player2_wins
            );

            // امتیاز کل و تعداد بردهای کل بازیکن اول را هم تازه کن.
            if (isset($game['player1']) && is_array($game['player1'])) {
                $player1_id = (int)($game['player1']['user_id'] ?? 0);

                if ($player1_id > 0) {
                    $game['player1']['total_points'] = (int)(
                        $state['rps_leaderboard'][(string)$player1_id]['points'] ?? 0
                    );
                    $game['player1']['total_wins'] = (int)(
                        $state['rps_leaderboard'][(string)$player1_id]['wins'] ?? 0
                    );
                }
            }

            $game['status'] = 'playing';
            $game['joined_at'] = time();
            $game['round'] = 1;

            gameRpsAddEvent(
                $game,
                '👋 بازیکن دوم وارد شد! راند ۱ شروع شد.'
            );

            return ['ok' => true, 'game' => $game];
        }
    );

    $result = $transaction['result'] ?? null;
    if (!is_array($result)) {
        gameRpsAnswer($callback_id, 'خطا در ورود به بازی.', true);
        return true;
    }

    if (empty($result['ok'])) {
        $messages = [
            'not_found' => 'این بازی پیدا نشد.',
            'wrong_context' => 'این دکمه متعلق به این پیام نیست.',
            'already_started' => 'بازی شروع شده است.',
            'game_full' => 'بازی پر شده است.',
            'already_joined' => 'شما سازنده این بازی هستید.'
        ];

        gameRpsAnswer(
            $callback_id,
            $messages[$result['reason'] ?? ''] ?? 'امکان ورود وجود ندارد.',
            true
        );
        return true;
    }

    gameRpsAnswer($callback_id, 'وارد بازی شدی! ✊✋✌️');

    $response = gameRpsEditBoard($chat_id, $message_id, $result['game']);

    if (!gameRpsResponseOk($response)) {
        error_log('Game RPS board edit error: ' . gameRpsResponseDescription($response));
    }

    return true;
}

function gameRpsHandleBack($callback, $game_id, $chat_id, $message_id, $user_id)
{
    $callback_id = (string)($callback['id'] ?? '');

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $chat_id, $message_id, $user_id) {
            if (!isset($state['rps_games'][$game_id]) || !is_array($state['rps_games'][$game_id])) {
                return ['ok' => false, 'reason' => 'not_found'];
            }

            $game = &$state['rps_games'][$game_id];

            if (
                (int)($game['group_id'] ?? 0) !== $chat_id ||
                (int)($game['message_id'] ?? 0) !== $message_id
            ) {
                return ['ok' => false, 'reason' => 'wrong_context'];
            }

            $status = (string)($game['status'] ?? '');

            // بعد از پایان بازی، هر یک از بازیکن‌ها می‌توانند به منو برگردند.
            if ($status === 'finished') {
                return ['ok' => true];
            }

            if ($status !== 'waiting' || !empty($game['player2'])) {
                return ['ok' => false, 'reason' => 'already_started'];
            }

            if ((int)($game['owner_id'] ?? 0) !== $user_id) {
                return ['ok' => false, 'reason' => 'not_owner'];
            }

            $game['status'] = 'returned';
            $game['returned_at'] = time();

            return ['ok' => true];
        }
    );

    $result = $transaction['result'] ?? null;
    if (!is_array($result)) {
        gameRpsAnswer($callback_id, 'خطا در بازگشت به منو.', true);
        return true;
    }

    if (empty($result['ok'])) {
        $messages = [
            'not_found' => 'این بازی پیدا نشد.',
            'wrong_context' => 'این دکمه متعلق به این پیام نیست.',
            'not_owner' => 'فقط سازنده این بازی می‌تواند بازگشت بزند.',
            'already_started' => 'بازی شروع شده و دیگر امکان بازگشت وجود ندارد.'
        ];

        gameRpsAnswer(
            $callback_id,
            $messages[$result['reason'] ?? ''] ?? 'امکان بازگشت وجود ندارد.',
            true
        );
        return true;
    }

    gameRpsAnswer($callback_id, 'بازگشت به منوی انتخاب بازی.');

    $response = gameRpsRestoreGameMenu($chat_id, $message_id);
    if (!gameRpsResponseOk($response)) {
        error_log('Game RPS back error: ' . gameRpsResponseDescription($response));
    }

    return true;
}

function gameRpsHandlePick($callback, $game_id, $choice, $chat_id, $message_id, $user_id)
{
    $callback_id = (string)($callback['id'] ?? '');

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $choice, $chat_id, $message_id, $user_id) {
            if (!isset($state['rps_games'][$game_id]) || !is_array($state['rps_games'][$game_id])) {
                return ['ok' => false, 'reason' => 'not_found'];
            }

            $game = &$state['rps_games'][$game_id];

            if (
                (int)($game['group_id'] ?? 0) !== $chat_id ||
                (int)($game['message_id'] ?? 0) !== $message_id
            ) {
                return ['ok' => false, 'reason' => 'wrong_context'];
            }

            if (($game['status'] ?? '') === 'waiting') {
                return ['ok' => false, 'reason' => 'wait_join'];
            }

            if (($game['status'] ?? '') === 'finished') {
                return ['ok' => false, 'reason' => 'finished'];
            }

            if (($game['status'] ?? '') !== 'playing') {
                return ['ok' => false, 'reason' => 'not_playing'];
            }

            if (!isset($game['player1']) || !is_array($game['player1'])) {
                return ['ok' => false, 'reason' => 'invalid_player'];
            }

            if (!isset($game['player2']) || !is_array($game['player2'])) {
                return ['ok' => false, 'reason' => 'invalid_player'];
            }

            $player_number = 0;

            if ((int)($game['player1']['user_id'] ?? 0) === $user_id) {
                $player_number = 1;
            } elseif ((int)($game['player2']['user_id'] ?? 0) === $user_id) {
                $player_number = 2;
            }

            if ($player_number === 0) {
                return ['ok' => false, 'reason' => 'not_player'];
            }

            $key = ($player_number === 1) ? 'player1' : 'player2';
            $player = &$game[$key];

            if (($player['status'] ?? '') !== 'active') {
                return ['ok' => false, 'reason' => 'not_active'];
            }

            if (!empty($player['choice'])) {
                return ['ok' => false, 'reason' => 'already_picked'];
            }

            $player['choice'] = $choice;

            $round = (int)($game['round'] ?? 1);
            $notice = 'picked';
            $round_winner = 0;
            $game_winner = 0;

            // هر دو انتخاب کردند: راند را مشخص کن.
            if (!empty($game['player1']['choice']) && !empty($game['player2']['choice'])) {
                $choice1 = (string)$game['player1']['choice'];
                $choice2 = (string)$game['player2']['choice'];
                $round_winner = gameRpsRoundWinner($choice1, $choice2);

                $name1 = htmlspecialchars(
                    (string)($game['player1']['name'] ?? 'بازیکن اول'),
                    ENT_QUOTES | ENT_SUBSTITUTE,
                    'UTF-8'
                );
                $name2 = htmlspecialchars(
                    (string)($game['player2']['name'] ?? 'بازیکن دوم'),
                    ENT_QUOTES | ENT_SUBSTITUTE,
                    'UTF-8'
                );

                if ($round_winner === 0) {
                    gameRpsAddEvent(
                        $game,
                        '🎲 راند ' . $round . ': ' .
                        gameRpsChoiceLabel($choice1) . ' ' . $name1 .
                        ' 🆚 ' .
                        gameRpsChoiceLabel($choice2) . ' ' . $name2 .
                        ' — مساوی! راند تکرار می‌شود.'
                    );
                    $notice = 'round_tie';
                } else {
                    $winner_key = ($round_winner === 1) ? 'player1' : 'player2';
                    $game[$winner_key]['round_wins'] = (int)($game[$winner_key]['round_wins'] ?? 0) + 1;
                    $winner_name = ($round_winner === 1) ? $name1 : $name2;

                    gameRpsAddEvent(
                        $game,
                        '🎲 راند ' . $round . ': ' .
                        gameRpsChoiceLabel($choice1) . ' ' . $name1 .
                        ' 🆚 ' .
                        gameRpsChoiceLabel($choice2) . ' ' . $name2 .
                        ' — ' . $winner_name . ' برد!'
                    );

                    $notice = 'round_win';
                }

                if ((int)($game['player1']['round_wins'] ?? 0) >= 2) {
                    $game_winner = 1;
                } elseif ((int)($game['player2']['round_wins'] ?? 0) >= 2) {
                    $game_winner = 2;
                }

                if ($game_winner !== 0) {
                    $winner_key = ($game_winner === 1) ? 'player1' : 'player2';
                    $loser_key = ($game_winner === 1) ? 'player2' : 'player1';
                    $winner = $game[$winner_key];
                    $loser = $game[$loser_key];

                    $game['status'] = 'finished';
                    $game['finished_at'] = time();
                    $game['finish_reason'] = 'win';
                    $game['winner_id'] = (int)($winner['user_id'] ?? 0);

                    gameRpsRecordGameResult(
                        $state,
                        (int)($winner['user_id'] ?? 0),
                        (string)($winner['name'] ?? 'بازیکن'),
                        (int)($loser['user_id'] ?? 0),
                        (string)($loser['name'] ?? 'بازیکن')
                    );

                    // امتیاز کل و تعداد بردهای کل هر دو بازیکن را تازه کن.
                    $game['player1']['total_points'] = (int)(
                        $state['rps_leaderboard'][(string)(int)($game['player1']['user_id'] ?? 0)]['points'] ?? 0
                    );
                    $game['player2']['total_points'] = (int)(
                        $state['rps_leaderboard'][(string)(int)($game['player2']['user_id'] ?? 0)]['points'] ?? 0
                    );
                    $game['player1']['total_wins'] = (int)(
                        $state['rps_leaderboard'][(string)(int)($game['player1']['user_id'] ?? 0)]['wins'] ?? 0
                    );
                    $game['player2']['total_wins'] = (int)(
                        $state['rps_leaderboard'][(string)(int)($game['player2']['user_id'] ?? 0)]['wins'] ?? 0
                    );

                    $notice = 'finished';
                } else {
                    // راند بعد: انتخاب‌ها پاک می‌شوند.
                    $game['round'] = $round + 1;
                    $game['player1']['choice'] = '';
                    $game['player2']['choice'] = '';
                }
            }

            return [
                'ok' => true,
                'game' => $game,
                'notice' => $notice,
                'round_winner' => $round_winner,
                'game_winner' => $game_winner,
                'choice' => $choice
            ];
        }
    );

    $result = $transaction['result'] ?? null;

    if (!is_array($result)) {
        gameRpsAnswer($callback_id, 'خطا در ثبت انتخاب.', true);
        return true;
    }

    if (empty($result['ok'])) {
        $messages = [
            'not_found' => 'این بازی پیدا نشد.',
            'wrong_context' => 'این گزینه متعلق به این پیام یا گروه نیست.',
            'wait_join' => 'ابتدا بازیکن دوم باید عضو شود.',
            'finished' => 'این بازی به پایان رسیده است.',
            'not_playing' => 'این بازی در حال حاضر فعال نیست.',
            'invalid_player' => 'اطلاعات بازیکن معتبر نیست.',
            'not_player' => 'شما بازیکن این بازی نیستید.',
            'not_active' => 'شما از این بازی خارج شده‌اید.',
            'already_picked' => 'قبلاً انتخاب کردی؛ منتظر حریف باش!'
        ];

        gameRpsAnswer(
            $callback_id,
            $messages[$result['reason'] ?? ''] ?? 'انتخاب مجاز نیست.',
            true
        );
        return true;
    }

    // جواب خصوصی فقط برای کسی که دکمه را زده است.
    $notice = (string)($result['notice'] ?? 'picked');

    if ($notice === 'picked') {
        gameRpsAnswer(
            $callback_id,
            'انتخابت ثبت شد: ' . gameRpsChoiceLabel((string)($result['choice'] ?? '')) . ' — منتظر حریف باش.'
        );
    } elseif ($notice === 'round_tie') {
        gameRpsAnswer($callback_id, 'مساوی شد! راند دوباره تکرار می‌شود.');
    } elseif ($notice === 'round_win') {
        $round_winner = (int)($result['round_winner'] ?? 0);
        $my_number = 0;
        $game = $result['game'];

        if ((int)($game['player1']['user_id'] ?? 0) === $user_id) {
            $my_number = 1;
        } elseif ((int)($game['player2']['user_id'] ?? 0) === $user_id) {
            $my_number = 2;
        }

        gameRpsAnswer(
            $callback_id,
            ($round_winner === $my_number) ? 'این راند را بردی! 🎉' : 'این راند را باختی! 😅'
        );
    } elseif ($notice === 'finished') {
        $game_winner = (int)($result['game_winner'] ?? 0);
        $game = $result['game'];

        $my_number = 0;
        if ((int)($game['player1']['user_id'] ?? 0) === $user_id) {
            $my_number = 1;
        } elseif ((int)($game['player2']['user_id'] ?? 0) === $user_id) {
            $my_number = 2;
        }

        gameRpsAnswer(
            $callback_id,
            ($game_winner === $my_number)
                ? '🏆 برنده شدی! ۱۰ امتیاز گرفتی.'
                : 'بازی به پایان رسید؛ حریف برنده شد.'
        );
    }

    $response = gameRpsEditBoard($chat_id, $message_id, $result['game']);

    if (!gameRpsResponseOk($response)) {
        error_log('Game RPS board edit error: ' . gameRpsResponseDescription($response));
    }

    return true;
}

function gameRpsHandleExit($callback, $game_id, $chat_id, $message_id, $user_id)
{
    $callback_id = (string)($callback['id'] ?? '');

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $chat_id, $message_id, $user_id) {
            if (!isset($state['rps_games'][$game_id]) || !is_array($state['rps_games'][$game_id])) {
                return ['ok' => false, 'reason' => 'not_found'];
            }

            $game = &$state['rps_games'][$game_id];

            if (
                (int)($game['group_id'] ?? 0) !== $chat_id ||
                (int)($game['message_id'] ?? 0) !== $message_id
            ) {
                return ['ok' => false, 'reason' => 'wrong_context'];
            }

            if (($game['status'] ?? '') !== 'playing') {
                return ['ok' => false, 'reason' => 'not_playing'];
            }

            $player_number = 0;

            if ((int)($game['player1']['user_id'] ?? 0) === $user_id) {
                $player_number = 1;
            } elseif ((int)($game['player2']['user_id'] ?? 0) === $user_id) {
                $player_number = 2;
            }

            if ($player_number === 0) {
                return ['ok' => false, 'reason' => 'not_player'];
            }

            $key = ($player_number === 1) ? 'player1' : 'player2';
            $other_key = ($player_number === 1) ? 'player2' : 'player1';
            $player = &$game[$key];
            $other = &$game[$other_key];

            if (($player['status'] ?? '') !== 'active') {
                return ['ok' => false, 'reason' => 'already_left'];
            }

            $player['status'] = 'exited';

            $safe_name = htmlspecialchars(
                (string)($player['name'] ?? 'بازیکن'),
                ENT_QUOTES | ENT_SUBSTITUTE,
                'UTF-8'
            );
            $other_name = htmlspecialchars(
                (string)($other['name'] ?? 'بازیکن'),
                ENT_QUOTES | ENT_SUBSTITUTE,
                'UTF-8'
            );

            // خروج یعنی باخت: حریف برنده بازی می‌شود و ۱۰ امتیاز می‌گیرد.
            $game['status'] = 'finished';
            $game['finished_at'] = time();
            $game['finish_reason'] = 'forfeit';
            $game['winner_id'] = (int)($other['user_id'] ?? 0);

            gameRpsRecordGameResult(
                $state,
                (int)($other['user_id'] ?? 0),
                (string)($other['name'] ?? 'بازیکن'),
                (int)($player['user_id'] ?? 0),
                (string)($player['name'] ?? 'بازیکن')
            );

            $game['player1']['total_points'] = (int)(
                $state['rps_leaderboard'][(string)(int)($game['player1']['user_id'] ?? 0)]['points'] ?? 0
            );
            $game['player2']['total_points'] = (int)(
                $state['rps_leaderboard'][(string)(int)($game['player2']['user_id'] ?? 0)]['points'] ?? 0
            );
            $game['player1']['total_wins'] = (int)(
                $state['rps_leaderboard'][(string)(int)($game['player1']['user_id'] ?? 0)]['wins'] ?? 0
            );
            $game['player2']['total_wins'] = (int)(
                $state['rps_leaderboard'][(string)(int)($game['player2']['user_id'] ?? 0)]['wins'] ?? 0
            );

            gameRpsAddEvent(
                $game,
                '🚪 بازیکن ' . $safe_name . ' از بازی خارج شد؛ ' . $other_name . ' برنده شد!'
            );

            return [
                'ok' => true,
                'game' => $game
            ];
        }
    );

    $result = $transaction['result'] ?? null;

    if (!is_array($result)) {
        gameRpsAnswer($callback_id, 'خطا در خروج از بازی.', true);
        return true;
    }

    if (empty($result['ok'])) {
        $messages = [
            'not_found' => 'این بازی پیدا نشد.',
            'wrong_context' => 'این گزینه متعلق به این پیام یا گروه نیست.',
            'not_playing' => 'این بازی دیگر فعال نیست.',
            'not_player' => 'شما بازیکن این بازی نیستید.',
            'already_left' => 'شما قبلاً از بازی خارج شده‌اید.'
        ];

        gameRpsAnswer(
            $callback_id,
            $messages[$result['reason'] ?? ''] ?? 'امکان خروج وجود ندارد.',
            true
        );
        return true;
    }

    gameRpsAnswer($callback_id, 'خروج شما ثبت شد.');

    $response = gameRpsEditBoard($chat_id, $message_id, $result['game']);

    if (!gameRpsResponseOk($response)) {
        error_log('Game RPS exit edit error: ' . gameRpsResponseDescription($response));
    }

    return true;
}

?>
