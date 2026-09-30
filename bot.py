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
    Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
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
        ("Ничего", 9), ("Перерыв на хосте", 5), ("Уголёк", 5)
    ],
    "титановая": [
        ("Алмаз", 40), ("Титан", 20), ("Перерыв на хосте", 20),
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

CREATE INDEX IF NOT EXISTS idx_users_balance ON users(balance DESC);
CREATE INDEX IF NOT EXISTS idx_users_daily ON users(daily_earned DESC);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
""")
db.commit()

def now_ts():
    return int(datetime.now().timestamp())

def today():
    return datetime.now(MSK).date().isoformat()

def fmt_money(value):
    return f"{value:,}".replace(",", ".")

def registration_date(timestamp):
    return datetime.fromtimestamp(timestamp, MSK).strftime("%d.%m.%Y %H:%M:%S")

def ensure_user(user):
    ts = now_ts()
    username = user.username or ""
    db.execute("""
        INSERT INTO users(user_id, username, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username
    """, (user.id, username, ts))
    db.commit()
    return db.execute("SELECT * FROM users WHERE user_id=?", (user.id,)).fetchone()

def is_admin(user_id):
    return user_id == ADMIN_ID

def is_blocked(user_id):
    row = db.execute("SELECT blocked FROM users WHERE user_id=?", (user_id,)).fetchone()
    return bool(row and row["blocked"])

def menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Спуститься в шахту")],
            [KeyboardButton(text="Профиль"), KeyboardButton(text="Лидеры")],
            [KeyboardButton(text="апгрейд"), KeyboardButton(text="магазин")],
            [KeyboardButton(text="Помощь")],
        ],
        resize_keyboard=True
    )

def mine_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добыть руду", callback_data="mine")],
        [InlineKeyboardButton(text="Назад", callback_data="mine_back")]
    ])

def profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Другие профили", callback_data="profile_search")],
        [InlineKeyboardButton(text="Изменить титульный значок", callback_data="change_title")]
    ])

def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="profile_cancel")]
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
    rows.append([InlineKeyboardButton(text="Назад", callback_data="upgrade_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def upgrade_confirm_keyboard(target):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Подтвердить", callback_data=f"upgrade_confirm:{target}")],
        [InlineKeyboardButton(text="Назад", callback_data="upgrade_back")]
    ])

def shop_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Ежедневка", callback_data="shop_daily")],
        [InlineKeyboardButton(text="Титулы", callback_data="shop_titles")],
        [InlineKeyboardButton(text="Донат", callback_data="shop_donate")]
    ])

def donate_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Вип", callback_data="donate_vip")],
        [InlineKeyboardButton(text="Осколки титула", callback_data="donate_shards")],
        [InlineKeyboardButton(text="Назад", callback_data="shop_back")]
    ])

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Заблокировать пользователя", callback_data="admin_block")],
        [InlineKeyboardButton(text="Черный список", callback_data="admin_blacklist")],
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="Очистить пользователя", callback_data="admin_clear")],
        [InlineKeyboardButton(text="Очистить всех", callback_data="admin_clear_all")],
        [InlineKeyboardButton(text="Выдать VIP", callback_data="admin_vip")],
        [InlineKeyboardButton(text="Выдать ОТ", callback_data="admin_shards")],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast")],
    ])

def pickaxe_upgrade_text(row):
    idx = PICKAXE_ORDER.index(row["pickaxe"])
    if idx == len(PICKAXE_ORDER) - 1:
        return "Апгрейд:\nУ вас максимальная кирка — титановая."

    nxt = PICKAXE_ORDER[idx + 1]
    cooldown = PICKAXES[nxt]["cooldown"] // 60
    extra = f"\nВремя ожидания: {cooldown} минуты." if nxt == "титановая" else ""
    return (
        f"Текущая кирка: {row['pickaxe']}\n"
        f"Следующая кирка: {nxt}\n"
        f"Цена: {fmt_money(PICKAXES[nxt]['price'])}${extra}\n\n"
        "Подтвердить улучшение?"
    )

def display_name(row):
    username = f"@{row['username']}" if row["username"] else str(row["user_id"])
    if row["user_id"] == ADMIN_ID:
        return f"😎 {username}"
    if row["vip_until"] > now_ts():
        return f"👑 {username}"
    if row["title"]:
        return f"{row['title']} {username}"
    return username

def profile_text(row):
    username = display_name(row)
    title = row["title"] or "нет"
    vip = "активен" if row["vip_until"] > now_ts() else "неактивен"
    place = get_place(row["user_id"], daily=False)
    daily_place = get_place(row["user_id"], daily=True)
    return (
        f"Никнейм: {username}\n"
        f"Текущая кирка: {row['pickaxe']}\n"
        f"Доллары: {fmt_money(row['balance'])}\n"
        f"Осколки титула: {fmt_money(row['shards'])}\n"
        f"Добыто руд: {row['ores_mined']}\n"
        f"Место в топе: {place}\n"
        f"Ежедневный топ: {daily_place}\n"
        f"Вип-статус: {vip}\n"
        f"Титульный значок: {title}\n"
        f"Дата регистрации: {registration_date(row['created_at'])}"
    )

def get_place(user_id, daily=False):
    field = "daily_earned" if daily else "balance"
    value = db.execute(f"SELECT {field} FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not value:
        return "—"
    return db.execute(
        f"SELECT COUNT(*) + 1 FROM users WHERE {field} > ? AND blocked=0",
        (value[0],)
    ).fetchone()[0]

def get_top(daily=False):
    field = "daily_earned" if daily else "balance"
    return db.execute(
        f"SELECT user_id, username, {field} AS value, title, vip_until FROM users WHERE blocked=0 ORDER BY {field} DESC, user_id ASC LIMIT 5"
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
    rows = get_top(True)
    rewards = {place: amount for amount, place in DAILY_REWARDS}
    winners = []
    for place, row in enumerate(rows, 1):
        amount = rewards.get(place, 0)
        if amount:
            user = db.execute("SELECT user_id FROM users WHERE username=?", (row["username"] or "",)).fetchone()
            # Username is not unique/reliable, so resolve by ordered IDs instead below.
            users = db.execute(
                "SELECT user_id, username, daily_earned FROM users WHERE blocked=0 ORDER BY daily_earned DESC, user_id ASC LIMIT 5"
            ).fetchall()
            if place <= len(users):
                winners.append((place, users[place - 1]["user_id"], users[place - 1]["username"], amount))

    lines = ["Ежедневные лидеры:"]
    for place, uid, username, amount in winners:
        name = f"@{username}" if username else str(uid)
        db.execute("UPDATE users SET shards=shards+? WHERE user_id=?", (amount, uid))
        lines.append(f"{place}. {name} — {amount} ОТ")
    db.commit()

    all_users = [r["user_id"] for r in db.execute("SELECT user_id FROM users WHERE blocked=0").fetchall()]
    message_text = "\n".join(lines) if winners else "Ежедневные лидеры:\nСегодня победителей нет."
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

# Search state only lives in RAM; nothing extra is written to the database.
profile_search_users = set()
admin_states = {}

dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    row = ensure_user(message.from_user)
    if row["blocked"]:
        await message.answer("Вы заблокированы.")
        return
    await send_menu(message, welcome=True)

@dp.message(F.text == "Спуститься в шахту")
async def mine_menu(message: Message):
    row = ensure_user(message.from_user)
    if row["blocked"]:
        return
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
    if remaining > 0:
        m, s = divmod(remaining, 60)
        await callback.answer(f"Подожди немного\nСледующее получение будет доступно через {m}:{s:02d}", show_alert=True)
        return

    result = weighted_result(row["pickaxe"])
    money = 0
    extra = ""

    if result in ORES:
        money = ORES[result]
        extra = f"\nполучено: {fmt_money(money)}$"
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
    else:
        db.execute(
            "UPDATE users SET total_mines=total_mines+1, last_mine=? WHERE user_id=?",
            (current, callback.from_user.id)
        )
        update_stats(mines=1)
        if result == "Перерыв на хосте":
            extra = "\nНа хосте перерыв."
        elif result == "Уголёк":
            extra = "\nВам попался уголёк."
        else:
            extra = "\nНичего не найдено."

    db.commit()
    await callback.answer()
    try:
        await callback.message.edit_text(f"Вы получили {result}!{extra}", reply_markup=mine_keyboard())
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

@dp.message(F.text == "Профиль")
async def profile(message: Message):
    row = ensure_user(message.from_user)
    if row["blocked"]:
        return
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

@dp.message(F.text)
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

@dp.callback_query(F.data == "change_title")
async def change_title(callback: CallbackQuery):
    row = db.execute("SELECT shards FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    buttons = []
    for title, price in TITLES.items():
        buttons.append([InlineKeyboardButton(
            text=f"{title} — {fmt_money(price)} ОТ",
            callback_data=f"title:{title}"
        )])
    buttons.append([InlineKeyboardButton(text="Снять значок", callback_data="title:remove")])
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="title_back")])
    await callback.answer()
    await callback.message.edit_text(
        f"Осколков титула: {fmt_money(row['shards'])}\nВыберите титульный значок:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@dp.callback_query(F.data.startswith("title:"))
async def title_action(callback: CallbackQuery):
    action = callback.data.split(":", 1)[1]
    if action == "remove":
        db.execute("UPDATE users SET title='' WHERE user_id=?", (callback.from_user.id,))
        db.commit()
        await callback.answer("Значок снят.")
        await profile_message(callback.bot, callback.message.chat.id, callback.from_user.id)
        return
    price = TITLES[action]
    row = db.execute("SELECT shards FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if row["shards"] < price:
        await callback.answer("Недостаточно Осколков титула.", show_alert=True)
        return
    db.execute(
        "UPDATE users SET shards=shards-?, title=? WHERE user_id=?",
        (price, action, callback.from_user.id)
    )
    db.commit()
    await callback.answer("Титульный значок установлен.")
    await profile_message(callback.bot, callback.message.chat.id, callback.from_user.id)

@dp.callback_query(F.data == "title_back")
async def title_back(callback: CallbackQuery):
    await callback.answer()
    await profile_message(callback.bot, callback.message.chat.id, callback.from_user.id)

@dp.message(F.text.in_({"Лидеры", "апгрейд", "Апгрейд", "магазин", "Магазин"}))
async def main_menu_sections(message: Message):
    row = ensure_user(message.from_user)
    if row["blocked"]:
        return

    action = (message.text or "").strip().casefold()

    if action == "лидеры":
        top = get_top(False)
        daily = get_top(True)
        lines = ["Постоянный топ:"]
        for i, r in enumerate(top, 1):
            lines.append(f"{i}. {display_name(r)} — {fmt_money(r['value'])}$")
        lines.append("\nЕжедневный топ:")
        for i, r in enumerate(daily, 1):
            lines.append(f"{i}. {display_name(r)} — {fmt_money(r['value'])}$")
        lines.append(
            "\nЕжедневный топ обновляется в 00:00 по МСК.\n"
            "По итогам дня топ-5 получают 1.000 Осколков титула:\n"
            "1 место — 350 ОТ\n2 место — 250 ОТ\n3 место — 200 ОТ\n"
            "4 место — 150 ОТ\n5 место — 50 ОТ"
        )
        await message.answer("\n".join(lines))
        return

    if action == "апгрейд":
        await show_upgrade(message.bot, message.chat.id, row)
        return

    if action == "магазин":
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
        f"Текущая кирка: {row['pickaxe']}\n"
        f"Новая кирка: {target}\n"
        f"Цена: {fmt_money(price)}$\n"
    )
    if target == "титановая":
        text += "\nВремя ожидания после добычи: 3 минуты вместо 5.\n"
    text += "\nПодтвердить улучшение?"
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=upgrade_confirm_keyboard(target))

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
    await show_upgrade(callback.bot, callback.message.chat.id, db.execute("SELECT * FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone())

@dp.callback_query(F.data == "upgrade_back")
async def upgrade_back(callback: CallbackQuery):
    await callback.answer()
    await send_menu(callback.message, welcome=False)

@dp.message(F.text == "магазин")
async def shop(message: Message):
    row = ensure_user(message.from_user)
    if row["blocked"]:
        return
    await message.answer("Магазин:", reply_markup=shop_keyboard())

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
        "UPDATE users SET balance=balance+?, shards=shards+?, last_daily=? WHERE user_id=?",
        (dollars, shards, d, callback.from_user.id)
    )
    db.commit()
    await callback.answer()
    await callback.message.edit_text(
        f"Ежедневка:\n+{dollars}$\n+{shards} ОТ",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="shop_back")]
        ])
    )

@dp.callback_query(F.data == "shop_titles")
async def shop_titles(callback: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text=f"{title} — {fmt_money(price)} ОТ", callback_data=f"shop_title:{title}")]
        for title, price in TITLES.items()
    ]
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="shop_back")])
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
            [InlineKeyboardButton(text="Купить", callback_data=f"buy_title:{title}")],
            [InlineKeyboardButton(text="Назад", callback_data="shop_titles")]
        ])
    )

@dp.callback_query(F.data.startswith("buy_title:"))
async def buy_title(callback: CallbackQuery):
    title = callback.data.split(":", 1)[1]
    price = TITLES[title]
    row = db.execute("SELECT shards FROM users WHERE user_id=?", (callback.from_user.id,)).fetchone()
    if row["shards"] < price:
        await callback.answer("Недостаточно Осколков титула.", show_alert=True)
        return
    db.execute(
        "UPDATE users SET shards=shards-?, title=? WHERE user_id=?",
        (price, title, callback.from_user.id)
    )
    db.commit()
    await callback.answer("Титул куплен.")
    await callback.message.edit_text(f"Титул {title} установлен.")

@dp.callback_query(F.data == "shop_back")
async def shop_back(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Магазин:", reply_markup=shop_keyboard())

@dp.callback_query(F.data == "shop_donate")
async def shop_donate(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Донат:", reply_markup=donate_keyboard())

@dp.callback_query(F.data == "donate_vip")
async def donate_vip(callback: CallbackQuery):
    text = (
        "VIP 35₽/мес:\n"
        "Вип титул\n"
        "2x ежедневки\n"
        "250 ОТ сразу на баланс\n\n"
        "Ссылка для оплаты -\n\n"
        "После оплаты получение товара может осуществляться в течение 24 часов! "
        "Товар возврату не подлежит!"
    )
    await callback.answer()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="shop_donate")]
    ])
    if VIP_PHOTO:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(FSInputFile(VIP_PHOTO), caption=text, reply_markup=keyboard)
            return
        except Exception:
            pass
    await callback.message.edit_text(text, reply_markup=keyboard)

@dp.callback_query(F.data == "donate_shards")
async def donate_shards(callback: CallbackQuery):
    buttons = [
        [InlineKeyboardButton(text="500 ОТ - 45₽", callback_data="pay:500")],
        [InlineKeyboardButton(text="1.000 ОТ - 80₽", callback_data="pay:1000")],
        [InlineKeyboardButton(text="5.000 ОТ - 300₽", callback_data="pay:5000")],
        [InlineKeyboardButton(text="Назад", callback_data="shop_donate")]
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.answer()
    if SHARDS_PHOTO:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(FSInputFile(SHARDS_PHOTO), caption="Осколки титула:", reply_markup=markup)
            return
        except Exception:
            pass
    await callback.message.edit_text("Осколки титула:", reply_markup=markup)

@dp.callback_query(F.data.startswith("pay:"))
async def pay(callback: CallbackQuery):
    amount = callback.data.split(":")[1]
    labels = {
        "500": "Обычный товар",
        "1000": "Выгодный товар",
        "5000": "Почти даром"
    }
    await callback.answer()
    await callback.message.edit_text(
        f"{amount} ОТ:\n\n{labels[amount]}\n\n"
        "Ссылка для оплаты -\n\n"
        "После оплаты получение товара может осуществляться в течение 24 часов! "
        "Товар возврату не подлежит!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="donate_shards")]
        ])
    )

@dp.message(F.text == "Помощь")
async def help_button(message: Message):
    row = ensure_user(message.from_user)
    if not row["blocked"]:
        await message.answer("Помощь пока недоступна.")
@dp.message(F.text.startswith("/admin"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("Админка:", reply_markup=admin_keyboard())

# Admin helpers
admin_target_states = {}

@dp.callback_query(F.data.startswith("admin_"))
async def admin_actions(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    action = callback.data
    await callback.answer()

    if action == "admin_stats":
        total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        money = db.execute("SELECT COALESCE(SUM(balance),0) FROM users").fetchone()[0]
        mines = db.execute("SELECT COALESCE(SUM(total_mines),0) FROM users").fetchone()[0]
        now = datetime.now(MSK)
        week = (now.date() - timedelta(days=6)).isoformat()
        month = now.date().replace(day=1).isoformat()
        day = today()
        def stat(d1, d2=None):
            if d2:
                r = db.execute(
                    "SELECT COALESCE(SUM(money_earned),0), COALESCE(SUM(mines),0) FROM stats_daily WHERE date BETWEEN ? AND ?",
                    (d1, d2)
                ).fetchone()
            else:
                r = db.execute(
                    "SELECT COALESCE(SUM(money_earned),0), COALESCE(SUM(mines),0) FROM stats_daily WHERE date=?",
                    (d1,)
                ).fetchone()
            return r[0], r[1]
        day_m, day_n = stat(day)
        week_m, week_n = stat(week, day)
        month_m, month_n = stat(month, day)
        await callback.message.edit_text(
            f"Статистика:\n\n"
            f"За всё время:\nПользователей: {total}\nБаланс всех: {fmt_money(money)}$\nКопаний: {mines}\n\n"
            f"За день:\nЗаработано: {fmt_money(day_m)}$\nКопаний: {day_n}\n\n"
            f"За неделю:\nЗаработано: {fmt_money(week_m)}$\nКопаний: {week_n}\n\n"
            f"За месяц:\nЗаработано: {fmt_money(month_m)}$\nКопаний: {month_n}",
            reply_markup=admin_keyboard()
        )
        return

    if action == "admin_blacklist":
        rows = db.execute("SELECT user_id, username FROM users WHERE blocked=1 ORDER BY user_id").fetchall()
        text = "Черный список:\n" + ("\n".join(
            f"{r['user_id']} — @{r['username']}" if r["username"] else str(r["user_id"])
            for r in rows
        ) if rows else "Пусто")
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Разблокировать", callback_data="admin_unblock")],
                [InlineKeyboardButton(text="Назад", callback_data="admin_cancel")]
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
        await callback.message.edit_text(
            "Точно очистить данные всех пользователей?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Да, очистить", callback_data="admin_confirm_clear_all")],
                [InlineKeyboardButton(text="Отмена", callback_data="admin_cancel")]
            ])
        )
        return

    if action == "admin_broadcast":
        admin_target_states[callback.from_user.id] = "admin_broadcast"
        await callback.message.answer("Введите текст рассылки.")
        return

@dp.callback_query(F.data == "admin_confirm_clear_all")
async def admin_confirm_clear_all(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    db.execute("""
        UPDATE users SET balance=0, shards=0, ores_mined=0, daily_earned=0,
        total_mines=0, pickaxe='обычная', title='', vip_until=0, last_mine=0, last_daily=''
    """)
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

@dp.message(F.text)
async def admin_input(message: Message):
    if not is_admin(message.from_user.id):
        return

    state = admin_target_states.get(message.from_user.id)
    if not state:
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
            if not message.text.isdigit():
                await message.answer("Введите количество дней.")
                return
            value = int(message.text)
            current_vip = db.execute(
                "SELECT vip_until FROM users WHERE user_id=?", (target_id,)
            ).fetchone()[0]
            until = max(now_ts(), current_vip) + value * 86400
            db.execute("UPDATE users SET vip_until=? WHERE user_id=?", (until, target_id))
            db.commit()
            admin_target_states.pop(message.from_user.id, None)
            await message.answer("VIP выдан.")
            return

        if action == "shards_amount":
            if not message.text.isdigit():
                await message.answer("Введите количество Осколков титула.")
                return
            value = int(message.text)
            db.execute("UPDATE users SET shards=shards+? WHERE user_id=?", (value, target_id))
            db.commit()
            admin_target_states.pop(message.from_user.id, None)
            await message.answer("Осколки выданы.")
            return

    if not message.text.isdigit():
        await message.answer("Нужен Telegram ID.")
        return

    target_id = int(message.text)
    target = db.execute("SELECT * FROM users WHERE user_id=?", (target_id,)).fetchone()
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
                [InlineKeyboardButton(text="Отмена", callback_data="admin_cancel")]
            ])
        )
        return

    if state == "admin_clear":
        admin_target_states[message.from_user.id] = ("clear_confirm", target_id)
        await message.answer(
            "Точно очистить пользователя?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Да", callback_data=f"confirm_clear:{target_id}")],
                [InlineKeyboardButton(text="Отмена", callback_data="admin_cancel")]
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
