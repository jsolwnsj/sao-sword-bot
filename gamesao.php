<?php

// ============================================================
// ربات شمشیر SAO — تکه اول + دوئل (نسخه 1.1 — 2026-11-15)
// ساخت کاراکتر + کارت + ضربه (حمله / /slash) + مهارت + لیدربورد
// + دوئل رسمی /duel (بهترین از ۳، مثل RPS)
//
// بر اساس طرح sao-first-slice.md و با همان الگوی gamebm.php و
// gamerps.php نوشته شده: همه دیتا در فایل JSON همان گروه
// (game_group_databases/group_m<id>.json) و همه خواندن/نوشتن
// از gameGroupDataTransaction با flock رد می‌شود.
//
// اسم فایل باید دقیقاً gamesao.php بماند، چون gameDispatchSubmodule
// در game_5_5ip3.php با همین اسم صدا می‌زند (همان مشکلی که
// gamebm_3_au46.php در برابر gamebm.php داشت).
//
// چیزی که در این تکه نیست:
// - عکس کاراکتر با هوش مصنوعی: جای file_id آماده است
//   (saoSetPlayerPhoto) ولی ساخت عکس بیرون از PHP بات است و
//   هنوز به هیچ API وصل نشده؛ کارت فعلاً متنی فرستاده می‌شود.
// - دوئل رسمی /duel (بهترین از ۳): در نسخه 1.1 اضافه شد
//   (saoCreateDuel و saoDuelApplyHit در انتهای فایل).
//   پچ تازه‌ای لازم ندارد: کال‌بک‌های sao_duel_* با همان دیسپچ
//   sao_ در پچ ۲ و دستور /duel با همان هوک پیام در پچ ۳ می‌رسند.
// - مکانیک شاهکار علی: تابع saoApplyKillerMechanic خالی گذاشته
//   شده و هیچ مکانیکی به‌جای آن حدس زده نشده.
//   دوئل هم از همین تابع رد می‌شود، پس وقتی پر شد روی دوئل هم اثر می‌گذارد.
// - ارتقای سطح/شمشیر: level فعلاً ۱ می‌ماند تا قانونش مشخص شود.
// ============================================================

