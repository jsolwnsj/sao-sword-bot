<?php

// ============================================================
// GAME MODULE
// ============================================================

// تنظیمات

if (!defined('GAME_ADD_GROUP_URL')) {
    define(
        'GAME_ADD_GROUP_URL',
        'https://t.me/Shadi8864_bot?startgroup=new'
    );
}

if (!defined('GAME_STATE_FILE')) {
    define(
        'GAME_STATE_FILE',
        __DIR__ . '/game_groups.json'
    );
}

// پوشه دیتابیس مستقل گروه‌ها

if (!defined('GAME_GROUP_DATA_DIR')) {
    define(
        'GAME_GROUP_DATA_DIR',
        __DIR__ . '/game_group_databases'
    );
}


// ============================================================
// تابع اصلی ماژول Game
// ============================================================

function handleGameUpdate($update)
{
    if (!is_array($update)) {
        return false;
    }

    if (isset($update['my_chat_member'])) {
        return gameHandleMembershipUpdate(
            $update['my_chat_member']
        );
    }

    if (isset($update['callback_query'])) {
        return gameHandleCallback(
            $update,
            $update['callback_query']
        );
    }

    if (isset($update['message'])) {
        return gameHandleGroupMessage(
            $update['message']
        );
    }

    return false;
}


// ============================================================
// دریافت مسیر دیتابیس اختصاصی گروه
// ============================================================

function gameGetGroupDatabasePath($group_id)
{
    $group_id = (int)$group_id;

    if ($group_id === 0) {
        return false;
    }

    $prefix = ($group_id < 0) ? 'm' : 'p';

    $safe_id = $prefix . abs($group_id);

    return GAME_GROUP_DATA_DIR .
        '/group_' .
        $safe_id .
        '.json';
}


// ============================================================
// تراکنش دیتابیس اختصاصی هر گروه
// ============================================================

function gameGroupDataTransaction(
    $group_id,
    $callback = null
) {

    $group_id = (int)$group_id;

    if ($group_id === 0) {
        return [
            'state' => [],
            'result' => null,
            'ok' => false
        ];
    }

    if (
        !is_dir(GAME_GROUP_DATA_DIR) &&
        !@mkdir(
            GAME_GROUP_DATA_DIR,
            0750,
            true
        )
    ) {

        error_log(
            'Game: Cannot create group database directory.'
        );

        return [
            'state' => [],
            'result' => null,
            'ok' => false
        ];
    }

    $file = gameGetGroupDatabasePath(
        $group_id
    );

    if ($file === false) {
        return [
            'state' => [],
            'result' => null,
            'ok' => false
        ];
    }

    $handle = @fopen($file, 'c+');

    if ($handle === false) {

        error_log(
            'Game: Cannot open group database: ' . $group_id
        );

        return [
            'state' => [],
            'result' => null,
            'ok' => false
        ];
    }

    if (!flock($handle, LOCK_EX)) {

        fclose($handle);

        return [
            'state' => [],
            'result' => null,
            'ok' => false
        ];
    }

    rewind($handle);

    $contents = stream_get_contents($handle);

    $default_state = [
        'group_id' => $group_id,
        'xo_games' => [],
        'xo_leaderboard' => []
    ];

    if (
        $contents === false ||
        trim($contents) === ''
    ) {

        $state = $default_state;

    } else {

        $state = json_decode(
            $contents,
            true
        );

        if (!is_array($state)) {

            error_log(
                'Game: Invalid group database JSON: ' . $group_id
            );

            flock($handle, LOCK_UN);
            fclose($handle);

            return [
                'state' => $default_state,
                'result' => null,
                'ok' => false
            ];
        }
    }

    if (!isset($state['group_id'])) {
        $state['group_id'] = $group_id;
    }

    if (
        !isset($state['xo_games']) ||
        !is_array($state['xo_games'])
    ) {
        $state['xo_games'] = [];
    }

    if (
        !isset($state['xo_leaderboard']) ||
        !is_array($state['xo_leaderboard'])
    ) {
        $state['xo_leaderboard'] = [];
    }

    $callback_result = null;

    $callback_failed = false;

    try {

        if (is_callable($callback)) {
            $callback_result = $callback($state);
        }

    } catch (Throwable $e) {

        $callback_failed = true;

        error_log(
            'Group database transaction error: ' .
            $e->getMessage()
        );
    }

    if ($callback_failed) {

        flock($handle, LOCK_UN);
        fclose($handle);

        return [
            'state' => $state,
            'result' => null,
            'ok' => false
        ];
    }

    $json = json_encode(
        $state,
        JSON_UNESCAPED_UNICODE |
        JSON_UNESCAPED_SLASHES |
        JSON_PRETTY_PRINT
    );

    $write_ok = false;

    if ($json !== false) {

        rewind($handle);

        if (ftruncate($handle, 0)) {

            $data_to_write = $json . PHP_EOL;

            $length = strlen($data_to_write);

            $written = 0;

            while ($written < $length) {

                $chunk = fwrite(
                    $handle,
                    substr(
                        $data_to_write,
                        $written
                    )
                );

                if ($chunk === false || $chunk === 0) {
                    break;
                }

                $written += $chunk;
            }

            if ($written === $length) {
                $write_ok = fflush($handle);
            }
        }
    }

    flock($handle, LOCK_UN);

    fclose($handle);

    @chmod($file, 0600);

    if (!$write_ok) {

        error_log(
            'Game: Group database save error: ' . $group_id
        );
    }

    return [
        'state' => $state,
        'result' => $callback_result,
        'ok' => $write_ok
    ];
}


