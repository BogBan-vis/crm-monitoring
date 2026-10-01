import os
import base64
import hashlib
import hmac
from datetime import datetime

from fastapi import FastAPI, Header

app = FastAPI(title="CRM Monitoring Server")

latest_data = {}

API_SECRET = os.getenv("API_SECRET")


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "CRM Monitoring Server"
    }


def create_pc_token(computer_id: str):
    if not API_SECRET:
        return None

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        computer_id.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    raw = f"{computer_id}:{signature}".encode("utf-8")

    return base64.urlsafe_b64encode(raw).decode("utf-8")


def check_pc_token(computer_id: str, token: str | None):
    if not API_SECRET or not token:
        return False

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
    if not API_SECRET:
        return False

    return authorization == f"Bearer {API_SECRET}"


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