function handleGameSaoUpdate($update, $group)
{
    if (!is_array($update) || !is_array($group)) {
        return false;
    }

    if (!function_exists('gameGroupDataTransaction')) {
        error_log('Game SAO: gameGroupDataTransaction is missing.');
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

    // دکمه «⚔️ شمشیر» در منوی بازی (فقط سازنده منو، مثل بمب).
    if ($data === 'game_sao') {
        $invoker_id = (int)($group['invoker_id'] ?? 0);

        if ($invoker_id <= 0 || $user_id !== $invoker_id) {
            saoAnswer(
                $callback_id,
                'فقط سازنده این منو می‌تواند شمشیر را انتخاب کند.',
                true
            );
            return true;
        }

        return saoShowOwnCard($callback, $chat_id, $message_id);
    }

    if (preg_match('/^sao_card:(-?\d+)$/', $data, $matches)) {
        return saoShowCard(
            $callback,
            $chat_id,
            $message_id,
            (int)$matches[1]
        );
    }

    if (preg_match('/^sao_slash:(-?\d+)$/', $data, $matches)) {
        return saoHandleSlash(
            $callback,
            $chat_id,
            $message_id,
            (int)$matches[1],
            false
        );
    }

    if (preg_match('/^sao_skill:(-?\d+)$/', $data, $matches)) {
        return saoHandleSlash(
            $callback,
            $chat_id,
            $message_id,
            (int)$matches[1],
            true
        );
    }

    if (preg_match('/^sao_duel_join:([a-f0-9]{12})$/', $data, $matches)) {
        return saoDuelJoin($callback, $chat_id, $message_id, $matches[1]);
    }

    if (preg_match('/^sao_duel_hit:([a-f0-9]{12})$/', $data, $matches)) {
        return saoDuelHit($callback, $chat_id, $message_id, $matches[1]);
    }

    if (preg_match('/^sao_duel_exit:([a-f0-9]{12})$/', $data, $matches)) {
        return saoDuelExit($callback, $chat_id, $message_id, $matches[1]);
    }

    if ($data === 'sao_top') {
        return saoShowTop($callback, $chat_id, $message_id);
    }

    if ($data === 'sao_back') {
        saoAnswer($callback_id, 'بازگشت');
        return saoRestoreGameMenu($chat_id, $message_id);
    }

    return false;
}


// ============================================================
// پیام‌های متنی گروه: «شمشیر»، ریپلای + «حمله»، «/slash»، «مهارت»
// این تابع فقط از gameHandleGroupMessage در game_5_5ip3.php صدا
// زده می‌شود (پچ لازم در game5-sao-patch.md) و باید قبل از خط
// `if (isset($message['reply_to_message'])) return false;`
// بررسی شود، چون حمله با ریپلای است.
// ============================================================

function handleGameSaoMessage($update, $group)
{
    if (!is_array($update) || !is_array($group)) {
        return false;
    }

    if (!function_exists('gameGroupDataTransaction')) {
        return false;
    }

    $message = $update['message'] ?? null;

    if (!is_array($message)) {
        return false;
    }

    $chat = $message['chat'] ?? [];
    $chat_type = (string)($chat['type'] ?? '');

    if (!in_array($chat_type, ['group', 'supergroup'], true)) {
        return false;
    }

    $chat_id = (int)($chat['id'] ?? 0);
    $user_id = (int)($message['from']['id'] ?? 0);
    $text = saoNormalizeText((string)($message['text'] ?? ''));

    if ($chat_id === 0 || $user_id === 0 || $text === '') {
        return false;
    }

    if (!empty($message['from']['is_bot'])) {
        return false;
    }

    $reply = $message['reply_to_message'] ?? null;
    $target_id = 0;

    if (is_array($reply) && isset($reply['from']['id'])) {
        $target_id = (int)$reply['from']['id'];
    }

    // «شمشیر» یا «/sao»: ساخت کاراکتر یا نمایش کارت خودم.
    if ($text === 'شمشیر' || $text === '/sao') {
        return saoSendOwnCard($chat_id, $user_id, $message);
    }

    // ریپلای + «حمله» یا «/slash»: یک ضربه به همان نفر.
    if (
        $target_id > 0 &&
        ($text === 'حمله' || $text === '/slash')
    ) {
        return saoSlashByMessage(
            $chat_id,
            $user_id,
            $target_id,
            $message,
            false
        );
    }

    // ریپلای + «مهارت»: ضربه ویژه بعد از ۵ ضربه عادی.
    if ($target_id > 0 && $text === 'مهارت') {
        return saoSlashByMessage(
            $chat_id,
            $user_id,
            $target_id,
            $message,
            true
        );
    }

    // ریپلای + «/duel» یا «دوئل»: دوئل رسمی بهترین از ۳.
    // «/duel@نام‌بات» هم قبول می‌شود (تلگرام در گروه گاهی همین را می‌فرستد).
    if (
        $target_id > 0 &&
        ($text === 'دوئل' || $text === '/duel' || strpos($text, '/duel@') === 0)
    ) {
        return saoCreateDuelByMessage($chat_id, $user_id, $target_id, $message);
    }

    return false;
}


// ============================================================
// ابزارهای کوچک
// ============================================================

function saoAnswer($callback_id, $text, $show_alert = false)
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

function saoResponseOk($response)
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

function saoResponseDescription($response)
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

function saoNormalizeText($text)
{
    $text = str_replace(['ي', 'ك'], ['ی', 'ک'], $text);
    $text = str_replace(["\xE2\x80\x8C", "\xC2\xA0"], ' ', $text);
    $text = preg_replace('/\s+/u', ' ', trim($text));

    return (string)$text;
}

function saoPlayerHtml($user_id, $name)
{
    $safe_name = htmlspecialchars(
        (string)$name,
        ENT_QUOTES | ENT_SUBSTITUTE,
        'UTF-8'
    );

    return '<a href="tg://user?id=' . (int)$user_id . '">' .
        $safe_name .
        '</a>';
}

function saoGetIdentity($user)
{
    $first_name = trim((string)($user['first_name'] ?? ''));
    $last_name = trim((string)($user['last_name'] ?? ''));
    $user_id = (int)($user['id'] ?? 0);

    $name = trim($first_name . ' ' . $last_name);

    if ($name === '') {
        $name = 'بازیکن ' . $user_id;
    }

    return ['name' => $name, 'first_name' => $first_name];
}


// ============================================================
// مدل داده — مثل bm_leaderboard و rps_leaderboard
// sao_players[<user_id>] و sao_leaderboard[<user_id>] و
// sao_floor و sao_cooldowns در همان فایل JSON گروه ذخیره می‌شوند.
// ============================================================

function saoNewPlayer($user_id, $name)
{
    return [
        'user_id' => (int)$user_id,
        'name' => (string)$name,
        'level' => 1,
        'hp' => 1000,
        'max_hp' => 1000,
        'sword' => 'شمشیر آهنی',
        'sword_level' => 0,
        'sword_base' => 30,
        'armor' => 'زره چرمی طبقه ۱',
        'col' => 0,
        'kills' => 0,
        'floor' => 1,
        'skill' => 'ضربه دوگانه',
        'guild' => '',
        'slashes' => 0,
        'photo_file_id' => null,
        'created_at' => time()
    ];
}

// دمیج پایه: قدرت شمشیر + سطح × ۲.
// مثال طرح: سطح ۱۲ با شمشیر +3 (پایه ۱۰۰) می‌شود ۱۲۴.
function saoBaseDamage($player)
{
    return (int)($player['sword_base'] ?? 30) +
        (int)($player['level'] ?? 1) * 2;
}

// جای مکانیک شاهکار علی — عمداً خالی است.
// وقتی علی مکانیکش را گفت، فقط همین تابع پر می‌شود.
function saoApplyKillerMechanic(&$state, $attacker, $defender, $damage)
{
    return (int)$damage;
}

// file_id عکس کاراکتر (وقتی با هوش مصنوعی ساخته شد) اینجا ذخیره
// می‌شود تا بعد هر بار همان عکس با کپشن تازه فرستاده شود.
function saoSetPlayerPhoto($group_id, $user_id, $file_id)
{
    $group_id = (int)$group_id;
    $user_id = (int)$user_id;
    $key = (string)$user_id;

    if ($group_id === 0 || $user_id === 0 || $file_id === '') {
        return false;
    }

    $result = gameGroupDataTransaction(
        $group_id,
        function (&$state) use ($key, $file_id) {
            if (!isset($state['sao_players'][$key])) {
                return false;
            }

            $state['sao_players'][$key]['photo_file_id'] = (string)$file_id;
            return true;
        }
    );

    return !empty($result['ok']) && ($result['result'] ?? false) === true;
}

function saoEnsurePlayer(&$state, $user_id, $name)
{
    $key = (string)(int)$user_id;

    if (!isset($state['sao_players']) || !is_array($state['sao_players'])) {
        $state['sao_players'] = [];
    }

    if (!isset($state['sao_players'][$key])) {
        $state['sao_players'][$key] = saoNewPlayer($user_id, $name);
    }

    // طبقه گروه روی کارت هر بازیکن هم نوشته می‌شود.
    if (isset($state['sao_floor'])) {
        $state['sao_players'][$key]['floor'] = (int)$state['sao_floor'];
    }

    return $state['sao_players'][$key];
}

function saoGetPlayer($group_id, $user_id)
{
    $key = (string)(int)$user_id;

    $result = gameGroupDataTransaction(
        (int)$group_id,
        function ($state) use ($key) {
            return $state['sao_players'][$key] ?? null;
        }
    );

    $player = $result['result'] ?? null;

    return is_array($player) ? $player : null;
}


// ============================================================
// کارت کاراکتر — همان فرمتی که در طرح توافق شد
// ============================================================

function saoBuildCardText($player, $group_floor = 1)
{
    $name = saoPlayerHtml(
        (int)($player['user_id'] ?? 0),
        (string)($player['name'] ?? 'بازیکن')
    );

    $level = (int)($player['level'] ?? 1);
    $hp = (int)($player['hp'] ?? 1000);
    $max_hp = (int)($player['max_hp'] ?? 1000);
    $sword = htmlspecialchars(
        (string)($player['sword'] ?? 'شمشیر آهنی'),
        ENT_QUOTES | ENT_SUBSTITUTE,
        'UTF-8'
    );
    $sword_level = (int)($player['sword_level'] ?? 0);
    $armor = htmlspecialchars(
        (string)($player['armor'] ?? '—'),
        ENT_QUOTES | ENT_SUBSTITUTE,
        'UTF-8'
    );
    $col = number_format((int)($player['col'] ?? 0));
    $kills = (int)($player['kills'] ?? 0);
    $floor = (int)($player['floor'] ?? $group_floor);
    $skill = htmlspecialchars(
        (string)($player['skill'] ?? 'ضربه دوگانه'),
        ENT_QUOTES | ENT_SUBSTITUTE,
        'UTF-8'
    );
    $guild = trim((string)($player['guild'] ?? ''));

    if ($guild === '') {
        $guild = '—';
    } else {
        $guild = htmlspecialchars($guild, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
    }

    $text = "⚔️ {$name} | سطح {$level}\n";
    $text .= "❤️ HP: {$hp} / {$max_hp}\n";
    $text .= "🗡️ شمشیر: {$sword} +{$sword_level}\n";
    $text .= "🛡️ زره: {$armor}\n";
    $text .= "💰 کول: {$col}\n";
    $text .= "🏆 کشته‌ها: {$kills}\n";
    $text .= "🏰 طبقه: {$floor}\n";
    $text .= "⚡ مهارت: {$skill}\n";
    $text .= "👥 گیلد: {$guild}";

    return $text;
}

function saoBuildCardKeyboard($player, $viewer_id)
{
    $target_id = (int)($player['user_id'] ?? 0);
    $keyboard = [];

    // روی کارت خودم دکمه حمله نیست؛ روی کارت بقیه هست.
    if ($target_id > 0 && $viewer_id > 0 && $target_id !== $viewer_id) {
        $keyboard[] = [
            [
                'text' => '⚔️ حمله',
                'callback_data' => 'sao_slash:' . $target_id,
                'style' => 'danger'
            ],
            [
                'text' => '⚡ مهارت',
                'callback_data' => 'sao_skill:' . $target_id,
                'style' => 'primary'
            ]
        ];
    }

    $keyboard[] = [
        [
            'text' => '🏆 جدول شمشیر',
            'callback_data' => 'sao_top',
            'style' => 'success'
        ],
        [
            'text' => 'بازگشت',
            'callback_data' => 'sao_back',
            'style' => 'danger'
        ]
    ];

    return ['inline_keyboard' => $keyboard];
}

function saoEditCard($chat_id, $message_id, $player, $viewer_id, $group_floor = 1)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    return makeCurl(
        API_URL . 'editMessageText',
        [
            'chat_id' => (int)$chat_id,
            'message_id' => (int)$message_id,
            'text' => saoBuildCardText($player, $group_floor),
            'parse_mode' => 'HTML',
            'reply_markup' => json_encode(
                saoBuildCardKeyboard($player, $viewer_id),
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            )
        ]
    );
}

function saoSendCard($chat_id, $player, $viewer_id, $reply_to = 0)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    $post_data = [
        'chat_id' => (int)$chat_id,
        'text' => saoBuildCardText($player),
        'parse_mode' => 'HTML',
        'reply_markup' => json_encode(
            saoBuildCardKeyboard($player, $viewer_id),
            JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
        )
    ];

    if ($reply_to > 0) {
        $post_data['reply_parameters'] = json_encode(
            [
                'message_id' => (int)$reply_to,
                'allow_sending_without_reply' => true
            ],
            JSON_UNESCAPED_UNICODE
        );
    }

    return makeCurl(API_URL . 'sendMessage', $post_data);
}

