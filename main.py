import json
import requests
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.concurrency import run_in_threadpool

# --------------------
# 設定
# --------------------
BBS_EXTERNAL_API_BASE_URL = "https://detabase.vercel.app"
max_api_wait_time = 5

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --------------------
# Utility
# --------------------
def getRandomUserAgent():
    return {"User-Agent": "Mozilla/5.0"}

# --------------------
# 外部BBS API
# --------------------
async def fetch_bbs_posts():
    def sync():
        r = requests.get(
            f"{BBS_EXTERNAL_API_BASE_URL}/posts",
            headers=getRandomUserAgent(),
            timeout=max_api_wait_time
        )
        r.raise_for_status()
        return r.json()

    return await run_in_threadpool(sync)


async def post_new_message(client_ip: str, name: str, body: str):
    def sync():
        r = requests.post(
            f"{BBS_EXTERNAL_API_BASE_URL}/post",
            json={"name": name, "body": body},
            headers={
                **getRandomUserAgent(),
                "X-Original-Client-IP": client_ip
            },
            timeout=max_api_wait_time
        )
        r.raise_for_status()

    await run_in_threadpool(sync)

# --------------------
# WebSocket Manager
# --------------------
class WSManager:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, message: dict):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(json.dumps(message))
            except:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

manager = WSManager()

# --------------------
# Routes
# --------------------
@app.get("/chat", response_class=HTMLResponse)
async def chat(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/api/messages")
async def api_messages():
    posts = await fetch_bbs_posts()
    return [
        {
            "username": p["name"],
            "message": p["body"]
        }
        for p in posts
    ]


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)

    try:
        while True:
            text = await ws.receive_text()
            payload = json.loads(text)

            if payload["type"] == "new_message":
                # 外部BBSに保存
                await post_new_message(
                    payload.get("ip", "unknown"),
                    payload["username"],
                    payload["message"]
                )

                # 全クライアントへ即時配信
                event = {
                    "type": "new_message",
                    "username": payload["username"],
                    "message": payload["message"]
                }

                await manager.broadcast(event)

    except WebSocketDisconnect:
        manager.disconnect(ws)
