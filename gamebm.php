<?php

function handleGameBmUpdate($update, $group)
{
    if (!is_array($update) || !is_array($group)) {
        return false;
    }

    if (!function_exists('gameGroupDataTransaction')) {
        error_log('Game BM: gameGroupDataTransaction is missing.');
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

    if ($data === 'game_bm') {
        return gameBmStartNewGame($callback, $group);
    }

    if (preg_match('/^bm_join:([a-f0-9]{12})$/', $data, $matches)) {
        return gameBmHandleJoin(
            $callback,
            $matches[1],
            $chat_id,
            $message_id,
            $user_id
        );
    }

    if (preg_match('/^bm_back:([a-f0-9]{12})$/', $data, $matches)) {
        return gameBmHandleBack(
            $callback,
            $matches[1],
            $chat_id,
            $message_id,
            $user_id
        );
    }

    if (preg_match('/^bm_exit:([a-f0-9]{12})$/', $data, $matches)) {
        return gameBmHandleExit(
            $callback,
            $matches[1],
            $chat_id,
            $message_id,
            $user_id
        );
    }

    if (preg_match('/^bm_pick:([a-f0-9]{12}):(\d{1,2})$/', $data, $matches)) {
        $index = (int)$matches[2];
        if ($index < 0 || $index > 17) {
            gameBmAnswer($callback_id, 'این خانه معتبر نیست.', true);
            return true;
        }

        return gameBmHandlePick(
            $callback,
            $matches[1],
            $index,
            $chat_id,
            $message_id,
            $user_id
        );
    }

    if (preg_match('/^bm_used:([a-f0-9]{12}):(\d{1,2})$/', $data, $matches)) {
        gameBmAnswer(
            $callback_id,
            'این گزینه قبلاً انتخاب شده است!',
            true
        );
        return true;
    }

    return false;
}

function gameBmAnswer($callback_id, $text, $show_alert = false)
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

function gameBmResponseOk($response)
{
    if (is_array($response)) {
        return !empty($response['ok']);
    }

    if (!is_string($response) || $response === '') {
        return false;
    }

    $decoded = json_decode($response, true);
    return is_array($decoded) && !empty($decoded['ok']);
}

function gameBmResponseDescription($response)
{
    if (is_array($response)) {
        return (string)($response['description'] ?? '');
    }

    $decoded = json_decode((string)$response, true);
    if (!is_array($decoded)) {
        return '';
    }

    return (string)($decoded['description'] ?? '');
}

function gameBmDecodeResponse($response)
{
    if (is_array($response)) {
        return $response;
    }

    if (!is_string($response) || $response === '') {
        return [];
    }

    $decoded = json_decode($response, true);
    return is_array($decoded) ? $decoded : [];
}

function gameBmGetIdentity($user)
{
    if (!is_array($user)) {
        $user = [];
    }

    $first = trim((string)($user['first_name'] ?? ''));
    $last = trim((string)($user['last_name'] ?? ''));
    $name = trim($first . ' ' . $last);

    if ($name === '') {
        $name = 'بازیکن ' . (int)($user['id'] ?? 0);
    }

    return ['name' => $name];
}

function gameBmPlayerHtml($user_id, $name)
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
// مثال: gameBmPlayerLabel(123, 'علی', 30) => 'علی (30 ⭐)'
// امتیاز کل همان points در bm_leaderboard است:
// هر الماس +10 و هر بمب ‎-20 (تا صفر).
function gameBmPlayerLabel($user_id, $name, $total_points)
{
    return gameBmPlayerHtml($user_id, $name) .
        ' (' . (int)$total_points . ' ⭐)';
}

// امتیاز کل یک بازیکن در یک گروه را از bm_leaderboard می‌خواند.
function gameBmLeaderboardPoints($group_id, $user_id)
{
    $key = (string)(int)$user_id;

    if ($key === '0') {
        return 0;
    }

    $result = gameGroupDataTransaction(
        (int)$group_id,
        function ($state) use ($key) {
            return (int)(
                $state['bm_leaderboard'][$key]['points'] ?? 0
            );
        }
    );

    return (int)($result['result'] ?? 0);
}

function gameBmGetGame($game_id, $group_id)
{
    $transaction = gameGroupDataTransaction((int)$group_id);

    if (empty($transaction['ok']) || !is_array($transaction['state'] ?? null)) {
        return null;
    }

    $state = $transaction['state'];

    if (!isset($state['bm_games']) || !is_array($state['bm_games'])) {
        return null;
    }

    if (!isset($state['bm_games'][$game_id]) || !is_array($state['bm_games'][$game_id])) {
        return null;
    }

    return $state['bm_games'][$game_id];
}

function gameBmNewPlayer($user_id, $name, $total_points = 0)
{
    return [
        'user_id' => (int)$user_id,
        'name' => (string)$name,
        'hearts' => 2,
        'status' => 'active', // active | exited | eliminated
        'earned_points' => 0,
        'penalty_points' => 0,
        'total_points' => (int)$total_points,
        'joined_at' => time()
    ];
}

function gameBmStartNewGame($callback, $group)
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
        gameBmAnswer($callback_id, 'اطلاعات شروع بازی معتبر نیست.', true);
        return true;
    }

    if ($invoker_id <= 0 || $user_id !== $invoker_id) {
        gameBmAnswer(
            $callback_id,
            'فقط سازنده این منو می‌تواند بازی را انتخاب کند.',
            true
        );
        return true;
    }

    try {
        $game_id = bin2hex(random_bytes(6));
    } catch (Throwable $e) {
        error_log('Game BM random ID error: ' . $e->getMessage());
        gameBmAnswer($callback_id, 'خطا در ساخت بازی؛ دوباره امتحان کنید.', true);
        return true;
    }

    $identity = gameBmGetIdentity($user);
    $now = time();

    // امتیاز کل بازیکن از بازی‌های قبلی در همین گروه،
    // تا از همان اول جلوی اسمش نشان داده شود.
    $player1_total = gameBmLeaderboardPoints($chat_id, $user_id);

    $game = [
        'game_id' => $game_id,
        'group_id' => $chat_id,
        'message_id' => $message_id,
        'owner_id' => $invoker_id,

        'player1' => gameBmNewPlayer($user_id, $identity['name'], $player1_total),
        'player2' => null,

        'tiles' => array_fill(0, 18, 0),
        'revealed' => array_fill(0, 18, false),
        'revealed_by' => array_fill(0, 18, 0),
        'bomb_count' => 4,

        'turn' => 1,
        'status' => 'waiting', // waiting | playing | finished | returned
        'created_at' => $now,
        'joined_at' => 0,
        'finished_at' => 0,

        'events' => [],
        'finish_reason' => '',
        'moves' => 0
    ];

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $game) {
            if (!isset($state['bm_games']) || !is_array($state['bm_games'])) {
                $state['bm_games'] = [];
            }

            if (isset($state['bm_games'][$game_id])) {
                return false;
            }

            $state['bm_games'][$game_id] = $game;
            return true;
        }
    );

    if (empty($transaction['ok']) || ($transaction['result'] ?? false) !== true) {
        gameBmAnswer($callback_id, 'ذخیره اطلاعات بازی ناموفق بود.', true);
        return true;
    }

    gameBmAnswer($callback_id, 'بازی الماس یا بمب ساخته شد؛ منتظر بازیکن دوم باشید.');

    $response = gameBmEditBoard($chat_id, $message_id, $game);

    if (!gameBmResponseOk($response)) {
        error_log('Game BM start edit error: ' . gameBmResponseDescription($response));

        gameGroupDataTransaction(
            $chat_id,
            function (&$state) use ($game_id) {
                if (isset($state['bm_games'][$game_id])) {
                    $state['bm_games'][$game_id]['status'] = 'error';
                }
                return true;
            }
        );
    }

    return true;
}