function saoRestoreGameMenu($chat_id, $message_id)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    $text = function_exists('gameGroupCommandMenuText')
        ? gameGroupCommandMenuText()
        : 'یک گزینه را انتخاب کنید:';

    $keyboard = function_exists('gameGroupGameKeyboard')
        ? gameGroupGameKeyboard()
        : ['inline_keyboard' => []];

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


// ============================================================
// نمایش کارت
// ============================================================

function saoShowOwnCard($callback, $chat_id, $message_id)
{
    $user = $callback['from'] ?? [];
    $user_id = (int)($user['id'] ?? 0);
    $callback_id = (string)($callback['id'] ?? '');
    $identity = saoGetIdentity($user);

    $result = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($user_id, $identity) {
            $player = saoEnsurePlayer($state, $user_id, $identity['name']);

            return [
                'player' => $player,
                'floor' => (int)($state['sao_floor'] ?? 1)
            ];
        }
    );

    if (empty($result['ok']) || !is_array($result['result'] ?? null)) {
        saoAnswer($callback_id, 'ذخیره کاراکتر ناموفق بود.', true);
        return true;
    }

    saoAnswer($callback_id, 'کاراکتر SAO تو آماده است.');
    saoEditCard(
        $chat_id,
        $message_id,
        $result['result']['player'],
        $user_id,
        $result['result']['floor']
    );

    return true;
}

function saoShowCard($callback, $chat_id, $message_id, $target_id)
{
    $viewer_id = (int)($callback['from']['id'] ?? 0);
    $callback_id = (string)($callback['id'] ?? '');
    $player = saoGetPlayer($chat_id, $target_id);

    if (!is_array($player)) {
        saoAnswer(
            $callback_id,
            'این بازیکن هنوز کاراکتر نساخته؛ اول از منوی بازی «شمشیر» را بزند.',
            true
        );
        return true;
    }

    saoAnswer($callback_id, 'کارت کاراکتر');
    saoEditCard($chat_id, $message_id, $player, $viewer_id);

    return true;
}

function saoSendOwnCard($chat_id, $user_id, $message)
{
    $identity = saoGetIdentity($message['from'] ?? []);
    $message_id = (int)($message['message_id'] ?? 0);

    $result = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($user_id, $identity) {
            return saoEnsurePlayer($state, $user_id, $identity['name']);
        }
    );

    if (empty($result['ok']) || !is_array($result['result'] ?? null)) {
        return true;
    }

    saoSendCard($chat_id, $result['result'], $user_id, $message_id);

    return true;
}


// ============================================================
// ضربه — قلب تکه اول
// کول‌داون ۱۰ ثانیه، کریتیکال ۱۵٪ (×۲)، جاخالی ۱۰٪.
// مهارت: بعد از ۵ ضربه عادی، دمیج ×۲، کول‌داون ۶۰ ثانیه.
// کشته: برنده ۱۰ امتیاز می‌گیرد (مثل RPS)، بازنده با HP کامل
// برمی‌گردد تا بازی ادامه‌دار بماند، نه حذف دائمی.
// ============================================================

function saoDoSlash(&$state, $attacker_id, $attacker_name, $target_id, $is_skill, $now)
{
    $attacker_key = (string)(int)$attacker_id;
    $target_key = (string)(int)$target_id;

    if (!isset($state['sao_cooldowns']) || !is_array($state['sao_cooldowns'])) {
        $state['sao_cooldowns'] = [];
    }

    // پاکسازی سبک: کول‌داون‌های قدیمی‌تر از یک ساعت حذف می‌شوند
    // تا فایل گروه بی‌نهایت بزرگ نشود (همان مشکلی که بمب و RPS دارند).
    foreach ($state['sao_cooldowns'] as $cool_key => $cool) {
        $last = (int)($cool['slash_at'] ?? 0);

        if ($last > 0 && $now - $last > 3600) {
            unset($state['sao_cooldowns'][$cool_key]);
        }
    }

    $attacker = saoEnsurePlayer($state, $attacker_id, $attacker_name);

    if (!isset($state['sao_players'][$target_key])) {
        return ['error' => 'no_target'];
    }

    $target = $state['sao_players'][$target_key];
    $cool = $state['sao_cooldowns'][$attacker_key] ?? [];
    $cooldown_seconds = $is_skill ? 60 : 10;
    $last_at = (int)($cool[$is_skill ? 'skill_at' : 'slash_at'] ?? 0);

    if ($now - $last_at < $cooldown_seconds) {
        return [
            'error' => 'cooldown',
            'wait' => $cooldown_seconds - ($now - $last_at)
        ];
    }

    if ($is_skill && (int)($attacker['slashes'] ?? 0) < 5) {
        return [
            'error' => 'skill_locked',
            'need' => 5 - (int)($attacker['slashes'] ?? 0)
        ];
    }

    $damage = saoBaseDamage($attacker);

    if ($is_skill) {
        $damage *= 2;
    }

    $damage = saoApplyKillerMechanic($state, $attacker, $target, $damage);

    $is_crit = random_int(1, 100) <= 15;
    $is_dodge = random_int(1, 100) <= 10;

    if ($is_crit) {
        $damage *= 2;
    }

    if ($is_dodge) {
        $damage = 0;
    }

    $target_hp = max(0, (int)($target['hp'] ?? 1000) - $damage);
    $killed = ($target_hp === 0);

    if ($killed) {
        $target_hp = (int)($target['max_hp'] ?? 1000);
    }

    $state['sao_players'][$target_key]['hp'] = $target_hp;

    if ($is_skill) {
        $state['sao_players'][$attacker_key]['slashes'] = 0;
        $state['sao_cooldowns'][$attacker_key]['skill_at'] = $now;
    } else {
        $state['sao_players'][$attacker_key]['slashes'] =
            (int)($attacker['slashes'] ?? 0) + 1;
        $state['sao_cooldowns'][$attacker_key]['slash_at'] = $now;
    }

    if ($killed) {
        $state['sao_players'][$attacker_key]['kills'] =
            (int)($attacker['kills'] ?? 0) + 1;

        if (!isset($state['sao_leaderboard'][$attacker_key])) {
            $state['sao_leaderboard'][$attacker_key] = [
                'points' => 0,
                'wins' => 0,
                'kills' => 0
            ];
        }

        $state['sao_leaderboard'][$attacker_key]['points'] += 10;
        $state['sao_leaderboard'][$attacker_key]['wins'] += 1;
        $state['sao_leaderboard'][$attacker_key]['kills'] += 1;
    }

    return [
        'attacker' => $state['sao_players'][$attacker_key],
        'target' => $state['sao_players'][$target_key],
        'damage' => (int)$damage,
        'is_crit' => $is_crit,
        'is_dodge' => $is_dodge,
        'killed' => $killed,
        'floor' => (int)($state['sao_floor'] ?? 1)
    ];
}

