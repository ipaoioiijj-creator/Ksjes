import asyncio
import os
import time
from statistics import mean

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Единственный разрешённый Telegram-пользователь
ALLOWED_USERNAME = "emptinessdurka"

# ------------------------------------------------------------
# АДРЕС ЛОКАЛЬНОЙ КОПИИ САЙТА
#
# Например:
# http://127.0.0.1:8080/
# http://localhost:3000/
#
# ------------------------------------------------------------

TARGET_URL = "https://safely-meditative-elephant.tilda.ws"


# Максимальная продолжительность теста
TEST_DURATION = 60


# Максимальный размер ответа.
#
# 100 * 1024 = 102400 байт = 100 КБ
#
MAX_RESPONSE_SIZE = 100 * 1024


# Размер одной порции при потоковом чтении
CHUNK_SIZE = 8192


# Максимальное время одного HTTP-запроса
REQUEST_TIMEOUT = 10


# Режимы нагрузки
#
# ВАЖНО:
# Здесь намеренно только 1 / 2 / 3 RPS.
#
MODES = {
    "light": {
        "name": "🟢 Лёгкий",
        "rps": 10,
    },

    "medium": {
        "name": "🟡 Средний",
        "rps": 200,
    },

    "heavy": {
        "name": "🔴 Сложный",
        "rps": 2000,
    },
}


# ============================================================
# ПРОВЕРКА BOT TOKEN
# ============================================================

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден.\n"
        "Добавь его в файл .env"
    )


# ============================================================
# TELEGRAM
# ============================================================

bot = Bot(
    token=BOT_TOKEN
)

dp = Dispatcher()


# ============================================================
# СОСТОЯНИЕ ТЕСТА
# ============================================================

test_running = False

test_task = None

test_started = 0.0

test_mode = ""


# ============================================================
# СТАТИСТИКА
# ============================================================

total_requests = 0

successful_requests = 0

failed_requests = 0

oversized_responses = 0

timeout_errors = 0

connection_errors = 0

response_times = []

http_codes = {}


# Событие для остановки теста
stop_event = asyncio.Event()


# ============================================================
# ПРОВЕРКА ДОСТУПА
# ============================================================

def is_allowed_user(user) -> bool:

    if user is None:
        return False

    username = (
        user.username or ""
    ).lower().lstrip("@")

    return (
        username
        == ALLOWED_USERNAME.lower()
    )


# ============================================================
# КЛАВИАТУРА
# ============================================================

def main_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🟢 Лёгкий",
                    callback_data="start:light",
                ),
                InlineKeyboardButton(
                    text="🟡 Средний",
                    callback_data="start:medium",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="🔴 Сложный",
                    callback_data="start:heavy",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="📊 Статус",
                    callback_data="status",
                ),

                InlineKeyboardButton(
                    text="🛑 Стоп",
                    callback_data="stop",
                ),
            ],
        ]
    )


# ============================================================
# СБРОС СТАТИСТИКИ
# ============================================================

def reset_statistics():

    global total_requests
    global successful_requests
    global failed_requests

    global oversized_responses
    global timeout_errors
    global connection_errors

    global response_times
    global http_codes

    total_requests = 0
    successful_requests = 0
    failed_requests = 0

    oversized_responses = 0

    timeout_errors = 0

    connection_errors = 0

    response_times = []

    http_codes = {}


# ============================================================
# ФОРМАТ СТАТИСТИКИ
# ============================================================

