import asyncio
import os
import time
from urllib.parse import urlparse
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
# ============================================================
# НАСТРОЙКИ
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")

ALLOWED_USERNAME = "emptinessdurka"

# ------------------------------------------------------------
# ТОЛЬКО ЛОКАЛЬНЫЙ СЕРВЕР
# ------------------------------------------------------------

TARGET_URL = "https://safely-meditative-elephant.tilda.ws"

ALLOWED_HOSTS = {
    "safely-meditative-elephant.tilda.ws",
}


# ============================================================
# ЛИМИТЫ
# ============================================================

TEST_DURATION = 60

MAX_CONCURRENT = 2000

MAX_RESPONSE_SIZE = 100 * 1024

CHUNK_SIZE = 8192

REQUEST_TIMEOUT = 10


# ============================================================
# РЕЖИМЫ
# ============================================================

MODES = {
    "light": {
        "name": "🟢 Лёгкий",
        "concurrency": 10,
    },

    "medium": {
        "name": "🟡 Средний",
        "concurrency": 100,
    },

    "heavy": {
        "name": "🔴 Сложный",
        "concurrency": 500,
    },

    "extreme": {
        "name": "💀 2000 Concurrent",
        "concurrency": 2000,
    },
}


# ============================================================
# ПРОВЕРКА URL
# ============================================================

parsed_url = urlparse(TARGET_URL)

if parsed_url.hostname not in ALLOWED_HOSTS:
    raise RuntimeError(
        "ОШИБКА: TARGET_URL должен указывать "
        "только на localhost."
    )


if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. "
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
# СОСТОЯНИЕ
# ============================================================

test_running = False

test_task = None

test_started = 0.0

test_mode = ""

current_concurrency = 0


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

active_requests = 0


# ============================================================
# LOCK ДЛЯ СТАТИСТИКИ
# ============================================================

stats_lock = asyncio.Lock()


# ============================================================
# ПРОВЕРКА ПОЛЬЗОВАТЕЛЯ
# ============================================================

def is_allowed_user(user):

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
                    text="💀 2000 Concurrent",
                    callback_data="start:extreme",
                ),
            ],

            [
                InlineKeyboardButton(
                    text="📊 Статус",
                    callback_data="status",
                ),
            ],
        ]
    )


# ============================================================
# СБРОС СТАТИСТИКИ
# ============================================================

async def reset_statistics():

    global total_requests
    global successful_requests
    global failed_requests

    global oversized_responses
    global timeout_errors
    global connection_errors

    global response_times
    global http_codes
    global active_requests

    async with stats_lock:

        total_requests = 0
        successful_requests = 0
        failed_requests = 0

        oversized_responses = 0
        timeout_errors = 0
        connection_errors = 0

        response_times = []

        http_codes = {}

        active_requests = 0


# ============================================================
# ЧТЕНИЕ ОТВЕТА НЕ БОЛЕЕ 100 КБ
# ============================================================

async def read_limited_response(response):

    global oversized_responses

    received = 0

    # --------------------------------------------------------
    # Проверяем Content-Length
    # --------------------------------------------------------

    content_length = response.headers.get(
        "Content-Length"
    )

    if content_length:

        try:
            declared_size = int(
                content_length
            )
        except (TypeError, ValueError):
            declared_size = None

        if (
            declared_size is not None
            and declared_size > MAX_RESPONSE_SIZE
        ):

            async with stats_lock:
                oversized_responses += 1

            response.close()

            return False


    # --------------------------------------------------------
    # Потоковое чтение
    # --------------------------------------------------------

    try:

        async for chunk in response.content.iter_chunked(
            CHUNK_SIZE
        ):

            received += len(chunk)

            if received > MAX_RESPONSE_SIZE:

                async with stats_lock:
                    oversized_responses += 1

                response.close()

                return False

        return True

    except Exception:

        response.close()

        raise


# ============================================================
# ОДИН ЗАПРОС
# ============================================================