function gameBmGenerateTiles()
{
    $tiles = array_fill(0, 18, 1); // ابتدا همه الماس هستند
    $positions = range(0, 17);

    for ($i = 0; $i < 4; $i++) {
        $j = random_int($i, 17);
        $temp = $positions[$i];
        $positions[$i] = $positions[$j];
        $positions[$j] = $temp;
        $tiles[$positions[$i]] = 2;
    }

    return $tiles;
}

function gameBmAddEvent(&$game, $event)
{
    if (!isset($game['events']) || !is_array($game['events'])) {
        $game['events'] = [];
    }

    $game['events'][] = (string)$event;

    if (count($game['events']) > 8) {
        $game['events'] = array_slice($game['events'], -8);
    }
}

function gameBmIsPlayerActive($game, $number)
{
    $key = ($number === 1) ? 'player1' : 'player2';
    return (
        isset($game[$key]) &&
        is_array($game[$key]) &&
        ($game[$key]['status'] ?? '') === 'active' &&
        (int)($game[$key]['hearts'] ?? 0) > 0
    );
}

function gameBmChooseActiveTurn($game, $preferred)
{
    $preferred = ((int)$preferred === 2) ? 2 : 1;
    $other = ($preferred === 1) ? 2 : 1;

    if (gameBmIsPlayerActive($game, $preferred)) {
        return $preferred;
    }

    if (gameBmIsPlayerActive($game, $other)) {
        return $other;
    }

    return 0;
}

