import os
import uuid
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# ─── Paths ───────────────────────────────────────────────
BASE_DIR     = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

# ─── App ─────────────────────────────────────────────────
app = FastAPI(title="Student Presence Monitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets (CSS/JS/images if any)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# ─── Session Manager ─────────────────────────────────────
class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, dict] = {}
        self.teacher_sockets: Dict[str, WebSocket] = {}
        self.student_sockets: Dict[str, WebSocket] = {}

    def create_session(self, teacher_name: str) -> str:
        sid = str(uuid.uuid4())[:8].upper()
        self.sessions[sid] = {
            "id": sid,
            "teacher_name": teacher_name,
            "created_at": datetime.now().isoformat(),
            "students": {},
        }
        return sid

    def add_student(self, session_id: str, student_name: str):
        if session_id not in self.sessions:
            return None
        student_id = str(uuid.uuid4())[:8]
        self.sessions[session_id]["students"][student_id] = {
            "id": student_id,
            "name": student_name,
            "present": True,
            "last_seen": datetime.now().isoformat(),
            "absence_count": 0,
            "joined_at": datetime.now().isoformat(),
        }
        return student_id

    def get_session(self, session_id: str):
        return self.sessions.get(session_id)

    def update_presence(self, session_id: str, student_id: str, present: bool):
        s = self.sessions.get(session_id, {}).get("students", {}).get(student_id)
        if s:
            s["present"] = present
            s["last_seen"] = datetime.now().isoformat()

    def get_students_list(self, session_id: str) -> list:
        return list(self.sessions.get(session_id, {}).get("students", {}).values())


mgr = SessionManager()

# ─── Pages ───────────────────────────────────────────────
@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/teacher")
async def teacher():
    return FileResponse(FRONTEND_DIR / "teacher.html")

@app.get("/student")
async def student():
    return FileResponse(FRONTEND_DIR / "student.html")

# ─── REST API ────────────────────────────────────────────
@app.post("/api/session/create")
async def create_session(data: dict):
    name = data.get("teacher_name", "معلم")
    sid  = mgr.create_session(name)
    return {"session_id": sid, "teacher_name": name}

@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    s = mgr.get_session(session_id.upper())
    return s if s else {"error": "جلسه یافت نشد"}

@app.post("/api/session/{session_id}/join")
async def join_session(session_id: str, data: dict):
    name       = data.get("student_name", "دانش‌آموز")
    student_id = mgr.add_student(session_id.upper(), name)
    if not student_id:
        return {"error": "جلسه یافت نشد"}
    return {"student_id": student_id, "session_id": session_id.upper()}

# ─── WebSocket: Teacher ──────────────────────────────────
@app.websocket("/ws/teacher/{session_id}")
async def ws_teacher(websocket: WebSocket, session_id: str):
    await websocket.accept()
    sid = session_id.upper()
    mgr.teacher_sockets[sid] = websocket
    try:
        s = mgr.get_session(sid)
        if s:
            await websocket.send_json({"type": "init", "session": s})
        while True:
            await asyncio.sleep(2)
            await websocket.send_json({
                "type": "update",
                "students": mgr.get_students_list(sid),
                "timestamp": datetime.now().isoformat(),
            })
    except WebSocketDisconnect:
        mgr.teacher_sockets.pop(sid, None)

# ─── WebSocket: Student ──────────────────────────────────
@app.websocket("/ws/student/{session_id}/{student_id}")
async def ws_student(websocket: WebSocket, session_id: str, student_id: str):
    await websocket.accept()
    sid = session_id.upper()
    mgr.student_sockets[student_id] = websocket

    THRESHOLD      = 300   # 5 minutes
    ALERT_COOLDOWN = 60    # re-alert every 60 s
    absence_start  = None
    last_alert     = None

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") != "presence":
                continue

            is_present = bool(data.get("present", False))
            mgr.update_presence(sid, student_id, is_present)
            now = datetime.now()

            if is_present:
                absence_start = None
                last_alert    = None
                await websocket.send_json({"type": "ack", "present": True,
                                           "absence_seconds": 0, "remaining_seconds": THRESHOLD})
            else:
                if absence_start is None:
                    absence_start = now
                elapsed   = int((now - absence_start).total_seconds())
                remaining = max(0, THRESHOLD - elapsed)

                await websocket.send_json({
                    "type": "ack", "present": False,
                    "absence_seconds": elapsed, "remaining_seconds": remaining,
                })

                # Fire alert
                if elapsed >= THRESHOLD:
                    need_alert = last_alert is None or (now - last_alert).total_seconds() >= ALERT_COOLDOWN
                    if need_alert:
                        last_alert = now
                        sess = mgr.get_session(sid)
                        sinfo = (sess or {}).get("students", {}).get(student_id, {})
                        if sinfo:
                            sinfo["absence_count"] = sinfo.get("absence_count", 0) + 1
                        tw = mgr.teacher_sockets.get(sid)
                        if tw:
                            try:
                                await tw.send_json({
                                    "type": "alert",
                                    "student_id": student_id,
                                    "student_name": sinfo.get("name", "دانش‌آموز"),
                                    "absence_minutes": elapsed // 60,
                                    "timestamp": now.isoformat(),
                                })
                            except Exception:
                                pass
    except WebSocketDisconnect:
        mgr.update_presence(sid, student_id, False)
        mgr.student_sockets.pop(student_id, None)
