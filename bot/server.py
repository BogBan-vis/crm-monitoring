from fastapi import FastAPI
from datetime import datetime


app = FastAPI(title="CRM Monitoring Server")

latest_data = {}


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "CRM Monitoring Server"
    }


@app.post("/api/metrics")
def receive_metrics(data: dict):

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

    return {
        "status": "ok"
    }


@app.get("/api/status/{computer_id}")
def get_status(computer_id: str):

    if computer_id not in latest_data:

        return {
            "status": "not_found"
        }

    return latest_data[computer_id]
