import asyncio
import os
import sys
import random
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, PreCheckoutQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, ReplyKeyboardRemove, LabeledPrice
)

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN") or (sys.argv[1] if len(sys.argv) > 1 else "")
if not BOT_TOKEN:
    raise RuntimeError("Не указан токен бота. Укажи переменную BOT_TOKEN на хостинге.")
ADMIN_ID = 5134277438
ADMIN_USERNAME = "@emptinessdurka"
DB_FILE = "deltamine.db"
MSK = ZoneInfo("Europe/Moscow")

WELCOME_PHOTO = "welcome.jpg"
VIP_PHOTO = "vip.jpg"
SHARDS_PHOTO = "shards.jpg"

DONATE_REAL_PRICES = {
    "vip": 25,
    "shards_500": 35,
    "shards_1000": 60,
    "shards_5000": 250,
}
TEST_STARS_PRICE = 1
PICKAXE_PHOTOS = {
    "обычная": "pickaxe_normal.jpg",
    "укреплённая": "pickaxe_reinforced.jpg",
    "золотая": "pickaxe_gold.jpg",
    "алмазная": "pickaxe_diamond.jpg",
    "титановая": "pickaxe_titanium.jpg",
}

PICKAXES = {
    "обычная": {"price": 0, "cooldown": 300},
    "укреплённая": {"price": 1000, "cooldown": 300},
    "золотая": {"price": 6500, "cooldown": 300},
    "алмазная": {"price": 12500, "cooldown": 300},
    "титановая": {"price": 20000, "cooldown": 180},
}
PICKAXE_ORDER = ["обычная", "укреплённая", "золотая", "алмазная", "титановая"]

ORES = {
    "Камень": 1,
    "Уголь": 5,
    "Медь": 10,
    "Железо": 50,
    "Аметист": 100,
    "Золото": 250,
    "Алмаз": 1500,
    "Титан": 6000,
}

ORE_ICONS = {
    "Камень": "🪨",
    "Уголь": "⚫",
    "Медь": "🟠",
    "Железо": "🔩",
    "Аметист": "🟣",
    "Золото": "🪙",
    "Алмаз": "💎",
    "Титан": "🔷",
    "Уголёк": "⚫",
}

def ore_name(name):
    return f"{ORE_ICONS.get(name, '⛏️')} {name}"

MINE_CHANCES = {
    "обычная": [
        ("Камень", 50), ("Уголь", 20), ("Медь", 15), ("Железо", 10), ("Аметист", 5)
    ],
    "укреплённая": [
        ("Уголь", 40), ("Медь", 25), ("Железо", 15), ("Аметист", 10), ("Ничего", 10)
    ],
    "золотая": [
        ("Железо", 40), ("Аметист", 25), ("Золото", 15), ("Алмаз", 5),
        ("Ничего", 10), ("Гномик вор", 5)
    ],
    "алмазная": [
        ("Аметист", 40), ("Золото", 25), ("Алмаз", 15), ("Титан", 1),
        ("Ничего", 14), ("Уголёк", 5)
    ],
    "титановая": [
        ("Алмаз", 40), ("Титан", 20), ("Ничего", 20),
        ("Темка не зашла", 10), ("Уголёк", 10)
    ],
}

TITLES = {
    "❤️": 250, "😇": 500, "❄️": 500, "🎃": 500, "🤑": 500,
    "😈": 750, "💀": 1000, "🧠": 2500, "👻": 3000, "🤡": 5000
}

DAILY_REWARDS = [(350, 1), (250, 2), (200, 3), (150, 4), (50, 5)]

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")
db.execute("PRAGMA temp_store=MEMORY")
db.execute("PRAGMA busy_timeout=5000")

db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    balance INTEGER NOT NULL DEFAULT 0,
    shards INTEGER NOT NULL DEFAULT 0,
    ores_mined INTEGER NOT NULL DEFAULT 0,
    daily_earned INTEGER NOT NULL DEFAULT 0,
    total_mines INTEGER NOT NULL DEFAULT 0,
    pickaxe TEXT NOT NULL DEFAULT 'обычная',
    title TEXT DEFAULT '',
    vip_until INTEGER NOT NULL DEFAULT 0,
    last_mine INTEGER NOT NULL DEFAULT 0,
    last_daily TEXT DEFAULT '',
    blocked INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS stats_daily (
    date TEXT PRIMARY KEY,
    money_earned INTEGER NOT NULL DEFAULT 0,
    mines INTEGER NOT NULL DEFAULT 0,
    users INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS activity_daily (
    date TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (date, user_id)
);

CREATE INDEX IF NOT EXISTS idx_activity_daily_date ON activity_daily(date);

CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC);
CREATE INDEX IF NOT EXISTS idx_users_daily ON users(daily_earned DESC);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);

CREATE TABLE IF NOT EXISTS user_titles (
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    PRIMARY KEY (user_id, title)
);