// ============================================================
// مدیریت فایل اطلاعات عمومی گروه‌ها
// ============================================================

function gameStateTransaction($callback = null)
{
    $file = GAME_STATE_FILE;

    $default_state = [
        'groups' => [],
        'users' => [],
        'game_sessions' => [],
        'xo_games' => [],
        'xo_leaderboard' => []
    ];

    $handle = @fopen($file, 'c+');

    if ($handle === false) {

        error_log(
            'Game: Cannot open state file.'
        );

        return [
            'state' => $default_state,
            'result' => null,
            'ok' => false
        ];
    }

    if (!flock($handle, LOCK_EX)) {

        fclose($handle);

        return [
            'state' => $default_state,
            'result' => null,
            'ok' => false
        ];
    }

    rewind($handle);

    $contents = stream_get_contents($handle);

    $state = json_decode(
        $contents !== false ? $contents : '',
        true
    );

    if (!is_array($state)) {
        $state = $default_state;
    }

    foreach (
        [
            'groups',
            'users',
            'game_sessions',
            'xo_games',
            'xo_leaderboard'
        ]
        as $key
    ) {

        if (
            !isset($state[$key]) ||
            !is_array($state[$key])
        ) {
            $state[$key] = [];
        }
    }

    $callback_result = null;

    try {

        if (is_callable($callback)) {
            $callback_result = $callback($state);
        }

    } catch (Throwable $e) {

        error_log(
            'Game state error: ' .
            $e->getMessage()
        );
    }

    $json = json_encode(
        $state,
        JSON_UNESCAPED_UNICODE |
        JSON_UNESCAPED_SLASHES |
        JSON_PRETTY_PRINT
    );

    $write_ok = false;

    if ($json !== false) {

        rewind($handle);

        if (ftruncate($handle, 0)) {

            $data_to_write = $json . PHP_EOL;

            $length = strlen($data_to_write);

            $written = 0;

            while ($written < $length) {

                $chunk = fwrite(
                    $handle,
                    substr(
                        $data_to_write,
                        $written
                    )
                );

                if ($chunk === false || $chunk === 0) {
                    break;
                }

                $written += $chunk;
            }

            if ($written === $length) {
                $write_ok = fflush($handle);
            }
        }
    }

    flock($handle, LOCK_UN);

    fclose($handle);

    @chmod($file, 0600);

    if (!$write_ok) {

        error_log(
            'Game: Could not save state.'
        );
    }

    return [
        'state' => $state,
        'result' => $callback_result,
        'ok' => $write_ok
    ];
}


// ============================================================
// ذخیره صفحه فعلی کاربر
// ============================================================

function gameSaveUserScreen(
    $user_id,
    $chat_id,
    $message_id,
    $screen
) {

    $user_key = (string)$user_id;

    return gameStateTransaction(

        function (&$state) use (
            $user_key,
            $chat_id,
            $message_id,
            $screen
        ) {

            if (!isset($state['users'][$user_key])) {
                $state['users'][$user_key] = [];
            }

            $state['users'][$user_key]['user_id'] =
                (int)$user_key;

            $state['users'][$user_key]['private_chat_id'] =
                (int)$chat_id;

            $state['users'][$user_key]['screen_message_id'] =
                (int)$message_id;

            $state['users'][$user_key]['screen'] =
                $screen;

            $state['users'][$user_key]['updated_at'] =
                time();

            return true;
        }
    );
}


// ============================================================
// دریافت اطلاعات گروه
// ============================================================

function gameGetGroupInfo($group_id)
{
    $result = gameStateTransaction();

    $state = $result['state'];

    $group_key = (string)$group_id;

    if (
        !isset($state['groups'][$group_key]) ||
        !is_array($state['groups'][$group_key])
    ) {
        return null;
    }

    return $state['groups'][$group_key];
}


// ============================================================
// دریافت گروه‌های فعال کاربر
// ============================================================

function gameGetActiveGroups($user_id)
{
    $result = gameStateTransaction();

    $state = $result['state'];

    $active_groups = [];

    foreach ($state['groups'] as $group) {

        if (!is_array($group)) {
            continue;
        }

        $owner_id = (int)(
            $group['owner_id'] ?? 0
        );

        $active = !empty(
            $group['active']
        );

        $status = $group['status'] ?? '';

        if (
            $owner_id === (int)$user_id &&
            $active &&
            $status === 'administrator'
        ) {

            $active_groups[] = $group;
        }
    }

    usort(
        $active_groups,
        function ($a, $b) {

            return
                (int)($b['updated_at'] ?? 0)
                <=>
                (int)($a['updated_at'] ?? 0);
        }
    );

    return $active_groups;
}


// ============================================================
// بررسی وجود گروه فعال
// ============================================================

function gameHasActiveGroups($user_id)
{
    return count(
        gameGetActiveGroups($user_id)
    ) > 0;
}


// ============================================================
// بررسی مالکیت گروه
// مخصوص پنل خصوصی مدیریت
// ============================================================

