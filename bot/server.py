import os
import base64
import hashlib
import hmac
import secrets
import json
import asyncio
import urllib.request
import urllib.error
from contextlib import asynccontextmanager
from datetime import datetime

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

API_SECRET = os.getenv("API_SECRET")
ADMIN_SECRET = os.getenv("ADMIN_SECRET")
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

telegram_app = None


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
                    last_seen TIMESTAMPTZ,
                    status TEXT NOT NULL DEFAULT 'active',
                    banned BOOLEAN NOT NULL DEFAULT FALSE,
                    disconnected BOOLEAN NOT NULL DEFAULT FALSE,
                    last_ip TEXT,
                    last_country TEXT,
                    last_city TEXT
                )
            """)

            cur.execute("""
                ALTER TABLE computers
                ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
            """)

            cur.execute("""
                ALTER TABLE computers
                ADD COLUMN IF NOT EXISTS banned BOOLEAN NOT NULL DEFAULT FALSE
            """)

            cur.execute("""
                ALTER TABLE computers
                ADD COLUMN IF NOT EXISTS disconnected BOOLEAN NOT NULL DEFAULT FALSE
            """)

            cur.execute("""
                ALTER TABLE computers
                ADD COLUMN IF NOT EXISTS last_ip TEXT
            """)

            cur.execute("""
                ALTER TABLE computers
                ADD COLUMN IF NOT EXISTS last_country TEXT
            """)

            cur.execute("""
                ALTER TABLE computers
                ADD COLUMN IF NOT EXISTS last_city TEXT
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


def db_create_registration(code, computer_id):
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


def db_confirm_registration(code, telegram_id, token):
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


def db_set_telegram_link(telegram_id, computer_id):
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


def db_create_pairing(code, computer_id):
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
    data,
    ip=None,
    country=None,
    city=None
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
                json.dumps(
                    data,
                    ensure_ascii=False
                ).replace("\\u0000", ""),
            ))

            cur.execute("""
                UPDATE computers
                SET
                    last_seen = NOW(),
                    last_ip = COALESCE(%s, last_ip),
                    last_country = COALESCE(%s, last_country),
                    last_city = COALESCE(%s, last_city)
                WHERE computer_id = %s
            """, (
                ip,
                country,
                city,
                computer_id,
            ))

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


def db_get_computer(computer_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    computer_id,
                    created_at,
                    last_seen,
                    status,
                    banned,
                    disconnected,
                    last_ip,
                    last_country,
                    last_city
                FROM computers
                WHERE computer_id = %s
            """, (computer_id,))

            return cur.fetchone()


def db_get_all_computers():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    computer_id,
                    created_at,
                    last_seen,
                    status,
                    banned,
                    disconnected,
                    last_ip,
                    last_country,
                    last_city
                FROM computers
                ORDER BY computer_id
            """)

            return cur.fetchall()


