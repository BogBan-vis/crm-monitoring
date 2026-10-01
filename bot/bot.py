import os
import json
import urllib.request
import urllib.error

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SERVER_URL = os.getenv(
    "SERVER_URL",
    "https://crm-monitoring-8yfm.onrender.com"
).rstrip("/")

API_SECRET = os.getenv("API_SECRET")


def server_request(method, path, data=None, admin=False):
    url = SERVER_URL + path

    headers = {
        "Content-Type": "application/json"
    }

    if admin:
        headers["Authorization"] = f"Bearer {API_SECRET}"

    body = None

    if data is not None:
        body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=10
        ) as response:
            return json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as error:
        try:
            body = error.read().decode("utf-8")
            return json.loads(body)
        except Exception:
            return {
                "status": "error",
                "message": f"HTTP {error.code}"
            }

    except Exception as error:
        return {
            "status": "error",
            "message": str(error)
        }


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "🔗 Привязать компьютер",
                callback_data="pair"
            )
        ],
        [
            InlineKeyboardButton(
                "💻 Мой компьютер",
                callback_data="status"
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


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    context.user_data["waiting_pairing_code"] = False

    await update.message.reply_text(
        "🖥 CRM Monitoring\n\n"
        "Управление мониторингом компьютера.",
        reply_markup=main_menu()
    )


async def button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    if query.data == "pair":
        context.user_data["waiting_pairing_code"] = True

        await query.message.reply_text(
            "Введите 6-значный код привязки, "
            "который показал агент на компьютере."
        )

        return

    if query.data == "status":
        await show_status(
            query.message,
            query.from_user.id
        )

        return

    if query.data == "info":
        await query.message.reply_text(
            "CRM Monitoring\n\n"
            "Компьютер отправляет последнее состояние.\n"
            "История мониторинга не хранится.",
            reply_markup=main_menu()
        )


async def pairing_code(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.user_data.get(
        "waiting_pairing_code"
    ):
        return

    code = update.message.text.strip()

    if len(code) != 6 or not code.isdigit():
        await update.message.reply_text(
            "Код должен состоять ровно из 6 цифр."
        )
        return

    telegram_id = str(
        update.effective_user.id
    )

    result = server_request(
        "POST",
        "/api/pairing/confirm",
        {
            "telegram_id": telegram_id,
            "code": code
        }
    )

    if result.get("status") != "ok":
        await update.message.reply_text(
            "❌ Код недействителен или уже использован.",
            reply_markup=main_menu()
        )
        return

    context.user_data[
        "waiting_pairing_code"
    ] = False

    computer_id = result.get(
        "computer_id",
        "неизвестно"
    )

    await update.message.reply_text(
        "✅ Компьютер успешно привязан.\n\n"
        f"Компьютер: {computer_id}",
        reply_markup=main_menu()
    )


async def show_status(
    message,
    telegram_id
):
    result = server_request(
        "GET",
        f"/api/user/status/{telegram_id}",
        admin=True
    )

    status = result.get("status")

    if status == "not_linked":
        await message.reply_text(
            "Компьютер ещё не привязан.",
            reply_markup=main_menu()
        )
        return

    if status == "not_found":
        await message.reply_text(
            "Компьютер привязан, "
            "но данные от него ещё не получены.",
            reply_markup=main_menu()
        )
        return

    if status != "ok":
        await message.reply_text(
            "Не удалось получить состояние компьютера.",
            reply_markup=main_menu()
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

    cpu = data.get(
        "cpu_percent",
        "—"
    )

    ram = data.get(
        "ram_percent",
        "—"
    )

    disk = data.get(
        "disk_percent",
        "—"
    )

    hostname = data.get(
        "hostname",
        "—"
    )

    received_at = latest.get(
        "received_at",
        "—"
    )

    text = (
        "💻 Мой компьютер\n\n"
        f"ID: {computer_id}\n"
        f"Имя: {hostname}\n\n"
        f"CPU: {cpu}%\n"
        f"RAM: {ram}%\n"
        f"Диск: {disk}%\n\n"
        f"Последние данные: {received_at}"
    )

    await message.reply_text(
        text,
        reply_markup=main_menu()
    )


async def error_handler(
    update,
    context: ContextTypes.DEFAULT_TYPE
):
    print(
        "Telegram error:",
        context.error
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    if not API_SECRET:
        raise RuntimeError(
            "API_SECRET is not configured"
        )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
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
            button
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            pairing_code
        )
    )

    application.add_error_handler(
        error_handler
    )

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