function gameGetUserActiveGroup(
    $user_id,
    $group_id
) {

    $group = gameGetGroupInfo($group_id);

    if (!is_array($group)) {
        return null;
    }

    if (
        (int)($group['owner_id'] ?? 0) !==
        (int)$user_id
    ) {
        return null;
    }

    if (empty($group['active'])) {
        return null;
    }

    if (($group['status'] ?? '') !== 'administrator') {
        return null;
    }

    return $group;
}


// ============================================================
// بررسی فعال بودن گروه بدون محدودیت مالکیت
// ============================================================

function gameIsGroupActive($group_id)
{
    $group = gameGetGroupInfo($group_id);

    if (!is_array($group)) {
        return false;
    }

    return (
        !empty($group['active']) &&
        ($group['status'] ?? '') === 'administrator'
    );
}


// ============================================================
// کوتاه کردن نام گروه
// ============================================================

function gameButtonGroupTitle($title)
{
    $title = trim((string)$title);

    if ($title === '') {
        return 'گروه بدون نام';
    }

    $characters = preg_split(
        '//u',
        $title,
        -1,
        PREG_SPLIT_NO_EMPTY
    );

    if (!is_array($characters)) {
        return 'گروه';
    }

    if (count($characters) > 55) {

        $title = implode(
            '',
            array_slice($characters, 0, 52)
        ) . '...';
    }

    return $title;
}


// ============================================================
// کیبورد منوی Game
// ============================================================

function gameHomeKeyboard($user_id = 0)
{
    $has_group = (
        $user_id > 0 &&
        gameHasActiveGroups($user_id)
    );

    return [
        'inline_keyboard' => [
            [
                [
                    'text' => 'مدیریت گروه',
                    'callback_data' => 'game_manage_group',
                    'style' => $has_group
                        ? 'success'
                        : 'danger'
                ]
            ],
            [
                [
                    'text' => 'بازگشت',
                    'callback_data' => 'game_home_back',
                    'style' => 'danger'
                ]
            ]
        ]
    ];
}


// ============================================================
// کیبورد منوی اصلی
// ============================================================

function gameMainKeyboard()
{
    return [
        'inline_keyboard' => [
            [
                [
                    'text' => '⚙️ پنل',
                    'callback_data' => 'open_panel',
                    'style' => 'primary'
                ]
            ],
            [
                [
                    'text' => '🎮 Game',
                    'callback_data' => 'open_game',
                    'style' => 'success'
                ]
            ]
        ]
    ];
}


// ============================================================
// متن منوی اصلی
// ============================================================

function gameMainWelcomeText($first_name)
{
    $first_name = htmlspecialchars(
        (string)$first_name,
        ENT_QUOTES | ENT_SUBSTITUTE,
        'UTF-8'
    );

    return
        "سلام {$first_name} جان! خوش اومدی.\n\n" .
        "برای تغییر تنظیمات از پنل زیر استفاده کنید👇🏻";
}


// ============================================================
// متن مدیریت گروه
// ============================================================

function gameManageGroupText($user_id = 0)
{
    if (
        $user_id > 0 &&
        gameHasActiveGroups($user_id)
    ) {
        return 'یک گزینه را انتخاب کنید:';
    }

    return
        'ابتدا از منوی زیر ربات رو به گروه خودتون اضافه و ادمین کنید ' .
        '(نکته: اگر ربات ادمین نباشه کار نمی‌کنه)';
}


// ============================================================
// کیبورد مدیریت گروه
// ============================================================

function gameManageGroupKeyboard($user_id)
{
    $groups = gameGetActiveGroups($user_id);

    $keyboard = [];

    if (!empty($groups)) {

        foreach ($groups as $group) {

            $group_id = (string)(
                $group['chat_id'] ?? ''
            );

            if ($group_id === '') {
                continue;
            }

            $title = gameButtonGroupTitle(
                $group['title'] ?? 'گروه'
            );

            $keyboard[] = [
                [
                    'text' => $title,
                    'callback_data' =>
                        'game_select_group:' . $group_id,
                    'style' => 'success'
                ]
            ];
        }

    } else {

        $keyboard[] = [
            [
                'text' => '➕ افزودن به گروه',
                'url' => GAME_ADD_GROUP_URL,
                'style' => 'success'
            ]
        ];
    }

    $keyboard[] = [
        [
            'text' => '🔙 بازگشت',
            'callback_data' => 'game_manage_back',
            'style' => 'danger'
        ]
    ];

    return [
        'inline_keyboard' => $keyboard
    ];
}


// ============================================================
// متن فعال‌سازی گروه
// ============================================================

function gameGroupActivationText()
{
    return
        '<b>ربات با موفقیت در گروه شما فعال شد.</b>' .
        "\n\n" .
        'از دستورات زیر استفاده کنید:';
}


// ============================================================
// دکمه‌های کپی دستورات
// ============================================================

function gameGroupActivationKeyboard()
{
    return [
        'inline_keyboard' => [
            [
                [
                    'text' => 'بازی',
                    'copy_text' => [
                        'text' => 'بازی'
                    ]
                ]
            ],
            [
                [
                    'text' => 'گیم',
                    'copy_text' => [
                        'text' => 'گیم'
                    ]
                ]
            ]
        ]
    ];
}


// ============================================================
// متن منوی انتخاب بازی
// ============================================================