function saoSlashResultText($result)
{
    $attacker = $result['attacker'];
    $target = $result['target'];

    $attacker_name = saoPlayerHtml(
        (int)($attacker['user_id'] ?? 0),
        (string)($attacker['name'] ?? 'بازیکن')
    );
    $target_name = saoPlayerHtml(
        (int)($target['user_id'] ?? 0),
        (string)($target['name'] ?? 'بازیکن')
    );

    $damage = (int)($result['damage'] ?? 0);
    $target_hp = (int)($target['hp'] ?? 0);

    if (!empty($result['is_dodge'])) {
        $text = "{$target_name} جاخالی داد! {$attacker_name} با ضربه شمشیر خطا رفت.";
    } else {
        $text = "{$attacker_name} با ضربه شمشیر {$damage} تا از HP {$target_name} کم کرد، {$target_hp} تا مونده.";

        if (!empty($result['is_crit'])) {
            $text .= "\n💥 ضربه کریتیکال!";
        }
    }

    if (!empty($result['killed'])) {
        $text .= "\n🏆 {$attacker_name} {$target_name} را شکست داد و ۱۰ امتیاز گرفت! {$target_name} با HP کامل برگشت.";
    }

    return $text;
}

function saoHandleSlash($callback, $chat_id, $message_id, $target_id, $is_skill)
{
    $user = $callback['from'] ?? [];
    $user_id = (int)($user['id'] ?? 0);
    $callback_id = (string)($callback['id'] ?? '');
    $identity = saoGetIdentity($user);

    if ($target_id === 0 || $target_id === $user_id) {
        saoAnswer($callback_id, 'نمی‌توانی به خودت حمله کنی.', true);
        return true;
    }

    $now = time();

    $result = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($user_id, $identity, $target_id, $is_skill, $now) {
            return saoDoSlash(
                $state,
                $user_id,
                $identity['name'],
                $target_id,
                $is_skill,
                $now
            );
        }
    );

    if (empty($result['ok']) || !is_array($result['result'] ?? null)) {
        saoAnswer($callback_id, 'ذخیره ضربه ناموفق بود.', true);
        return true;
    }

    $slash = $result['result'];

    if (isset($slash['error'])) {
        if ($slash['error'] === 'no_target') {
            saoAnswer(
                $callback_id,
                'این بازیکن هنوز کاراکتر نساخته؛ اول از منوی بازی «شمشیر» را بزند.',
                true
            );
        } elseif ($slash['error'] === 'cooldown') {
            saoAnswer(
                $callback_id,
                'صبر کن؛ ' . (int)($slash['wait'] ?? 10) . ' ثانیه دیگر می‌توانی حمله کنی.',
                true
            );
        } elseif ($slash['error'] === 'skill_locked') {
            saoAnswer(
                $callback_id,
                'مهارت هنوز قفل است؛ ' . (int)($slash['need'] ?? 5) . ' ضربه عادی دیگر بزن.',
                true
            );
        }

        return true;
    }

    saoAnswer($callback_id, '⚔️');

    // پیام نتیجه ضربه + کارت به‌روز شده حریف.
    $text = saoSlashResultText($slash) . "\n\n" .
        saoBuildCardText($slash['target'], $slash['floor']);

    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return true;
    }

    makeCurl(
        API_URL . 'editMessageText',
        [
            'chat_id' => (int)$chat_id,
            'message_id' => (int)$message_id,
            'text' => $text,
            'parse_mode' => 'HTML',
            'reply_markup' => json_encode(
                saoBuildCardKeyboard($slash['target'], $user_id),
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            )
        ]
    );

    return true;
}

function saoSlashByMessage($chat_id, $user_id, $target_id, $message, $is_skill)
{
    $identity = saoGetIdentity($message['from'] ?? []);
    $message_id = (int)($message['message_id'] ?? 0);

    if ($target_id === $user_id) {
        return true;
    }

    $target = saoGetPlayer($chat_id, $target_id);

    if (!is_array($target)) {
        if (!function_exists('makeCurl') || !defined('API_URL')) {
            return true;
        }

        makeCurl(
            API_URL . 'sendMessage',
            [
                'chat_id' => (int)$chat_id,
                'text' => 'این بازیکن هنوز کاراکتر نساخته؛ اول از منوی بازی «شمشیر» را بزند.',
                'reply_parameters' => json_encode(
                    [
                        'message_id' => $message_id,
                        'allow_sending_without_reply' => true
                    ],
                    JSON_UNESCAPED_UNICODE
                )
            ]
        );

        return true;
    }

    $now = time();

    $result = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($user_id, $identity, $target_id, $is_skill, $now) {
            return saoDoSlash(
                $state,
                $user_id,
                $identity['name'],
                $target_id,
                $is_skill,
                $now
            );
        }
    );

    if (empty($result['ok']) || !is_array($result['result'] ?? null)) {
        return true;
    }

    $slash = $result['result'];

    if (isset($slash['error'])) {
        return true;
    }

    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return true;
    }

    makeCurl(
        API_URL . 'sendMessage',
        [
            'chat_id' => (int)$chat_id,
            'text' => saoSlashResultText($slash),
            'parse_mode' => 'HTML',
            'reply_parameters' => json_encode(
                [
                    'message_id' => $message_id,
                    'allow_sending_without_reply' => true
                ],
                JSON_UNESCAPED_UNICODE
            )
        ]
    );

    return true;
}


// ============================================================
// جدول شمشیر — ۱۰ نفر اول بر اساس امتیاز، مثل tablebot
// ============================================================

