import os
import urllib.request
import json

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

SERVER_URL = os.getenv(
    "SERVER_URL",
    "http://127.0.0.1:8000"
)

# Пока используем компьютер, с которого агент уже отправляет данные.
# Позже заменим это на выбор компьютера из списка.
COMPUTER_ID = "DESKTOP-JMPKV7V"

WINDOWS_AGENT_URL = (
    "https://github.com/BogBan-vis/crm-monitoring/"
    "releases/download/v1.1/CRM_Monitoring_Agent.exe"
)


def get_status():
    url = f"{SERVER_URL}/api/status/{COMPUTER_ID}"

    try:
        with urllib.request.urlopen(
            url,
            timeout=60
        ) as response:

            return json.loads(
                response.read().decode("utf-8")
            )

    except Exception as error:

        return {
            "status": "error",
            "message": str(error)
        }


def format_status(result):

    if result.get("status") == "not_found":

        return (
            f"❌ Данных от компьютера "
            f"{COMPUTER_ID} пока нет."
        )

    if result.get("status") == "error":

        return (
            "❌ Не удалось получить данные "
            "от сервера.\n\n"
            f"{result.get('message', 'Неизвестная ошибка')}"
        )

    data = result.get("data", {})

    received_at = result.get(
        "received_at",
        "неизвестно"
    )

    cpu = data.get("cpu_percent")
    ram = data.get("ram_percent")
    ram_used = data.get("ram_used_gb")
    ram_total = data.get("ram_total_gb")
    connections = data.get("network_connections")

    text = (
        "🖥 CRM Monitoring\n\n"
        f"Компьютер: "
        f"{data.get('computer_id', COMPUTER_ID)}\n"
        f"CPU: {cpu}%\n"
        f"RAM: {ram}% "
        f"({ram_used} / {ram_total} GB)\n"
        f"Сетевые соединения: {connections}\n\n"
        "Диски:\n"
    )

    disks = data.get(
        "disks",
        []
    )

    if disks:

        for disk in disks:

            text += (
                f"{disk.get('mountpoint')} — "
                f"{disk.get('used_gb')} / "
                f"{disk.get('total_gb')} GB "
                f"(свободно "
                f"{disk.get('free_gb')} GB)\n"
            )

    else:

        text += "Нет данных\n"

    text += (
        f"\nПоследнее получение: "
        f"{received_at}"
    )

    return text


def start_keyboard():

    return ReplyKeyboardMarkup(
        [["▶️ Запуск"]],
        resize_keyboard=True,
        one_time_keyboard=False
    )


def main_menu():

    return InlineKeyboardMarkup([
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
        ]
    ])


def windows_menu():

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "⬇️ Скачать Windows Agent",
                url=WINDOWS_AGENT_URL
            )
        ],
        [
            InlineKeyboardButton(
                "📊 Статус компьютера",
                callback_data="status"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Назад",
                callback_data="back_main"
            )
        ]
    ])


def linux_menu():

    return InlineKeyboardMarkup([
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
                callback_data="back_main"
            )
        ]
    ])


async def start(
    update,
    context
):

    await update.message.reply_text(
        "CRM Monitoring Bot",
        reply_markup=start_keyboard()
    )


async def text_handler(
    update,
    context
):

    if update.message.text == "▶️ Запуск":

        await update.message.reply_text(
            "Выберите операционную систему:",
            reply_markup=main_menu()
        )


async def button_handler(
    update,
    context
):

    query = update.callback_query

    await query.answer()

    if query.data == "os_windows":

        await query.edit_message_text(
            "🪟 Windows\n\n"
            "Выберите действие:",
            reply_markup=windows_menu()
        )

    elif query.data == "os_linux":

        await query.edit_message_text(
            "🐧 Linux\n\n"
            "Выберите дистрибутив:",
            reply_markup=linux_menu()
        )

    elif query.data == "status":

        await query.edit_message_text(
            "⏳ Подключение к серверу...\n"
            "Если сервер спит, это может занять "
            "до примерно 1 минуты."
        )

        result = get_status()

        await query.edit_message_text(
            format_status(result),
            reply_markup=windows_menu()
        )

    elif query.data == "back_main":

        await query.edit_message_text(
            "Выберите операционную систему:",
            reply_markup=main_menu()
        )

    elif query.data == "linux_debian":

        await query.edit_message_text(
            "🐧 Debian\n\n"
            "Пакет .deb будет добавлен позже.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="os_linux"
                    )
                ]
            ])
        )

    elif query.data == "linux_astra":

        await query.edit_message_text(
            "🐧 Astra Linux\n\n"
            "Пакет для Astra Linux будет "
            "добавлен позже.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="os_linux"
                    )
                ]
            ])
        )

    elif query.data == "linux_ubuntu":

        await query.edit_message_text(
            "🐧 Ubuntu\n\n"
            "Пакет .deb будет добавлен позже.",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "⬅️ Назад",
                        callback_data="os_linux"
                    )
                ]
            ])
        )


async def ignore_other_messages(
    update,
    context
):

    return


def main():

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    if not token:

        print(
            "Ошибка: переменная "
            "TELEGRAM_BOT_TOKEN "
            "не установлена."
        )

        return

    application = (
        Application.builder()
        .token(token)
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    application.add_handler(
        MessageHandler(
            ~filters.TEXT,
            ignore_other_messages
        )
    )

    print(
        "Telegram-бот запущен."
    )

    application.run_polling()


if __name__ == "__main__":

    main()
