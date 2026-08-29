import asyncio
import os
import sqlite3
import time
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)



BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 5134277438
OWNER_USERNAME = "@emptinessdurka"

DB_FILE = "/app/data/bot.db"
REWARD = 10
COOLDOWN = 3600


if not BOT_TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN. Установите переменную окружения BOT_TOKEN."
    )


db = sqlite3.connect(DB_FILE)
db.row_factory = sqlite3.Row

db.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT NOT NULL DEFAULT '',
        points INTEGER NOT NULL DEFAULT 0,
        last_claim INTEGER NOT NULL DEFAULT 0,
        banned INTEGER NOT NULL DEFAULT 0
    )
    """
)
db.commit()

# Сохраняем признак бота для защиты списка лидеров.
try:
    db.execute("ALTER TABLE users ADD COLUMN is_bot INTEGER NOT NULL DEFAULT 0")
    db.commit()
except sqlite3.OperationalError:
    pass

db.execute("CREATE INDEX IF NOT EXISTS idx_users_leaderboard ON users(is_bot, points DESC, user_id ASC)")
db.commit()

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# Состояние админ-панели. В боте только один владелец.
admin_states: dict[int, str] = {}


def ensure_user(user_id: int, username: str | None, is_bot: bool = False) -> None:
    username = username or ""
    db.execute(
        """
        INSERT INTO users (user_id, username, is_bot)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET username = excluded.username, is_bot = excluded.is_bot
        """,
        (user_id, username, int(is_bot)),
    )
    db.commit()


def get_user(user_id: int):
    return db.execute(
        "SELECT * FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()


def find_user(identifier: str):
    identifier = identifier.strip()

    if not identifier:
        return None

    # Поддержка как @username/username, так и числового Telegram ID.
    if identifier.lstrip("-").isdigit():
        return db.execute(
            "SELECT * FROM users WHERE user_id = ? LIMIT 1",
            (int(identifier),),
        ).fetchone()

    username = identifier.lstrip("@").lower()

    return db.execute(
        """
        SELECT * FROM users
        WHERE LOWER(username) = ?
        LIMIT 1
        """,
        (username,),
    ).fetchone()


def username_text(user) -> str:
    if user["user_id"] == OWNER_ID:
        return f"{escape(OWNER_USERNAME)} 😎"

    if user["username"]:
        name = f"@{escape(user['username'].lstrip('@'))}"
    else:
        name = f"ID {user['user_id']}"

    if user["banned"]:
        name += " 🚫"

    return name


def get_remaining(last_claim: int) -> int:
    return max(0, COOLDOWN - (int(time.time()) - last_claim))


def format_remaining(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds %= 60

    if hours:
        return f"{hours} ч. {minutes} мин."
    if minutes:
        return f"{minutes} мин. {seconds} сек."
    return f"{seconds} сек."


def get_rank(user_id: int):
    row = db.execute(
        """
        SELECT 1 + COUNT(*) AS rank
        FROM users AS other
        WHERE other.is_bot = 0
          AND other.points > (
            SELECT points FROM users WHERE user_id = ? AND is_bot = 0
        )
        """,
        (user_id,),
    ).fetchone()
    return row["rank"] if row else None


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Получить очки", callback_data="claim")],
            [
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
                InlineKeyboardButton(text="🏆 Лидеры", callback_data="leaders"),
            ],
            [InlineKeyboardButton(text="📰 Новости", callback_data="news")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="help")],
        ]
    )

def owner_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Получить очки")],
            [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏆 Лидеры")],
            [KeyboardButton(text="📰 Новости")],
            [KeyboardButton(text="⚙️ Админ-панель")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🚫 Забанить"),
                KeyboardButton(text="♻️ Чёрный список"),
            ],
            [KeyboardButton(text="🧹 Очистить игрока")],
            [KeyboardButton(text="👥 Пользователи")],
            [KeyboardButton(text="📢 Рассылка")],
            [KeyboardButton(text="💥 Сбросить очки")],
            [KeyboardButton(text="🗑️ Очистить всех пользователей")],
            [KeyboardButton(text="🔙 Главное меню")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        is_persistent=True,
    )


async def check_access(message: Message) -> bool:
    user = message.from_user
    if user is None or message.chat.type != "private":
        return False

    if user.is_bot and user.id != OWNER_ID:
        return False

    ensure_user(user.id, user.username, user.is_bot)
    row = get_user(user.id)
    if row is None:
        return False

    if row["banned"] and user.id != OWNER_ID:
        await message.answer(
            "🚫 <b>Ваша учётная запись была заблокирована в боте!</b>\n"
            "Подать апелляцию - @emptinessdurka"
        )
        return False

    return True


def is_owner(message: Message) -> bool:
    return message.from_user is not None and message.from_user.id == OWNER_ID


@dp.message(CommandStart())
async def start(message: Message) -> None:
    user = message.from_user
    if user is None or message.chat.type != "private" or user.is_bot:
        return

    ensure_user(user.id, user.username, user.is_bot)
    row = get_user(user.id)
    if row is None:
        await message.answer("Не удалось создать профиль. Попробуйте ещё раз.")
        return

    if row["banned"] and user.id != OWNER_ID:
        await message.answer(
            "🚫 <b>Ваша учётная запись была заблокирована в боте!</b>\n"
            "Подать апелляцию - @emptinessdurka"
        )
        return

    if user.id != OWNER_ID:
        # Убираем старую Reply-клавиатуру из предыдущей версии бота.
        await message.answer("✨ Обновляю меню...", reply_markup=ReplyKeyboardRemove())

    await message.answer(
        "🎉 <b>Добро пожаловать в самого бесполезного бота в вашей жизни!</b> 🤡\n"
        "🎯 Собирай очки каждый час и попади в лидеры 🏆\n"
        "😎 Автор: @emptinessdurka",
        reply_markup=owner_menu_keyboard() if user.id == OWNER_ID else main_keyboard(),
    )

@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    if message.from_user is None or message.chat.type != "private" or message.from_user.is_bot:
        return
    await send_help(message, "help")


async def replace_callback_message(callback, text: str, markup: InlineKeyboardMarkup) -> None:
    """Заменяет содержимое callback-сообщения независимо от того, было ли это фото."""
    message = callback.message
    if message.photo:
        await message.delete()
        await message.answer(text, reply_markup=markup)
    else:
        await message.edit_text(text, reply_markup=markup)

async def send_help(target, section: str = "help") -> None:
    texts = {
        "help": "Привет, я Уголёк! 🐾\nГотова рассказать тебе всё ✨",
        "base": (
            "📖 <b>Основа</b>\n\n"
            "В меню есть кнопка «🎁 Получить очки». Нажимай на неё и получай 10 очков каждый час! "
            "В «Профиле» ты можешь увидеть кол-во своих очков и место в таблице лидеров. "
            "В «Лидерах» ты можешь отслеживать лучших игроков. "
            "В «Новостях» ты найдёшь ссылку для перехода в новостной канал бота, там вся полезная информация и опросы 🐾"
        ),
        "wipes": (
            "🧹 <b>Вайпы</b>\n\n"
            "Вайпы - (от англ. wipe — «стереть», «очистить»)\n\n"
            "Вайпы (очистка серверов) нужна для баланса между новичками и долгими игроками. "
            "В девятое число каждого месяца проходит опрос в новостном канале. После опроса решается будет ли сброс в этом месяце всех очков или нет."
        ),
        "badges": (
            "🏅 <b>Значки</b>\n\n"
            "Наверняка вы замечали в лидерах какие-то значки после никнейма. Что они значат?\n\n"
            "😎 - администрация бота (данный значок есть только у владельца бота)\n\n"
            "🚫 - блокировка (человек заблокирован в боте и не может ничего в нём делать)"
        ),
    }
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Основа", callback_data="help:base"), InlineKeyboardButton(text="🧹 Вайпы", callback_data="help:wipes")],
        [InlineKeyboardButton(text="🏅 Значки", callback_data="help:badges")],
    ]) if section == "help" else InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="help")]])
    text = texts.get(section, texts["help"])
    photo = "/app/data/maskot.jpeg"
    if section == "help" and os.path.exists(photo):
        from aiogram.types import FSInputFile
        if isinstance(target, Message):
            await target.answer_photo(FSInputFile(photo), caption=text, reply_markup=markup)
        elif target.message.photo:
            await target.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await target.message.delete()
            await target.message.answer_photo(FSInputFile(photo), caption=text, reply_markup=markup)
    elif isinstance(target, Message):
        await target.answer(text, reply_markup=markup)
    else:
        await target.message.edit_text(text, reply_markup=markup)

async def build_profile_text(user_id: int) -> str | None:
    row = get_user(user_id)
    if row is None:
        return None
    rank = get_rank(row["user_id"])
    remaining = get_remaining(row["last_claim"])
    timer = "Можно забрать сейчас 🎁" if remaining == 0 else f"До следующего получения: {format_remaining(remaining)} ⏰"
    return (
        "👤 <b>Ваш профиль:</b>\n"
        f"Юзернейм - {username_text(row)}\n"
        f"Очки - {row['points']} 💰\n"
        f"Место в топе - {rank} 🏆\n"
        f"{timer}"
    )

async def claim_action(message: Message, user_id: int) -> None:
    if not await check_access(message):
        return
    now = int(time.time())
    cursor = db.execute(
        """UPDATE users SET points = points + ?, last_claim = ?
           WHERE user_id = ? AND last_claim <= ? AND banned = 0 AND is_bot = 0""",
        (REWARD, now, user_id, now - COOLDOWN),
    )
    db.commit()
    if cursor.rowcount == 0:
        row = get_user(user_id)
        remaining = get_remaining(row["last_claim"]) if row else COOLDOWN
        await message.answer(f"⏳ Награду пока нельзя забрать!\nПопробуйте через {format_remaining(remaining)} 🕐", reply_markup=main_keyboard())
        return
    await message.answer(f"🎁 Вы получили {REWARD} очков!\nСледующее получение будет доступно через 1 час ⏰", reply_markup=main_keyboard())

@dp.message(F.text == "🎁 Получить очки")
async def owner_claim(message: Message) -> None:
    if message.from_user and message.from_user.id == OWNER_ID:
        await claim_action(message, OWNER_ID)

@dp.callback_query(F.data == "claim")
async def claim_callback(callback) -> None:
    if callback.from_user is None or callback.message is None or callback.message.chat.type != "private":
        await callback.answer()
        return
    await callback.answer()
    await claim_action(callback.message, callback.from_user.id)

@dp.callback_query(F.data == "profile")
async def profile_callback(callback) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    user_id = callback.from_user.id
    if not await check_access(callback.message):
        await callback.answer("Недоступно", show_alert=True)
        return
    text = await build_profile_text(user_id)
    if text is not None:
        await replace_callback_message(callback, text, InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить", callback_data="profile")], [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await callback.answer()

@dp.callback_query(F.data == "leaders")
async def leaders_callback(callback) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    if not await check_access(callback.message):
        await callback.answer("Недоступно", show_alert=True)
        return
    rows = db.execute("SELECT * FROM users WHERE is_bot = 0 ORDER BY points DESC, user_id ASC LIMIT 5").fetchall()
    text = "🏆 <b>Лидеры</b>\n\n"
    places = ["👑", "2 место", "3 место", "4 место", "5 место"]
    for index, row in enumerate(rows):
        text += f"{places[index]}: {username_text(row)} - {row['points']} очков\n"
    if not rows:
        text += "Пока здесь никого нет 😴\n"
    await replace_callback_message(callback, text, InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await callback.answer()

@dp.callback_query(F.data == "news")
async def news_callback(callback) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    if not await check_access(callback.message):
        await callback.answer("Недоступно", show_alert=True)
        return
    await replace_callback_message(callback, "📰 <b>Новости</b>", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📰 Открыть новостной канал", url="https://t.me/points_collector_channel")], [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]]))
    await callback.answer()

@dp.callback_query(F.data == "menu")
async def menu_callback(callback) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    if not await check_access(callback.message):
        await callback.answer("Недоступно", show_alert=True)
        return
    await replace_callback_message(
        callback,
        "🎉 <b>Добро пожаловать в самого бесполезного бота в вашей жизни!</b> 🤡\n"
        "🎯 Собирай очки каждый час и попади в лидеры 🏆\n"
        "😎 Автор: @emptinessdurka",
        main_keyboard(),
    )
    await callback.answer()

@dp.callback_query(F.data == "help")
async def help_callback(callback) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    if not await check_access(callback.message):
        await callback.answer("Недоступно", show_alert=True)
        return
    await send_help(callback, "help")
    await callback.answer()

@dp.callback_query(F.data.startswith("help:"))
async def help_section_callback(callback) -> None:
    if callback.from_user is None or callback.message is None:
        await callback.answer()
        return
    if not await check_access(callback.message):
        await callback.answer("Недоступно", show_alert=True)
        return
    await send_help(callback, callback.data.split(":", 1)[1])
    await callback.answer()

@dp.message(F.text == "👤 Профиль")
async def owner_profile(message: Message) -> None:
    if message.from_user and message.from_user.id == OWNER_ID and await check_access(message):
        text = await build_profile_text(OWNER_ID)
        if text:
            await message.answer(text, reply_markup=owner_menu_keyboard())

@dp.message(F.text == "🏆 Лидеры")
async def owner_leaders(message: Message) -> None:
    if message.from_user and message.from_user.id == OWNER_ID:
        rows = db.execute("SELECT * FROM users WHERE is_bot = 0 ORDER BY points DESC, user_id ASC LIMIT 5").fetchall()
        text = "🏆 <b>Лидеры</b>\n\n"
        places = ["👑", "2 место", "3 место", "4 место", "5 место"]
        for index, row in enumerate(rows):
            text += f"{places[index]}: {username_text(row)} - {row['points']} очков\n"
        await message.answer(text, reply_markup=owner_menu_keyboard())

@dp.message(F.text == "📰 Новости")
async def owner_news(message: Message) -> None:
    if message.from_user and message.from_user.id == OWNER_ID:
        await message.answer("📰 <b>Новости</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📰 Открыть новостной канал", url="https://t.me/points_collector_channel")]]))




@dp.message(F.text == "⚙️ Админ-панель")
async def admin_panel(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states.pop(OWNER_ID, None)

    await message.answer(
        "⚙️ <b>Админ-панель</b>",
        reply_markup=admin_keyboard(),
    )


@dp.message(F.text == "🚫 Забанить")
async def ban_start(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states[OWNER_ID] = "ban"

    await message.answer(
        "🚫 Введите юзернейм:",
        reply_markup=cancel_keyboard(),
    )


@dp.message(F.text == "♻️ Чёрный список")
async def blacklist(message: Message) -> None:
    if not is_owner(message):
        return

    rows = db.execute(
        "SELECT * FROM users WHERE banned = 1 ORDER BY user_id"
    ).fetchall()

    text = "♻️ <b>Чёрный список</b>\n\n"

    if rows:
        for row in rows:
            text += f"🚫 {username_text(row)}\n"

        text += "\nВведите имя пользователя для разблокировки:"
        admin_states[OWNER_ID] = "unban"
        markup = cancel_keyboard()
    else:
        text += "Список пуст."
        markup = admin_keyboard()

    await message.answer(text, reply_markup=markup)


@dp.message(F.text == "🧹 Очистить игрока")
async def clear_player_start(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states[OWNER_ID] = "clear_user"

    await message.answer(
        "🧹 Введите юзернейм:",
        reply_markup=cancel_keyboard(),
    )


@dp.message(F.text == "👥 Пользователи")
async def users_count(message: Message) -> None:
    if not is_owner(message):
        return

    row = db.execute(
        "SELECT COUNT(*) AS count FROM users"
    ).fetchone()

    count = row["count"] if row else 0

    await message.answer(
        f"👥 Число пользователей в боте: {count}",
        reply_markup=admin_keyboard(),
    )


@dp.message(F.text == "📢 Рассылка")
async def broadcast_start(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states[OWNER_ID] = "broadcast"
    await message.answer(
        "📢 Введите сообщение для рассылки всем пользователям бота.",
        reply_markup=cancel_keyboard(),
    )


@dp.message(F.text == "💥 Сбросить очки")
async def clear_all_start(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states[OWNER_ID] = "wipe_first"

    await message.answer(
        "⚠️ Сбросить очки у всех пользователей?\n\n"
        "Напишите ДА для продолжения.",
        reply_markup=cancel_keyboard(),
    )


@dp.message(F.text == "🗑️ Очистить всех пользователей")
async def clear_all_users_start(message: Message) -> None:
    if not is_owner(message):
        return
    admin_states[OWNER_ID] = "delete_all_first"
    await message.answer(
        "⚠️ Это полностью удалит все аккаунты пользователей из базы.\n\nНапишите УДАЛИТЬ для продолжения.",
        reply_markup=cancel_keyboard(),
    )

@dp.message(F.text == "❌ Отмена")
async def cancel(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states.pop(OWNER_ID, None)
    profile_states.pop(message.from_user.id, None)

    await message.answer(
        "❌ Действие отменено.",
        reply_markup=admin_keyboard(),
    )


@dp.message(F.text == "🔙 Главное меню")
async def back_to_menu(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states.pop(OWNER_ID, None)

    await message.answer(
        "🏠 Главное меню",
        reply_markup=owner_menu_keyboard(),
    )


@dp.message()
async def admin_input(message: Message) -> None:
    if not is_owner(message):
        return

    state = admin_states.get(OWNER_ID)
    if not state:
        return

    text = (message.text or "").strip()

    if state == "broadcast":
        if not text:
            await message.answer(
                "❌ Сообщение не может быть пустым.",
                reply_markup=cancel_keyboard(),
            )
            return

        rows = db.execute(
            "SELECT user_id FROM users WHERE banned = 0"
        ).fetchall()

        admin_states.pop(OWNER_ID, None)
        sent = 0
        failed = 0

        for row in rows:
            try:
                await bot.send_message(row["user_id"], text)
                sent += 1
            except Exception:
                failed += 1

        await message.answer(
            f"📢 Рассылка завершена.\n"
            f"✅ Доставлено: {sent}\n"
            f"❌ Не доставлено: {failed}",
            reply_markup=admin_keyboard(),
        )
        return

    if state == "ban":
        row = find_user(text)

        if row is None:
            await message.answer(
                "❌ Пользователь не найден.",
                reply_markup=cancel_keyboard(),
            )
            return

        if row["user_id"] == OWNER_ID:
            await message.answer(
                "❌ Нельзя заблокировать владельца бота.",
                reply_markup=cancel_keyboard(),
            )
            return

        if row["banned"]:
            await message.answer(
                "🚫 Пользователь уже заблокирован.",
                reply_markup=cancel_keyboard(),
            )
            return

        db.execute(
            "UPDATE users SET banned = 1 WHERE user_id = ?",
            (row["user_id"],),
        )
        db.commit()
        admin_states.pop(OWNER_ID, None)

        try:
            await bot.send_message(
                row["user_id"],
                "🚫 Ваша учётная запись была заблокирована в боте!\n"
                "Подать апелляцию - @emptinessdurka",
            )
        except Exception:
            pass

        await message.answer(
            f"🚫 {username_text(row)} заблокирован.",
            reply_markup=admin_keyboard(),
        )
        return

    if state == "unban":
        row = find_user(text)

        if row is None:
            await message.answer(
                "❌ Пользователь не найден.",
                reply_markup=cancel_keyboard(),
            )
            return

        if not row["banned"]:
            await message.answer(
                "ℹ️ Пользователь не находится в чёрном списке.",
                reply_markup=cancel_keyboard(),
            )
            return

        db.execute(
            "UPDATE users SET banned = 0 WHERE user_id = ?",
            (row["user_id"],),
        )
        db.commit()
        admin_states.pop(OWNER_ID, None)

        try:
            await bot.send_message(
                row["user_id"],
                "♻️ Ваша учётная запись снова доступна в боте!",
            )
        except Exception:
            pass

        await message.answer(
            f"♻️ {username_text(row)} снова доступен.",
            reply_markup=admin_keyboard(),
        )
        return

    if state == "clear_user":
        row = find_user(text)

        if row is None:
            await message.answer(
                "❌ Пользователь не найден.",
                reply_markup=cancel_keyboard(),
            )
            return

        if row["user_id"] == OWNER_ID:
            await message.answer(
                "❌ Нельзя очистить профиль владельца этим действием.",
                reply_markup=cancel_keyboard(),
            )
            return

        db.execute(
            """
            UPDATE users
            SET points = 0,
                last_claim = 0
            WHERE user_id = ?
            """,
            (row["user_id"],),
        )
        db.commit()
        admin_states.pop(OWNER_ID, None)

        await message.answer(
            f"🧹 Данные игрока {username_text(row)} очищены.",
            reply_markup=admin_keyboard(),
        )
        return

    if state == "delete_all_first":
        if text.upper() != "УДАЛИТЬ":
            await message.answer("❌ Напишите УДАЛИТЬ для подтверждения.", reply_markup=cancel_keyboard())
            return
        db.execute("DELETE FROM users")
        db.commit()
        admin_states.pop(OWNER_ID, None)
        await message.answer("🗑️ Все пользовательские аккаунты удалены из базы.", reply_markup=admin_keyboard())
        return

    if state == "wipe_first":
        if text.upper() != "ДА":
            await message.answer(
                "❌ Напишите ДА для продолжения.",
                reply_markup=cancel_keyboard(),
            )
            return

        admin_states[OWNER_ID] = "wipe_second"

        await message.answer(
            "⚠️ Последнее подтверждение.\n\n"
            "Напишите УДАЛИТЬ для сброса очков.",
            reply_markup=cancel_keyboard(),
        )
        return

    if state == "wipe_second":
        if text.upper() != "УДАЛИТЬ":
            await message.answer(
                "❌ Напишите УДАЛИТЬ для подтверждения.",
                reply_markup=cancel_keyboard(),
            )
            return

        # Обычный вайп не удаляет аккаунты: сбрасываются только очки и таймеры.
        db.execute("UPDATE users SET points = 0, last_claim = 0")
        db.commit()
        admin_states.pop(OWNER_ID, None)

        await message.answer(
            "💥 Очки и таймеры всех пользователей сброшены. Аккаунты сохранены.",
            reply_markup=admin_keyboard(),
        )


async def main() -> None:
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