function gameBmFinishIfNobodyActive(&$game)
{
    $active1 = gameBmIsPlayerActive($game, 1);
    $active2 = gameBmIsPlayerActive($game, 2);

    if (!$active1 && !$active2) {
        if (($game['status'] ?? '') !== 'finished') {
            $game['status'] = 'finished';
            $game['finished_at'] = time();
            $game['finish_reason'] = 'both_inactive';
            // رویداد جدا اضافه نمی‌کنیم: متن پایان بازی یک بار
            // در انتهای gameBmBuildText نوشته می‌شود، وگرنه
            // جمله «بازی به پایان رسید!» دو بار دیده می‌شود.
        }

        return true;
    }

    return false;
}

function gameBmHandleJoin($callback, $game_id, $chat_id, $message_id, $user_id)
{
    $callback_id = (string)($callback['id'] ?? '');
    $identity = gameBmGetIdentity($callback['from'] ?? []);

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $chat_id, $message_id, $user_id, $identity) {
            if (!isset($state['bm_games'][$game_id]) || !is_array($state['bm_games'][$game_id])) {
                return ['ok' => false, 'reason' => 'not_found'];
            }

            $game = &$state['bm_games'][$game_id];

            if (
                (int)($game['group_id'] ?? 0) !== $chat_id ||
                (int)($game['message_id'] ?? 0) !== $message_id
            ) {
                return ['ok' => false, 'reason' => 'wrong_context'];
            }

            if (($game['status'] ?? '') !== 'waiting') {
                return ['ok' => false, 'reason' => 'not_waiting'];
            }

            $player1_id = (int)($game['player1']['user_id'] ?? 0);

            if ($user_id === $player1_id) {
                return ['ok' => false, 'reason' => 'self_join'];
            }

            if (!empty($game['player2'])) {
                return ['ok' => false, 'reason' => 'game_full'];
            }

            $player2_total = (int)(
                $state['bm_leaderboard'][(string)$user_id]['points'] ?? 0
            );

            $game['player2'] = gameBmNewPlayer(
                $user_id,
                $identity['name'],
                $player2_total
            );

            // امتیاز کل بازیکن اول را هم تازه کن،
            // چون ممکن است از بازی‌های قبلی تغییر کرده باشد.
            if (isset($game['player1']) && is_array($game['player1'])) {
                $player1_id = (int)($game['player1']['user_id'] ?? 0);

                if ($player1_id > 0) {
                    $game['player1']['total_points'] = (int)(
                        $state['bm_leaderboard'][(string)$player1_id]['points'] ?? 0
                    );
                }
            }

            $game['tiles'] = gameBmGenerateTiles();
            $game['revealed'] = array_fill(0, 18, false);
            $game['revealed_by'] = array_fill(0, 18, 0);
            $game['joined_at'] = time();
            $game['status'] = 'playing';
            $game['turn'] = 1;

            return ['ok' => true, 'game' => $game];
        }
    );

    $result = $transaction['result'] ?? null;

    if (!is_array($result)) {
        gameBmAnswer($callback_id, 'خطا در ثبت عضویت.', true);
        return true;
    }

    if (empty($result['ok'])) {
        $messages = [
            'not_found' => 'این بازی پیدا نشد.',
            'wrong_context' => 'این دکمه متعلق به این پیام یا گروه نیست.',
            'not_waiting' => 'این بازی دیگر در انتظار بازیکن نیست.',
            'self_join' => 'سازنده بازی نمی‌تواند حریف خودش باشد.',
            'game_full' => 'بازیکن دوم قبلاً وارد بازی شده است.'
        ];

        gameBmAnswer(
            $callback_id,
            $messages[$result['reason'] ?? ''] ?? 'امکان عضویت وجود ندارد.',
            true
        );
        return true;
    }

    gameBmAnswer($callback_id, 'عضویت ثبت شد! بازی شروع شد.');

    $response = gameBmEditBoard($chat_id, $message_id, $result['game']);

    if (!gameBmResponseOk($response)) {
        error_log('Game BM join edit error: ' . gameBmResponseDescription($response));
    }

    return true;
}

