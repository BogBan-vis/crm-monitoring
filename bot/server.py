import os
import base64
import hashlib
import hmac
import secrets
from datetime import datetime

from fastapi import FastAPI, Header


app = FastAPI(title="CRM Monitoring Server")


API_SECRET = os.getenv("API_SECRET")


# =========================================================
# ХРАНИЛИЩА
# =========================================================

# Только последнее состояние каждого компьютера.
latest_data = {}

# telegram_id -> computer_id
telegram_links = {}

# code -> pairing information
pairing_codes = {}

# code -> registration information
registration_codes = {}


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
# ГЛАВНАЯ
# =========================================================

@app.get("/")
def root():
    return {
        "status": "online",
        "service": "CRM Monitoring Server",
    }


# =========================================================
# ПЕРВИЧНАЯ РЕГИСТРАЦИЯ АГЕНТА
# =========================================================

@app.post("/api/register/start")
def register_start(data: dict):
    """
    Агент вызывает этот маршрут при первом запуске.

    Получает одноразовый 6-значный код.
    API_SECRET агенту не нужен.
    """

    computer_id = str(
        data.get("computer_id", "")
    ).strip()

    if not computer_id:
        return {
            "status": "error",
            "message": "computer_id is required",
        }

    # Генерируем код регистрации.
    code = str(
        secrets.randbelow(900000) + 100000
    )

    registration_codes[code] = {
        "computer_id": computer_id,
        "created_at": datetime.now().isoformat(),
        "confirmed": False,
        "telegram_id": None,
    }

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
    """
    Telegram подтверждает регистрацию компьютера.

    ВАЖНО:
    код здесь НЕ удаляется.

    Агенту ещё необходимо получить токен
    через /api/register/token.
    """

    telegram_id = str(
        data.get("telegram_id", "")
    ).strip()

    code = str(
        data.get("code", "")
    ).strip()

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

    registration = registration_codes.get(code)

    if not registration:
        return {
            "status": "error",
            "message": "Invalid or expired registration code",
        }

    computer_id = registration["computer_id"]

    # Привязываем компьютер к Telegram.
    telegram_links[telegram_id] = computer_id

    # Создаём токен компьютера.
    token = create_pc_token(computer_id)

    if not token:
        return {
            "status": "error",
            "message": "API_SECRET is not configured",
        }

    # Помечаем регистрацию как подтверждённую.
    registration["confirmed"] = True
    registration["telegram_id"] = telegram_id
    registration["token"] = token
    registration["confirmed_at"] = datetime.now().isoformat()

    return {
        "status": "ok",
        "telegram_id": telegram_id,
        "computer_id": computer_id,
    }


# =========================================================
# ПОЛУЧЕНИЕ ТОКЕНА АГЕНТОМ
# =========================================================

@app.post("/api/register/token")
def register_token(data: dict):
    """
    Агент использует этот маршрут после подтверждения
    регистрации в Telegram.

    Передаются компьютер и регистрационный код.

    После успешной выдачи токена код удаляется.
    """

    computer_id = str(
        data.get("computer_id", "")
    ).strip()

    code = str(
        data.get("code", "")
    ).strip()

    if not computer_id:
        return {
            "status": "error",
            "message": "computer_id is required",
        }

    if not code:
        return {
            "status": "error",
            "message": "code is required",
        }

    registration = registration_codes.get(code)

    if not registration:
        return {
            "status": "error",
            "message": "Invalid or expired registration code",
        }

    if registration["computer_id"] != computer_id:
        return {
            "status": "error",
            "message": "Computer ID does not match",
        }

    # Telegram должен сначала подтвердить регистрацию.
    if not registration.get("confirmed"):
        return {
            "status": "error",
            "message": "Registration is not confirmed",
        }

    token = registration.get("token")

    if not token:
        return {
            "status": "error",
            "message": "Registration token is not available",
        }

    # Теперь регистрационный код действительно становится
    # одноразовым и удаляется.
    del registration_codes[code]

    return {
        "status": "ok",
        "computer_id": computer_id,
        "token": token,
    }


# =========================================================
# ADMIN PROVISION
# =========================================================

@app.post("/api/admin/provision")
def provision_pc(
    data: dict,
    authorization: str | None = Header(default=None),
):
    if not check_admin(authorization):
        return {
            "status": "error",
            "message": "Unauthorized",
        }

    computer_id = data.get("computer_id")

    if not computer_id:
        return {
            "status": "error",
            "message": "computer_id is required",
        }

    token = create_pc_token(computer_id)

    if not token:
        return {
            "status": "error",
            "message": "API_SECRET is not configured",
        }

    return {
        "status": "ok",
        "computer_id": computer_id,
        "token": token,
    }


# =========================================================
# ПРИЁМ МЕТРИК
# =========================================================

@app.post("/api/metrics")
def receive_metrics(
    data: dict,
    authorization: str | None = Header(default=None),
):
    computer_id = data.get("computer_id")

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

    latest_data[computer_id] = {
        "data": data,
        "received_at": datetime.now().isoformat(),
    }

    return {
        "status": "ok",
    }


# =========================================================
# СОЗДАНИЕ КОДА ПРИВЯЗКИ
# =========================================================

@app.post("/api/pairing/create")
def create_pairing_code(
    data: dict,
    authorization: str | None = Header(default=None),
):
    computer_id = data.get("computer_id")

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

    pairing_codes[code] = {
        "computer_id": computer_id,
        "created_at": datetime.now().isoformat(),
    }

    return {
        "status": "ok",
        "computer_id": computer_id,
        "code": code,
    }


# =========================================================
# ПОДТВЕРЖДЕНИЕ ПРИВЯЗКИ
# =========================================================

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
            "message": "telegram_id is required",
        }

    if not code:
        return {
            "status": "error",
            "message": "code is required",
        }

    pairing = pairing_codes.get(code)

    if not pairing:
        return {
            "status": "error",
            "message": "Invalid or expired code",
        }

    computer_id = pairing["computer_id"]

    telegram_links[telegram_id] = computer_id

    del pairing_codes[code]

    return {
        "status": "ok",
        "telegram_id": telegram_id,
        "computer_id": computer_id,
    }


# =========================================================
# СТАТУС КОМПЬЮТЕРА
# =========================================================

@app.get("/api/status/{computer_id}")
def get_status(
    computer_id: str,
    authorization: str | None = Header(default=None),
):
    if not check_admin(authorization):
        return {
            "status": "error",
            "message": "Unauthorized",
        }

    if computer_id not in latest_data:
        return {
            "status": "not_found",
        }

    return latest_data[computer_id]


# =========================================================
# СТАТУС КОМПЬЮТЕРА ПОЛЬЗОВАТЕЛЯ
# =========================================================

@app.get("/api/user/status/{telegram_id}")
def get_user_status(
    telegram_id: str,
    authorization: str | None = Header(default=None),
):
    if not check_admin(authorization):
        return {
            "status": "error",
            "message": "Unauthorized",
        }

    computer_id = telegram_links.get(
        str(telegram_id)
    )

    if not computer_id:
        return {
            "status": "not_linked",
        }

    if computer_id not in latest_data:
        return {
            "status": "not_found",
            "computer_id": computer_id,
        }

    return {
        "status": "ok",
        "computer_id": computer_id,
        "data": latest_data[computer_id],
    }