def db_set_computer_state(
    computer_id,
    status=None,
    banned=None,
    disconnected=None
):
    fields = []
    values = []

    if status is not None:
        fields.append("status = %s")
        values.append(status)

    if banned is not None:
        fields.append("banned = %s")
        values.append(banned)

    if disconnected is not None:
        fields.append("disconnected = %s")
        values.append(disconnected)

    if not fields:
        return

    values.append(computer_id)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE computers
                SET {", ".join(fields)}
                WHERE computer_id = %s
                """,
                values
            )

        conn.commit()


def get_client_ip(request: Request):
    forwarded_for = request.headers.get(
        "X-Forwarded-For"
    )

    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get(
        "X-Real-IP"
    )

    if real_ip:
        return real_ip.strip()

    if request.client:
        return request.client.host

    return None


def get_ip_geolocation(ip):
    if not ip:
        return None, None

    if ip in {
        "127.0.0.1",
        "localhost",
        "::1"
    }:
        return None, None

    try:
        url = f"https://ipinfo.io/{ip}/json"

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CRM-Monitoring-Server"
            },
            method="GET"
        )

        with urllib.request.urlopen(
            request,
            timeout=5
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

        country = result.get("country")
        city = result.get("city")

        return country, city

    except Exception as error:
        print(
            "IP geolocation error:",
            error
        )

        return None, None


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


def check_pc_token(computer_id: str, token: str | None):
    if not API_SECRET or not token:
        return False

    if token.startswith("Bearer "):
        token = token[7:]

    try:
        raw = base64.urlsafe_b64decode(
            token.encode("utf-8")
        ).decode("utf-8")

        token_computer_id, signature = raw.rsplit(":", 1)

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
    if not authorization:
        return False

    token = authorization.strip()

    if token.startswith("Admin "):
        token = token[6:].strip()

        if not ADMIN_SECRET:
            return False

        return hmac.compare_digest(
            token,
            ADMIN_SECRET
        )

    if token.startswith("Bearer "):
        token = token[7:].strip()

    if not API_SECRET:
        return False

    return hmac.compare_digest(
        token,
        API_SECRET
    )


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


async def start(update, context):
    context.user_data["waiting_pairing_code"] = False

    await update.message.reply_text(
        "🖥 CRM Monitoring\n\n"
        "Управление мониторингом компьютера.",
        reply_markup=main_menu()
    )


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
            reply_markup=InlineKeyboardMarkup(keyboard)
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

        telegram_id = str(query.from_user.id)

        existing_computer_id = db_get_telegram_link(
            telegram_id
        )

        if existing_computer_id:

            context.user_data[
                "waiting_pairing_code"
            ] = False

            await query.message.reply_text(
                "✅ Компьютер уже привязан.\n\n"
                f"Компьютер: {existing_computer_id}\n\n"
                "Чтобы посмотреть состояние, "
                "нажмите «💻 Мой компьютер».",
                reply_markup=main_menu()
            )

            return

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

    network_connections = data.get(
        "network_connections",
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

    local_time = data.get(
        "local_time"
    )

    if local_time:
        try:
            local_time_text = datetime.fromisoformat(
                str(local_time)
            ).strftime(
                "%d.%m.%Y %H:%M:%S"
            )

        except Exception:
            local_time_text = str(local_time)

    else:
        local_time_text = "—"

    text = (
        "💻 Мой компьютер\n\n"
        f"ID: {computer_id}\n"
        f"Имя Windows: {hostname}\n\n"
        f"CPU: {cpu}%\n"
        f"Сетевые соединения: {network_connections}\n"
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
        text += "Нет данных о дисках.\n"

    text += (
        "\n🕒 Время компьютера:\n"
        f"{local_time_text}"
    )

    await message.reply_text(
        text,
        reply_markup=main_menu()
    )


async def error_handler(update, context):
    print(
        "Telegram error:",
        context.error
    )


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
            filters.TEXT & ~filters.COMMAND,
            registration_code
        )
    )

    application.add_error_handler(
        error_handler
    )

    return application


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


app = FastAPI(
    title="CRM Monitoring Server",
    lifespan=lifespan
)


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "CRM Monitoring Server"
    }


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
            "message": "computer_id is required"
        }

    code = str(
        secrets.randbelow(900000) + 100000
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
            "message": "telegram_id is required"
        }

    if not code:
        return {
            "status": "error",
            "message": "code is required"
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

    computer_id = registration["computer_id"]

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
        "telegram_id": telegram_id,
        "computer_id": computer_id,
    }


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
            "message": "computer_id is required"
        }

    if not code:
        return {
            "status": "error",
            "message": "code is required"
        }

    registration = db_get_registration(code)

    if registration:
        if registration["computer_id"] != computer_id:
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
            "computer_id": computer_id,
            "token": token,
        }

    computer = db_get_computer(
        computer_id
    )

    if not computer:
        return {
            "status": "error",
            "message": (
                "Invalid or expired "
                "registration code"
            )
        }

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT telegram_id
                FROM telegram_links
                WHERE computer_id = %s
                LIMIT 1
            """, (computer_id,))

            telegram_link = cur.fetchone()

    if not telegram_link:
        return {
            "status": "error",
            "message": (
                "Computer is not linked "
                "to Telegram"
            )
        }

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

    return {
        "status": "ok",
        "computer_id": computer_id,
        "token": token,
    }