function saoShowTop($callback, $chat_id, $message_id)
{
    $callback_id = (string)($callback['id'] ?? '');
    $viewer_id = (int)($callback['from']['id'] ?? 0);

    $result = gameGroupDataTransaction(
        $chat_id,
        function ($state) {
            $board = $state['sao_leaderboard'] ?? [];
            $players = $state['sao_players'] ?? [];

            if (!is_array($board)) {
                $board = [];
            }

            uasort(
                $board,
                function ($a, $b) {
                    $pa = (int)($a['points'] ?? 0);
                    $pb = (int)($b['points'] ?? 0);

                    if ($pa === $pb) {
                        return (int)($b['kills'] ?? 0) -
                            (int)($a['kills'] ?? 0);
                    }

                    return $pb - $pa;
                }
            );

            $rows = [];

            foreach (array_slice($board, 0, 10, true) as $uid => $row) {
                $rows[] = [
                    'user_id' => (int)$uid,
                    'name' => (string)(
                        $players[(string)$uid]['name'] ?? ('بازیکن ' . $uid)
                    ),
                    'points' => (int)($row['points'] ?? 0),
                    'kills' => (int)($row['kills'] ?? 0)
                ];
            }

            return $rows;
        }
    );

    $rows = $result['result'] ?? [];

    if (!is_array($rows) || empty($rows)) {
        saoAnswer($callback_id, 'هنوز کسی در جدول شمشیر نیست.', true);
        return true;
    }

    $text = "<b>🏆 جدول شمشیر — آینکراد</b>\n\n";
    $rank = 0;

    foreach ($rows as $row) {
        $rank++;
        $medal = ($rank === 1) ? '🥇' : (($rank === 2) ? '🥈' : (($rank === 3) ? '🥉' : "#{$rank}"));
        $name = saoPlayerHtml((int)$row['user_id'], (string)$row['name']);
        $text .= "{$medal} {$name} — {$row['points']} امتیاز، {$row['kills']} کشته\n";
    }

    saoAnswer($callback_id, 'جدول شمشیر');

    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return true;
    }

    makeCurl(
        API_URL . 'editMessageText',
        [
            'chat_id' => (int)$chat_id,
            'message_id' => (int)$message_id,
            'text' => $text,
            'parse_mode' => 'HTML',
            'reply_markup' => json_encode(
                [
                    'inline_keyboard' => [
                        [
                            [
                                'text' => 'بازگشت',
                                'callback_data' => 'sao_back',
                                'style' => 'danger'
                            ]
                        ]
                    ]
                ],
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            )
        ]
    );

    return true;
}


// ============================================================
// دوئل رسمی — نسخه 1.1 (2026-11-15)
// /duel با ریپلای، بهترین از ۳ راند، مثل RPS.
//
// جریان: چالش با /duel → حریف دکمه «قبول دوئل» را می‌زند →
// هر راند هر دو نفر یک بار «⚔️ ضربه» می‌زنند → دمیج هر دو
// با همان فرمول ضربه حساب می‌شود (قدرت شمشیر + سطح × ۲،
// کریتیکال ۱۵٪ ×۲، جاخالی ۱۰٪، مکانیک شاهکار از
// saoApplyKillerMechanic) → دمیج بیشتر راند را می‌برد.
// راند مساوی تکرار می‌شود و شماره راند جلو نمی‌رود (برخلاف
// باگ RPS که راند مساوی هم شماره راند را زیاد می‌کرد).
// هر ضربه HP دوئل حریف را هم کم می‌کند؛ HP دوئل به صفر برسد
// دوئل همان‌جا با ناک‌اوت تمام می‌شود. برنده دوئل ۱۰ امتیاز
// و ۱ برد در sao_leaderboard می‌گیرد، مثل RPS.
//
// دیتا: $state['sao_duels'][<id دوازده‌رقمی hex>]، با همان
// الگوی $state['rps_games'] در gamerps. دوئل‌های waiting
// قدیمی‌تر از ۳۰ دقیقه و finished قدیمی‌تر از ۱ ساعت موقع
// ساخت دوئل تازه پاک می‌شوند تا فایل گروه بزرگ نشود.
// ============================================================

function saoDuelNewPlayer($player, $total_points = 0, $total_wins = 0)
{
    return [
        'user_id' => (int)($player['user_id'] ?? 0),
        'name' => (string)($player['name'] ?? 'بازیکن'),
        'round_wins' => 0,
        'duel_hp' => (int)($player['max_hp'] ?? 1000),
        'max_hp' => (int)($player['max_hp'] ?? 1000),
        'strike' => null,
        'total_points' => (int)$total_points,
        'total_wins' => (int)$total_wins
    ];
}

function saoDuelPrune(&$state, $now)
{
    if (!isset($state['sao_duels']) || !is_array($state['sao_duels'])) {
        $state['sao_duels'] = [];
        return;
    }

    foreach ($state['sao_duels'] as $duel_id => $duel) {
        $status = (string)($duel['status'] ?? '');
        $created = (int)($duel['created_at'] ?? 0);
        $finished = (int)($duel['finished_at'] ?? 0);

        if ($status === 'waiting' && $created > 0 && $now - $created > 1800) {
            unset($state['sao_duels'][$duel_id]);
        } elseif ($status === 'finished' && $finished > 0 && $now - $finished > 3600) {
            unset($state['sao_duels'][$duel_id]);
        }
    }
}

// دمیج یک ضربه در دوئل: همان فرمول saoDoSlash، بدون کول‌داون
// (کول‌داون دوئل همان نوبت راند است، نه زمان).
function saoDuelRollDamage(&$state, $attacker, $defender)
{
    $damage = saoBaseDamage($attacker);
    $damage = saoApplyKillerMechanic($state, $attacker, $defender, $damage);

    $is_crit = random_int(1, 100) <= 15;
    $is_dodge = random_int(1, 100) <= 10;

    if ($is_crit) {
        $damage *= 2;
    }

    if ($is_dodge) {
        $damage = 0;
    }

    return [
        'damage' => (int)$damage,
        'is_crit' => $is_crit,
        'is_dodge' => $is_dodge
    ];
}

function saoDuelRecordResult(&$state, $winner_id, $winner_name, $loser_id, $loser_name)
{
    if (!isset($state['sao_leaderboard']) || !is_array($state['sao_leaderboard'])) {
        $state['sao_leaderboard'] = [];
    }

    $winner_key = (string)(int)$winner_id;
    $loser_key = (string)(int)$loser_id;

    if (!isset($state['sao_leaderboard'][$winner_key])) {
        $state['sao_leaderboard'][$winner_key] = [
            'points' => 0,
            'wins' => 0,
            'kills' => 0
        ];
    }

    $state['sao_leaderboard'][$winner_key]['points'] += 10;
    $state['sao_leaderboard'][$winner_key]['wins'] += 1;

    if (!isset($state['sao_leaderboard'][$loser_key])) {
        $state['sao_leaderboard'][$loser_key] = [
            'points' => 0,
            'wins' => 0,
            'kills' => 0
        ];
    }
}

function saoDuelAddEvent(&$duel, $text)
{
    if (!isset($duel['events']) || !is_array($duel['events'])) {
        $duel['events'] = [];
    }

    $duel['events'][] = (string)$text;

    // فقط ۶ رویداد آخر نگه داشته می‌شود تا پیام دوئل شلوغ نشود.
    if (count($duel['events']) > 6) {
        $duel['events'] = array_slice($duel['events'], -6);
    }
}