function gameBmBuildText($game)
{
    $p1 = $game['player1'] ?? [];
    $p2 = $game['player2'] ?? null;

    $p1_id = (int)($p1['user_id'] ?? 0);
    $p1_name_raw = (string)($p1['name'] ?? 'بازیکن اول');
    // امتیاز کل از bm_leaderboard؛ برای بازی‌های قدیمی که
    // total_points ندارند، امتیاز خالص همین بازی نشان داده می‌شود.
    $p1_total = isset($p1['total_points'])
        ? (int)$p1['total_points']
        : max(
            0,
            (int)($p1['earned_points'] ?? 0) -
            (int)($p1['penalty_points'] ?? 0)
        );
    $p1_name = gameBmPlayerLabel($p1_id, $p1_name_raw, $p1_total);
    $p1_heart_count = max(0, min(2, (int)($p1['hearts'] ?? 2)));
    $p1_hearts = ($p1_heart_count > 0) ? str_repeat('❤', $p1_heart_count) : '0';

    $text = "<b>🎮 بازی الماس یا بمب</b>\n\n";
    $text .= "🔴 بازیکن اول:({$p1_hearts}) {$p1_name}\n";

    if (is_array($p2)) {
        $p2_id = (int)($p2['user_id'] ?? 0);
        $p2_name_raw = (string)($p2['name'] ?? 'بازیکن دوم');
        $p2_total = isset($p2['total_points'])
            ? (int)$p2['total_points']
            : max(
                0,
                (int)($p2['earned_points'] ?? 0) -
                (int)($p2['penalty_points'] ?? 0)
            );
        $p2_name = gameBmPlayerLabel($p2_id, $p2_name_raw, $p2_total);
        $p2_heart_count = max(0, min(2, (int)($p2['hearts'] ?? 2)));
        $p2_hearts = ($p2_heart_count > 0) ? str_repeat('❤', $p2_heart_count) : '0';
        $text .= "🔵 بازیکن دوم:({$p2_hearts}) {$p2_name}\n\n";
    } else {
        $text .= "🔵 بازیکن دوم:(❤❤) <i>در انتظار ورود حریف...</i>\n\n";
    }

    $status = (string)($game['status'] ?? 'waiting');

    if ($status === 'waiting') {
        $text .= '⏳ منتظر بازیکن دوم هستیم؛ برای شروع، یک نفر روی «عضو شدن» بزند.';
        return $text;
    }

    if ($status === 'returned') {
        return $text . '<b>این بازی به منوی انتخاب بازی برگشته است.</b>';
    }

    if ($status === 'error') {
        return $text . '<b>⚠️ ساخت بازی با خطا روبه‌رو شد.</b>';
    }

    if ($status === 'playing') {
        $turn = (int)($game['turn'] ?? 1);

        if ($turn === 1) {
            $text .= "⏱ نوبت بازیکن اول : {$p1_name}";
        } elseif (is_array($p2)) {
            $p2_name = gameBmPlayerLabel(
                (int)($p2['user_id'] ?? 0),
                (string)($p2['name'] ?? 'بازیکن دوم'),
                $p2_total ?? 0
            );
            $text .= "⏱ نوبت بازیکن دوم : {$p2_name}";
        }
    }

    $events = $game['events'] ?? [];
    if (is_array($events) && !empty($events)) {
        $text .= "\n" . implode("\n", $events);
    }

    if ($status === 'finished') {
        $text .= "\n<b>🏁 بازی به پایان رسید!</b>";
    }

    return $text;
}