@app.get("/api/admin/verify")
def admin_verify(
    authorization: str | None = Header(
        default=None
    ),
):
    if not authorization:
        return {
            "status": "error",
            "message": "Unauthorized",
        }

    token = authorization.strip()

    if not token.startswith("Admin "):
        return {
            "status": "error",
            "message": "Unauthorized",
        }

    token = token[6:].strip()

    if not ADMIN_SECRET:
        return {
            "status": "error",
            "message": "ADMIN_SECRET is not configured",
        }

    if not hmac.compare_digest(
        token,
        ADMIN_SECRET
    ):
        return {
            "status": "error",
            "message": "Unauthorized",
        }

    return {
        "status": "ok",
    }


@app.post("/api/admin/provision")
def provision_pc(
    data: dict,
    authorization: str | None = Header(
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
            "message": "computer_id is required",
        }

    token = create_pc_token(
        computer_id
    )

    if not token:
        return {
            "status": "error",
            "message": "API_SECRET is not configured",
        }

    db_register_computer(
        computer_id
    )

    return {
        "status": "ok",
        "computer_id": computer_id,
        "token": token,
    }


@app.post("/api/metrics")
def receive_metrics(
    data: dict,
    request: Request,
    authorization: str | None = Header(
        default=None
    ),
):
    computer_id = data.get(
        "computer_id"
    )

    if not computer_id:
        return {
            "status": "error",
            "message": "computer_id is required",
        }

    if not check_pc_token(
        computer_id,
        authorization
    ):
        return {
            "status": "error",
            "message": "Unauthorized",
        }

    client_ip = get_client_ip(
        request
    )

    country, city = get_ip_geolocation(
        client_ip
    )

    db_save_metrics(
        computer_id,
        data,
        client_ip,
        country,
        city
    )

    return {
        "status": "ok",
    }


@app.post("/api/pairing/create")
def create_pairing_code(
    data: dict,
    authorization: str | None = Header(
        default=None
    ),
):
    computer_id = data.get(
        "computer_id"
    )

    if not computer_id:
        return {
            "status": "error",
            "message": "computer_id is required",
        }

    if not check_pc_token(
        computer_id,
        authorization
    ):
        return {
            "status": "error",
            "message": "Unauthorized",
        }

    code = str(
        secrets.randbelow(900000) + 100000
    )

    db_create_pairing(
        code,
        computer_id
    )

    return {
        "status": "ok",
        "computer_id": computer_id,
        "code": code,
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
            "message": "telegram_id is required",
        }

    if not code:
        return {
            "status": "error",
            "message": "code is required",
        }

    pairing = db_get_pairing(code)

    if not pairing:
        return {
            "status": "error",
            "message": "Invalid or expired code",
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
        "telegram_id": telegram_id,
        "computer_id": computer_id,
    }


@app.get("/api/status/{computer_id}")
def get_status(
    computer_id: str,
    authorization: str | None = Header(
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

    latest = db_get_metrics(
        computer_id
    )

    if not latest:
        return {
            "status": "not_found",
        }

    return {
        "data": latest["data"],
        "received_at": latest["received_at"].isoformat(),
    }


@app.get("/api/user/status/{telegram_id}")
def get_user_status(
    telegram_id: str,
    authorization: str | None = Header(
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

    computer_id = db_get_telegram_link(
        str(telegram_id)
    )

    if not computer_id:
        return {
            "status": "not_linked",
        }

    latest = db_get_metrics(
        computer_id
    )

    if not latest:
        return {
            "status": "not_found",
            "computer_id": computer_id,
        }

    return {
        "status": "ok",
        "computer_id": computer_id,
        "data": {
            "data": latest["data"],
            "received_at": latest["received_at"].isoformat(),
        },
    }


@app.get("/api/admin/devices")
def admin_devices(
    authorization: str | None = Header(
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

    devices = db_get_all_computers()

    return {
        "status": "ok",
        "devices": [
            {
                "computer_id": device["computer_id"],
                "created_at": device["created_at"].isoformat()
                if device["created_at"]
                else None,
                "last_seen": device["last_seen"].isoformat()
                if device["last_seen"]
                else None,
                "status": device["status"],
                "banned": device["banned"],
                "disconnected": device["disconnected"],
                "last_ip": device["last_ip"],
                "last_country": device["last_country"],
                "last_city": device["last_city"],
            }
            for device in devices
        ],
    }


@app.get("/api/admin/device/{computer_id}")
def admin_device(
    computer_id: str,
    authorization: str | None = Header(
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

    computer = db_get_computer(
        computer_id
    )

    if not computer:
        return {
            "status": "not_found",
        }

    latest = db_get_metrics(
        computer_id
    )

    return {
        "status": "ok",
        "device": {
            "computer_id": computer["computer_id"],
            "created_at": computer["created_at"].isoformat()
            if computer["created_at"]
            else None,
            "last_seen": computer["last_seen"].isoformat()
            if computer["last_seen"]
            else None,
            "status": computer["status"],
            "banned": computer["banned"],
            "disconnected": computer["disconnected"],
            "last_ip": computer["last_ip"],
            "last_country": computer["last_country"],
            "last_city": computer["last_city"],
            "latest_metrics": latest["data"]
            if latest
            else None,
            "metrics_received_at": latest["received_at"].isoformat()
            if latest
            else None,
        },
    }


@app.post("/api/admin/device/{computer_id}/disconnect")
def admin_disconnect_device(
    computer_id: str,
    authorization: str | None = Header(
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

    computer = db_get_computer(
        computer_id
    )

    if not computer:
        return {
            "status": "not_found",
        }

    db_set_computer_state(
        computer_id,
        status="disconnected",
        disconnected=True,
    )

    return {
        "status": "ok",
        "computer_id": computer_id,
        "status": "disconnected",
    }


@app.post("/api/admin/device/{computer_id}/ban")
def admin_ban_device(
    computer_id: str,
    authorization: str | None = Header(
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

    computer = db_get_computer(
        computer_id
    )

    if not computer:
        return {
            "status": "not_found",
        }

    db_set_computer_state(
        computer_id,
        status="banned",
        banned=True,
        disconnected=False,
    )

    return {
        "status": "ok",
        "computer_id": computer_id,
        "status": "banned",
    }


@app.post("/api/admin/device/{computer_id}/unban")
def admin_unban_device(
    computer_id: str,
    authorization: str | None = Header(
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

    computer = db_get_computer(
        computer_id
    )

    if not computer:
        return {
            "status": "not_found",
        }

    db_set_computer_state(
        computer_id,
        status="active",
        banned=False,
        disconnected=False,
    )

    return {
        "status": "ok",
        "computer_id": computer_id,
        "status": "active",
    }


@app.post("/api/admin/device/{computer_id}/unlink")
def admin_unlink_device(
    computer_id: str,
    authorization: str | None = Header(
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

    computer = db_get_computer(
        computer_id
    )

    if not computer:
        return {
            "status": "not_found",
        }

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM telegram_links
                WHERE computer_id = %s
            """, (computer_id,))

            cur.execute("""
                DELETE FROM registration_codes
                WHERE computer_id = %s
            """, (computer_id,))

            cur.execute("""
                DELETE FROM pairing_codes
                WHERE computer_id = %s
            """, (computer_id,))

            cur.execute("""
                UPDATE computers
                SET
                    status = 'disconnected',
                    disconnected = TRUE,
                    banned = FALSE
                WHERE computer_id = %s
            """, (computer_id,))

        conn.commit()

    return {
        "status": "ok",
        "computer_id": computer_id,
        "status": "disconnected",
    }
