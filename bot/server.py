```python
import os
import base64
import hashlib
import hmac
import secrets
import json
import asyncio
import urllib.request
import urllib.error
from datetime import datetime, timezone
from contextlib import asynccontextmanager

import psycopg
from psycopg.rows import dict_row

from fastapi import FastAPI, Header, Request

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# НАСТРОЙКИ
# =========================================================

API_SECRET = os.getenv("API_SECRET")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

SERVER_URL = os.getenv(
    "SERVER_URL",
    "https://crm-monitoring-8yfm.onrender.com"
).rstrip("/")

DATABASE_URL = os.getenv("DATABASE_URL")

WINDOWS_AGENT_URL = (
    "https://github.com/BogBan-vis/crm-monitoring"
    "/releases/download/v1.1/CRM_Monitoring_Agent.exe"
)


# =========================================================
# TELEGRAM APPLICATION
# =========================================================

telegram_app = None


# =========================================================
# DATABASE
# =========================================================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
    )


def init_database():
    if not DATABASE_URL:
        print("DATABASE_URL is not configured")
        return

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS computers (
                    computer_id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_seen TIMESTAMPTZ
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS telegram_links (
                    telegram_id TEXT PRIMARY KEY,
                    computer_id TEXT NOT NULL
                        REFERENCES computers(computer_id)
                        ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS registration_codes (
                    code TEXT PRIMARY KEY,
                    computer_id TEXT NOT NULL
                        REFERENCES computers(computer_id)
                        ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    confirmed BOOLEAN NOT NULL DEFAULT FALSE,
                    telegram_id TEXT,
                    token TEXT,
                    confirmed_at TIMESTAMPTZ
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS pairing_codes (
                    code TEXT PRIMARY KEY,
                    computer_id TEXT NOT NULL
                        REFERENCES computers(computer_id)
                        ON DELETE CASCADE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS latest_metrics (
                    computer_id TEXT PRIMARY KEY
                        REFERENCES computers(computer_id)
                        ON DELETE CASCADE,
                    data JSONB NOT NULL,
                    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

        conn.commit()

    print("PostgreSQL database initialized")


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ БАЗЫ
# =========================================================

def db_register_computer(computer_id):
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO computers (
                    computer_id
                )
                VALUES (%s)
                ON CONFLICT (computer_id)
                DO NOTHING
            """, (computer_id,))

        conn.commit()


def db_create_registration(
    code,
    computer_id
):
    db_register_computer(computer_id)

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO registration_codes (
                    code,
                    computer_id
                )
                VALUES (%s, %s)
            """, (
                code,
                computer_id,
            ))

        conn.commit()


def db_get_registration(code):
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    code,
                    computer_id,
                    created_at,
                    confirmed,
                    telegram_id,
                    token,
                    confirmed_at
                FROM registration_codes
                WHERE code = %s
            """, (code,))

            return cur.fetchone()


def db_confirm_registration(
    code,
    telegram_id,
    token
):
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                UPDATE registration_codes
                SET
                    confirmed = TRUE,
                    telegram_id = %s,
                    token = %s,
                    confirmed_at = NOW()
                WHERE code = %s
                RETURNING computer_id
            """, (
                telegram_id,
                token,
                code,
            ))

            row = cur.fetchone()

        conn.commit()

    return row


def db_delete_registration(code):
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM registration_codes
                WHERE code = %s
            """, (code,))

        conn.commit()


def db_set_telegram_link(
    telegram_id,
    computer_id
):
    db_register_computer(computer_id)

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO telegram_links (
                    telegram_id,
                    computer_id
                )
                VALUES (%s, %s)
                ON CONFLICT (telegram_id)
                DO UPDATE SET
                    computer_id = EXCLUDED.computer_id
            """, (
                str(telegram_id),
                computer_id,
            ))

        conn.commit()


def db_get_telegram_link(telegram_id):
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT computer_id
                FROM telegram_links
                WHERE telegram_id = %s
            """, (str(telegram_id),))

            row = cur.fetchone()

    if not row:
        return None

    return row["computer_id"]


def db_create_pairing(
    code,
    computer_id
):
    db_register_computer(computer_id)

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO pairing_codes (
                    code,
                    computer_id
                )
                VALUES (%s, %s)
            """, (
                code,
                computer_id,
            ))

        conn.commit()


def db_get_pairing(code):
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    code,
                    computer_id,
                    created_at
                FROM pairing_codes
                WHERE code = %s
            """, (code,))

            return cur.fetchone()


def db_delete_pairing(code):
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM pairing_codes
                WHERE code = %s
            """, (code,))

        conn.commit()


def db_save_metrics(
    computer_id,
    data
):
    db_register_computer(computer_id)

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                INSERT INTO latest_metrics (
                    computer_id,
                    data,
                    received_at
                )
                VALUES (
                    %s,
                    %s::jsonb,
                    NOW()
                )
                ON CONFLICT (computer_id)
                DO UPDATE SET
                    data = EXCLUDED.data,
                    received_at = NOW()
            """, (
                computer_id,
                json.dumps(data, ensure_ascii=False),
            ))

            cur.execute("""
                UPDATE computers
                SET last_seen = NOW()
                WHERE computer_id = %s
            """, (computer_id,))

        conn.commit()


def db_get_metrics(computer_id):
    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    data,
                    received_at
                FROM latest_metrics
                WHERE computer_id = %s
            """, (computer_id,))

            return cur.fetchone()


# =========================================================
# ТОКЕНЫ КОМПЬЮТЕРОВ
# =========================================================

def create_pc_token(computer_id: str):
    if not API_SECRET:
        return None

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        computer_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    raw = f"{computer_id}:{signature}".encode("utf-8")

    return base64.urlsafe_b64encode(raw).decode("utf-8")


def check_pc_token(
    computer_id: str,
    token: str | None
):
    if not API_SECRET or not token:
        return False

    if token.startswith("Bearer "):
        token = token[7:]

    try:
        raw = base64.urlsafe_b64decode(
            token.encode("utf-8")
        ).decode("utf-8")

        token_computer_id, signature = raw.rsplit(
            ":",
            1
        )

    except Exception:
        return False

    if token_computer_id != computer_id:
        return False

    expected_signature = hmac.new(
        API_SECRET.encode("utf-8"),
        computer_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        signature,
        expected_signature,
    )


def check_admin(authorization):
    if not API_SECRET or not authorization:
        return False

    if authorization.startswith("Bearer "):
        authorization = authorization[7:]

    return hmac.compare_digest(
        authorization,
        API_SECRET,
    )


# =========================================================
# TELEGRAM API
# =========================================================

def telegram_api_request(method, data=None):

    if not BOT_TOKEN:
        return {
            "ok": False,
            "description": "TELEGRAM_BOT_TOKEN is not configured",
        }

    url = (
        f"https://api.telegram.org/bot"
        f"{BOT_TOKEN}/{method}"
    )

    body = None

    headers = {
        "Content-Type": "application/json"
    }

    if data is not None:
        body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=15
        ) as response:

            return json.loads(
                response.read().decode("utf-8")
            )

    except Exception as error:

        return {
            "ok": False,
            "description": str(error),
        }


# =========================================================
# TELEGRAM МЕНЮ
# =========================================================

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


# =========================================================
# TELEGRAM /start
# =========================================================

async def start(update, context):

    context.user_data[
        "waiting_pairing_code"
    ] = False

    await update.message.reply_text(

        "🖥 CRM Monitoring\n\n"
        "Управление мониторингом компьютера.",

        reply_markup=main_menu()
    )


# =========================================================
# TELEGRAM КНОПКИ
# =========================================================

async def button(update, context):

    query = update.callback_query

    await query.answer()

    if query.data == "downloads":

        await query.message.reply_text(

            "📥 Скачать агент\n\n"
            "Выберите операционную систему.",

            reply_markup=downloads_menu()
        )

        return

    if query.data == "windows_download":

        keyboard = [

            [
                InlineKeyboardButton(
                    "⬇️ Скачать Windows Agent",
                    url=WINDOWS_AGENT_URL
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

    if query.data == "linux_download":

        await query.message.reply_text(

            "🐧 Linux\n\n"
            "Выберите вариант.",

            reply_markup=linux_menu()
        )

        return

    if query.data == "linux_deb":

        await query.message.reply_text(

            "🐧 Linux\n\n"
            "Пакет агента для Debian / Ubuntu "
            "пока не опубликован.",

            reply_markup=linux_menu()
        )

        return

    if query.data == "pair":

        context.user_data[
            "waiting_pairing_code"
        ] = True

        await query.message.reply_text(

            "🔗 Привязка компьютера\n\n"
            "1. Запустите агент на компьютере.\n"
            "2. Агент автоматически покажет "
            "6-значный код регистрации.\n"
            "3. Введите этот код сюда."

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
            "Компьютер отправляет только последнее "
            "состояние.\n"
            "История мониторинга не хранится.",

            reply_markup=main_menu()
        )

        return

    if query.data == "back":

        await query.message.reply_text(

            "🖥 CRM Monitoring",

            reply_markup=main_menu()
        )

        return


# =========================================================
# ЗАПРОС К НАШЕМУ API
# =========================================================

def server_request(
    method,
    path,
    data=None,
    admin=False
):

    url = SERVER_URL + path

    headers = {
        "Content-Type": "application/json"
    }

    if admin:

        headers[
            "Authorization"
        ] = f"Bearer {API_SECRET}"

    body = None

    if data is not None:

        body = json.dumps(
            data
        ).encode("utf-8")

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

            body = error.read().decode(
                "utf-8"
            )

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


# =========================================================
# ВВОД КОДА РЕГИСТРАЦИИ
# =========================================================

async def registration_code(update, context):

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

        "/api/register/confirm",

        {
            "telegram_id": telegram_id,
            "code": code
        }

    )

    if result.get("status") != "ok":

        await update.message.reply_text(

            "❌ Код недействителен, "
            "истёк или уже использован.",

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

        "✅ Регистрация компьютера подтверждена.\n\n"
        "Агент теперь автоматически получит "
        "токен доступа.\n\n"
        f"Компьютер: {computer_id}",

        reply_markup=main_menu()
    )


# =========================================================
# СТАТУС КОМПЬЮТЕРА
# =========================================================

async def show_status(
    message,
    telegram_id
):

    result = await server_request_async(

        "GET",

        f"/api/user/status/{telegram_id}",

        admin=True
    )

    status = result.get(
        "status"
    )

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

            "❌ Не удалось получить "
            "состояние компьютера.\n\n"
            f"Ошибка: {result.get('message', 'неизвестная ошибка')}",

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

    text = (

        "💻 Мой компьютер\n\n"

        f"ID: {computer_id}\n"
        f"Имя Windows: {hostname}\n\n"

        f"CPU: {cpu}%\n"
        f"Потоки CPU: {threads}\n"
        f"RAM: {ram}%"
    )

    if (
        ram_used is not None
        and ram_total is not None
    ):

        text += (
            f" ({ram_used} / {ram_total} GB)"
        )

    text += "\n\n💾 Диски:\n"

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

                f"\n{device} {mountpoint}\n"

                f"  Всего: {total} GB\n"
                f"  Занято: {used} GB ({percent}%)\n"
                f"  Свободно: {free} GB\n"
            )

    else:

        text += (
            "Нет данных о дисках.\n"
        )

    text += (

        "\n🕒 Последние данные:\n"
        f"{received_at}"
    )

    await message.reply_text(

        text,

        reply_markup=main_menu()
    )


# =========================================================
# TELEGRAM ОШИБКИ
# =========================================================

async def error_handler(
    update,
    context
):

    print(
        "Telegram error:",
        context.error
    )


# =========================================================
# СОЗДАНИЕ TELEGRAM APPLICATION
# =========================================================

def create_telegram_application():

    if not BOT_TOKEN:
        return None

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
            filters.TEXT
            & ~filters.COMMAND,
            registration_code
        )
    )

    application.add_error_handler(
        error_handler
    )

    return application


# =========================================================
# LIFESPAN FASTAPI
# =========================================================

@asynccontextmanager
async def lifespan(app):

    global telegram_app

    print("Starting CRM Monitoring Server")

    try:
        init_database()
    except Exception as error:
        print(
            "DATABASE INITIALIZATION ERROR:",
            error
        )
        raise

    telegram_app = create_telegram_application()

    if telegram_app:

        await telegram_app.initialize()

        await telegram_app.start()

        webhook_url = (
            f"{SERVER_URL}/telegram/webhook"
        )

        result = await telegram_app.bot.set_webhook(
            url=webhook_url
        )

        print(
            "Telegram webhook:",
            webhook_url
        )

        print(
            "Telegram webhook result:",
            result
        )

    else:

        print(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    yield

    if telegram_app:

        await telegram_app.stop()

        await telegram_app.shutdown()


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI(
    title="CRM Monitoring Server",
    lifespan=lifespan
)


# =========================================================
# ГЛАВНАЯ
# =========================================================

@app.get("/")
def root():

    return {

        "status": "online",

        "service": (
            "CRM Monitoring Server"
        )

    }


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request
):

    if not telegram_app:

        return {
            "status": "error",
            "message": (
                "Telegram bot is not configured"
            )
        }

    try:

        body = await request.json()

        update = Update.de_json(
            body,
            telegram_app.bot
        )

        await telegram_app.process_update(
            update
        )

        return {
            "status": "ok"
        }

    except Exception as error:

        print(
            "Telegram webhook error:",
            error
        )

        return {
            "status": "error",
            "message": str(error)
        }


# =========================================================
# ПЕРВИЧНАЯ РЕГИСТРАЦИЯ АГЕНТА
# =========================================================

@app.post("/api/register/start")
def register_start(data: dict):

    computer_id = str(
        data.get(
            "computer_id",
            ""
        )
    ).strip()

    if not computer_id:

        return {

            "status": "error",

            "message": (
                "computer_id is required"
            )

        }

    code = str(
        secrets.randbelow(900000)
        + 100000
    )

    db_create_registration(
        code,
        computer_id
    )

    return {

        "status": "ok",

        "computer_id": computer_id,

        "code": code,

    }


# =========================================================
# ПОДТВЕРЖДЕНИЕ РЕГИСТРАЦИИ TELEGRAM
# =========================================================

@app.post("/api/register/confirm")
def register_confirm(data: dict):

    telegram_id = str(
        data.get(
            "telegram_id",
            ""
        )
    ).strip()

    code = str(
        data.get(
            "code",
            ""
        )
    ).strip()

    if not telegram_id:

        return {

            "status": "error",

            "message": (
                "telegram_id is required"
            )

        }

    if not code:

        return {

            "status": "error",

            "message": (
                "code is required"
            )

        }

    registration = db_get_registration(code)

    if not registration:

        return {

            "status": "error",

            "message": (
                "Invalid or expired "
                "registration code"
            )

        }

    computer_id = registration[
        "computer_id"
    ]

    token = create_pc_token(
        computer_id
    )

    if not token:

        return {

            "status": "error",

            "message": (
                "API_SECRET is not configured"
            )

        }

    db_set_telegram_link(
        telegram_id,
        computer_id
    )

    db_confirm_registration(
        code,
        telegram_id,
        token
    )

    return {

        "status": "ok",

        "telegram_id":
            telegram_id,

        "computer_id":
            computer_id,

    }


# =========================================================
# ПОЛУЧЕНИЕ ТОКЕНА АГЕНТОМ
# =========================================================

@app.post("/api/register/token")
def register_token(data: dict):

    computer_id = str(
        data.get(
            "computer_id",
            ""
        )
    ).strip()

    code = str(
        data.get(
            "code",
            ""
        )
    ).strip()

    if not computer_id:

        return {

            "status": "error",

            "message": (
                "computer_id is required"
            )

        }

    if not code:

        return {

            "status": "error",

            "message": (
                "code is required"
            )

        }

    registration = db_get_registration(code)

    if not registration:

        return {

            "status": "error",

            "message": (
                "Invalid or expired "
                "registration code"
            )

        }

    if (
        registration["computer_id"]
        != computer_id
    ):

        return {

            "status": "error",

            "message": (
                "Computer ID does not match"
            )

        }

    if not registration["confirmed"]:

        return {

            "status": "error",

            "message": (
                "Registration is not confirmed"
            )

        }

    token = registration["token"]

    if not token:

        return {

            "status": "error",

            "message": (
                "Registration token "
                "is not available"
            )

        }

    db_delete_registration(code)

    return {

        "status": "ok",

        "computer_id":
            computer_id,

        "token":
            token,

    }


# =========================================================
# ADMIN PROVISION
# =========================================================

@app.post("/api/admin/provision")
def provision_pc(

    data: dict,

    authorization:
        str | None = Header(
            default=None
        ),

):

    if not check_admin(
        authorization
    ):

        return {

            "status": "error",

            "message": "Unauthorized",

        }

    computer_id = data.get(
        "computer_id"
    )

    if not computer_id:

        return {

            "status": "error",

            "message":
                "computer_id is required",

        }

    token = create_pc_token(
        computer_id
    )

    if not token:

        return {

            "status": "error",

            "message":
                "API_SECRET is not configured",

        }

    db_register_computer(
        computer_id
    )

    return {

        "status": "ok",

        "computer_id":
            computer_id,

        "token":
            token,

    }


# =========================================================
# ПРИЁМ МЕТРИК
# =========================================================

@app.post("/api/metrics")
def receive_metrics(

    data: dict,

    authorization:
        str | None = Header(
            default=None
        ),

):

    computer_id = data.get(
        "computer_id"
    )

    if not computer_id:

        return {

            "status": "error",

            "message":
                "computer_id is required",

        }

    if not check_pc_token(
        computer_id,
        authorization
    ):

        return {

            "status": "error",

            "message":
                "Unauthorized",

        }

    db_save_metrics(
        computer_id,
        data
    )

    return {

        "status": "ok",

    }


# =========================================================
# СТАРАЯ ПРИВЯЗКА
# =========================================================

@app.post("/api/pairing/create")
def create_pairing_code(

    data: dict,

    authorization:
        str | None = Header(
            default=None
        ),

):

    computer_id = data.get(
        "computer_id"
    )

    if not computer_id:

        return {

            "status": "error",

            "message":
                "computer_id is required",

        }

    if not check_pc_token(
        computer_id,
        authorization
    ):

        return {

            "status": "error",

            "message":
                "Unauthorized",

        }

    code = str(
        secrets.randbelow(900000)
        + 100000
    )

    db_create_pairing(
        code,
        computer_id
    )

    return {

        "status": "ok",

        "computer_id":
            computer_id,

        "code":
            code,

    }


@app.post("/api/pairing/confirm")
def confirm_pairing(
    data: dict
):

    telegram_id = str(
        data.get(
            "telegram_id",
            ""
        )
    )

    code = str(
        data.get(
            "code",
            ""
        )
    )

    if not telegram_id:

        return {

            "status": "error",

            "message":
                "telegram_id is required",

        }

    if not code:

        return {

            "status": "error",

            "message":
                "code is required",

        }

    pairing = db_get_pairing(code)

    if not pairing:

        return {

            "status": "error",

            "message":
                "Invalid or expired code",

        }

    computer_id = pairing[
        "computer_id"
    ]

    db_set_telegram_link(
        telegram_id,
        computer_id
    )

    db_delete_pairing(code)

    return {

        "status": "ok",

        "telegram_id":
            telegram_id,

        "computer_id":
            computer_id,

    }


# =========================================================
# СТАТУС КОМПЬЮТЕРА
# =========================================================

@app.get("/api/status/{computer_id}")
def get_status(

    computer_id: str,

    authorization:
        str | None = Header(
            default=None
        ),

):

    if not check_admin(
        authorization
    ):

        return {

            "status": "error",

            "message":
                "Unauthorized",

        }

    latest = db_get_metrics(
        computer_id
    )

    if not latest:

        return {

            "status":
                "not_found",

        }

    return {

        "data":
            latest["data"],

        "received_at":
            latest["received_at"].isoformat(),

    }


# =========================================================
# СТАТУС КОМПЬЮТЕРА ПОЛЬЗОВАТЕЛЯ
# =========================================================

@app.get("/api/user/status/{telegram_id}")
def get_user_status(

    telegram_id: str,

    authorization:
        str | None = Header(
            default=None
        ),

):

    if not check_admin(
        authorization
    ):

        return {

            "status": "error",

            "message":
                "Unauthorized",

        }

    computer_id = db_get_telegram_link(
        str(telegram_id)
    )

    if not computer_id:

        return {

            "status":
                "not_linked",

        }

    latest = db_get_metrics(
        computer_id
    )

    if not latest:

        return {

            "status":
                "not_found",

            "computer_id":
                computer_id,

        }

    return {

        "status":
            "ok",

        "computer_id":
            computer_id,

        "data": {

            "data":
                latest["data"],

            "received_at":
                latest["received_at"].isoformat(),

        },

    }
```