CREATE TABLE IF NOT EXISTS star_payments (
    telegram_payment_charge_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    product TEXT NOT NULL,
    amount INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
""")
db.execute("INSERT OR IGNORE INTO bot_settings(key, value) VALUES('daily_rewards_enabled', '1')")
db.commit()

def daily_rewards_enabled():
    row = db.execute("SELECT value FROM bot_settings WHERE key='daily_rewards_enabled'").fetchone()
    return bool(row and row["value"] == "1")

def set_daily_rewards_enabled(enabled):
    db.execute("UPDATE bot_settings SET value=? WHERE key='daily_rewards_enabled'", ("1" if enabled else "0",))
    db.commit()

for _row in db.execute("SELECT user_id, title FROM users WHERE title != ''").fetchall():
    db.execute("INSERT OR IGNORE INTO user_titles(user_id, title) VALUES(?, ?)", (_row['user_id'], _row['title']))
db.commit()

def now_ts():
    return int(datetime.now().timestamp())

def today():
    return datetime.now(MSK).date().isoformat()

def fmt_money(value):
    return f"{value:,}".replace(",", ".")

def registration_date(timestamp):
    return datetime.fromtimestamp(timestamp, MSK).strftime("%d.%m.%Y %H:%M:%S")

def mark_activity(user_id):
    db.execute(
        "INSERT OR IGNORE INTO activity_daily(date, user_id) VALUES(?, ?)",
        (today(), user_id)
    )

def ensure_user(user):
    ts = now_ts()
    username = user.username or ""
    db.execute("""
        INSERT INTO users(user_id, username, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
    """, (user.id, username, ts))
    row = db.execute("SELECT * FROM users WHERE user_id=?", (user.id,)).fetchone()
    if not row["blocked"]:
        mark_activity(user.id)
    db.commit()
    return row

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_blocked(user_id):
    row = db.execute("SELECT blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
    return bool(row and row["blocked"])

def menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⛏ Спуститься в шахту")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏆 Лидеры")],
            [KeyboardButton(text="🔧 Апгрейд"), KeyboardButton(text="🛒 Магазин")],
            [KeyboardButton(text="❓ Помощь")],
        ],
        resize_keyboard=True
    )

def mine_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ Добыть руду", callback_data="mine")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="mine_back")]
    ])

def profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Другие профили", callback_data="profile_search")],
        [InlineKeyboardButton(text="🏷 Изменить титульный значок", callback_data="change_title")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="profile_back")]
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="profile_cancel")]
    ])

def upgrade_keyboard(current):
    idx = PICKAXE_ORDER.index(current)
    rows = []
    if idx < len(PICKAXE_ORDER) - 1:
        nxt = PICKAXE_ORDER[idx + 1]
        rows.append([InlineKeyboardButton(
            text=f"Улучшить до {nxt}",
            callback_data=f"upgrade:{nxt}"
        )])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="upgrade_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def upgrade_confirm_keyboard(target):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"upgrade_confirm:{target}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="upgrade_back")]
    ])

def shop_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Ежедневка", callback_data="shop_daily")],
        [InlineKeyboardButton(text="🏷 Титулы", callback_data="shop_titles")],
        [InlineKeyboardButton(text="💳 Донат", callback_data="shop_donate")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="shop_main_back")]
    ])

def donate_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 VIP - 25 ⭐", callback_data="donate:vip")],
        [InlineKeyboardButton(text="🔹 500 ОТ - 35 ⭐", callback_data="donate:shards_500")],
        [InlineKeyboardButton(text="🔹 1.000 ОТ - 60 ⭐", callback_data="donate:shards_1000")],
        [InlineKeyboardButton(text="🔹 5.000 ОТ - 250 ⭐", callback_data="donate:shards_5000")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="shop_back")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Заблокировать пользователя", callback_data="admin_block")],
        [InlineKeyboardButton(text="📋 Черный список", callback_data="admin_blacklist")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🗑 Очистить пользователя", callback_data="admin_clear")],
        [InlineKeyboardButton(text="🗑 Очистить всех", callback_data="admin_clear_all")],
        [InlineKeyboardButton(text="Выдать VIP", callback_data="admin_vip")],
        [InlineKeyboardButton(text="🔹 Выдать ОТ", callback_data="admin_shards")],
        [InlineKeyboardButton(text="💰 Выдать себе деньги", callback_data="admin_test_money")],
        [InlineKeyboardButton(text=f"⏱ Ожидание: {'ВЫКЛ' if admin_test_no_cooldown else 'ВКЛ'}", callback_data="admin_test_cooldown")],
        [InlineKeyboardButton(text=f"🏆 Награды ежедневного топа: {'ВКЛ' if daily_rewards_enabled() else 'ВЫКЛ'}", callback_data="admin_daily_rewards")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
    ])

def pickaxe_upgrade_text(row):
    idx = PICKAXE_ORDER.index(row["pickaxe"])
    if idx == len(PICKAXE_ORDER) - 1:
        return "Апгрейд:\nУ вас максимальная кирка - титановая."

    nxt = PICKAXE_ORDER[idx + 1]
    cooldown = PICKAXES[nxt]["cooldown"] // 60
    extra = f"\nВремя ожидания: {cooldown} минуты." if nxt == "титановая" else ""
    return (
        f"⛏ Текущая кирка: {row['pickaxe']}\n"
        f"Следующая кирка: {nxt}\n"
        f"Цена: {fmt_money(PICKAXES[nxt]['price'])}${extra}\n\n"
        "Подтвердить улучшение?"
    )

def display_name(row):
    username = f"@{row['username']}" if row["username"] else str(row["user_id"])
    prefix = ""
    if row["user_id"] == ADMIN_ID:
        prefix += "😎 "
    if row["vip_until"] > now_ts():
        prefix += "👑 "
    suffix = ""
    if row["blocked"]:
        suffix += " 🚫"
    if row["title"]:
        suffix += f" {row['title']}"
    return f"{prefix}{username}{suffix}"

def profile_text(row):
    username = display_name(row)
    title = row["title"] or "нет"
    
    if row["vip_until"] > now_ts():
        remaining = row["vip_until"] - now_ts()
        days, rem = divmod(remaining, 86400)
        hours = rem // 3600
        vip = f"осталось {days} дн. {hours} ч."
    else:
        vip = "неактивен"
    place = get_place(row["user_id"], daily=False)
    daily_place = get_place(row["user_id"], daily=True)
    return (
        f"Никнейм: {username}\n"
        f"⛏ Текущая кирка: {row['pickaxe']}\n"
        f"💰 Доллары: {fmt_money(row['balance'])}\n"
        f"🔹 Осколки титула: {fmt_money(row['shards'])}\n"
        f"💎 Добыто руд: {row['ores_mined']}\n"
        f"🏆 Место в топе: {place}\n"
        f"📅 Ежедневный топ: {daily_place}\n"
        f"👑 Вип-статус: {vip}\n"
        f"🏷 Титульный значок: {title}\n"
        f"📅 Дата регистрации: {registration_date(row['created_at'])}"
    )

def get_place(user_id, daily=False):
    field = "daily_earned" if daily else "balance"
    value = db.execute(f"SELECT {field} FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not value:
        return "-"
    return db.execute(
        f"SELECT COUNT(*) + 1 FROM users WHERE {field} > ? AND blocked=0",
        (value[0],)
    ).fetchone()[0]

def get_top(daily=False):
    return db.execute(
        "SELECT user_id, username, balance AS value, title, vip_until, blocked FROM users WHERE blocked=0 ORDER BY balance DESC, user_id ASC LIMIT 5"
    ).fetchall()

def weighted_result(pickaxe):
    items = MINE_CHANCES[pickaxe]
    r = random.uniform(0, 100)
    total = 0
    for result, chance in items:
        total += chance
        if r <= total:
            return result
    return items[-1][0]

def update_stats(money=0, mines=0):
    d = today()
    db.execute("""
        INSERT INTO stats_daily(date, money_earned, mines, users)
        VALUES (?, ?, ?, (SELECT COUNT(*) FROM users))
        ON CONFLICT(date) DO UPDATE SET
            money_earned=money_earned+excluded.money_earned,
            mines=mines+excluded.mines,
            users=(SELECT COUNT(*) FROM users)
    """, (d, money, mines))
    db.commit()

async def hide_menu(message):
    msg = await message.answer("Меню скрыто.", reply_markup=ReplyKeyboardRemove())
    try:
        await msg.delete()
    except TelegramBadRequest:
        pass

async def send_menu(message, welcome=False):
    if welcome and WELCOME_PHOTO:
        try:
            await message.answer_photo(
                FSInputFile(WELCOME_PHOTO),
                caption="Добро пожаловать в DeltaMine! Добывай руду, прокачивай кирку, вступай в лидеры. Удачной игры!",
                reply_markup=menu()
            )
            return
        except Exception:
            pass
    if welcome:
        await message.answer(
            "Добро пожаловать в DeltaMine! Добывай руду, прокачивай кирку, вступай в лидеры. Удачной игры!",
            reply_markup=menu()
        )
    else:
        await message.answer("Меню:", reply_markup=menu())

async def profile_message(bot, chat_id, target_id):
    row = db.execute("SELECT * FROM users WHERE user_id=?", (target_id,)).fetchone()
    if not row:
        return False
    text = profile_text(row)
    try:
        photos = await bot.get_user_profile_photos(target_id, limit=1)
        if photos.total_count:
            await bot.send_photo(
                chat_id, photos.photos[0][-1].file_id,
                caption=text, reply_markup=profile_keyboard()
            )
            return True
    except Exception:
        pass
    await bot.send_message(chat_id, text, reply_markup=profile_keyboard())
    return True

async def show_upgrade(bot, chat_id, row):
    photo = PICKAXE_PHOTOS.get(row["pickaxe"])
    text = pickaxe_upgrade_text(row)
    if photo:
        try:
            await bot.send_photo(chat_id, FSInputFile(photo), caption=text, reply_markup=upgrade_keyboard(row["pickaxe"]))
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, reply_markup=upgrade_keyboard(row["pickaxe"]))

async def daily_rewards(bot):
    enabled = daily_rewards_enabled()
    rows = get_top(True)
    rewards = {place: amount for amount, place in DAILY_REWARDS}
    winners = []

    if enabled:
        for place, row in enumerate(rows, 1):
            amount = rewards.get(place, 0)
            if amount:
                winners.append((place, row["user_id"], row["username"], amount))

    if enabled:
        for place, uid, username, amount in winners:
            db.execute("UPDATE users SET shards=shards+? WHERE user_id=?", (amount, uid))
        db.commit()

    if not enabled:
        message_text = (
            "🏆 Ежедневные лидеры\n\n"
            "⛔ Награды за ежедневный топ сейчас отключены администратором.\n"
            "📊 Сам топ продолжает работать как обычно."
        )
    elif winners:
        lines = ["🏆 Ежедневные лидеры", "", "🎁 Награды выданы:"]
        for place, uid, username, amount in winners:
            name = f"@{username}" if username else str(uid)
            lines.append(f"{place}. {name} - +{amount} 🔹 ОТ")
        message_text = "\n".join(lines)
    else:
        message_text = "🏆 Ежедневные лидеры\n\n📭 Сегодня победителей нет."

    all_users = [r["user_id"] for r in db.execute("SELECT user_id FROM users WHERE blocked=0").fetchall()]
    for uid in all_users:
        try:
            await bot.send_message(uid, message_text)
            await asyncio.sleep(0.04)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except (TelegramForbiddenError, TelegramBadRequest):
            pass

    db.execute("UPDATE users SET daily_earned=0")
    db.commit()

async def daily_loop(bot):
    while True:
        now = datetime.now(MSK)
        next_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        await asyncio.sleep(max(1, (next_day - now).total_seconds()))
        await daily_rewards(bot)

profile_search_users = set()
admin_states = {}
admin_test_no_cooldown = False

from aiogram import BaseMiddleware

class ActivityMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            row = db.execute("SELECT blocked FROM users WHERE user_id=?", (user.id,)).fetchone()
            if row is None:
                ensure_user(user)
            elif not row["blocked"]:
                mark_activity(user.id)
                db.commit()
        return await handler(event, data)

dp = Dispatcher()
dp.message.outer_middleware(ActivityMiddleware())
dp.callback_query.outer_middleware(ActivityMiddleware())

@dp.message(CommandStart())
async def start(message: Message):
    row = ensure_user(message.from_user)
    if row["blocked"]:
        await message.answer("Вы заблокированы.")
        return
    await send_menu(message, welcome=True)

@dp.message(F.text.in_({"Спуститься в шахту", "⛏ Спуститься в шахту"}))
async def mine_menu(message: Message):
    row = ensure_user(message.from_user)
    if row["blocked"]:
        return
    await hide_menu(message)
    await message.answer("Шахта:", reply_markup=mine_keyboard())

@dp.callback_query(F.data == "mine")
async def mine(callback: CallbackQuery):
    row = ensure_user(callback.from_user)
    if row["blocked"]:
        await callback.answer("Вы заблокированы.", show_alert=True)
        return

    current = now_ts()
    cooldown = PICKAXES[row["pickaxe"]]["cooldown"]
    remaining = cooldown - (current - row["last_mine"])
    if callback.from_user.id == ADMIN_ID and admin_test_no_cooldown:
        remaining = 0
    if remaining > 0:
        m, s = divmod(remaining, 60)
        await callback.answer(f"Подожди немного\nСледующее получение будет доступно через {m}:{s:02d}", show_alert=True)
        return

    result = weighted_result(row["pickaxe"])
    money = 0
    extra = ""

    if result in ORES:
        money = ORES[result]
        extra = f"\n{ore_name(result)}: +{fmt_money(money)}$"
        db.execute("""
            UPDATE users
            SET balance=balance+?, daily_earned=daily_earned+?, ores_mined=ores_mined+1,
                total_mines=total_mines+1, last_mine=?
            WHERE user_id=?
        """, (money, money, current, callback.from_user.id))
        update_stats(money=money, mines=1)
    elif result == "Гномик вор":
        loss = max(0, row["balance"] * 5 // 100)
        db.execute(
            "UPDATE users SET balance=balance-?, total_mines=total_mines+1, last_mine=? WHERE user_id=?",
            (loss, current, callback.from_user.id)
        )
        update_stats(mines=1)
        extra = f"\nГномик вор забрал 5% баланса: {fmt_money(loss)}$"
    elif result == "Темка не зашла":
        loss = max(0, row["balance"] * 3 // 100)
        db.execute(
            "UPDATE users SET balance=balance-?, total_mines=total_mines+1, last_mine=? WHERE user_id=?",
            (loss, current, callback.from_user.id)
        )
        update_stats(mines=1)
        extra = f"\nТемка не зашла. Минус 3% баланса: {fmt_money(loss)}$"
    elif result == "Уголёк":
        money = ORES["Уголь"]
        extra = f"\n{ore_name(result)}: +{fmt_money(money)}$\nВам попался {ore_name('Уголь')}."
        db.execute("UPDATE users SET balance=balance+?, daily_earned=daily_earned+?, ores_mined=ores_mined+1, total_mines=total_mines+1, last_mine=? WHERE user_id=?", (money, money, current, callback.from_user.id))
        update_stats(money=money, mines=1)
    else:
        db.execute(
            "UPDATE users SET total_mines=total_mines+1, last_mine=? WHERE user_id=?",
            (current, callback.from_user.id)
        )
        update_stats(mines=1)
        extra = "\nНичего не найдено."

    db.commit()
    await callback.answer()
    try:
        await callback.message.edit_text(f"Вы получили {ore_name(result) if result in ORES or result == 'Уголёк' else result}!{extra}", reply_markup=mine_keyboard())
    except TelegramBadRequest:
        pass

@dp.callback_query(F.data == "mine_back")
async def mine_back(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.answer()
    await send_menu(callback.message, welcome=False)

@dp.message(F.text.in_({"Профиль", "👤 Профиль"}))
async def profile(message: Message):
    row = ensure_user(message.from_user)
    if row["blocked"]:
        return
    await hide_menu(message)
    await profile_message(message.bot, message.chat.id, message.from_user.id)

@dp.callback_query(F.data == "profile_search")
async def profile_search(callback: CallbackQuery):
    profile_search_users.add(callback.from_user.id)
    await callback.answer()
    await callback.message.answer(
        "Введите @username или Telegram ID игрока для поиска профиля.",
        reply_markup=cancel_keyboard()
    )

@dp.callback_query(F.data == "profile_cancel")
async def profile_cancel(callback: CallbackQuery):
    profile_search_users.discard(callback.from_user.id)
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await send_menu(callback.message, welcome=False)

@dp.message(F.text, lambda message: message.from_user.id in profile_search_users)
async def profile_search_handler(message: Message):
    uid = message.from_user.id
    if uid not in profile_search_users:
        return
    profile_search_users.discard(uid)
    query = message.text.strip()
    target = None

    if query.startswith("@"):
        target = db.execute(
            "SELECT * FROM users WHERE lower(username)=lower(?)",
            (query[1:],)
        ).fetchone()
    elif query.isdigit():
        target = db.execute("SELECT * FROM users WHERE user_id=?", (int(query),)).fetchone()

    if not target:
        await message.answer("Игрок не найден.")
        return
    await profile_message(message.bot, message.chat.id, target["user_id"])

@dp.callback_query(F.data == "profile_back")
async def profile_back(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await send_menu(callback.message, welcome=False)

@dp.callback_query(F.data == "change_title")
async def change_title(callback: CallbackQuery):
    owned = db.execute("SELECT title FROM user_titles WHERE user_id=? ORDER BY title", (callback.from_user.id,)).fetchall()
    buttons = []
    for item in owned:
        title = item["title"]
        buttons.append([InlineKeyboardButton(text=f"🏷 {title}", callback_data=f"title:{title}")])
    buttons.append([InlineKeyboardButton(text="❌ Снять значок", callback_data="title:remove")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="title_back")])
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.message.answer(
        "🏷 Выберите купленный титульный значок:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data.startswith("title:"))
async def title_action(callback: CallbackQuery):
    action = callback.data.split(":", 1)[1]
    if action == "remove":
        db.execute("UPDATE users SET title='' WHERE user_id=?", (callback.from_user.id,))
        db.commit()
        await callback.answer("Значок снят.")
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await profile_message(callback.bot, callback.message.chat.id, callback.from_user.id)
        return
    owned = db.execute("SELECT 1 FROM user_titles WHERE user_id=? AND title=?", (callback.from_user.id, action)).fetchone()
    if not owned:
        await callback.answer("Этот значок ещё не куплен.", show_alert=True)
        return
    db.execute("UPDATE users SET title=? WHERE user_id=?", (action, callback.from_user.id))
    db.commit()
    await callback.answer("Титульный значок установлен.")
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await profile_message(callback.bot, callback.message.chat.id, callback.from_user.id)

@dp.callback_query(F.data == "title_back")
async def title_back(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await profile_message(callback.bot, callback.message.chat.id, callback.from_user.id)

async def check_user_message(message: Message):
    row = ensure_user(message.from_user)
    return None if row["blocked"] else row

@dp.message(F.text.in_({"Лидеры", "🏆 Лидеры"}))
async def leaders_menu(message: Message):
    row = await check_user_message(message)
    if not row:
        return
    top = get_top(False)
    daily = get_top(True)
    lines = ["🏆 Постоянный топ:"]
    if top:
        for i, r in enumerate(top, 1):
            lines.append(f"{i}. {display_name(r)} - {fmt_money(r['value'])}$ 💰")
    else:
        lines.append("📭 Пока пусто.")
    lines.append("\n📅 Ежедневный топ:")
    if daily:
        for i, r in enumerate(daily, 1):
            lines.append(f"{i}. {display_name(r)} - {fmt_money(r['value'])}$ 💰")
    else:
        lines.append("📭 Пока пусто.")
    lines.append("\n⏰ Ежедневный топ обновляется в 00:00 по МСК.")
    lines.append("\n🎁 Награды выдаются только за ЕЖЕДНЕВНЫЙ ТОП-5:")
    if daily_rewards_enabled():
        lines.append("🥇 1 место - +350 🔹 ОТ\n🥈 2 место - +250 🔹 ОТ\n🥉 3 место - +200 🔹 ОТ\n4️⃣ 4 место - +150 🔹 ОТ\n5️⃣ 5 место - +50 🔹 ОТ")
    else:
        lines.append("⛔ Награды за ежедневный топ отключены администратором.")
    await hide_menu(message)
    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="leaders_back")]]))

@dp.callback_query(F.data == "leaders_back")
async def leaders_back(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await send_menu(callback.message, welcome=False)

@dp.message(F.text.in_({"апгрейд", "Апгрейд", "⛏ Апгрейд", "🔧 Апгрейд"}))
async def upgrade_menu(message: Message):
    row = await check_user_message(message)
    if not row:
        return
    await hide_menu(message)
    await show_upgrade(message.bot, message.chat.id, row)

@dp.message(F.text.in_({"магазин", "Магазин", "🛒 Магазин"}))
async def shop_menu(message: Message):
    row = await check_user_message(message)
    if not row:
        return
    await hide_menu(message)
    await message.answer("Магазин:", reply_markup=shop_keyboard())

@dp.callback_query(F.data.startswith("upgrade:"))
async def upgrade_action(callback: CallbackQuery):
    target = callback.data.split(":", 1)[1]
    row = db.execute("SELECT * FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if not row or row["blocked"]:
        return
    if target not in PICKAXE_ORDER or PICKAXE_ORDER.index(target) != PICKAXE_ORDER.index(row["pickaxe"]) + 1:
        await callback.answer("Недоступное улучшение.", show_alert=True)
        return
    price = PICKAXES[target]["price"]
    if row["balance"] < price:
        await callback.answer("Недостаточно долларов.", show_alert=True)
        return
    text = (
        f"⛏ Текущая кирка: {row['pickaxe']}\n"
        f"Новая кирка: {target}\n"
        f"Цена: {fmt_money(price)}$\n"
    )
    if target == "титановая":
        text += "\nВремя ожидания после добычи: 3 минуты вместо 5.\n"
    text += "\nПодтвердить улучшение?"
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await callback.message.answer(text, reply_markup=upgrade_confirm_keyboard(target))

@dp.callback_query(F.data.startswith("upgrade_confirm:"))
async def upgrade_confirm(callback: CallbackQuery):
    target = callback.data.split(":", 1)[1]
    row = db.execute("SELECT * FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if not row or row["blocked"]:
        return
    if target not in PICKAXE_ORDER or PICKAXE_ORDER.index(target) != PICKAXE_ORDER.index(row["pickaxe"]) + 1:
        await callback.answer("Недоступное улучшение.", show_alert=True)
        return
    price = PICKAXES[target]["price"]
    if row["balance"] < price:
        await callback.answer("Недостаточно долларов.", show_alert=True)
        return
    db.execute("UPDATE users SET balance=balance-?, pickaxe=? WHERE user_id=?", (price, target, callback.from_user.id))
    db.commit()
    await callback.answer("Кирка улучшена.")
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await show_upgrade(callback.bot, callback.message.chat.id, db.execute("SELECT * FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone())

@dp.callback_query(F.data == "upgrade_back")
async def upgrade_back(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await send_menu(callback.message, welcome=False)

@dp.callback_query(F.data == "shop_main_back")
async def shop_main_back(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass
    await send_menu(callback.message, welcome=False)

@dp.callback_query(F.data == "shop_daily")
async def shop_daily(callback: CallbackQuery):
    row = db.execute("SELECT * FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    d = today()
    if row["last_daily"] == d:
        await callback.answer("Сегодня ежедневка уже получена.", show_alert=True)
        return
    multiplier = 2 if row["vip_until"] > now_ts() else 1
    dollars = 100 * multiplier
    shards = 30 * multiplier
    db.execute(
        "UPDATE users SET balance=balance+?, daily_earned=daily_earned+?, shards=shards+?, last_daily=? WHERE user_id=?",
        (dollars, dollars, shards, d, callback.from_user.id)
    )
    db.commit()
    await callback.answer()
    await callback.message.edit_text(
        f"Ежедневка:\n+{dollars}$\n+{shards} ОТ",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="shop_back")]
        ])
    )

@dp.callback_query(F.data == "shop_titles")
async def shop_titles(callback: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text=f"{title} - {fmt_money(price)} ОТ", callback_data=f"shop_title:{title}")]
        for title, price in TITLES.items()
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="shop_back")])
    await callback.answer()
    await callback.message.edit_text("Титулы:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("shop_title:"))
async def shop_title(callback: CallbackQuery):
    title = callback.data.split(":", 1)[1]
    price = TITLES[title]
    await callback.answer()
    await callback.message.edit_text(
        f"{title}\nЦена: {fmt_money(price)} ОТ\n\nКупить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy_title:{title}")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="shop_titles")]
        ])
    )

@dp.callback_query(F.data.startswith("buy_title:"))
async def buy_title(callback: CallbackQuery):
    title = callback.data.split(":", 1)[1]
    if title not in TITLES:
        await callback.answer("Такого титула нет.", show_alert=True)
        return
    price = TITLES[title]
    owned = db.execute("SELECT 1 FROM user_titles WHERE user_id=? AND title=?", (callback.from_user.id, title)).fetchone()
    if owned:
        await callback.answer("Этот титул уже куплен.", show_alert=True)
        return
    row = db.execute("SELECT shards, blocked FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if not row or row["blocked"]:
        return
    if row["shards"] < price:
        await callback.answer("Недостаточно Осколков титула.", show_alert=True)
        return
    db.execute("UPDATE users SET shards=shards-?, title=? WHERE user_id=?", (price, title, callback.from_user.id))
    db.execute("INSERT INTO user_titles(user_id, title) VALUES(?, ?)", (callback.from_user.id, title))
    db.commit()
    await callback.answer("Титул куплен.")
    await callback.message.edit_text(
        f"✅ Титул {title} куплен и установлен.\n\n🔹 Списано: {fmt_money(price)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="shop_titles")]
        ])
    )

@dp.callback_query(F.data == "shop_back")
async def shop_back(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Магазин:", reply_markup=shop_keyboard())

@dp.callback_query(F.data == "shop_donate")
async def shop_donate(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Донат:", reply_markup=donate_keyboard())

DONATE_PRODUCTS = {
    "vip": {
        "title": "👑 VIP на месяц",
        "description": "Вип титул\n2x ежедневки\n250 ОТ сразу на баланс",
        "real_price": 25,
        "photo": VIP_PHOTO,
    },
    "shards_500": {
        "title": "🔹 500 ОТ",
        "description": "Обычный товар",
        "real_price": 35,
        "photo": SHARDS_PHOTO,
    },
    "shards_1000": {
        "title": "🔹 1.000 ОТ",
        "description": "Выгодный товар",
        "real_price": 60,
        "photo": SHARDS_PHOTO,
    },
    "shards_5000": {
        "title": "🔹 5.000 ОТ",
        "description": "Почти даром",
        "real_price": 250,
        "photo": SHARDS_PHOTO,
    },
}

def donate_price(product):
    return DONATE_REAL_PRICES[product]

@dp.callback_query(F.data.startswith("donate:"))
async def donate_product(callback: CallbackQuery):
    product = callback.data.split(":", 1)[1]
    item = DONATE_PRODUCTS.get(product)
    if not item:
        await callback.answer("Товар не найден.", show_alert=True)
        return
    row = db.execute("SELECT blocked FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if not row or row["blocked"]:
        await callback.answer("Вы заблокированы.", show_alert=True)
        return

    price = donate_price(product)
    await callback.answer()
    try:
        await callback.message.delete()
    except TelegramBadRequest:
        pass

    if os.path.exists(item["photo"]):
        try:
            await callback.message.answer_photo(
                FSInputFile(item["photo"]),
                caption=f"{item['title']}\n\n{item['description']}\n\nЦена: {price} ⭐"
            )
        except Exception:
            pass

    await callback.message.answer_invoice(
        title=item["title"],
        description=item["description"],
        payload=f"deltamine:{product}",
        currency="XTR",
        prices=[LabeledPrice(label=item["title"], amount=price)],
        provider_token="",
    )

@dp.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    payload = pre_checkout_query.invoice_payload
    if not payload.startswith("deltamine:"):
        await pre_checkout_query.answer(ok=False, error_message="Товар не найден.")
        return
    product = payload.split(":", 1)[1]
    if product not in DONATE_PRODUCTS:
        await pre_checkout_query.answer(ok=False, error_message="Товар не найден.")
        return
    if pre_checkout_query.currency != "XTR" or pre_checkout_query.total_amount != DONATE_REAL_PRICES.get(product, -1):
        await pre_checkout_query.answer(ok=False, error_message="Цена товара изменилась. Откройте оплату заново.")
        return
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    if not payload.startswith("deltamine:"):
        return
    product = payload.split(":", 1)[1]
    item = DONATE_PRODUCTS.get(product)
    if not item or payment.currency != "XTR":
        return

    try:
        db.execute(
            "INSERT INTO star_payments(telegram_payment_charge_id, user_id, product, amount, created_at) VALUES(?, ?, ?, ?, ?)",
            (payment.telegram_payment_charge_id, message.from_user.id, product, payment.total_amount, now_ts())
        )
    except sqlite3.IntegrityError:
        return

    if product == "vip":
        row = db.execute("SELECT vip_until FROM users WHERE user_id=?", (message.from_user.id,)).fetchone()
        current = row["vip_until"] if row else 0
        until = max(now_ts(), current) + 30 * 86400
        db.execute("UPDATE users SET vip_until=?, shards=shards+250 WHERE user_id=?", (until, message.from_user.id))
        result = "👑 VIP активирован на 30 дней.\n🔹 +250 ОТ"
    else:
        amounts = {"shards_500": 500, "shards_1000": 1000, "shards_5000": 5000}
        amount = amounts[product]
        db.execute("UPDATE users SET shards=shards+? WHERE user_id=?", (amount, message.from_user.id))
        result = f"🔹 На баланс зачислено: {fmt_money(amount)} ОТ"
    db.commit()
    await message.answer(f"✅ Оплата прошла успешно!\n\n{result}")

def help_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏ Основа", callback_data="help:base")],
        [InlineKeyboardButton(text="🎲 Шансы", callback_data="help:chances")],
        [InlineKeyboardButton(text="ℹ️ Другое", callback_data="help:other")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="help:back")]
    ])

HELP_BASE = (
    "⛏ Основа\n\n"
    "Добывай руду в шахте раз в 5 минут. С титановой киркой ожидание - 3 минуты.\n\n"
    "Стоимость руды:\n"
    f"{ore_name('Камень')} - 1$\n{ore_name('Уголь')} - 5$\n{ore_name('Медь')} - 10$\n{ore_name('Железо')} - 50$\n"
    f"{ore_name('Аметист')} - 100$\n{ore_name('Золото')} - 250$\n{ore_name('Алмаз')} - 1.500$\n{ore_name('Титан')} - 6.000$\n\n"
    "Кирки постепенно открывают более ценные руды. У каждой кирки свои шансы.\n\n"
    "Негативные эффекты: Гномик вор забирает 5% баланса, Темка не зашла забирает 3%. Иногда выпадает Ничего. Уголёк - редкий случай, когда даже на кирке, где обычного шанса угля нет, можно получить уголь.\n\n"
    "Есть постоянный и ежедневный топ. Ежедневный топ обновляется в 00:00 по МСК, а топ-5 получают Осколки титула. В магазине также есть ежедневка, титулы и донат."
)

HELP_CHANCES = (
    "🎲 Шансы на добычу\n\n"
    "⛏ Обычная:\nКамень 50% | Уголь 20% | Медь 15% | Железо 10% | Аметист 5%\n\n"
    "🔨 Укреплённая:\nУголь 40% | Медь 25% | Железо 15% | Аметист 10% | Ничего 10%\n\n"
    "🥇 Золотая:\nЖелезо 40% | Аметист 25% | Золото 15% | Алмаз 5% | Ничего 10% | Гномик вор 5%\n\n"
    "💎 Алмазная:\nАметист 40% | Золото 25% | Алмаз 15% | Титан 1% | Ничего 14% | Уголёк 5%\n\n"
    "🔷 Титановая:\nАлмаз 40% | Титан 20% | Ничего 20% | Темка не зашла 10% | Уголёк 10%"
)

HELP_OTHER = (
    "ℹ️ Другое\n\n"
    "Профиль показывает баланс, кирку, Осколки титула, добытую руду, позиции в топах, VIP и дату регистрации.\n\n"
    "В магазине можно получать ежедневную награду, покупать титульные значки и приобретать донат за Telegram Stars.\n\n"
    "Если что-то не сработало, не нажимай кнопку много раз подряд - сначала проверь результат предыдущего действия.\n\n"
    "Осколки титула нужны для покупки значков, а доллары - для улучшения кирки.\n\n"
    "👑 VIP-игрок: у его никнейма отображается значок 👑. VIP даёт бонус к ежедневной награде.\n"
    "😎 Администратор: у его никнейма отображается значок 😎. Админский статус доступен только владельцу админки.\n"
    "🏷 Титул игрока: выбранный игроком титульный значок отображается рядом с его никнеймом.\n"
    "🚫 Заблокированный игрок: после блокировки у его никнейма отображается 🚫, а пользоваться ботом он не может.\n"
    "Если у игрока одновременно есть несколько статусов, специальные значки отображаются вместе с его никнеймом."
)

@dp.message(F.text.in_({"Помощь", "❓ Помощь"}))
async def help_button(message: Message):
    row = ensure_user(message.from_user)
    if not row["blocked"]:
        await hide_menu(message)
        await message.answer("Помощь:", reply_markup=help_keyboard())

@dp.callback_query(F.data.startswith("help:"))
async def help_section(callback: CallbackQuery):
    action = callback.data.split(":", 1)[1]
    await callback.answer()
    if action == "back":
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        await send_menu(callback.message, welcome=False)
        return
    texts = {"base": HELP_BASE, "chances": HELP_CHANCES, "other": HELP_OTHER}
    if action in texts:
        await callback.message.edit_text(texts[action], reply_markup=help_keyboard())
@dp.message(F.text.in_({"/admin", "/админка"}))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Админка:", reply_markup=admin_keyboard())

admin_target_states = {}

@dp.callback_query(F.data.startswith("admin_"))
async def admin_actions(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    action = callback.data
    await callback.answer()

    if action == "admin_test_money":
        admin_target_states[callback.from_user.id] = "admin_test_money"
        await callback.message.answer("💰 Введите количество долларов для выдачи себе:")
        return

    if action == "admin_test_cooldown":
        global admin_test_no_cooldown
        admin_test_no_cooldown = not admin_test_no_cooldown
        status = "ВЫКЛ" if admin_test_no_cooldown else "ВКЛ"
        await callback.message.edit_text("Админка:", reply_markup=admin_keyboard())
        await callback.answer(f"Ожидание: {status}")
        return

    if action == "admin_daily_rewards":
        enabled = not daily_rewards_enabled()
        set_daily_rewards_enabled(enabled)
        status = "ВКЛ" if enabled else "ВЫКЛ"
        await callback.message.edit_text(
            f"🏆 Награды ежедневного топа: {status}",
            reply_markup=admin_keyboard()
        )
        await callback.answer(f"Награды: {status}")
        return

    if action == "admin_stats":
        total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        money = db.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0]
        mines = db.execute("SELECT COALESCE(SUM(total_mines),0) FROM users").fetchone()[0]
        now = datetime.now(MSK).date()
        day = now.isoformat()
        week_start = now - timedelta(days=6)
        month_start = now - timedelta(days=29)

        def active_count(date_value):
            return db.execute(
                """SELECT COUNT(*) FROM activity_daily a
                   JOIN users u ON u.user_id=a.user_id
                   WHERE a.date=? AND u.blocked=0""",
                (date_value.isoformat() if hasattr(date_value, "isoformat") else date_value,)
            ).fetchone()[0]

        def activity_lines(start_date, end_date):
            rows = db.execute(
                """SELECT a.date, COUNT(*) AS cnt
                   FROM activity_daily a
                   JOIN users u ON u.user_id=a.user_id
                   WHERE a.date BETWEEN ? AND ? AND u.blocked=0
                   GROUP BY a.date""",
                (start_date.isoformat(), end_date.isoformat())
            ).fetchall()
            counts = {r["date"]: r["cnt"] for r in rows}
            lines = []
            current = start_date
            while current <= end_date:
                lines.append(f"{current.strftime('%d.%m')}: {counts.get(current.isoformat(), 0)}")
                current += timedelta(days=1)
            return " | ".join(lines)

        today_active = active_count(now)
        week_active = activity_lines(week_start, now)
        month_active = activity_lines(month_start, now)

        await callback.message.edit_text(
            f"Статистика:\n\n"
            f"За всё время:\nПользователей: {total}\nБаланс всех: {fmt_money(money)}$\nКопаний: {mines}\n\n"
            f"Активность сегодня: {today_active} игроков\n\n"
            f"Активность за последние 7 дней (игроков в день):\n{week_active}\n\n"
            f"Активность за последние 30 дней (игроков в день):\n{month_active}",
            reply_markup=admin_keyboard()
        )
        return

    if action == "admin_blacklist":
        rows = db.execute("SELECT user_id, username FROM users WHERE blocked=1 ORDER BY user_id").fetchall()
        text = "Черный список:\n" + ("\n".join(
            f"{r['user_id']} - @{r['username']}" if r["username"] else str(r["user_id"])
            for r in rows
        ) if rows else "Пусто")
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Разблокировать", callback_data="admin_unblock")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_cancel")]
            ])
        )
        return

    if action == "admin_unblock":
        admin_target_states[callback.from_user.id] = "admin_unblock"
        await callback.message.answer("Введите @username или Telegram ID для разблокировки.")
        return

    if action in {"admin_block", "admin_clear", "admin_vip", "admin_shards"}:
        admin_target_states[callback.from_user.id] = action
        await callback.message.answer("Введите Telegram ID пользователя.")
        return

    if action == "admin_clear_all":
        admin_target_states.pop(callback.from_user.id, None)
        admin_states.pop(callback.from_user.id, None)
        await callback.message.edit_text(
            "Точно очистить данные всех пользователей?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Да, очистить", callback_data="confirm_clear_all")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ])
        )
        return

    if action == "admin_broadcast":
        admin_target_states[callback.from_user.id] = "admin_broadcast"
        await callback.message.answer("Введите текст рассылки.")
        return

@dp.callback_query(F.data == "confirm_clear_all")
async def admin_confirm_clear_all(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db.execute("""
        UPDATE users SET balance=0, shards=0, ores_mined=0, daily_earned=0,
        total_mines=0, pickaxe='обычная', title='', vip_until=0, last_mine=0, last_daily=''
    """)
    db.execute("DELETE FROM user_titles")
    db.execute("DELETE FROM activity_daily")
    db.execute("DELETE FROM stats_daily")
    db.commit()
    await callback.answer("Данные всех пользователей очищены.")
    await callback.message.edit_text("Данные всех пользователей очищены.", reply_markup=admin_keyboard())

@dp.callback_query(F.data == "admin_cancel")
async def admin_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    admin_target_states.pop(callback.from_user.id, None)
    admin_states.pop(callback.from_user.id, None)
    await callback.answer()
    await callback.message.edit_text("Админка:", reply_markup=admin_keyboard())

@dp.message(F.text, lambda message: message.from_user.id in admin_target_states)
async def admin_input(message: Message):
    if not is_admin(message.from_user.id):
        return

    state = admin_target_states.get(message.from_user.id)
    if not state:
        return

    if state == "admin_test_money":
        try:
            amount = int(message.text.strip())
        except ValueError:
            await message.answer("Введите целое число, например 500 или -900.")
            return
        db.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amount, ADMIN_ID))
        db.commit()
        admin_target_states.pop(message.from_user.id, None)
        await message.answer(f"💰 Выдано себе: {fmt_money(amount)}$", reply_markup=admin_keyboard())
        return

    if state == "admin_broadcast":
        admin_target_states.pop(message.from_user.id, None)
        users = [r["user_id"] for r in db.execute("SELECT user_id FROM users WHERE blocked=0").fetchall()]
        sent = 0
        for uid in users:
            try:
                await message.bot.send_message(uid, message.text)
                sent += 1
                await asyncio.sleep(0.04)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after)
            except (TelegramForbiddenError, TelegramBadRequest):
                pass
        await message.answer(f"Рассылка завершена. Отправлено: {sent}")
        return

    if state == "admin_unblock":
        query = message.text.strip()
        if query.startswith("@"):
            target = db.execute(
                "SELECT * FROM users WHERE lower(username)=lower(?) AND blocked=1",
                (query[1:],)
            ).fetchone()
        elif query.isdigit():
            target = db.execute(
                "SELECT * FROM users WHERE user_id=? AND blocked=1",
                (int(query),)
            ).fetchone()
        else:
            target = None

        if not target:
            await message.answer("Заблокированный пользователь не найден.")
            return

        db.execute("UPDATE users SET blocked=0 WHERE user_id=?", (target["user_id"],))
        db.commit()
        admin_target_states.pop(message.from_user.id, None)
        try:
            await message.bot.send_message(target["user_id"], "Вы были разблокированы в DeltaMine.")
        except Exception:
            pass
        await message.answer("Пользователь разблокирован.", reply_markup=admin_keyboard())
        return

    if isinstance(state, tuple):
        action, target_id = state

        if action == "vip_days":
            try:
                value = int(message.text.strip())
            except ValueError:
                await message.answer("Введите целое количество дней, например 30 или -5.")
                return

            current_vip = db.execute(
                "SELECT vip_until FROM users WHERE user_id=?", (target_id,)
            ).fetchone()[0]
            now = now_ts()
            current_remaining = max(0, current_vip - now)
            new_remaining = max(0, current_remaining + value * 86400)
            until = now + new_remaining if new_remaining else 0

            bonus_shards = 250 if value > 0 and current_remaining == 0 else 0
            db.execute(
                "UPDATE users SET vip_until=?, shards=shards+? WHERE user_id=?",
                (until, bonus_shards, target_id)
            )
            db.commit()
            admin_target_states.pop(message.from_user.id, None)
            remaining_days = new_remaining // 86400
            total_shards = db.execute("SELECT shards FROM users WHERE user_id=?", (target_id,)).fetchone()[0]

            if value > 0:
                action_text = f"+{value} дн."
            elif value < 0:
                action_text = f"{value} дн."
            else:
                action_text = "0 дн."
            bonus_text = f"\n🎁 Бонус: +250 ОТ, так как VIP не было." if bonus_shards else ""

            await message.answer(
                f"👑 VIP: {action_text}\nУ пользователя осталось: {remaining_days} дн. VIP.{bonus_text}",
                reply_markup=admin_keyboard()
            )
            try:
                if value > 0:
                    user_text = f"👑 Вам выдали VIP на {value} дн.\nТеперь VIP действует ещё {remaining_days} дн."
                elif value < 0:
                    user_text = f"👑 Срок VIP изменён на {value} дн.\nТеперь VIP действует ещё {remaining_days} дн."
                else:
                    user_text = f"👑 Срок VIP не изменён. Сейчас осталось {remaining_days} дн."
                if bonus_shards:
                    user_text += "\n🎁 За выдачу VIP с нулевого срока вам начислено +250 ОТ."
                await message.bot.send_message(target_id, user_text)
            except Exception:
                pass
            return

        if action == "shards_amount":
            try:
                value = int(message.text.strip())
            except ValueError:
                await message.answer("Введите целое количество Осколков титула, например 500 или -900.")
                return
            db.execute("UPDATE users SET shards=shards+? WHERE user_id=?", (value, target_id))
            db.commit()
            admin_target_states.pop(message.from_user.id, None)
            total_shards = db.execute("SELECT shards FROM users WHERE user_id=?", (target_id,)).fetchone()[0]
            sign = "+" if value > 0 else ""
            await message.answer(f"🔹 Осколки титула: {sign}{value}\nТеперь на балансе: {total_shards} ОТ", reply_markup=admin_keyboard())
            try:
                await message.bot.send_message(target_id, f"🔹 Изменение ОТ: {sign}{value}\nТеперь на балансе: {total_shards} ОТ")
            except Exception:
                pass
            return

    query = message.text.strip()
    if query.startswith("@"):
        target = db.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (query[1:],)).fetchone()
    elif query.isdigit():
        target = db.execute("SELECT * FROM users WHERE user_id=?", (int(query),)).fetchone()
    else:
        target = None

    if not target:
        await message.answer("Пользователь не найден.")
        admin_target_states.pop(message.from_user.id, None)
        return

    target_id = target["user_id"]
    if not target:
        await message.answer("Пользователь не найден.")
        admin_target_states.pop(message.from_user.id, None)
        return

    if state == "admin_block":
        if target_id == ADMIN_ID:
            admin_target_states.pop(message.from_user.id, None)
            await message.answer("Нельзя заблокировать администратора.")
            return
        admin_target_states[message.from_user.id] = ("block_confirm", target_id)
        await message.answer(
            "Точно заблокировать пользователя?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Да", callback_data=f"confirm_block:{target_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ])
        )
        return

    if state == "admin_clear":
        admin_target_states[message.from_user.id] = ("clear_confirm", target_id)
        await message.answer(
            "Точно очистить пользователя?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Да", callback_data=f"confirm_clear:{target_id}")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_cancel")]
            ])
        )
        return

    if state == "admin_vip":
        admin_target_states[message.from_user.id] = ("vip_days", target_id)
        await message.answer("Введите количество дней VIP.")
        return

    if state == "admin_shards":
        admin_target_states[message.from_user.id] = ("shards_amount", target_id)
        await message.answer("Введите количество Осколков титула.")
        return

@dp.callback_query(F.data.startswith("confirm_block:"))
async def confirm_block(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    target_id = int(callback.data.split(":")[1])
    if target_id == ADMIN_ID:
        await callback.answer("Нельзя заблокировать администратора.", show_alert=True)
        return
    db.execute("UPDATE users SET blocked=1 WHERE user_id=?", (target_id,))
    db.commit()
    admin_target_states.pop(callback.from_user.id, None)
    try:
        await callback.bot.send_message(target_id, "Вы были заблокированы в DeltaMine.")
    except Exception:
        pass
    await callback.answer("Пользователь заблокирован.")
    await callback.message.edit_text("Пользователь заблокирован.", reply_markup=admin_keyboard())

@dp.callback_query(F.data.startswith("confirm_clear:"))
async def confirm_clear(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    target_id = int(callback.data.split(":")[1])
    db.execute("""
        UPDATE users SET balance=0, shards=0, ores_mined=0, daily_earned=0,
        total_mines=0, pickaxe='обычная', title='', vip_until=0, last_mine=0, last_daily=''
        WHERE user_id=?
    """, (target_id,))
    db.execute("DELETE FROM user_titles WHERE user_id=?", (target_id,))
    db.execute("DELETE FROM activity_daily WHERE user_id=?", (target_id,))
    db.commit()
    admin_states.pop(callback.from_user.id, None)
    admin_target_states.pop(callback.from_user.id, None)
    await callback.answer("Очищено.")
    await callback.message.edit_text("Данные пользователя очищены.", reply_markup=admin_keyboard())

async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    asyncio.create_task(daily_loop(bot))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