function saoDuelBoardText($duel)
{
    $p1 = $duel['player1'];
    $p2 = $duel['player2'];
    $status = (string)($duel['status'] ?? 'waiting');
    $round = (int)($duel['round'] ?? 1);

    $name1 = saoPlayerHtml((int)($p1['user_id'] ?? 0), (string)($p1['name'] ?? 'بازیکن اول'));
    $name2 = is_array($p2)
        ? saoPlayerHtml((int)($p2['user_id'] ?? 0), (string)($p2['name'] ?? 'بازیکن دوم'))
        : '؟';

    $text = "<b>⚔️ دوئل شمشیر — آینکراد</b>\n\n";
    $text .= "🔴 {$name1} | برد راند: " . (int)($p1['round_wins'] ?? 0) .
        " 🏆 | HP دوئل: " . (int)($p1['duel_hp'] ?? 0) . " / " . (int)($p1['max_hp'] ?? 1000) . "\n";

    if (is_array($p2)) {
        $text .= "🔵 {$name2} | برد راند: " . (int)($p2['round_wins'] ?? 0) .
            " 🏆 | HP دوئل: " . (int)($p2['duel_hp'] ?? 0) . " / " . (int)($p2['max_hp'] ?? 1000) . "\n";
    } else {
        $text .= "🔵 در انتظار حریف…\n";
    }

    if ($status === 'waiting') {
        $text .= "\n⏳ منتظر قبول دوئل توسط {$name2} — دوئل بهترین از ۳ راند است، برنده ۱۰ امتیاز می‌گیرد.";
    } elseif ($status === 'playing') {
        $text .= "\n🎲 راند {$round} از ۳ — اول به ۲ برد راند.\nهر دو نفر دکمه «⚔️ ضربه» را بزنند.";
    } elseif ($status === 'finished') {
        $winner_id = (int)($duel['winner_id'] ?? 0);
        $winner_name = ($winner_id === (int)($p1['user_id'] ?? 0)) ? $name1 : $name2;
        $reason = (string)($duel['finish_reason'] ?? 'win');
        $how = ($reason === 'forfeit') ? 'با تسلیم حریف' : (($reason === 'ko') ? 'با ناک‌اوت' : 'با برد ۲ راند');
        $text .= "\n🏆 {$winner_name} دوئل را برد {$how} و ۱۰ امتیاز گرفت!";
    }

    $events = $duel['events'] ?? [];

    if (is_array($events) && !empty($events)) {
        $text .= "\n\n" . implode("\n", $events);
    }

    return $text;
}

function saoDuelBoardKeyboard($duel, $viewer_id)
{
    $duel_id = (string)($duel['duel_id'] ?? '');
    $status = (string)($duel['status'] ?? 'waiting');
    $keyboard = [];

    if ($status === 'waiting') {
        $keyboard[] = [
            [
                'text' => '🤝 قبول دوئل',
                'callback_data' => 'sao_duel_join:' . $duel_id,
                'style' => 'success'
            ],
            [
                'text' => '❌ لغو',
                'callback_data' => 'sao_duel_exit:' . $duel_id,
                'style' => 'danger'
            ]
        ];
    } elseif ($status === 'playing') {
        $keyboard[] = [
            [
                'text' => '⚔️ ضربه',
                'callback_data' => 'sao_duel_hit:' . $duel_id,
                'style' => 'danger'
            ],
            [
                'text' => '🏳️ تسلیم',
                'callback_data' => 'sao_duel_exit:' . $duel_id,
                'style' => 'primary'
            ]
        ];
    } else {
        $keyboard[] = [
            [
                'text' => '🏆 جدول شمشیر',
                'callback_data' => 'sao_top',
                'style' => 'success'
            ],
            [
                'text' => 'بازگشت',
                'callback_data' => 'sao_back',
                'style' => 'danger'
            ]
        ];
    }

    return ['inline_keyboard' => $keyboard];
}

function saoDuelEditBoard($chat_id, $message_id, $duel, $viewer_id)
{
    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return false;
    }

    return makeCurl(
        API_URL . 'editMessageText',
        [
            'chat_id' => (int)$chat_id,
            'message_id' => (int)$message_id,
            'text' => saoDuelBoardText($duel),
            'parse_mode' => 'HTML',
            'reply_markup' => json_encode(
                saoDuelBoardKeyboard($duel, $viewer_id),
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            )
        ]
    );
}

function saoDuelMessageId($response)
{
    if (is_string($response)) {
        $response = json_decode($response, true);
    }

    if (!is_array($response)) {
        return 0;
    }

    return (int)($response['result']['message_id'] ?? 0);
}

// ساخت دوئل با ریپلای + /duel (یا «دوئل»).
function saoCreateDuelByMessage($chat_id, $user_id, $target_id, $message)
{
    if ($target_id === $user_id) {
        return true;
    }

    $reply = $message['reply_to_message'] ?? [];

    if (!empty($reply['from']['is_bot'])) {
        return true;
    }

    $identity = saoGetIdentity($message['from'] ?? []);
    $target_identity = saoGetIdentity($reply['from'] ?? []);
    $message_id = (int)($message['message_id'] ?? 0);
    $now = time();

    try {
        $duel_id = bin2hex(random_bytes(6));
    } catch (Throwable $e) {
        error_log('Game SAO duel random ID error: ' . $e->getMessage());
        return true;
    }

    $result = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($duel_id, $chat_id, $user_id, $identity, $target_id, $target_identity, $now) {
            saoDuelPrune($state, $now);

            // یک نفر هم‌زمان فقط در یک دوئل فعال می‌تواند باشد.
            foreach ($state['sao_duels'] as $old) {
                if (!is_array($old) || !in_array((string)($old['status'] ?? ''), ['waiting', 'playing'], true)) {
                    continue;
                }

                $ids = [
                    (int)($old['player1']['user_id'] ?? 0),
                    (int)(($old['player2'] ?? [])['user_id'] ?? 0)
                ];

                if (in_array($user_id, $ids, true) || in_array($target_id, $ids, true)) {
                    return ['error' => 'busy'];
                }
            }

            $challenger = saoEnsurePlayer($state, $user_id, $identity['name']);
            $opponent = saoEnsurePlayer($state, $target_id, $target_identity['name']);

            $duel = [
                'duel_id' => $duel_id,
                'group_id' => (int)$chat_id,
                'message_id' => 0,
                'player1' => saoDuelNewPlayer($challenger),
                'player2' => saoDuelNewPlayer($opponent),
                'round' => 1,
                'status' => 'waiting',
                'created_at' => $now,
                'joined_at' => 0,
                'finished_at' => 0,
                'winner_id' => 0,
                'events' => [],
                'finish_reason' => ''
            ];

            $state['sao_duels'][$duel_id] = $duel;

            return ['ok' => true, 'duel' => $duel];
        }
    );

    if (empty($result['ok']) || !is_array($result['result'] ?? null)) {
        return true;
    }

    $created = $result['result'];

    if (isset($created['error'])) {
        // یکی از دو نفر همین حالا در یک دوئل فعال است.
        if (($created['error'] ?? '') === 'busy' && function_exists('makeCurl') && defined('API_URL')) {
            makeCurl(
                API_URL . 'sendMessage',
                [
                    'chat_id' => (int)$chat_id,
                    'text' => 'یکی از شما همین حالا در یک دوئل فعال است؛ اول آن را تمام یا لغو کنید.',
                    'reply_parameters' => json_encode(
                        [
                            'message_id' => $message_id,
                            'allow_sending_without_reply' => true
                        ],
                        JSON_UNESCAPED_UNICODE
                    )
                ]
            );
        }

        return true;
    }

    $duel = $created['duel'];

    if (!function_exists('makeCurl') || !defined('API_URL')) {
        return true;
    }

    $response = makeCurl(
        API_URL . 'sendMessage',
        [
            'chat_id' => (int)$chat_id,
            'text' => saoDuelBoardText($duel),
            'parse_mode' => 'HTML',
            'reply_markup' => json_encode(
                saoDuelBoardKeyboard($duel, $user_id),
                JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES
            ),
            'reply_parameters' => json_encode(
                [
                    'message_id' => $message_id,
                    'allow_sending_without_reply' => true
                ],
                JSON_UNESCAPED_UNICODE
            )
        ]
    );

    $board_id = saoDuelMessageId($response);

    if ($board_id > 0) {
        gameGroupDataTransaction(
            $chat_id,
            function (&$state) use ($duel_id, $board_id) {
                if (isset($state['sao_duels'][$duel_id])) {
                    $state['sao_duels'][$duel_id]['message_id'] = $board_id;
                }

                return true;
            }
        );
    }

    return true;
}