function gameBmBuildKeyboard($game)
{
    $status = (string)($game['status'] ?? 'waiting');

    if ($status === 'finished' || $status === 'returned' || $status === 'error') {
        return ['inline_keyboard' => []];
    }

    $tiles = $game['tiles'] ?? array_fill(0, 18, 0);
    $revealed = $game['revealed'] ?? array_fill(0, 18, false);
    $revealed_by = $game['revealed_by'] ?? array_fill(0, 18, 0);
    $game_id = (string)($game['game_id'] ?? '');

    $keyboard = [];
    $blank = "\u{2800}";

    for ($row_index = 0; $row_index < 6; $row_index++) {
        $row = [];

        for ($column_index = 0; $column_index < 3; $column_index++) {
            $index = ($row_index * 3) + $column_index;
            $value = (int)($tiles[$index] ?? 0);

            if (empty($revealed[$index])) {
                $row[] = [
                    'text' => $blank,
                    'callback_data' => 'bm_pick:' . $game_id . ':' . $index
                ];
                continue;
            }

            $picker = (int)($revealed_by[$index] ?? 0);
            $style = ($picker === 1) ? 'danger' : 'primary';
            $emoji = ($value === 2) ? '💣' : '💎';

            $row[] = [
                'text' => $emoji,
                'callback_data' => 'bm_used:' . $game_id . ':' . $index,
                'style' => $style
            ];
        }

        $keyboard[] = $row;
    }

    if ($status === 'waiting') {
        $keyboard[] = [
            [
                'text' => '🟢 عضو شدن',
                'callback_data' => 'bm_join:' . $game_id,
                'style' => 'success'
            ]
        ];

        $keyboard[] = [
            [
                'text' => '🔴 بازگشت',
                'callback_data' => 'bm_back:' . $game_id,
                'style' => 'danger'
            ]
        ];
    } elseif ($status === 'playing') {
        $keyboard[] = [
            [
                'text' => '🔴 تا اینجا کافیه!',
                'callback_data' => 'bm_exit:' . $game_id,
                'style' => 'danger'
            ]
        ];
    }

    return ['inline_keyboard' => $keyboard];
}

function gameBmEditBoard($chat_id, $message_id, $game)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    return makeCurl(
        API_URL . 'editMessageText',
        [
            'chat_id' => (int)$chat_id,
            'message_id' => (int)$message_id,
            'text' => gameBmBuildText($game),
            'parse_mode' => 'HTML',
            'reply_markup' => json_encode(
                gameBmBuildKeyboard($game),
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            )
        ]
    );
}

function gameBmRestoreGameMenu($chat_id, $message_id)
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

function gameBmHandleBack($callback, $game_id, $chat_id, $message_id, $user_id)
{
    $callback_id = (string)($callback['id'] ?? '');

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $chat_id, $message_id, $user_id) {
            if (!isset($state['bm_games'][$game_id]) || !is_array($state['bm_games'][$game_id])) {
                return ['ok' => false, 'reason' => 'not_found'];
            }

            $game = &$state['bm_games'][$game_id];

            if (
                (int)($game['group_id'] ?? 0) !== $chat_id ||
                (int)($game['message_id'] ?? 0) !== $message_id
            ) {
                return ['ok' => false, 'reason' => 'wrong_context'];
            }

            if ((int)($game['owner_id'] ?? 0) !== $user_id) {
                return ['ok' => false, 'reason' => 'not_owner'];
            }

            if (
                ($game['status'] ?? '') !== 'waiting' ||
                !empty($game['player2'])
            ) {
                return ['ok' => false, 'reason' => 'already_started'];
            }

            $game['status'] = 'returned';
            $game['returned_at'] = time();

            return ['ok' => true];
        }
    );

    $result = $transaction['result'] ?? null;
    if (!is_array($result)) {
        gameBmAnswer($callback_id, 'خطا در بازگشت به منو.', true);
        return true;
    }

    if (empty($result['ok'])) {
        $messages = [
            'not_found' => 'این بازی پیدا نشد.',
            'wrong_context' => 'این دکمه متعلق به این پیام نیست.',
            'not_owner' => 'فقط سازنده این بازی می‌تواند بازگشت بزند.',
            'already_started' => 'بازی شروع شده و دیگر امکان بازگشت وجود ندارد.'
        ];

        gameBmAnswer(
            $callback_id,
            $messages[$result['reason'] ?? ''] ?? 'امکان بازگشت وجود ندارد.',
            true
        );
        return true;
    }

    gameBmAnswer($callback_id, 'بازگشت به منوی انتخاب بازی.');

    $response = gameBmRestoreGameMenu($chat_id, $message_id);
    if (!gameBmResponseOk($response)) {
        error_log('Game BM back error: ' . gameBmResponseDescription($response));
    }

    return true;
}