def get_status_text():

    if test_started:

        elapsed = (
            time.monotonic()
            - test_started
        )

    else:

        elapsed = 0


    if elapsed > 0:

        current_rps = (
            total_requests
            / elapsed
        )

    else:

        current_rps = 0


    # --------------------------------------------------------
    # ВРЕМЯ ОТВЕТА
    # --------------------------------------------------------

    if response_times:

        average = (
            mean(response_times)
            * 1000
        )

        minimum = (
            min(response_times)
            * 1000
        )

        maximum = (
            max(response_times)
            * 1000
        )

        sorted_times = sorted(
            response_times
        )

        p95_index = int(
            len(sorted_times)
            * 0.95
        )

        if (
            p95_index
            >= len(sorted_times)
        ):
            p95_index = (
                len(sorted_times)
                - 1
            )

        p95 = (
            sorted_times[p95_index]
            * 1000
        )

    else:

        average = 0
        minimum = 0
        maximum = 0
        p95 = 0


    # --------------------------------------------------------
    # СОСТОЯНИЕ
    # --------------------------------------------------------

    if test_running:

        state = "🟢 Запущен"

    else:

        state = "🔴 Не запущен"


    # --------------------------------------------------------
    # HTTP-КОДЫ
    # --------------------------------------------------------

    if http_codes:

        codes = ", ".join(
            f"{code}: {count}"
            for code, count
            in sorted(
                http_codes.items()
            )
        )

    else:

        codes = "—"


    return (
        "📊 <b>Статус теста</b>\n\n"

        f"Состояние: {state}\n"

        f"Режим: "
        f"{test_mode or '—'}\n"

        f"Время: "
        f"{elapsed:.1f} сек.\n\n"

        f"🎯 URL:\n"
        f"<code>{TARGET_URL}</code>\n\n"

        f"📨 Всего запросов: "
        f"<b>{total_requests}</b>\n"

        f"✅ Успешных: "
        f"<b>{successful_requests}</b>\n"

        f"❌ Неуспешных: "
        f"<b>{failed_requests}</b>\n"

        f"📦 Слишком большие ответы: "
        f"<b>{oversized_responses}</b>\n"

        f"⏰ Таймауты: "
        f"<b>{timeout_errors}</b>\n"

        f"🔌 Ошибки соединения: "
        f"<b>{connection_errors}</b>\n\n"

        f"⚡ Фактический RPS: "
        f"<b>{current_rps:.2f}</b>\n\n"

        f"⏱ Средний ответ: "
        f"<b>{average:.1f} мс</b>\n"

        f"⬇️ Минимальный: "
        f"<b>{minimum:.1f} мс</b>\n"

        f"⬆️ Максимальный: "
        f"<b>{maximum:.1f} мс</b>\n"

        f"📈 P95: "
        f"<b>{p95:.1f} мс</b>\n\n"

        f"HTTP-коды:\n"
        f"<code>{codes}</code>\n\n"

        f"🔒 Лимит ответа: "
        f"<b>100 КБ</b>"
    )


# ============================================================
# БЕЗОПАСНОЕ ЧТЕНИЕ ОТВЕТА
# ============================================================

async def read_response_limited(
    response
):

    global oversized_responses

    received = 0


    # --------------------------------------------------------
    # ПРОВЕРКА CONTENT-LENGTH
    # --------------------------------------------------------

    content_length = (
        response.headers.get(
            "Content-Length"
        )
    )


    if content_length:

        try:

            declared_size = int(
                content_length
            )

        except (
            ValueError,
            TypeError
        ):

            declared_size = None


        # Если сервер заранее сообщил,
        # что ответ больше 100 КБ —
        # тело вообще не читаем.

        if (
            declared_size is not None
            and declared_size
            > MAX_RESPONSE_SIZE
        ):

            oversized_responses += 1

            # Закрываем ответ
            response.close()

            return False


    # --------------------------------------------------------
    # ПОТОКОВОЕ ЧТЕНИЕ
    # --------------------------------------------------------

    try:

        async for chunk in (
            response.content.iter_chunked(
                CHUNK_SIZE
            )
        ):

            received += len(chunk)


            # ------------------------------------------------
            # ЖЁСТКИЙ ЛИМИТ
            # ------------------------------------------------

            if (
                received
                > MAX_RESPONSE_SIZE
            ):

                oversized_responses += 1

                # Немедленно закрываем соединение.
                response.close()

                return False


        return True


    except Exception:

        response.close()

        raise


# ============================================================
# ОДИН HTTP-ЗАПРОС
# ============================================================