// قبول دوئل: فقط همان حریفی که چالش شده.
function saoDuelJoin($callback, $chat_id, $message_id, $duel_id)
{
    $user_id = (int)($callback['from']['id'] ?? 0);
    $callback_id = (string)($callback['id'] ?? '');
    $now = time();

    $result = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($duel_id, $user_id, $now) {
            saoDuelPrune($state, $now);

            if (!isset($state['sao_duels'][$duel_id])) {
                return ['error' => 'not_found'];
            }

            $duel = &$state['sao_duels'][$duel_id];

            if ((string)($duel['status'] ?? '') !== 'waiting') {
                return ['error' => 'not_waiting'];
            }

            if ((int)($duel['player2']['user_id'] ?? 0) !== $user_id) {
                return ['error' => 'not_opponent'];
            }

            $duel['status'] = 'playing';
            $duel['joined_at'] = $now;

            return ['ok' => true, 'duel' => $duel];
        }
    );

    if (empty($result['ok']) || !is_array($result['result'] ?? null)) {
        saoAnswer($callback_id, 'ذخیره دوئل ناموفق بود.', true);
        return true;
    }

    $joined = $result['result'];

    if (isset($joined['error'])) {
        if ($joined['error'] === 'not_found') {
            saoAnswer($callback_id, 'این دوئل دیگر نیست؛ شاید منقضی شده.', true);
        } elseif ($joined['error'] === 'not_waiting') {
            saoAnswer($callback_id, 'این دوئل دیگر منتظر نیست.', true);
        } elseif ($joined['error'] === 'not_opponent') {
            saoAnswer($callback_id, 'این دوئل برای تو نیست.', true);
        }

        return true;
    }

    saoAnswer($callback_id, 'دوئل شروع شد! ⚔️');
    saoDuelEditBoard($chat_id, $message_id, $joined['duel'], $user_id);

    return true;
}

