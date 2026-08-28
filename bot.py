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
from aiogram.types import FSInputFile



BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 5134277438
OWNER_USERNAME = "@emptinessdurka"

DB_FILE = "/app/data/bot.db"
REWARD = 10
COOLDOWN = 3600
MASCOT_PATH = "/app/data/maskot.jpeg"


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


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

# Состояние админ-панели. В боте только один владелец.
admin_states: dict[int, str] = {}


def ensure_user(user_id: int, username: str | None) -> None:
    username = username or ""

    db.execute(
        """
        INSERT INTO users (user_id, username)
        VALUES (?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET username = excluded.username
        """,
        (user_id, username),
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
        WHERE other.points > (
            SELECT points FROM users WHERE user_id = ?
        )
        """,
        (user_id,),
    ).fetchone()
    return row["rank"] if row else None


def main_inline_keyboard(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎁 Получить очки", callback_data="main_claim")],
        [
            InlineKeyboardButton(text="👤 Профиль", callback_data="main_profile"),
            InlineKeyboardButton(text="🏆 Лидеры", callback_data="main_leaders"),
        ],
        [InlineKeyboardButton(text="📰 Новости", callback_data="main_news")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="main_help")],
    ]
    if user_id == OWNER_ID:
        rows.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    if user is None:
        return False

    ensure_user(user.id, user.username)
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
    if user is None:
        return

    ensure_user(user.id, user.username)
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

    # У старых пользователей могла остаться прежняя Reply-клавиатура.
    # Убираем её один раз при /start, затем показываем новое inline-меню.
    if user.id != OWNER_ID:
        cleanup = await message.answer("✨", reply_markup=ReplyKeyboardRemove())
        try:
            await cleanup.delete()
        except Exception:
            pass

    await message.answer(
        "🎉 <b>Добро пожаловать в самого бесполезного бота в вашей жизни!</b> 🤡\n"
        "🎯 Собирай очки каждый час и попади в лидеры 🏆\n"
        "😎 Автор: @emptinessdurka",
        reply_markup=main_inline_keyboard(user.id),
    )


@dp.callback_query(F.data == "main_claim")
async def claim(callback) -> None:
    message = callback.message
    user = callback.from_user
    if message is None or user is None:
        return
    await callback.answer()
    if not await check_access(message):
        return

    user_id = user.id
    now = int(time.time())

    # Атомарная проверка и выдача награды защищает от двойного начисления
    # при почти одновременных запросах.
    cursor = db.execute(
        """
        UPDATE users
        SET points = points + ?,
            last_claim = ?
        WHERE user_id = ?
          AND last_claim <= ?
          AND banned = 0
        """,
        (REWARD, now, user_id, now - COOLDOWN),
    )
    db.commit()

    if cursor.rowcount == 0:
        row = get_user(user_id)
        remaining = get_remaining(row["last_claim"]) if row else COOLDOWN

        await message.edit_text(
            "⏳ Награду нельзя забрать сейчас!\n"
            f"Попробуйте через {format_remaining(remaining)} 🕐",
            reply_markup=main_inline_keyboard(user_id),
        )
        return

    await message.edit_text(
        f"🎁 Вы получили {REWARD} очков!\n"
        "Возвращайтесь через 1 час! ⏰",
        reply_markup=main_inline_keyboard(user_id),
    )


@dp.callback_query(F.data == "main_profile")
async def profile_callback(callback) -> None:
    user = callback.from_user
    message = callback.message
    if user is None or message is None:
        return
    await callback.answer()
    if not await check_access(message):
        return
    row = get_user(user.id)
    if row is None:
        return
    rank = get_rank(row["user_id"])
    await message.edit_text(
        "👤 <b>Ваш профиль:</b>\n"
        f"Юзернейм - {username_text(row)}\n"
        f"Очки - {row['points']} 💰\n"
        f"Место в топе - {rank} 🏆",
        reply_markup=back_main_keyboard(),
    )


def back_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")]]
    )


@dp.callback_query(F.data == "main_news")
async def news_callback(callback) -> None:
    user = callback.from_user
    message = callback.message
    if user is None or message is None:
        return
    await callback.answer()
    if not await check_access(message):
        return
    await message.edit_text(
        "📰 <b>Новости</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📰 Открыть новостной канал", url="https://t.me/points_collector_channel")],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="main_menu")],
        ]),
    )


@dp.callback_query(F.data == "main_leaders")
async def leaders_callback(callback) -> None:
    user = callback.from_user
    message = callback.message
    if user is None or message is None:
        return
    await callback.answer()
    if not await check_access(message):
        return
    rows = db.execute("SELECT * FROM users ORDER BY points DESC, user_id ASC LIMIT 5").fetchall()
    places = ["👑", "2 место", "3 место", "4 место", "5 место"]
    text = "🏆 <b>Лидеры</b>\n\n"
    for index, row in enumerate(rows):
        text += f"{places[index]}: {username_text(row)} - {row['points']} очков\n"
    if not rows:
        text += "Пока здесь никого нет 😴\n"
    await message.edit_text(text, reply_markup=back_main_keyboard())


@dp.callback_query(F.data == "main_menu")
async def main_menu_callback(callback) -> None:
    user = callback.from_user
    message = callback.message
    if user is None or message is None:
        return
    await callback.answer()
    if not await check_access(message):
        return
    await message.edit_text(
        "🎉 <b>Добро пожаловать в самого бесполезного бота в вашей жизни!</b> 🤡\n"
        "🎯 Собирай очки каждый час и попади в лидеры 🏆\n"
        "😎 Автор: @emptinessdurka",
        reply_markup=main_inline_keyboard(user.id),
    )



def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📖 Основа", callback_data="help_base"),
                InlineKeyboardButton(text="🧹 Вайпы", callback_data="help_wipes"),
            ],
            [
                InlineKeyboardButton(text="🏅 Значки", callback_data="help_badges"),
            ],
        ]
    )


def help_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="help_home")]
        ]
    )


HELP_HOME = (
    "Привет, я Уголёк! 🐾\n"
    "Готова рассказать тебе всё ✨"
)

HELP_BASE = (
    "📖 <b>Основа</b>\n\n"
    "В меню есть кнопка «🎁 Получить очки». Нажимай на неё и получай "
    "10 очков каждый час! ⏰\n\n"
    "В «👤 Профиле» ты можешь увидеть количество своих очков и место "
    "в таблице лидеров. 🏆\n\n"
    "В «🏆 Лидерах» ты можешь отслеживать лучших игроков.\n\n"
    "В «📰 Новостях» ты найдёшь ссылку для перехода в новостной канал "
    "бота. Там вся полезная информация и опросы. 💌"
)

HELP_WIPES = (
    "🧹 <b>Вайпы</b>\n\n"
    "Вайп от английского wipe означает «стереть» или «очистить».\n\n"
    "Вайпы, то есть очистка очков, нужны для баланса между новичками "
    "и теми, кто играет давно. ⚖️\n\n"
    "Девятого числа каждого месяца в новостном канале проходит опрос. "
    "После него решается, будет ли в этом месяце сброс всех очков или нет. 📊"
)

HELP_BADGES = (
    "🏅 <b>Значки</b>\n\n"
    "Наверняка ты замечал(а) в лидерах какие-то значки после никнейма. "
    "Вот что они значат:\n\n"
    "😎 - администрация бота. Этот значок есть только у владельца бота.\n\n"
    "🚫 - блокировка. Человек заблокирован в боте и не может ничего в нём делать."
)


async def send_help(message: Message) -> None:
    if not await check_access(message):
        return

    if os.path.exists(MASCOT_PATH):
        await message.answer_photo(
            photo=FSInputFile(MASCOT_PATH),
            caption=HELP_HOME,
            reply_markup=help_keyboard(),
        )
    else:
        await message.answer(
            HELP_HOME + "\n\n💡 Файл maskot.jpeg пока не найден, но раздел помощи уже работает.",
            reply_markup=help_keyboard(),
        )


async def edit_help_message(callback, text: str, markup: InlineKeyboardMarkup) -> None:
    """Меняет текст помощи независимо от того, отправлена она с фото или без него."""
    message = callback.message
    if message is None:
        return

    if message.photo:
        await message.edit_caption(caption=text, reply_markup=markup)
    else:
        await message.edit_text(text, reply_markup=markup)


@dp.message(Command("help"))
async def help_command(message: Message) -> None:
    await send_help(message)


@dp.callback_query(F.data == "main_help")
async def help_button(callback) -> None:
    message = callback.message
    if message is None:
        return
    await callback.answer()
    await send_help(message)


@dp.callback_query(F.data == "help_home")
async def help_home_callback(callback) -> None:
    await callback.answer()
    await edit_help_message(callback, HELP_HOME, help_keyboard())


@dp.callback_query(F.data == "help_base")
async def help_base_callback(callback) -> None:
    await callback.answer()
    await edit_help_message(callback, HELP_BASE, help_back_keyboard())


@dp.callback_query(F.data == "help_wipes")
async def help_wipes_callback(callback) -> None:
    await callback.answer()
    await edit_help_message(callback, HELP_WIPES, help_back_keyboard())


@dp.callback_query(F.data == "help_badges")
async def help_badges_callback(callback) -> None:
    await callback.answer()
    await edit_help_message(callback, HELP_BADGES, help_back_keyboard())


@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback) -> None:
    if callback.from_user is None or callback.from_user.id != OWNER_ID or callback.message is None:
        await callback.answer("Недоступно", show_alert=True)
        return
    await callback.answer()
    admin_states.pop(OWNER_ID, None)
    await callback.message.answer("⚙️ <b>Админ-панель</b>", reply_markup=admin_keyboard())


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
        "Пользователи и их аккаунты останутся на месте.\n"
        "Напишите ДА для продолжения.",
        reply_markup=cancel_keyboard(),
    )



@dp.message(F.text == "🗑️ Очистить всех пользователей")
async def clear_all_users_start(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states[OWNER_ID] = "delete_users_first"

    await message.answer(
        "⚠️ <b>Удаление всех пользователей</b>\n\n"
        "Все аккаунты пользователей будут удалены из базы, вместе с очками, "
        "таймерами и блокировками.\n\n"
        "Напишите ДА для продолжения.",
        reply_markup=cancel_keyboard(),
    )


@dp.message(F.text == "❌ Отмена")
async def cancel(message: Message) -> None:
    if not is_owner(message):
        return

    admin_states.pop(OWNER_ID, None)

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
        reply_markup=main_inline_keyboard(OWNER_ID),
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

    if state == "delete_users_first":
        if text.upper() != "ДА":
            await message.answer(
                "❌ Напишите ДА для продолжения.",
                reply_markup=cancel_keyboard(),
            )
            return

        admin_states[OWNER_ID] = "delete_users_second"

        await message.answer(
            "⚠️ Последнее подтверждение.\n\n"
            "Будут удалены все аккаунты пользователей. "
            "После этого счётчик пользователей станет 0.\n\n"
            "Напишите УДАЛИТЬ для подтверждения.",
            reply_markup=cancel_keyboard(),
        )
        return

    if state == "delete_users_second":
        if text.upper() != "УДАЛИТЬ":
            await message.answer(
                "❌ Напишите УДАЛИТЬ для подтверждения.",
                reply_markup=cancel_keyboard(),
            )
            return

        db.execute("DELETE FROM users")
        db.commit()
        admin_states.pop(OWNER_ID, None)

        await message.answer(
            "🗑️ Все аккаунты пользователей удалены.\n"
            "👥 Сейчас в базе: 0 пользователей.\n\n"
            "Новый пользователь снова появится в базе после первого взаимодействия с ботом.",
            reply_markup=admin_keyboard(),
        )
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
            "Очки и таймеры будут сброшены у всех пользователей.\n"
            "Напишите УДАЛИТЬ для подтверждения.",
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

        # Сбрасываем только игровые данные, но сохраняем все аккаунты.
        db.execute(
            """
            UPDATE users
            SET points = 0,
                last_claim = 0
            """
        )
        db.commit()
        admin_states.pop(OWNER_ID, None)

        await message.answer(
            "💥 Все очки и таймеры сброшены.\n"
            "👥 Пользователи и их аккаунты сохранены.",
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