async def make_request(
    session
):

    global total_requests
    global successful_requests
    global failed_requests

    global timeout_errors
    global connection_errors


    started = time.monotonic()


    try:

        # ----------------------------------------------------
        # HTTP GET
        # ----------------------------------------------------

        async with session.get(
            TARGET_URL,

            allow_redirects=True,

            timeout=aiohttp.ClientTimeout(
                total=REQUEST_TIMEOUT,
                connect=5,
                sock_read=REQUEST_TIMEOUT,
            ),
        ) as response:


            # ------------------------------------------------
            # РЕГИСТРИРУЕМ HTTP-КОД
            # ------------------------------------------------

            http_codes[
                response.status
            ] = (
                http_codes.get(
                    response.status,
                    0
                )
                + 1
            )


            # ------------------------------------------------
            # ЧИТАЕМ НЕ БОЛЕЕ 100 КБ
            # ------------------------------------------------

            response_ok = (
                await read_response_limited(
                    response
                )
            )


            elapsed = (
                time.monotonic()
                - started
            )


            total_requests += 1

            response_times.append(
                elapsed
            )


            # ------------------------------------------------
            # УСПЕШНОСТЬ
            # ------------------------------------------------

            if (
                response_ok
                and 200
                <= response.status
                < 400
            ):

                successful_requests += 1

            else:

                failed_requests += 1


    # --------------------------------------------------------
    # ТАЙМАУТ
    # --------------------------------------------------------

    except asyncio.TimeoutError:

        elapsed = (
            time.monotonic()
            - started
        )

        total_requests += 1

        failed_requests += 1

        timeout_errors += 1

        response_times.append(
            elapsed
        )

        print(
            "Request timeout"
        )


    # --------------------------------------------------------
    # ОШИБКА СОЕДИНЕНИЯ
    # --------------------------------------------------------

    except (
        aiohttp.ClientConnectionError,
        aiohttp.ClientConnectorError,
    ) as error:

        elapsed = (
            time.monotonic()
            - started
        )

        total_requests += 1

        failed_requests += 1

        connection_errors += 1

        response_times.append(
            elapsed
        )

        print(
            f"Connection error: {error}"
        )


    # --------------------------------------------------------
    # ПРОЧИЕ ОШИБКИ
    # --------------------------------------------------------

    except Exception as error:

        elapsed = (
            time.monotonic()
            - started
        )

        total_requests += 1

        failed_requests += 1

        response_times.append(
            elapsed
        )

        print(
            f"Request error: {error}"
        )


# ============================================================
# ЗАПУСК ТЕСТА
# ============================================================

async def run_test(
    mode_key
):

    global test_running
    global test_started


    mode = MODES[
        mode_key
    ]


    reset_statistics()


    test_running = True

    test_started = (
        time.monotonic()
    )


    stop_event.clear()


    rps = mode["rps"]


    # --------------------------------------------------------
    # ИНТЕРВАЛ МЕЖДУ ЗАПРОСАМИ
    #
    # 1 RPS = 1 сек
    # 2 RPS = 0.5 сек
    # 3 RPS = ~0.333 сек
    # --------------------------------------------------------

    interval = 1 / rps


    # --------------------------------------------------------
    # CONNECTOR
    #
    # Только одно одновременное соединение.
    # Это дополнительно предотвращает накопление
    # огромного количества запросов.
    # --------------------------------------------------------

    connector = aiohttp.TCPConnector(
        limit=1,
        limit_per_host=1,
        force_close=False,
    )


    timeout = aiohttp.ClientTimeout(
        total=REQUEST_TIMEOUT,
        connect=5,
        sock_read=REQUEST_TIMEOUT,
    )


    try:

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,

            headers={
                "User-Agent":
                    "Local-Diagnostic-Test/1.0"
            },
        ) as session:


            deadline = (
                time.monotonic()
                + TEST_DURATION
            )


            next_request = (
                time.monotonic()
            )


            # ------------------------------------------------
            # ОСНОВНОЙ ЦИКЛ
            # ------------------------------------------------

            while (
                time.monotonic()
                < deadline
                and not stop_event.is_set()
            ):


                # --------------------------------------------
                # ОДИН ЗАПРОС
                # --------------------------------------------

                await make_request(
                    session
                )


                # --------------------------------------------
                # РАССЧИТЫВАЕМ ВРЕМЯ СЛЕДУЮЩЕГО
                # --------------------------------------------

                next_request += interval


                delay = (
                    next_request
                    - time.monotonic()
                )


                if delay > 0:

                    try:

                        await asyncio.wait_for(
                            stop_event.wait(),
                            timeout=delay,
                        )

                    except asyncio.TimeoutError:

                        pass

                else:

                    # Если предыдущий запрос
                    # оказался слишком медленным,
                    # НЕ запускаем очередь из запросов.
                    #
                    # Просто начинаем новый интервал
                    # от текущего времени.

                    next_request = (
                        time.monotonic()
                    )


    except asyncio.CancelledError:

        pass


    except Exception as error:

        print(
            f"Test error: {error}"
        )


    finally:

        test_running = False

        stop_event.set()


# ============================================================
# /START
# ============================================================

