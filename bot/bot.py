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


# =========================
# GitHub
# =========================

GITHUB_WINDOWS_DOWNLOAD = (
    "https://github.com/BogBan-vis/crm-monitoring"
    "/releases/download/v1.1/CRM_Monitoring_Agent.exe"
)


# =========================
# Server request
# =========================

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


# =========================
# Main menu
# =========================

def main_menu():

    keyboard = [

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


# =========================
# Download menu
# =========================

def downloads_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "🪟 Windows",
                callback_data="windows_download"
            )
        ],

        [
            InlineKeyboardButton(
                "🐧 Linux",
                callback_data="linux_download"
            )
        ],

        [
            InlineKeyboardButton(
                "◀️ Назад",
                callback_data="back"
            )
        ]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# Linux menu
# =========================

def linux_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "📦 Debian / Ubuntu",
                callback_data="linux_deb"
            )
        ],

        [
            InlineKeyboardButton(
                "◀️ Назад",
                callback_data="downloads"
            )
        ]

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================
# /start
# =========================

async def start(update, context):

    context.user_data[
        "waiting_pairing_code"
    ] = False

    await update.message.reply_text(

        "🖥 CRM Monitoring\n\n"
        "Управление мониторингом компьютера.",

        reply_markup=main_menu()
    )


# =========================
# Buttons
# =========================

async def button(update, context):

    query = update.callback_query

    await query.answer()


    # -------------------------
    # Downloads
    # -------------------------

    if query.data == "downloads":

        await query.message.reply_text(

            "📥 Скачать агент\n\n"
            "Выберите операционную систему.",

            reply_markup=downloads_menu()
        )

        return


    # -------------------------
    # Windows download
    # -------------------------

    if query.data == "windows_download":

        keyboard = [

            [
                InlineKeyboardButton(
                    "⬇️ Скачать Windows Agent",
                    url=GITHUB_WINDOWS_DOWNLOAD
                )
            ],

            [
                InlineKeyboardButton(
                    "◀️ Назад",
                    callback_data="downloads"
                )
            ]

        ]

        await query.message.reply_text(

            "🪟 Windows\n\n"
            "Нажмите кнопку ниже для загрузки агента.",

            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

        return


    # -------------------------
    # Linux
    # -------------------------

    if query.data == "linux_download":

        await query.message.reply_text(

            "🐧 Linux\n\n"
            "Выберите вариант.",

            reply_markup=linux_menu()
        )

        return


    # -------------------------
    # Debian / Ubuntu
    # -------------------------

    if query.data == "linux_deb":

        await query.message.reply_text(

            "🐧 Linux\n\n"
            "Пакет агента для Debian / Ubuntu "
            "пока не опубликован.",

            reply_markup=linux_menu()
        )

        return


    # -------------------------
    # Pair
    # -------------------------

    if query.data == "pair":

        context.user_data[
            "waiting_pairing_code"
        ] = True

        await query.message.reply_text(

            "🔗 Привязка компьютера\n\n"

            "1. Запустите агент на компьютере.\n"
            "2. Нажмите в агенте "
            "«Получить код привязки».\n"
            "3. Введите сюда полученные 6 цифр."

        )

        return


    # -------------------------
    # Status
    # -------------------------

    if query.data == "status":

        await show_status(
            query.message,
            query.from_user.id
        )

        return


    # -------------------------
    # Information
    # -------------------------

    if query.data == "info":

        await query.message.reply_text(

            "CRM Monitoring\n\n"

            "Компьютер отправляет последнее состояние.\n"
            "История мониторинга не хранится.",

            reply_markup=main_menu()
        )

        return


    # -------------------------
    # Back
    # -------------------------

    if query.data == "back":

        await query.message.reply_text(

            "🖥 CRM Monitoring",

            reply_markup=main_menu()
        )

        return


# =========================
# Pairing code
# =========================

async def pairing_code(update, context):

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


    result = await server_request_async(

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


# =========================
# Computer status
# =========================

async def show_status(message, telegram_id):

    result = await server_request_async(

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

        error_message = result.get(
            "message",
            "неизвестная ошибка"
        )

        await message.reply_text(

            "❌ Не удалось получить состояние компьютера.\n\n"
            f"Ошибка: {error_message}",

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


# =========================
# Error handler
# =========================

async def error_handler(update, context):

    print(
        "Telegram error:",
        context.error
    )
