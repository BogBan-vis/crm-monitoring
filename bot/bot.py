import os
import urllib.request
import urllib.parse
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

API_SECRET = os.getenv("API_SECRET")

WINDOWS_AGENT_URL = (
    "https://github.com/BogBan-vis/crm-monitoring/"
    "releases/download/v1.1/CRM_Monitoring_Agent.exe"
)


def server_request(
    path,
    method="GET",
    body=None,
    authorization=None
):
    url = f"{SERVER_URL}{path}"

    headers = {}

    if authorization:
        headers["Authorization"] = (
            f"Bearer {authorization}"
        )

    data = None

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            request,
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


def get_user_status(telegram_id):
    if not API_SECRET:
        return {
            "status": "error",
            "message": "API_SECRET не настроен."
        }

    return server_request(
        f"/api/user/status/{telegram_id}",
        authorization=API_SECRET
    )


def format_status(result):
    if result.get("status") == "not_linked":
        return (
            "❌ Компьютер ещё не привязан "
            "к этому Telegram-аккаунту."
        )

    if result.get("status") == "not_found":
        return (
            "⏳ Компьютер привязан, но сервер "
            "ещё не получил от него данные."
        )

    if result.get("status") == "error":
        return (
            "❌ Ошибка сервера.\n\n"
            f"{result.get('message', 'Неизвестная ошибка')}"
        )

    computer_id = result.get(
        "computer_id",
        "неизвестно"
    )

    saved = result.get("data", {})
    data = saved.get("data", {})
    received_at = saved.get(
        "received_at",
        "неизвестно"
    )

    cpu = data.get("cpu_percent")
    ram = data.get("ram_percent")
    ram_used = data.get("ram_used_gb")
    ram_total = data.get("ram_total_gb")
    connections = data.get(
        "network_connections"
    )

    text = (
        "🖥 CRM Monitoring\n\n"
        f"Компьютер: {computer_id}\n"
        f"CPU: {cpu}%\n"
        f"RAM: {ram}% "
        f"({ram_used} / {ram_total} GB)\n"
        f"Сетевые соединения: {connections}\n\n"
        "Диски:\n"
    )

    disks = data.get("disks", [])

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
        ],
        [
            InlineKeyboardButton(
                "🔗 Привязать компьютер",
                callback_data="pair"
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
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "CRM Monitoring Bot",
        reply_markup=start_keyboard()
    )


async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.message.text == "▶️ Запуск":
        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=main_menu()
        )


async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    telegram_id = str(query.from_user.id)

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
            "⏳ Получение данных..."
        )

        result = get_user_status(
            telegram_id
        )

        await query.edit_message_text(
            format_status(result),
            reply_markup=main_menu()
        )

    elif query.data == "pair":
        context.user_data["waiting_pair_code"] = True

        await query.edit_message_text(
            "🔗 Привязка компьютера\n\n"
            "Введите одноразовый код, который "
            "был создан для этого компьютера."
        )

    elif query.data == "back_main":
        await query.edit_message_text(
            "Выберите действие:",
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
            "Пакет для Astra Linux будет добавлен позже.",
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


async def pairing_code_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.user_data.get(
        "waiting_pair_code"
    ):
        return

    code = update.message.text.strip()

    if not code.isdigit() or len(code) != 6:
        await update.message.reply_text(
            "❌ Код должен состоять из 6 цифр."
        )
        return

    telegram_id = str(
        update.effective_user.id
    )

    result = server_request(
        "/api/pairing/confirm",
        method="POST",
        body={
            "telegram_id": telegram_id,
            "code": code
        }
    )

    if result.get("status") == "ok":
        context.user_data[
            "waiting_pair_code"
        ] = False

        computer_id = result.get(
            "computer_id",
            "неизвестно"
        )

        await update.message.reply_text(
            "✅ Компьютер успешно привязан.\n\n"
            f"Компьютер: {computer_id}",
            reply_markup=start_keyboard()
        )

    else:
        await update.message.reply_text(
            "❌ Не удалось привязать компьютер.\n\n"
            f"{result.get('message', 'Неверный код.')}"
        )


async def ignore_other_messages(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    return


def main():
    token = os.getenv(
        "TELEGRAM_BOT_TOKEN"
    )

    if not token:
        print(
            "Ошибка: переменная "
            "TELEGRAM_BOT_TOKEN не установлена."
        )
        return

    application = (
        Application.builder()
        .token(token)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            pairing_code_handler
        ),
        group=0
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        ),
        group=1
    )

    application.add_handler(
        MessageHandler(
            ~filters.TEXT,
            ignore_other_messages
        )
    )

    print("Telegram-бот запущен.")

    application.run_polling()


if __name__ == "__main__":
    main()