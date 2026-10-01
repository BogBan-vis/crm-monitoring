import os
import json
import asyncio
import urllib.request
import urllib.error

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SERVER_URL = os.getenv(
    "SERVER_URL",
    "https://crm-monitoring-8yfm.onrender.com"
).rstrip("/")

API_SECRET = os.getenv("API_SECRET")

WINDOWS_AGENT_URL = (
    "https://github.com/BogBan-vis/crm-monitoring"
    "/releases/download/v1.1/CRM_Monitoring_Agent.exe"
)


def server_request(method, path, data=None, admin=False):
    url = f"{SERVER_URL}{path}"

    headers = {
        "Content-Type": "application/json"
    }

    if admin and API_SECRET:
        headers["Authorization"] = f"Bearer {API_SECRET}"

    request_data = None

    if data is not None:
        request_data = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=request_data,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            raw = response.read().decode("utf-8")

            if not raw:
                return {}

            return json.loads(raw)

    except urllib.error.HTTPError as error:

        try:
            raw = error.read().decode("utf-8")
            return json.loads(raw)

        except Exception:
            return {
                "status": "error",
                "message": str(error)
            }

    except Exception as error:

        return {
            "status": "error",
            "message": str(error)
        }


async def server_request_async(
    method,
    path,
    data=None,
    admin=False
):
    return await asyncio.to_thread(
        server_request,
        method,
        path,
        data,
        admin
    )


def main_menu():

    keyboard = [
        [
            InlineKeyboardButton(
                "▶️ Запустить агента",
                callback_data="start_agent"
            ),
            InlineKeyboardButton(
                "⏹ Остановить агента",
                callback_data="stop_agent"
            )
        ],
        [
            InlineKeyboardButton(
                "📥 Скачать агент",
                callback_data="downloads"
            )
        ],
        [
            InlineKeyboardButton(
                "🔗 Привязать компьютер",
                callback_data="pair"
            )
        ],
        [
            InlineKeyboardButton(
                "💻 Мой компьютер",
                callback_data="my_pc"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ Информация",
                callback_data="info"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def downloads_menu():

    keyboard = [
        [
            InlineKeyboardButton(
                "🪟 Windows",
                callback_data="os_windows"
            )
        ],
        [
            InlineKeyboardButton(
                "🐧 Linux",
                callback_data="os_linux"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="back_main"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


def linux_menu():

    keyboard = [
        [
            InlineKeyboardButton(
                "Debian",
                callback_data="linux_debian"
            )
        ],
        [
            InlineKeyboardButton(
                "Astra Linux",
                callback_data="linux_astra"
            )
        ],
        [
            InlineKeyboardButton(
                "Ubuntu",
                callback_data="linux_ubuntu"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="downloads"
            )
        ]
    ]

    return InlineKeyboardMarkup(keyboard)


async def edit_message(query, text, reply_markup=None):

    try:

        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )

    except Exception as error:

        if "Message is not modified" not in str(error):
            raise


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["waiting_pairing_code"] = False

    text = (
        "🤖 CRM Monitoring\n\n"
        "Выберите действие:"
    )

    if update.message:

        await update.message.reply_text(
            text,
            reply_markup=main_menu()
        )

    elif update.callback_query:

        await edit_message(
            update.callback_query,
            text,
            main_menu()
        )


async def button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data


    if data == "back_main":

        context.user_data["waiting_pairing_code"] = False

        await edit_message(
            query,
            "🤖 CRM Monitoring\n\n"
            "Выберите действие:",
            main_menu()
        )

        return


    if data == "downloads":

        await edit_message(
            query,
            "📥 Скачать агент\n\n"
            "Выберите операционную систему:",
            downloads_menu()
        )

        return


    if data == "os_windows":

        keyboard = [
            [
                InlineKeyboardButton(
                    "⬇️ Скачать Windows Agent",
                    url=WINDOWS_AGENT_URL
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Назад",
                    callback_data="downloads"
                )
            ]
        ]

        await edit_message(
            query,
            "🪟 Windows\n\n"
            "Нажмите кнопку ниже для скачивания агента.",
            InlineKeyboardMarkup(keyboard)
        )

        return


    if data == "os_linux":

        await edit_message(
            query,
            "🐧 Linux\n\n"
            "Выберите дистрибутив:",
            linux_menu()
        )

        return


    if data == "linux_debian":

        await edit_message(
            query,
            "Пакет .deb будет добавлен позже.",
            linux_menu()
        )

        return


    if data == "linux_ubuntu":

        await edit_message(
            query,
            "Пакет .deb будет добавлен позже.",
            linux_menu()
        )

        return


    if data == "linux_astra":

        await edit_message(
            query,
            "Пакет для Astra Linux будет добавлен позже.",
            linux_menu()
        )

        return


    if data == "pair":

        context.user_data["waiting_pairing_code"] = True

        await edit_message(
            query,
            "🔗 Привязка компьютера\n\n"
            "Введите 6-значный код, "
            "который показывает агент.",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ])
        )

        return


    if data == "my_pc":

        await show_status(
            query,
            context
        )

        return


    if data == "info":

        await edit_message(
            query,
            "ℹ️ Информация\n\n"
            "CRM Monitoring — система "
            "мониторинга компьютеров.\n\n"
            "Агент отправляет на сервер "
            "актуальное состояние ПК.\n\n"
            "История данных не хранится.",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ])
        )

        return


    if data == "start_agent":

        await edit_message(
            query,
            "▶️ Запуск агента\n\n"
            "Команда запуска отправлена.",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ])
        )

        return


    if data == "stop_agent":

        await edit_message(
            query,
            "⏹ Остановка агента\n\n"
            "Команда остановки отправлена.",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ])
        )

        return


