import os
import base64
import hashlib
import hmac
import secrets
import asyncio
from datetime import datetime

from fastapi import FastAPI, Header, Request
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from bot.bot import (
    BOT_TOKEN,
    SERVER_URL,
    start,
    button,
    pairing_code,
    error_handler,
)

app = FastAPI(title="CRM Monitoring Server")

API_SECRET = os.getenv("API_SECRET")

latest_data = {}
telegram_links = {}
pairing_codes = {}

telegram_app = None


def create_pc_token(computer_id):
    if not API_SECRET:
        return None

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        computer_id.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    raw = f"{computer_id}:{signature}".encode("utf-8")

    return base64.urlsafe_b64encode(raw).decode("utf-8")


def check_pc_token(computer_id, token):
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
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(
        signature,
        expected_signature
    )


def check_admin(authorization):
    if not API_SECRET or not authorization:
        return False

    if authorization.startswith("Bearer "):
        authorization = authorization[7:]

    return hmac.compare_digest(
        authorization,
        API_SECRET
    )


@app.on_event("startup")
async def startup():
    global telegram_app

    if not BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured"
        )

    if not API_SECRET:
        raise RuntimeError(
            "API_SECRET is not configured"
        )

    telegram_app = (
        Application.builder()
        .token(BOT_TOKEN)
        .updater(None)
        .build()
    )

    telegram_app.add_handler(
        CommandHandler("start", start)
    )

    telegram_app.add_handler(
        CallbackQueryHandler(button)
    )

    telegram_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            pairing_code
        )
    )

    telegram_app.add_error_handler(
        error_handler
    )

    await telegram_app.initialize()
    await telegram_app.start()

    await telegram_app.bot.set_webhook(
        url=f"{SERVER_URL}/telegram/webhook",
        drop_pending_updates=True
    )

    print("Telegram webhook configured")


@app.on_event("shutdown")
async def shutdown():
    global telegram_app

    if telegram_app is not None:
        await telegram_app.stop()
        await telegram_app.shutdown()
        telegram_app = None


async def process_telegram_update(update):
    try:
        await telegram_app.process_update(update)

    except Exception as error:
        print(
            "Telegram update error:",
            error
        )


@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    if telegram_app is None:
        return {
            "status": "error",
            "message": "Telegram bot is not initialized"
        }

    data = await request.json()

    update = Update.de_json(
        data,
        telegram_app.bot
    )

    asyncio.create_task(
        process_telegram_update(update)
    )

    return {
        "status": "ok"
    }


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "CRM Monitoring Server"
    }


@app.post("/api/admin/provision")
def provision_pc(
    data: dict,
    authorization: str | None = Header(default=None)
):
    if not check_admin(authorization):
        return {
            "status": "error",
            "message": "Unauthorized"
        }

    computer_id = data.get("computer_id")

    if not computer_id:
        return {
            "status": "error",
            "message": "computer_id is required"
        }

    token = create_pc_token(computer_id)

    if not token:
        return {
            "status": "error",
            "message": "API_SECRET is not configured"
        }

    return {
        "status": "ok",
        "computer_id": computer_id,
        "token": token
    }


@app.post("/api/metrics")
def receive_metrics(
    data: dict,
    authorization: str | None = Header(default=None)
):
    computer_id = data.get("computer_id")

    if not computer_id:
        return {
            "status": "error",
            "message": "computer_id is required"
        }

    if not check_pc_token(
        computer_id,
        authorization
    ):
        return {
            "status": "error",
            "message": "Unauthorized"
        }

    latest_data[computer_id] = {
        "data": data,
        "received_at": datetime.now().isoformat()
    }

    return {
        "status": "ok"
    }


@app.post("/api/pairing/create")
def create_pairing_code(
    data: dict,
    authorization: str | None = Header(default=None)
):
    computer_id = data.get("computer_id")

    if not computer_id:
        return {
            "status": "error",
            "message": "computer_id is required"
        }

    if not check_pc_token(
        computer_id,
        authorization
    ):
        return {
            "status": "error",
            "message": "Unauthorized"
        }

    code = str(
        secrets.randbelow(900000) + 100000
    )

    pairing_codes[code] = {
        "computer_id": computer_id,
        "created_at": datetime.now().isoformat()
    }

    return {
        "status": "ok",
        "computer_id": computer_id,
        "code": code
    }


@app.post("/api/pairing/confirm")
def confirm_pairing(data: dict):
    telegram_id = str(
        data.get("telegram_id", "")
    )

    code = str(
        data.get("code", "")
    )

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

    pairing = pairing_codes.get(code)

    if not pairing:
        return {
            "status": "error",
            "message": "Invalid or expired code"
        }

    computer_id = pairing["computer_id"]

    telegram_links[telegram_id] = computer_id

    del pairing_codes[code]

    return {
        "status": "ok",
        "telegram_id": telegram_id,
        "computer_id": computer_id
    }


@app.get("/api/status/{computer_id}")
def get_status(
    computer_id: str,
    authorization: str | None = Header(default=None)
):
    if not check_admin(authorization):
        return {
            "status": "error",
            "message": "Unauthorized"
        }

    if computer_id not in latest_data:
        return {
            "status": "not_found"
        }

    return latest_data[computer_id]


@app.get("/api/user/status/{telegram_id}")
def get_user_status(
    telegram_id: str,
    authorization: str | None = Header(default=None)
):
    if not check_admin(authorization):
        return {
            "status": "error",
            "message": "Unauthorized"
        }

    computer_id = telegram_links.get(
        str(telegram_id)
    )

    if not computer_id:
        return {
            "status": "not_linked"
        }

    if computer_id not in latest_data:
        return {
            "status": "not_found",
            "computer_id": computer_id
        }

    return {
        "status": "ok",
        "computer_id": computer_id,
        "data": latest_data[computer_id]
    }