function gameBmChangeLeaderboard(&$state, $user_id, $name, $delta)
{
    if (!isset($state['bm_leaderboard']) || !is_array($state['bm_leaderboard'])) {
        $state['bm_leaderboard'] = [];
    }

    $key = (string)(int)$user_id;
    if ($key === '0') {
        return 0;
    }

    $record = $state['bm_leaderboard'][$key] ?? [];
    if (!is_array($record)) {
        $record = [];
    }

    $record['user_id'] = (int)$user_id;
    $record['name'] = (string)$name;
    $record['points'] = max(0, (int)($record['points'] ?? 0));
    $record['diamonds'] = max(0, (int)($record['diamonds'] ?? 0));
    $record['bombs'] = max(0, (int)($record['bombs'] ?? 0));
    $record['updated_at'] = time();

    if ($delta > 0) {
        $record['points'] += $delta;
        $record['diamonds']++;
        $changed = $delta;
    } elseif ($delta < 0) {
        $changed = min(abs($delta), $record['points']);
        $record['points'] -= $changed;
        $record['bombs']++;
    } else {
        $changed = 0;
    }

    $state['bm_leaderboard'][$key] = $record;

    return $changed;
}

function gameBmHandlePick($callback, $game_id, $index, $chat_id, $message_id, $user_id)
{
    $callback_id = (string)($callback['id'] ?? '');

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $index, $chat_id, $message_id, $user_id) {
            if (!isset($state['bm_games'][$game_id]) || !is_array($state['bm_games'][$game_id])) {
                return ['ok' => false, 'reason' => 'not_found'];
            }

            $game = &$state['bm_games'][$game_id];

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

            if (
                !isset($game['tiles'][$index]) ||
                !isset($game['revealed'][$index]) ||
                !isset($game['revealed_by'][$index])
            ) {
                return ['ok' => false, 'reason' => 'bad_index'];
            }

            if (!empty($game['revealed'][$index])) {
                return ['ok' => false, 'reason' => 'used'];
            }

            $turn = (int)($game['turn'] ?? 0);
            $player_key = ($turn === 1) ? 'player1' : 'player2';
            $other_key = ($turn === 1) ? 'player2' : 'player1';

            if (!isset($game[$player_key]) || !is_array($game[$player_key])) {
                return ['ok' => false, 'reason' => 'invalid_player'];
            }

            $player = &$game[$player_key];
            $other = &$game[$other_key];

            if ((int)($player['user_id'] ?? 0) !== $user_id) {
                if (
                    isset($game['player1']['user_id']) &&
                    (int)$game['player1']['user_id'] === $user_id &&
                    !gameBmIsPlayerActive($game, 1)
                ) {
                    return ['ok' => false, 'reason' => 'not_active'];
                }
                if (
                    isset($game['player2']['user_id']) &&
                    (int)$game['player2']['user_id'] === $user_id &&
                    !gameBmIsPlayerActive($game, 2)
                ) {
                    return ['ok' => false, 'reason' => 'not_active'];
                }
                return ['ok' => false, 'reason' => 'not_turn'];
            }

            if (($player['status'] ?? '') !== 'active' || (int)($player['hearts'] ?? 0) <= 0) {
                return ['ok' => false, 'reason' => 'not_active'];
            }

            $tile_value = (int)$game['tiles'][$index];
            $game['revealed'][$index] = true;
            $game['revealed_by'][$index] = $turn;
            $game['moves'] = (int)($game['moves'] ?? 0) + 1;

            $user_name = (string)($player['name'] ?? 'بازیکن');
            $user_id_for_score = (int)($player['user_id'] ?? 0);

            if ($tile_value === 1) {
                $player['earned_points'] = (int)($player['earned_points'] ?? 0) + 10;
                $credited = gameBmChangeLeaderboard(
                    $state,
                    $user_id_for_score,
                    $user_name,
                    10
                );

                $preferred = ($turn === 1) ? 2 : 1;
                $game['turn'] = gameBmChooseActiveTurn($game, $preferred);

                $notice = 'diamond';
                $notice_points = $credited;
            } elseif ($tile_value === 2) {
                $player['hearts'] = max(0, (int)($player['hearts'] ?? 0) - 1);

                $deducted = gameBmChangeLeaderboard(
                    $state,
                    $user_id_for_score,
                    $user_name,
                    -20
                );

                $player['penalty_points'] = (int)($player['penalty_points'] ?? 0) + $deducted;

                gameBmAddEvent(
                    $game,
                    '💥بوووومممم💣 ( ⭐' . $deducted . ' - )'
                );

                if ((int)$player['hearts'] <= 0) {
                    $player['hearts'] = 0;
                    $player['status'] = 'eliminated';

                    $safe_name = htmlspecialchars(
                        $user_name,
                        ENT_QUOTES | ENT_SUBSTITUTE,
                        'UTF-8'
                    );

                    gameBmAddEvent(
                        $game,
                        '💀 بازیکن ' . $safe_name . ' تمام قلب‌هایش را از دست داد و از بازی حذف شد!'
                    );

                    $game['turn'] = gameBmChooseActiveTurn(
                        $game,
                        ($turn === 1) ? 2 : 1
                    );
                } else {
                    $game['turn'] = $turn;
                }

                $notice = 'bomb';
                $notice_points = $deducted;
            } else {
                return ['ok' => false, 'reason' => 'bad_tile'];
            }

            // امتیاز کل هر دو بازیکن را از bm_leaderboard تازه کن،
            // تا روی صفحه بازی همان عدد جدید نشان داده شود.
            $player['total_points'] = (int)(
                $state['bm_leaderboard'][(string)$user_id_for_score]['points'] ?? 0
            );

            if (is_array($other)) {
                $other_id = (int)($other['user_id'] ?? 0);

                if ($other_id > 0) {
                    $other['total_points'] = (int)(
                        $state['bm_leaderboard'][(string)$other_id]['points'] ?? 0
                    );
                }
            }

            if (gameBmIsPlayerActive($game, 1) && !gameBmIsPlayerActive($game, 2)) {
                $game['turn'] = 1;
            } elseif (!gameBmIsPlayerActive($game, 1) && gameBmIsPlayerActive($game, 2)) {
                $game['turn'] = 2;
            }

            $finished = gameBmFinishIfNobodyActive($game);

            if (
                !$finished &&
                !in_array(false, $game['revealed'], true)
            ) {
                $game['status'] = 'finished';
                $game['finished_at'] = time();
                $game['finish_reason'] = 'all_tiles_opened';
                // فقط دلیل پایان را می‌نویسیم؛ جمله «بازی به پایان رسید!»
                // یک بار در انتهای gameBmBuildText می‌آید.
                gameBmAddEvent($game, '<b>🏁 همه گزینه‌ها باز شدند!</b>');
                $finished = true;
            }

            return [
                'ok' => true,
                'game' => $game,
                'notice' => $notice,
                'notice_points' => $notice_points,
                'finished' => $finished
            ];
        }
    );

    $result = $transaction['result'] ?? null;

    if (!is_array($result)) {
        gameBmAnswer($callback_id, 'خطا در پردازش انتخاب.', true);
        return true;
    }

    if (empty($result['ok'])) {
        $messages = [
            'not_found' => 'این بازی پیدا نشد.',
            'wrong_context' => 'این گزینه متعلق به این پیام یا گروه نیست.',
            'wait_join' => 'ابتدا بازیکن دوم باید عضو شود.',
            'finished' => 'این بازی به پایان رسیده است.',
            'not_playing' => 'این بازی در حال حاضر فعال نیست.',
            'bad_index' => 'شماره خانه معتبر نیست.',
            'used' => 'این گزینه قبلاً انتخاب شده است!',
            'invalid_player' => 'اطلاعات بازیکن معتبر نیست.',
            'not_active' => 'شما از این بازی خارج شده‌اید یا حذف شده‌اید.',
            'not_turn' => 'اکنون نوبت شما نیست.',
            'bad_tile' => 'محتوای این خانه معتبر نیست.'
        ];

        gameBmAnswer(
            $callback_id,
            $messages[$result['reason'] ?? ''] ?? 'انتخاب مجاز نیست.',
            true
        );
        return true;
    }

    if (($result['notice'] ?? '') === 'diamond') {
        gameBmAnswer($callback_id, '💎 الماس پیدا کردی! 10 امتیاز گرفتی.');
    } else {
        gameBmAnswer($callback_id, '💥 بمب منفجر شد! ' . (int)($result['notice_points'] ?? 0) . ' امتیاز کسر شد.', true);
    }

    $response = gameBmEditBoard($chat_id, $message_id, $result['game']);

    if (!gameBmResponseOk($response)) {
        error_log('Game BM board edit error: ' . gameBmResponseDescription($response));
    }

    return true;
}