async def perform_request(
    session,
):

    global total_requests
    global successful_requests
    global failed_requests

    global timeout_errors
    global connection_errors

    global active_requests

    started = time.monotonic()

    async with stats_lock:
        active_requests += 1

    try:

        async with session.get(
            TARGET_URL,
            allow_redirects=True,
        ) as response:

            code = response.status

            async with stats_lock:

                http_codes[code] = (
                    http_codes.get(
                        code,
                        0
                    ) + 1
                )

            response_ok = (
                await read_limited_response(
                    response
                )
            )

            elapsed = (
                time.monotonic()
                - started
            )

            async with stats_lock:

                total_requests += 1

                response_times.append(
                    elapsed
                )

                if (
                    response_ok
                    and 200 <= code < 400
                ):

                    successful_requests += 1

                else:

                    failed_requests += 1

    except asyncio.TimeoutError:

        elapsed = (
            time.monotonic()
            - started
        )

        async with stats_lock:

            total_requests += 1

            failed_requests += 1

            timeout_errors += 1

            response_times.append(
                elapsed
            )

    except aiohttp.ClientConnectionError:

        elapsed = (
            time.monotonic()
            - started
        )

        async with stats_lock:

            total_requests += 1

            failed_requests += 1

            connection_errors += 1

            response_times.append(
                elapsed
            )

    except Exception as error:

        elapsed = (
            time.monotonic()
            - started
        )

        async with stats_lock:

            total_requests += 1

            failed_requests += 1

            response_times.append(
                elapsed
            )

        print(
            f"Request error: {error}"
        )

    finally:

        async with stats_lock:
            active_requests -= 1


# ============================================================
# ГРУППА ЗАПРОСОВ
# ============================================================

async def worker(
    session,
    end_time,
):

    while (
        time.monotonic()
        < end_time
    ):

        await perform_request(
            session
        )


# ============================================================
# ТЕСТ
# ============================================================

async def run_test(
    mode_key,
):

    global test_running
    global test_started
    global test_mode
    global current_concurrency

    mode = MODES[
        mode_key
    ]

    current_concurrency = min(
        mode["concurrency"],
        MAX_CONCURRENT,
    )

    test_mode = mode["name"]

    await reset_statistics()

    test_running = True

    test_started = (
        time.monotonic()
    )

    end_time = (
        test_started
        + TEST_DURATION
    )


    timeout = aiohttp.ClientTimeout(
        total=REQUEST_TIMEOUT,
        connect=5,
        sock_read=REQUEST_TIMEOUT,
    )


    connector = aiohttp.TCPConnector(
        limit=MAX_CONCURRENT,
        limit_per_host=MAX_CONCURRENT,
        ttl_dns_cache=300,
    )


    tasks = []

    try:

        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                "User-Agent":
                    "Local-Load-Test/1.0"
            },
        ) as session:

            # ------------------------------------------------
            # Создаём заданное количество параллельных workers
            # ------------------------------------------------

            for _ in range(
                current_concurrency
            ):

                task = asyncio.create_task(
                    worker(
                        session,
                        end_time,
                    )
                )

                tasks.append(task)


            # ------------------------------------------------
            # Ждём окончания 60 секунд
            # ------------------------------------------------

            remaining = max(
                0,
                end_time
                - time.monotonic()
            )

            await asyncio.sleep(
                remaining
            )


    except Exception as error:

        print(
            f"Test error: {error}"
        )


    finally:

        # ----------------------------------------------------
        # После 60 секунд прекращаем workers
        # ----------------------------------------------------

        for task in tasks:
            task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        test_running = False

        current_concurrency = 0


# ============================================================
# СТАТИСТИКА
# ============================================================