async def pairing_code(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.user_data.get(
        "waiting_pairing_code"
    ):
        return

    code = update.message.text.strip()

    if not code.isdigit() or len(code) != 6:

        await update.message.reply_text(
            "Введите корректный 6-значный код."
        )

        return

    telegram_id = str(
        update.effective_user.id
    )

    result = await server_request_async(
        "POST",
        "/api/pairing/confirm",
        {
            "telegram_id": telegram_id,
            "code": code
        }
    )

    context.user_data["waiting_pairing_code"] = False

    if result.get("status") != "ok":

        await update.message.reply_text(
            "❌ Не удалось привязать компьютер:\n"
            + str(
                result.get(
                    "message",
                    "Неизвестная ошибка"
                )
            ),
            reply_markup=main_menu()
        )

        return

    computer_id = result.get(
        "computer_id",
        "неизвестно"
    )

    await update.message.reply_text(
        "✅ Компьютер успешно привязан.\n\n"
        f"ID: {computer_id}",
        reply_markup=main_menu()
    )


async def show_status(
    query,
    context
):

    telegram_id = str(
        query.from_user.id
    )

    result = await server_request_async(
        "GET",
        f"/api/user/status/{telegram_id}",
        admin=True
    )

    if result.get("status") == "not_linked":

        await edit_message(
            query,
            "💻 Мой компьютер\n\n"
            "Компьютер ещё не привязан.",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔗 Привязать компьютер",
                        callback_data="pair"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ])
        )

        return


    if result.get("status") == "not_found":

        computer_id = result.get(
            "computer_id",
            "неизвестно"
        )

        await edit_message(
            query,
            "💻 Мой компьютер\n\n"
            f"ID: {computer_id}\n\n"
            "Данные от компьютера ещё не получены.",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔄 Обновить",
                        callback_data="my_pc"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ])
        )

        return


    if result.get("status") != "ok":

        await edit_message(
            query,
            "❌ Не удалось получить состояние компьютера.",
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔄 Повторить",
                        callback_data="my_pc"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="back_main"
                    )
                ]
            ])
        )

        return


    computer_id = result.get(
        "computer_id",
        "неизвестно"
    )

    latest = result.get(
        "data",
        {}
    )

    data = latest.get(
        "data",
        {}
    )

    hostname = data.get(
        "hostname",
        "—"
    )

    cpu = data.get(
        "cpu_percent",
        "—"
    )

    threads = data.get(
        "cpu_threads",
        "—"
    )

    ram = data.get(
        "ram_percent",
        "—"
    )

    ram_used = data.get(
        "ram_used_gb"
    )

    ram_total = data.get(
        "ram_total_gb"
    )

    disks = data.get(
        "disks",
        []
    )

    received_at = latest.get(
        "received_at",
        "—"
    )


    if isinstance(cpu, (int, float)):
        cpu_text = f"{cpu:.1f}%"
    else:
        cpu_text = str(cpu)


    if isinstance(ram, (int, float)):
        ram_text = f"{ram:.1f}%"
    else:
        ram_text = str(ram)


    if (
        isinstance(ram_used, (int, float))
        and isinstance(ram_total, (int, float))
    ):

        ram_text += (
            f" ({ram_used:.2f} / "
            f"{ram_total:.2f} GB)"
        )


    text = (
        "💻 Мой компьютер\n\n"
        f"ID: {computer_id}\n"
        f"Имя: {hostname}\n\n"
        f"CPU: {cpu_text}\n"
        f"Потоки CPU: {threads}\n"
        f"RAM: {ram_text}\n\n"
        "💾 Диски:\n"
    )


    if disks:

        for disk in disks:

            device = disk.get(
                "device",
                "—"
            )

            mountpoint = disk.get(
                "mountpoint",
                "—"
            )

            total = disk.get(
                "total_gb",
                "—"
            )

            used = disk.get(
                "used_gb",
                "—"
            )

            free = disk.get(
                "free_gb",
                "—"
            )

            percent = disk.get(
                "percent",
                "—"
            )

            text += (
                f"\n{device} "
                f"({mountpoint})\n"
                f"  Всего: {total} GB\n"
                f"  Занято: {used} GB "
                f"({percent}%)\n"
                f"  Свободно: {free} GB\n"
            )

    else:

        text += "\nДиски не обнаружены.\n"


    text += (
        "\n🕒 Последние данные:\n"
        f"{received_at}"
    )


    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 Обновить",
                callback_data="my_pc"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="back_main"
            )
        ]
    ]


    await edit_message(
        query,
        text,
        InlineKeyboardMarkup(keyboard)
    )


async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print(
        "Telegram error:",
        context.error
    )
