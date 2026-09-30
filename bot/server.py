import os
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


def check_secret(authorization):
    if not API_SECRET:
        return False

    expected = f"Bearer {API_SECRET}"
    return authorization == expected


@app.post("/api/metrics")
def receive_metrics(
    data: dict,
    authorization: str | None = Header(default=None)
):
    if not check_secret(authorization):
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

    latest_data[computer_id] = {
        "data": data,
        "received_at": datetime.now().isoformat()
    }

    return {"status": "ok"}


@app.get("/api/status/{computer_id}")
def get_status(
    computer_id: str,
    authorization: str | None = Header(default=None)
):
    if not check_secret(authorization):
        return {
            "status": "error",
            "message": "Unauthorized"
        }

    if computer_id not in latest_data:
        return {"status": "not_found"}

    return latest_data[computer_id]
