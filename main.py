from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from datetime import datetime
from typing import Dict
import uuid

BASE_DIR = Path(__file__).parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="Student Presence Monitor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, dict] = {}
        self.teacher_sockets: Dict[str, WebSocket] = {}
        self.student_sockets: Dict[str, WebSocket] = {}

    def create_session(self, teacher_name: str) -> str:
        session_id = str(uuid.uuid4())[:8].upper()
        self.sessions[session_id] = {
            "id": session_id,
            "teacher_name": teacher_name,
            "created_at": datetime.now().isoformat(),
            "students": {},
            "active": True
        }
        return session_id

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
            "joined_at": datetime.now().isoformat()
        }
        return student_id

    def get_session(self, session_id: str):
        return self.sessions.get(session_id)

    def update_presence(self, session_id: str, student_id: str, present: bool):
        if session_id in self.sessions and student_id in self.sessions[session_id]["students"]:
            self.sessions[session_id]["students"][student_id]["present"] = present
            self.sessions[session_id]["students"][student_id]["last_seen"] = datetime.now().isoformat()

    def get_students_status(self, session_id: str) -> list:
        if session_id not in self.sessions:
            return []
        return list(self.sessions[session_id]["students"].values())


manager = SessionManager()


@app.get("/")
async def root():
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/teacher")
async def teacher_page():
    return FileResponse(FRONTEND_DIR / "teacher.html")

@app.get("/student")
async def student_page():
    return FileResponse(FRONTEND_DIR / "student.html")

@app.post("/api/session/create")
async def create_session(data: dict):
    teacher_name = data.get("teacher_name", "معلم")
    session_id = manager.create_session(teacher_name)
    return {"session_id": session_id, "teacher_name": teacher_name}

@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    session = manager.get_session(session_id.upper())
    if not session:
        return {"error": "جلسه یافت نشد"}
    return session

@app.post("/api/session/{session_id}/join")
async def join_session(session_id: str, data: dict):
    student_name = data.get("student_name", "دانش‌آموز")
    student_id = manager.add_student(session_id.upper(), student_name)
    if not student_id:
        return {"error": "جلسه یافت نشد"}
    return {"student_id": student_id, "session_id": session_id.upper()}


@app.websocket("/ws/teacher/{session_id}")
async def teacher_websocket(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session_id = session_id.upper()
    manager.teacher_sockets[session_id] = websocket
    try:
        session = manager.get_session(session_id)
        if session:
            await websocket.send_json({"type": "init", "session": session})
        while True:
            await asyncio.sleep(2)
            students = manager.get_students_status(session_id)
            await websocket.send_json({
                "type": "update",
                "students": students,
                "timestamp": datetime.now().isoformat()
            })
    except WebSocketDisconnect:
        if session_id in manager.teacher_sockets:
            del manager.teacher_sockets[session_id]


@app.websocket("/ws/student/{session_id}/{student_id}")
async def student_websocket(websocket: WebSocket, session_id: str, student_id: str):
    await websocket.accept()
    session_id = session_id.upper()
    manager.student_sockets[student_id] = websocket
    absence_start_time = None
    ABSENCE_THRESHOLD = 300
    last_alert_time = None
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "presence":
                is_present = data.get("present", False)
                manager.update_presence(session_id, student_id, is_present)
                now = datetime.now()
                if is_present:
                    absence_start_time = None
                    last_alert_time = None
                    await websocket.send_json({"type": "ack", "present": True})
                else:
                    if absence_start_time is None:
                        absence_start_time = now
                    elapsed = int((now - absence_start_time).total_seconds())
                    remaining = max(0, ABSENCE_THRESHOLD - elapsed)
                    await websocket.send_json({
                        "type": "ack",
                        "present": False,
                        "absence_seconds": elapsed,
                        "remaining_seconds": remaining
                    })
                    if elapsed >= ABSENCE_THRESHOLD:
                        should_alert = (
                            last_alert_time is None or
                            (now - last_alert_time).total_seconds() >= 60
                        )
                        if should_alert:
                            last_alert_time = now
                            session = manager.get_session(session_id)
                            student_info = None
                            if session and student_id in session["students"]:
                                student_info = session["students"][student_id]
                                session["students"][student_id]["absence_count"] += 1
                            if session_id in manager.teacher_sockets:
                                try:
                                    await manager.teacher_sockets[session_id].send_json({
                                        "type": "alert",
                                        "student_id": student_id,
                                        "student_name": student_info["name"] if student_info else "دانش‌آموز",
                                        "absence_minutes": elapsed // 60,
                                        "timestamp": now.isoformat()
                                    })
                                except Exception:
                                    pass
    except WebSocketDisconnect:
        manager.update_presence(session_id, student_id, False)
        if student_id in manager.student_sockets:
            del manager.student_sockets[student_id]