function gameGroupCommandMenuText()
{
    return
        'لطفا یک گزینه رو انتخاب کنید و منتظر جوین شدن حریف بمونید...';
}


// ============================================================
// کیبورد انتخاب بازی
// ============================================================

function gameGroupGameKeyboard()
{
    return [
        'inline_keyboard' => [
            [
                [
                    'text' => 'بمب 💣💎',
                    'callback_data' => 'game_bm',
                    'style' => 'primary'
                ],
                [
                    'text' => 'دوز ❌⭕️',
                    'callback_data' => 'game_dz',
                    'style' => 'success'
                ]
            ],
            [
                [
                    'text' => '✊✋✌️ سنگ کاغذ قیچی',
                    'callback_data' => 'game_rps',
                    'style' => 'danger'
                ]
            ],
            [
                [
                    'text' => '⚔️ شمشیر',
                    'callback_data' => 'game_sao',
                    'style' => 'primary'
                ]
            ]
        ]
    ];
}


// ============================================================
// بررسی پاسخ Telegram API
// ============================================================

function gameTelegramResponseOk($response)
{
    if (is_array($response)) {
        return !empty($response['ok']);
    }

    if (!is_string($response)) {
        return false;
    }

    $result = json_decode(
        $response,
        true
    );

    return (
        is_array($result) &&
        !empty($result['ok'])
    );
}


// ============================================================
// دریافت توضیحات خطای Telegram
// ============================================================

function gameTelegramErrorDescription($response)
{
    if (is_array($response)) {
        return (string)($response['description'] ?? '');
    }

    $result = json_decode(
        (string)$response,
        true
    );

    if (!is_array($result)) {
        return '';
    }

    return (string)(
        $result['description'] ?? ''
    );
}


// ============================================================
// ارسال پیام فعال‌سازی به گروه
// ============================================================

function gameSendGroupActivationMessage($group_id)
{
    if (!function_exists('makeCurl')) {
        return false;
    }

    $post_data = [
        'chat_id' => $group_id,
        'text' => gameGroupActivationText(),
        'parse_mode' => 'HTML',
        'reply_markup' => json_encode(
            gameGroupActivationKeyboard(),
            JSON_UNESCAPED_UNICODE |
            JSON_UNESCAPED_SLASHES
        )
    ];

    $response = makeCurl(
        API_URL . 'sendMessage',
        $post_data
    );

    if (!gameTelegramResponseOk($response)) {

        error_log(
            'Game activation message error: ' .
            gameTelegramErrorDescription($response)
        );

        return false;
    }

    return is_string($response)
        ? json_decode($response, true)
        : $response;
}


// ============================================================
// ثبت ارسال پیام فعال‌سازی
// ============================================================

function gameMarkActivationMessageSent(
    $group_id,
    $message_id
) {

    $group_key = (string)$group_id;

    return gameStateTransaction(

        function (&$state) use (
            $group_key,
            $message_id
        ) {

            if (!isset($state['groups'][$group_key])) {
                return false;
            }

            $state['groups'][$group_key]['activation_notified'] =
                true;

            $state['groups'][$group_key]['activation_message_id'] =
                (int)$message_id;

            $state['groups'][$group_key]['updated_at'] =
                time();

            return true;
        }
    );
}


// ============================================================
// به‌روزرسانی صفحه کاربر پس از تغییر وضعیت گروه
// ============================================================

function gameRefreshManageScreen($user_id)
{
    $result = gameStateTransaction();

    $state = $result['state'];

    $user_key = (string)$user_id;

    if (!isset($state['users'][$user_key])) {
        return false;
    }

    $user_state = $state['users'][$user_key];

    $screen = $user_state['screen'] ?? '';

    if (
        !in_array(
            $screen,
            ['game_home', 'manage_group'],
            true
        )
    ) {
        return false;
    }

    $private_chat_id = (int)(
        $user_state['private_chat_id'] ?? 0
    );

    $message_id = (int)(
        $user_state['screen_message_id'] ?? 0
    );

    if (
        $private_chat_id === 0 ||
        $message_id === 0
    ) {
        return false;
    }

    if (!function_exists('editMessageText')) {
        return false;
    }

    if ($screen === 'game_home') {

        $text = 'یک گزینه را انتخاب کنید:';

        $keyboard = gameHomeKeyboard($user_id);

    } else {

        $text = gameManageGroupText($user_id);

        $keyboard = gameManageGroupKeyboard($user_id);
    }

    $response = editMessageText(
        $private_chat_id,
        $message_id,
        $text,
        $keyboard
    );

    if (gameTelegramResponseOk($response)) {
        return true;
    }

    $description = gameTelegramErrorDescription(
        $response
    );

    if (
        stripos(
            $description,
            'message is not modified'
        ) !== false
    ) {
        return true;
    }

    error_log(
        'Game screen refresh error: ' .
        $description
    );

    return false;
}


// ============================================================
// پاسخ به کلیک
// ============================================================