@dp.message(
    CommandStart()
)
async def command_start(
    message: Message
):

    if not is_allowed_user(
        message.from_user
    ):

        await message.answer(
            "⛔ Доступ запрещён."
        )

        return


    await message.answer(
        "🖥 <b>Local Load Test</b>\n\n"

        f"🎯 Цель:\n"
        f"<code>{TARGET_URL}</code>\n\n"

        "Режимы:\n"

        "🟢 Лёгкий — "
        "<b>1 запрос/сек</b>\n"

        "🟡 Средний — "
        "<b>2 запроса/сек</b>\n"

        "🔴 Сложный — "
        "<b>3 запроса/сек</b>\n\n"

        f"⏱ Максимальная длительность: "
        f"<b>{TEST_DURATION} сек.</b>\n"

        f"🔒 Максимальный ответ: "
        f"<b>100 КБ</b>\n\n"

        "Выбери режим:",
        reply_markup=main_keyboard(),
    )


# ============================================================
# СТАРТ РЕЖИМА
# ============================================================

@dp.callback_query(
    F.data.startswith("start:")
)
async def start_callback(
    callback: CallbackQuery
):

    global test_task
    global test_mode


    if not is_allowed_user(
        callback.from_user
    ):

        await callback.answer(
            "⛔ Доступ запрещён.",
            show_alert=True,
        )

        return


    if test_running:

        await callback.answer(
            "⚠️ Тест уже запущен.",
            show_alert=True,
        )

        return


    mode_key = (
        callback.data.split(
            ":",
            1
        )[1]
    )


    if mode_key not in MODES:

        await callback.answer(
            "Неизвестный режим.",
            show_alert=True,
        )

        return


    mode = MODES[
        mode_key
    ]


    test_mode = (
        mode["name"]
    )


    test_task = (
        asyncio.create_task(
            run_test(
                mode_key
            )
        )
    )


    await callback.answer(
        f"Запущен {mode['name']}"
    )


    await callback.message.edit_text(
        "🚀 <b>Тест запущен</b>\n\n"

        f"Режим: "
        f"{mode['name']}\n"

        f"Скорость: "
        f"<b>{mode['rps']} RPS</b>\n"

        f"Длительность: "
        f"<b>{TEST_DURATION} сек.</b>\n"

        f"Лимит ответа: "
        f"<b>100 КБ</b>\n\n"

        "📊 Нажми «Статус» "
        "для просмотра статистики.",

        reply_markup=main_keyboard(),
    )


# ============================================================
# СТАТУС
# ============================================================

@dp.callback_query(
    F.data == "status"
)
async def status_callback(
    callback: CallbackQuery
):

    if not is_allowed_user(
        callback.from_user
    ):

        await callback.answer(
            "⛔ Доступ запрещён.",
            show_alert=True,
        )

        return


    await callback.answer()


    await callback.message.edit_text(
        get_status_text(),

        reply_markup=main_keyboard(),
    )


# ============================================================
# СТОП
# ============================================================

@dp.callback_query(
    F.data == "stop"
)
async def stop_callback(
    callback: CallbackQuery
):

    global test_task


    if not is_allowed_user(
        callback.from_user
    ):

        await callback.answer(
            "⛔ Доступ запрещён.",
            show_alert=True,
        )

        return


    if not test_running:

        await callback.answer(
            "Тест сейчас не запущен.",
            show_alert=True,
        )

        return


    # --------------------------------------------------------
    # СИГНАЛ ОСТАНОВКИ
    # --------------------------------------------------------

    stop_event.set()


    # --------------------------------------------------------
    # ОТМЕНЯЕМ ЗАДАЧУ
    # --------------------------------------------------------

    if test_task:

        test_task.cancel()


    await callback.answer(
        "🛑 Тест остановлен."
    )


    await asyncio.sleep(
        0.2
    )


    await callback.message.edit_text(
        "🛑 <b>Тест остановлен</b>\n\n"

        + get_status_text(),

        reply_markup=main_keyboard(),
    )


# ============================================================
# ЗАПУСК
# ============================================================

async def main():

    print(
        "======================================"
    )

    print(
        "Local Load Test Bot"
    )

    print(
        "======================================"
    )

    print(
        f"Target: {TARGET_URL}"
    )

    print(
        "Light : 1 RPS"
    )

    print(
        "Medium: 2 RPS"
    )

    print(
        "Heavy : 3 RPS"
    )

    print(
        "Duration: 60 seconds"
    )

    print(
        "Max response: 100 KB"
    )

    print(
        "Max simultaneous requests: 1"
    )

    print(
        "======================================"
    )


    await dp.start_polling(
        bot
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\nBot stopped."
        )