// یک ضربه در راند دوئل. وقتی هر دو نفر زدند راند مشخص می‌شود.
function saoDuelHit($callback, $chat_id, $message_id, $duel_id)
{
    $user = $callback['from'] ?? [];
    $user_id = (int)($user['id'] ?? 0);
    $callback_id = (string)($callback['id'] ?? '');
    $identity = saoGetIdentity($user);
    $now = time();

    $result = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($duel_id, $user_id, $identity, $now) {
            if (!isset($state['sao_duels'][$duel_id]) || !is_array($state['sao_duels'][$duel_id])) {
                return ['error' => 'not_found'];
            }

            $duel = &$state['sao_duels'][$duel_id];

            if ((string)($duel['status'] ?? '') !== 'playing') {
                return ['error' => 'not_playing'];
            }

            $player_number = 0;

            if ((int)($duel['player1']['user_id'] ?? 0) === $user_id) {
                $player_number = 1;
            } elseif ((int)($duel['player2']['user_id'] ?? 0) === $user_id) {
                $player_number = 2;
            }

            if ($player_number === 0) {
                return ['error' => 'not_player'];
            }

            $key = ($player_number === 1) ? 'player1' : 'player2';
            $other_key = ($player_number === 1) ? 'player2' : 'player1';

            if (!empty($duel[$key]['strike'])) {
                return ['error' => 'already_hit'];
            }

            $attacker = saoEnsurePlayer($state, $user_id, $identity['name']);
            $defender_id = (int)($duel[$other_key]['user_id'] ?? 0);
            $defender = $state['sao_players'][(string)$defender_id] ?? $duel[$other_key];

            $duel[$key]['strike'] = saoDuelRollDamage($state, $attacker, $defender);

            $notice = 'hit';
            $round_winner = 0;
            $game_winner = 0;

            // هر دو زدند: راند را مشخص کن.
            if (!empty($duel['player1']['strike']) && !empty($duel['player2']['strike'])) {
                $round = (int)($duel['round'] ?? 1);
                $d1 = (int)($duel['player1']['strike']['damage'] ?? 0);
                $d2 = (int)($duel['player2']['strike']['damage'] ?? 0);

                $name1 = htmlspecialchars((string)($duel['player1']['name'] ?? 'بازیکن اول'), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
                $name2 = htmlspecialchars((string)($duel['player2']['name'] ?? 'بازیکن دوم'), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');

                $hp1_before = (int)($duel['player1']['duel_hp'] ?? 0);
                $hp2_before = (int)($duel['player2']['duel_hp'] ?? 0);
                $hp1_after = $hp1_before - $d2;
                $hp2_after = $hp2_before - $d1;

                $line = '🎲 راند ' . $round . ': ' . $name1 . ' ' . $d1 . ' ⚔️ 🆚 ' . $d2 . ' ' . $name2;

                if ($d1 === $d2) {
                    // مساوی: راند تکرار می‌شود، شماره راند جلو نمی‌رود.
                    $line .= ' — مساوی! راند تکرار می‌شود.';
                    saoDuelAddEvent($duel, $line);
                    $duel['player1']['strike'] = null;
                    $duel['player2']['strike'] = null;
                    $notice = 'round_tie';
                } else {
                    $round_winner = ($d1 > $d2) ? 1 : 2;
                    $winner_key = ($round_winner === 1) ? 'player1' : 'player2';
                    $loser_key = ($round_winner === 1) ? 'player2' : 'player1';
                    $duel[$winner_key]['round_wins'] = (int)($duel[$winner_key]['round_wins'] ?? 0) + 1;

                    // HP دوئل هر دو نفر کم می‌شود (نه HP اصلی کاراکتر).
                    $duel['player1']['duel_hp'] = $hp1_after;
                    $duel['player2']['duel_hp'] = $hp2_after;

                    $winner_name = ($round_winner === 1) ? $name1 : $name2;
                    $line .= ' — ' . $winner_name . ' برد!';
                    saoDuelAddEvent($duel, $line);
                    $notice = 'round_win';

                    // ناک‌اوت: HP دوئل یکی به صفر رسید.
                    $ko_winner = 0;

                    if ($hp1_after <= 0 && $hp2_after <= 0) {
                        $ko_winner = $round_winner;
                    } elseif ($hp1_after <= 0) {
                        $ko_winner = 2;
                    } elseif ($hp2_after <= 0) {
                        $ko_winner = 1;
                    }

                    if ($ko_winner !== 0) {
                        $game_winner = $ko_winner;
                        $duel['finish_reason'] = 'ko';
                    } elseif ((int)($duel['player1']['round_wins'] ?? 0) >= 2) {
                        $game_winner = 1;
                    } elseif ((int)($duel['player2']['round_wins'] ?? 0) >= 2) {
                        $game_winner = 2;
                    }

                    if ($game_winner !== 0) {
                        $winner_key = ($game_winner === 1) ? 'player1' : 'player2';
                        $loser_key = ($game_winner === 1) ? 'player2' : 'player1';
                        $duel['status'] = 'finished';
                        $duel['finished_at'] = $now;
                        $duel['winner_id'] = (int)($duel[$winner_key]['user_id'] ?? 0);

                        if ($duel['finish_reason'] === '') {
                            $duel['finish_reason'] = 'win';
                        }

                        saoDuelRecordResult(
                            $state,
                            (int)($duel[$winner_key]['user_id'] ?? 0),
                            (string)($duel[$winner_key]['name'] ?? 'بازیکن'),
                            (int)($duel[$loser_key]['user_id'] ?? 0),
                            (string)($duel[$loser_key]['name'] ?? 'بازیکن')
                        );

                        $duel['player1']['total_points'] = (int)($state['sao_leaderboard'][(string)(int)($duel['player1']['user_id'] ?? 0)]['points'] ?? 0);
                        $duel['player2']['total_points'] = (int)($state['sao_leaderboard'][(string)(int)($duel['player2']['user_id'] ?? 0)]['points'] ?? 0);
                        $duel['player1']['total_wins'] = (int)($state['sao_leaderboard'][(string)(int)($duel['player1']['user_id'] ?? 0)]['wins'] ?? 0);
                        $duel['player2']['total_wins'] = (int)($state['sao_leaderboard'][(string)(int)($duel['player2']['user_id'] ?? 0)]['wins'] ?? 0);

                        $notice = 'finished';
                    } else {
                        $duel['round'] = $round + 1;
                        $duel['player1']['strike'] = null;
                        $duel['player2']['strike'] = null;
                    }
                }
            }

            return [
                'ok' => true,
                'duel' => $duel,
                'notice' => $notice,
                'round_winner' => $round_winner,
                'game_winner' => $game_winner
            ];
        }
    );

    if (empty($result['ok']) || !is_array($result['result'] ?? null)) {
        saoAnswer($callback_id, 'ذخیره ضربه ناموفق بود.', true);
        return true;
    }

    $hit = $result['result'];

    if (isset($hit['error'])) {
        if ($hit['error'] === 'not_found') {
            saoAnswer($callback_id, 'این دوئل دیگر نیست.', true);
        } elseif ($hit['error'] === 'not_playing') {
            saoAnswer($callback_id, 'دوئل هنوز شروع نشده یا تمام شده.', true);
        } elseif ($hit['error'] === 'not_player') {
            saoAnswer($callback_id, 'تو در این دوئل نیستی.', true);
        } elseif ($hit['error'] === 'already_hit') {
            saoAnswer($callback_id, 'این راند را زدی؛ منتظر حریف باش.', true);
        }

        return true;
    }

    saoAnswer($callback_id, '⚔️');
    saoDuelEditBoard($chat_id, $message_id, $hit['duel'], $user_id);

    return true;
}

// لغو دوئل در انتظار (فقط چالش‌دهنده) یا تسلیم وسط دوئل.
function saoDuelExit($callback, $chat_id, $message_id, $duel_id)
{
    $user_id = (int)($callback['from']['id'] ?? 0);
    $callback_id = (string)($callback['id'] ?? '');
    $now = time();

    $result = gameGroupDataTransaction(
        $chat_id,
        function (&$state) use ($duel_id, $user_id, $now) {
            if (!isset($state['sao_duels'][$duel_id]) || !is_array($state['sao_duels'][$duel_id])) {
                return ['error' => 'not_found'];
            }

            $duel = &$state['sao_duels'][$duel_id];
            $status = (string)($duel['status'] ?? '');

            if ($status === 'finished') {
                return ['error' => 'finished'];
            }

            $p1 = (int)($duel['player1']['user_id'] ?? 0);
            $p2 = (int)(($duel['player2'] ?? [])['user_id'] ?? 0);

            if ($status === 'waiting') {
                if ($user_id !== $p1) {
                    return ['error' => 'not_challenger'];
                }

                unset($state['sao_duels'][$duel_id]);

                return ['ok' => true, 'duel' => null, 'notice' => 'cancelled'];
            }

            // تسلیم وسط بازی: حریف برنده می‌شود.
            if ($user_id !== $p1 && $user_id !== $p2) {
                return ['error' => 'not_player'];
            }

            $winner_key = ($user_id === $p1) ? 'player2' : 'player1';
            $loser_key = ($user_id === $p1) ? 'player1' : 'player2';

            $duel['status'] = 'finished';
            $duel['finished_at'] = $now;
            $duel['finish_reason'] = 'forfeit';
            $duel['winner_id'] = (int)($duel[$winner_key]['user_id'] ?? 0);

            saoDuelAddEvent(
                $duel,
                '🏳️ ' . htmlspecialchars((string)($duel[$loser_key]['name'] ?? 'بازیکن'), ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8') . ' تسلیم شد.'
            );

            saoDuelRecordResult(
                $state,
                (int)($duel[$winner_key]['user_id'] ?? 0),
                (string)($duel[$winner_key]['name'] ?? 'بازیکن'),
                (int)($duel[$loser_key]['user_id'] ?? 0),
                (string)($duel[$loser_key]['name'] ?? 'بازیکن')
            );

            return ['ok' => true, 'duel' => $duel, 'notice' => 'forfeit'];
        }
    );

    if (empty($result['ok']) || !is_array($result['result'] ?? null)) {
        saoAnswer($callback_id, 'ذخیره ناموفق بود.', true);
        return true;
    }

    $exit = $result['result'];

    if (isset($exit['error'])) {
        if ($exit['error'] === 'not_found') {
            saoAnswer($callback_id, 'این دوئل دیگر نیست.', true);
        } elseif ($exit['error'] === 'finished') {
            saoAnswer($callback_id, 'دوئل تمام شده.', true);
        } elseif ($exit['error'] === 'not_challenger') {
            saoAnswer($callback_id, 'فقط چالش‌دهنده می‌تواند لغو کند.', true);
        } elseif ($exit['error'] === 'not_player') {
            saoAnswer($callback_id, 'تو در این دوئل نیستی.', true);
        }

        return true;
    }

    if (($exit['notice'] ?? '') === 'cancelled') {
        saoAnswer($callback_id, 'دوئل لغو شد.');
        return saoRestoreGameMenu($chat_id, $message_id);
    }

    saoAnswer($callback_id, '🏳️');
    saoDuelEditBoard($chat_id, $message_id, $exit['duel'], $user_id);

    return true;
}