function gameAnswerCallbackQuery(
    $callback_id,
    $text,
    $show_alert = false
) {

    if (!function_exists('makeCurl')) {
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


// ============================================================
// ثبت منوی بازی و مالک آن
// ============================================================

function gameRegisterGameSession(
    $group_id,
    $message_id,
    $user_id
) {

    $session_key =
        (string)$group_id .
        ':' .
        (string)$message_id;

    return gameStateTransaction(

        function (&$state) use (
            $session_key,
            $group_id,
            $message_id,
            $user_id
        ) {

            $state['game_sessions'][$session_key] = [
                'group_id' => (int)$group_id,
                'message_id' => (int)$message_id,
                'owner_id' => (int)$user_id,
                'created_at' => time()
            ];

            return true;
        }
    );
}


// ============================================================
// دریافت صاحب منوی بازی
// ============================================================

function gameGetGameSession(
    $group_id,
    $message_id
) {

    $session_key =
        (string)$group_id .
        ':' .
        (string)$message_id;

    $result = gameStateTransaction();

    $state = $result['state'];

    if (!isset($state['game_sessions'][$session_key])) {
        return null;
    }

    return $state['game_sessions'][$session_key];
}


// ============================================================
// تشخیص دستورهای شروع بازی
// ============================================================

function gameIsStartGameCommand($text)
{
    if (!is_string($text)) {
        return false;
    }

    $text = str_replace(
        ['ي', 'ك'],
        ['ی', 'ک'],
        $text
    );

    $text = str_replace(
        ["\xE2\x80\x8C", "\xC2\xA0"],
        ' ',
        $text
    );

    $text = preg_replace(
        '/\s+/u',
        ' ',
        trim($text)
    );

    $allowed_commands = [
        'بازی',
        'بازی ها',
        'بازی‌ها',
        'گیم'
    ];

    return in_array(
        $text,
        $allowed_commands,
        true
    );
}


// ============================================================
// مدیریت پیام‌های گروه
// ============================================================

function gameHandleGroupMessage($message)
{
    if (!is_array($message)) {
        return false;
    }

    $chat = $message['chat'] ?? [];

    $chat_type = $chat['type'] ?? '';

    if (
        !in_array(
            $chat_type,
            ['group', 'supergroup'],
            true
        )
    ) {
        return false;
    }

    $group_id = (int)(
        $chat['id'] ?? 0
    );

    $message_id = (int)(
        $message['message_id'] ?? 0
    );

    $user_id = (int)(
        $message['from']['id'] ?? 0
    );

    $text = $message['text'] ?? '';

    if (
        $group_id === 0 ||
        $message_id === 0 ||
        $user_id === 0
    ) {
        return false;
    }

    if (!empty($message['from']['is_bot'])) {
        return false;
    }

    // مسیر SAO: ریپلای + «حمله» / «/slash» / «مهارت» و دستور «شمشیر».
    // باید قبل از رد کردن پیام‌های ریپلای بررسی شود.
    if (gameIsGroupActive($group_id)) {
        $sao_group = gameGetGroupInfo($group_id);

        if (is_array($sao_group)) {
            $sao_handled = gameDispatchSubmodule(
                'gamesao.php',
                'handleGameSaoMessage',
                ['message' => $message],
                $sao_group
            );

            if ($sao_handled) {
                return true;
            }
        }
    }

    if (isset($message['reply_to_message'])) {
        return false;
    }

    if (!gameIsStartGameCommand($text)) {
        return false;
    }

    if (!gameIsGroupActive($group_id)) {
        return false;
    }

    if (!function_exists('makeCurl')) {
        return false;
    }

    $post_data = [
        'chat_id' => $group_id,
        'text' => gameGroupCommandMenuText(),

        'reply_parameters' => json_encode(
            [
                'message_id' => $message_id,
                'allow_sending_without_reply' => true
            ],
            JSON_UNESCAPED_UNICODE
        ),

        'reply_markup' => json_encode(
            gameGroupGameKeyboard(),
            JSON_UNESCAPED_UNICODE |
            JSON_UNESCAPED_SLASHES
        )
    ];

    if (isset($message['message_thread_id'])) {
        $post_data['message_thread_id'] =
            (int)$message['message_thread_id'];
    }

    $response = makeCurl(
        API_URL . 'sendMessage',
        $post_data
    );

    if (!gameTelegramResponseOk($response)) {

        error_log(
            'Game menu send error: ' .
            gameTelegramErrorDescription($response)
        );

        return true;
    }

    $result = is_string($response)
        ? json_decode($response, true)
        : $response;

    $game_message_id = (int)(
        $result['result']['message_id'] ?? 0
    );

    if ($game_message_id <= 0) {
        return true;
    }

    $save_result = gameRegisterGameSession(
        $group_id,
        $game_message_id,
        $user_id
    );

    if (
        empty($save_result['ok']) ||
        ($save_result['result'] ?? false) !== true
    ) {

        error_log(
            'Game menu session registration failed.'
        );

        makeCurl(
            API_URL . 'editMessageReplyMarkup',
            [
                'chat_id' => $group_id,
                'message_id' => $game_message_id,
                'reply_markup' => json_encode([
                    'inline_keyboard' => []
                ])
            ]
        );
    }

    return true;
}


// ============================================================
// مدیریت تغییر وضعیت عضویت ربات در گروه
// ============================================================

function gameHandleMembershipUpdate($membership)
{
    if (!is_array($membership)) {
        return true;
    }

    $chat = $membership['chat'] ?? [];

    $chat_type = $chat['type'] ?? '';

    if (
        !in_array(
            $chat_type,
            ['group', 'supergroup'],
            true
        )
    ) {
        return true;
    }

    $group_id = (string)(
        $chat['id'] ?? ''
    );

    if ($group_id === '') {
        return true;
    }

    $group_title = (string)(
        $chat['title'] ?? 'گروه بدون نام'
    );

    $actor_id = (int)(
        $membership['from']['id'] ?? 0
    );

    $old_status = (string)(
        $membership['old_chat_member']['status'] ?? 'left'
    );

    $new_status = (string)(
        $membership['new_chat_member']['status'] ?? 'left'
    );

    $is_admin = (
        $new_status === 'administrator'
    );

    $is_removed = in_array(
        $new_status,
        ['left', 'kicked'],
        true
    );

    $transaction = gameStateTransaction(

        function (&$state) use (
            $group_id,
            $group_title,
            $chat_type,
            $actor_id,
            $old_status,
            $new_status,
            $is_admin,
            $is_removed
        ) {

            $group_key = (string)$group_id;

            $existing = (
                isset($state['groups'][$group_key]) &&
                is_array($state['groups'][$group_key])
            )
                ? $state['groups'][$group_key]
                : [];

            $owner_id = (int)(
                $existing['owner_id'] ?? 0
            );

            if ($owner_id === 0) {
                $owner_id = $actor_id;
            }

            $was_active = !empty(
                $existing['active']
            );

            $was_notified = !empty(
                $existing['activation_notified']
            );

            $should_notify = (
                $is_admin &&
                (!$was_active || !$was_notified)
            );

            $record = $existing;

            $record['chat_id'] = (int)$group_id;
            $record['title'] = $group_title;
            $record['type'] = $chat_type;
            $record['owner_id'] = $owner_id;
            $record['status'] = $new_status;
            $record['active'] = $is_admin;
            $record['activation_notified'] = $was_notified;
            $record['last_actor_id'] = $actor_id;
            $record['last_old_status'] = $old_status;
            $record['updated_at'] = time();

            if ($is_removed) {
                $record['active'] = false;
            }

            $state['groups'][$group_key] = $record;

            return [
                'owner_id' => $owner_id,
                'should_notify' => $should_notify,
                'active' => $is_admin,
                'removed' => $is_removed
            ];
        }
    );

    $result = $transaction['result'] ?? null;

    if (!is_array($result)) {
        return true;
    }

    $owner_id = (int)(
        $result['owner_id'] ?? 0
    );

    if (!empty($result['should_notify'])) {

        $response = gameSendGroupActivationMessage(
            $group_id
        );

        if (is_array($response)) {

            $sent_message_id = (int)(
                $response['result']['message_id'] ?? 0
            );

            gameMarkActivationMessageSent(
                $group_id,
                $sent_message_id
            );
        }
    }

    if ($owner_id > 0) {
        gameRefreshManageScreen($owner_id);
    }

    return true;
}


// ============================================================
// اتصال به فایل‌های بازی
// ============================================================

function gameDispatchSubmodule(
    $filename,
    $handler_name,
    $update,
    $context
) {

    $path = __DIR__ . '/' . $filename;

    if (!is_file($path)) {
        return false;
    }

    try {

        require_once $path;

        if (!function_exists($handler_name)) {

            error_log(
                'Game handler missing: ' . $handler_name
            );

            return false;
        }

        $result = call_user_func(
            $handler_name,
            $update,
            $context
        );

        return $result === true;

    } catch (Throwable $e) {

        error_log(
            'Game submodule error (' .
            $filename .
            '): ' .
            $e->getMessage()
        );

        return false;
    }
}


// ============================================================
// مدیریت کلیک‌های شیشه‌ای
// ============================================================

function gameHandleCallback(
    $update,
    $callback_query
) {

    $data = (string)(
        $callback_query['data'] ?? ''
    );

    $callback_id = (string)(
        $callback_query['id'] ?? ''
    );

    $message = $callback_query['message'] ?? [];

    $chat = $message['chat'] ?? [];

    $chat_id = (int)(
        $chat['id'] ?? 0
    );

    $message_id = (int)(
        $message['message_id'] ?? 0
    );

    $chat_type = (string)(
        $chat['type'] ?? ''
    );

    $user_id = (int)(
        $callback_query['from']['id'] ?? 0
    );

    if (
        $callback_id === '' ||
        $chat_id === 0 ||
        $message_id === 0 ||
        $user_id === 0
    ) {
        return false;
    }


    // ========================================================
    // کلیک‌های خصوصی
    // ========================================================

    if ($chat_type === 'private') {

        if ($data === 'open_game') {

            gameSaveUserScreen(
                $user_id,
                $chat_id,
                $message_id,
                'game_home'
            );

            answerCallbackQuery(
                $callback_id,
                'بخش Game'
            );

            editMessageText(
                $chat_id,
                $message_id,
                'یک گزینه را انتخاب کنید:',
                gameHomeKeyboard($user_id)
            );

            return true;
        }


        if ($data === 'game_manage_group') {

            gameSaveUserScreen(
                $user_id,
                $chat_id,
                $message_id,
                'manage_group'
            );

            answerCallbackQuery(
                $callback_id,
                'مدیریت گروه'
            );

            editMessageText(
                $chat_id,
                $message_id,
                gameManageGroupText($user_id),
                gameManageGroupKeyboard($user_id)
            );

            return true;
        }


        if ($data === 'game_manage_back') {

            gameSaveUserScreen(
                $user_id,
                $chat_id,
                $message_id,
                'game_home'
            );

            answerCallbackQuery(
                $callback_id,
                'بازگشت'
            );

            editMessageText(
                $chat_id,
                $message_id,
                'یک گزینه را انتخاب کنید:',
                gameHomeKeyboard($user_id)
            );

            return true;
        }


        if ($data === 'game_home_back') {

            gameSaveUserScreen(
                $user_id,
                $chat_id,
                $message_id,
                'main'
            );

            $first_name = (string)(
                $callback_query['from']['first_name'] ?? 'دوست عزیز'
            );

            answerCallbackQuery(
                $callback_id,
                'بازگشت به منوی اصلی'
            );

            editMessageText(
                $chat_id,
                $message_id,
                gameMainWelcomeText($first_name),
                gameMainKeyboard()
            );

            return true;
        }


        // ----------------------------------------------------
        // انتخاب گروه
        // ----------------------------------------------------

        if (
            preg_match(
                '/^game_select_group:(-?\d+)$/',
                $data,
                $matches
            )
        ) {

            $group_id = (int)$matches[1];

            $group = gameGetUserActiveGroup(
                $user_id,
                $group_id
            );

            if (!is_array($group)) {

                answerCallbackQuery(
                    $callback_id,
                    'این گروه فعال نیست یا به حساب شما متصل نشده است.'
                );

                gameSaveUserScreen(
                    $user_id,
                    $chat_id,
                    $message_id,
                    'manage_group'
                );

                editMessageText(
                    $chat_id,
                    $message_id,
                    gameManageGroupText($user_id),
                    gameManageGroupKeyboard($user_id)
                );

                return true;
            }

            $handled = gameDispatchSubmodule(
                'gamept2.php',
                'handleGamePt2Update',
                $update,
                $group
            );

            if (!$handled) {

                answerCallbackQuery(
                    $callback_id,
                    'بخش مدیریت گروه در دسترس نیست.'
                );
            }

            return true;
        }


        // ----------------------------------------------------
        // اتصال دکمه‌های gamept2.php
        // ----------------------------------------------------

        if (
            strpos($data, 'game_pt2_') === 0
        ) {

            if (
                !preg_match(
                    '/^game_pt2_(delete_yes|delete_no|time|delete|back):(-?\d+)$/',
                    $data,
                    $matches
                )
            ) {

                answerCallbackQuery(
                    $callback_id,
                    'اطلاعات گزینه معتبر نیست.'
                );

                return true;
            }

            $group_id = (int)$matches[2];

            $group = gameGetUserActiveGroup(
                $user_id,
                $group_id
            );

            if (!is_array($group)) {

                answerCallbackQuery(
                    $callback_id,
                    'این گروه دیگر فعال نیست.'
                );

                gameSaveUserScreen(
                    $user_id,
                    $chat_id,
                    $message_id,
                    'manage_group'
                );

                editMessageText(
                    $chat_id,
                    $message_id,
                    gameManageGroupText($user_id),
                    gameManageGroupKeyboard($user_id)
                );

                return true;
            }

            $handled = gameDispatchSubmodule(
                'gamept2.php',
                'handleGamePt2Update',
                $update,
                $group
            );

            if (!$handled) {

                answerCallbackQuery(
                    $callback_id,
                    'پردازش گزینه ناموفق بود.'
                );
            }

            return true;
        }


        if (
            strpos($data, 'game_') === 0
        ) {

            answerCallbackQuery(
                $callback_id,
                'این گزینه شناخته نشد!'
            );

            return true;
        }

        return false;
    }


    // ========================================================
    // کلیک‌های گروه
    // ========================================================

    if (
        in_array(
            $chat_type,
            ['group', 'supergroup'],
            true
        )
    ) {


        // ====================================================
        // اتصال Callbackهای بازی شمشیر (SAO)
        // ====================================================

        if (
            strpos($data, 'sao_') === 0
        ) {

            if (!gameIsGroupActive($chat_id)) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'ربات دیگر در این گروه فعال نیست.',
                    true
                );

                return true;
            }

            $group = gameGetGroupInfo($chat_id);

            $handled = gameDispatchSubmodule(
                'gamesao.php',
                'handleGameSaoUpdate',
                $update,
                $group
            );

            if (!$handled) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'پردازش شمشیر ناموفق بود.',
                    true
                );
            }

            return true;
        }


        // ====================================================
        // اتصال Callbackهای بازی الماس یا بمب
        //
        // این بخش باید قبل از سایر بررسی‌های بازی قرار بگیرد.
        //
        // Callbackهای:
        // bm_join
        // bm_back
        // bm_pick
        // bm_used
        // bm_exit
        //
        // مستقیماً به gamebm.php فرستاده می‌شوند.
        // ====================================================

        if (
            strpos($data, 'bm_') === 0
        ) {

            if (!gameIsGroupActive($chat_id)) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'ربات دیگر در این گروه فعال نیست.',
                    true
                );

                return true;
            }

            $group = gameGetGroupInfo($chat_id);

            $handled = gameDispatchSubmodule(
                'gamebm.php',
                'handleGameBmUpdate',
                $update,
                $group
            );

            if (!$handled) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'پردازش بازی الماس یا بمب ناموفق بود.',
                    true
                );
            }

            return true;
        }


        // ====================================================
        // اتصال Callbackهای بازی دوز
        // ====================================================

        if (
            strpos($data, 'dz_') === 0
        ) {

            if (!gameIsGroupActive($chat_id)) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'ربات دیگر در این گروه فعال نیست.',
                    true
                );

                return true;
            }

            $group = gameGetGroupInfo($chat_id);

            $handled = gameDispatchSubmodule(
                'gamedz.php',
                'handleGameDzUpdate',
                $update,
                $group
            );

            if (!$handled) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'پردازش بازی ناموفق بود.',
                    true
                );
            }

            return true;
        }


        // ====================================================
        // اتصال Callbackهای سنگ کاغذ قیچی
        // ====================================================

        if (
            strpos($data, 'rps_') === 0
        ) {

            if (!gameIsGroupActive($chat_id)) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'ربات دیگر در این گروه فعال نیست.',
                    true
                );

                return true;
            }

            $group = gameGetGroupInfo($chat_id);

            $handled = gameDispatchSubmodule(
                'gamerps.php',
                'handleGameRpsUpdate',
                $update,
                $group
            );

            if (!$handled) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'پردازش بازی ناموفق بود.',
                    true
                );
            }

            return true;
        }


        // ====================================================
        // بازگشت از پیام فعال‌سازی قدیمی
        // ====================================================

        if ($data === 'game_group_back') {

            gameAnswerCallbackQuery(
                $callback_id,
                'بازگشت'
            );

            editMessageText(
                $chat_id,
                $message_id,
                gameGroupActivationText(),
                [
                    'inline_keyboard' => []
                ]
            );

            return true;
        }


        // ====================================================
        // فقط دکمه‌های اصلی بازی مجاز هستند
        // ====================================================

        if (
            $data !== 'game_dz' &&
            $data !== 'game_bm' &&
            $data !== 'game_rps' &&
            $data !== 'game_sao'
        ) {
            return false;
        }


        // ====================================================
        // بررسی فعال بودن گروه
        // ====================================================

        if (!gameIsGroupActive($chat_id)) {

            gameAnswerCallbackQuery(
                $callback_id,
                'ربات دیگر در این گروه فعال نیست.',
                true
            );

            return true;
        }


        // ====================================================
        // دریافت اطلاعات صاحب منوی بازی
        // ====================================================

        $session = gameGetGameSession(
            $chat_id,
            $message_id
        );

        if (!is_array($session)) {

            gameAnswerCallbackQuery(
                $callback_id,
                'این منوی بازی معتبر نیست یا منقضی شده است.',
                true
            );

            return true;
        }


        $session_owner_id = (int)(
            $session['owner_id'] ?? 0
        );

        if (
            $session_owner_id === 0 ||
            $session_owner_id !== $user_id
        ) {

            gameAnswerCallbackQuery(
                $callback_id,
                'این منوی بازی فقط برای شخصی است که دستور بازی را ارسال کرده است.',
                true
            );

            return true;
        }


        // ====================================================
        // دریافت اطلاعات گروه بدون بررسی مالکیت
        // ====================================================

        $group = gameGetGroupInfo($chat_id);

        if (
            !is_array($group) ||
            empty($group['active']) ||
            ($group['status'] ?? '') !== 'administrator'
        ) {

            gameAnswerCallbackQuery(
                $callback_id,
                'ربات دیگر در این گروه فعال نیست.',
                true
            );

            return true;
        }


        // اطلاعات تکمیلی

        $group['invoker_id'] = $session_owner_id;

        $group['game_menu_message_id'] = $message_id;

        $group['game_group_id'] = $chat_id;


        // ====================================================
        // اتصال بازی دوز
        // ====================================================

        if ($data === 'game_dz') {

            $handled = gameDispatchSubmodule(
                'gamedz.php',
                'handleGameDzUpdate',
                $update,
                $group
            );

            if (!$handled) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'بخش بازی دوز در دسترس نیست.',
                    true
                );
            }

            return true;
        }


        // ====================================================
        // اتصال بازی الماس یا بمب
        // ====================================================

        if ($data === 'game_bm') {

            $handled = gameDispatchSubmodule(
                'gamebm.php',
                'handleGameBmUpdate',
                $update,
                $group
            );

            if (!$handled) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'بخش بازی الماس یا بمب در دسترس نیست.',
                    true
                );
            }

            return true;
        }


        // ====================================================
        // اتصال بازی سنگ کاغذ قیچی
        // ====================================================

        if ($data === 'game_rps') {

            $handled = gameDispatchSubmodule(
                'gamerps.php',
                'handleGameRpsUpdate',
                $update,
                $group
            );

            if (!$handled) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'بخش بازی سنگ کاغذ قیچی در دسترس نیست.',
                    true
                );
            }

            return true;
        }


        // ====================================================
        // اتصال بازی شمشیر (SAO)
        // ====================================================

        if ($data === 'game_sao') {

            $handled = gameDispatchSubmodule(
                'gamesao.php',
                'handleGameSaoUpdate',
                $update,
                $group
            );

            if (!$handled) {

                gameAnswerCallbackQuery(
                    $callback_id,
                    'بخش بازی شمشیر در دسترس نیست.',
                    true
                );
            }

            return true;
        }
    }

    return false;
}

?>