async def get_status_text():

    async with stats_lock:

        total = total_requests

        successful = (
            successful_requests
        )

        failed = failed_requests

        oversized = (
            oversized_responses
        )

        timeouts = (
            timeout_errors
        )

        connection_errors_count = (
            connection_errors
        )

        active = active_requests

        times = list(
            response_times
        )

        codes = dict(
            http_codes
        )


    if test_started:

        elapsed = (
            time.monotonic()
            - test_started
        )

    else:

        elapsed = 0


    if elapsed > 0:

        rps = (
            total / elapsed
        )

    else:

        rps = 0


    if times:

        average = (
            mean(times)
            * 1000
        )

        minimum = (
            min(times)
            * 1000
        )

        maximum = (
            max(times)
            * 1000
        )

        sorted_times = sorted(
            times
        )

        p95_index = int(
            len(sorted_times)
            * 0.95
        )

        p95_index = min(
            p95_index,
            len(sorted_times) - 1,
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


    if codes:

        codes_text = ", ".join(
            f"{code}: {count}"
            for code, count
            in sorted(
                codes.items()
            )
        )

    else:

        codes_text = "—"


    state = (
        "🟢 Запущен"
        if test_running
        else "🔴 Завершён"
    )


    return (
        "📊 <b>Статус теста</b>\n\n"

        f"Состояние: {state}\n"

        f"Режим: "
        f"{test_mode or '—'}\n"

        f"Concurrency: "
        f"<b>{current_concurrency}</b>\n"

        f"Время: "
        f"{elapsed:.1f} сек.\n\n"

        f"📨 Всего запросов: "
        f"<b>{total}</b>\n"

        f"✅ Успешных: "
        f"<b>{successful}</b>\n"

        f"❌ Неуспешных: "
        f"<b>{failed}</b>\n"

        f"📦 >100 КБ: "
        f"<b>{oversized}</b>\n"

        f"⏰ Таймаутов: "
        f"<b>{timeouts}</b>\n"

        f"🔌 Ошибок соединения: "
        f"<b>{connection_errors_count}</b>\n\n"

        f"⚡ RPS: "
        f"<b>{rps:.2f}</b>\n"

        f"🔄 Сейчас выполняется: "
        f"<b>{active}</b>\n\n"

        f"⏱ Средний latency: "
        f"<b>{average:.1f} мс</b>\n"

        f"⬇️ Минимальный: "
        f"<b>{minimum:.1f} мс</b>\n"

        f"⬆️ Максимальный: "
        f"<b>{maximum:.1f} мс</b>\n"

        f"📈 P95: "
        f"<b>{p95:.1f} мс</b>\n\n"

        f"HTTP-коды:\n"
        f"<code>{codes_text}</code>\n\n"

        f"🔒 Лимит тела ответа: "
        f"<b>100 КБ</b>\n"

        f"⏱ Длительность: "
        f"<b>{TEST_DURATION} сек.</b>"
    )


# ============================================================
# /START
# ============================================================

@dp.message(
    CommandStart()
)
async def start_command(
    message: Message,
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

        f"Цель:\n"
        f"<code>{TARGET_URL}</code>\n\n"

        "🟢 Лёгкий — 10 concurrent\n"
        "🟡 Средний — 100 concurrent\n"
        "🔴 Сложный — 500 concurrent\n"
        "💀 Стресс — 2000 concurrent\n\n"

        f"⏱ Тест: "
        f"<b>{TEST_DURATION} секунд</b>\n"

        f"🔒 Ответ: максимум "
        f"<b>100 КБ</b>\n\n"

        "Выбери режим:",
        reply_markup=main_keyboard(),
    )


# ============================================================
# START BUTTON
# ============================================================

@dp.callback_query(
    F.data.startswith("start:")
)
async def start_test_callback(
    callback: CallbackQuery,
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


    test_task = asyncio.create_task(
        run_test(
            mode_key
        )
    )


    await callback.answer(
        f"Запущен {mode['name']}"
    )


    await callback.message.edit_text(
        "🚀 <b>Тест запущен</b>\n\n"

        f"Режим: "
        f"{mode['name']}\n"

        f"Одновременных запросов: "
        f"<b>{mode['concurrency']}</b>\n"

        f"Продолжительность: "
        f"<b>{TEST_DURATION} сек.</b>\n"

        f"Лимит ответа: "
        f"<b>100 КБ</b>\n\n"

        "📊 Статистика доступна "
        "через кнопку «Статус».\n\n"

        "Тест автоматически завершится "
        "через 60 секунд.",

        reply_markup=main_keyboard(),
    )


# ============================================================
# STATUS BUTTON
# ============================================================

@dp.callback_query(
    F.data == "status"
)
async def status_callback(
    callback: CallbackQuery,
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
        await get_status_text(),
        reply_markup=main_keyboard(),
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    print(
        "===================================="
    )

    print(
        "LOCAL LOAD TEST BOT"
    )

    print(
        "===================================="
    )

    print(
        f"Target: {TARGET_URL}"
    )

    print(
        "Light: 10 concurrent"
    )

    print(
        "Medium: 100 concurrent"
    )

    print(
        "Heavy: 500 concurrent"
    )

    print(
        "Extreme: 2000 concurrent"
    )

    print(
        "Response limit: 100 KB"
    )

    print(
        "Duration: 60 seconds"
    )

    print(
        "===================================="
    )


    await dp.start_polling(
        bot
    )


# ============================================================
# START
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