function gameBmHandleExit($callback, $game_id, $chat_id, $message_id, $user_id)
{
    $callback_id = (string)($callback['id'] ?? '');

    $transaction = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($game_id, $chat_id, $message_id, $user_id) {
            if (!isset($state['bm_games'][$game_id]) || !is_array($state['bm_games'][$game_id])) {
                return ['ok' => false, 'reason' => 'not_found'];
            }

            $game = &$state['bm_games'][$game_id];

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
            $player = &$game[$key];

            if (($player['status'] ?? '') !== 'active') {
                return ['ok' => false, 'reason' => 'already_left'];
            }

            $player['status'] = 'exited';
            $player['exited_at'] = time();

            $safe_name = htmlspecialchars(
                (string)($player['name'] ?? 'بازیکن'),
                ENT_QUOTES | ENT_SUBSTITUTE,
                'UTF-8'
            );

            $saved_points = max(0,
                (int)($player['earned_points'] ?? 0) -
                (int)($player['penalty_points'] ?? 0)
            );

            gameBmAddEvent(
                $game,
                '🔔بازیکن ' . $safe_name . ' از بازی خارج شد و ' . $saved_points . ' امتیاز ⭐ سیو کرد!'
            );

            if ((int)($game['turn'] ?? 0) === $player_number) {
                $game['turn'] = gameBmChooseActiveTurn(
                    $game,
                    ($player_number === 1) ? 2 : 1
                );
            }

            if (gameBmIsPlayerActive($game, 1) && !gameBmIsPlayerActive($game, 2)) {
                $game['turn'] = 1;
            } elseif (!gameBmIsPlayerActive($game, 1) && gameBmIsPlayerActive($game, 2)) {
                $game['turn'] = 2;
            }

            $finished = gameBmFinishIfNobodyActive($game);

            return [
                'ok' => true,
                'game' => $game,
                'finished' => $finished
            ];
        }
    );

    $result = $transaction['result'] ?? null;

    if (!is_array($result)) {
        gameBmAnswer($callback_id, 'خطا در خروج از بازی.', true);
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

        gameBmAnswer(
            $callback_id,
            $messages[$result['reason'] ?? ''] ?? 'امکان خروج وجود ندارد.',
            true
        );
        return true;
    }

    gameBmAnswer($callback_id, 'خروج شما ثبت شد و امتیازها ذخیره شدند.');

    $response = gameBmEditBoard($chat_id, $message_id, $result['game']);

    if (!gameBmResponseOk($response)) {
        error_log('Game BM exit edit error: ' . gameBmResponseDescription($response));
    }

    return true;
}

?>
