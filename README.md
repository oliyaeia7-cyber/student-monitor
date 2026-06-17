# سامانه حضور هوشمند 📡

سیستم تشخیص حضور دانش‌آموز بر پایه دوربین با حفظ کامل حریم خصوصی.

## اجرای محلی

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

سپس به آدرس `http://localhost:8000` بروید.

## دیپلوی روی Render.com

1. این پوشه را روی GitHub آپلود کنید
2. در Render: New → Web Service → Connect Repository
3. تنظیمات:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. فایل `render.yaml` تنظیمات را خودکار اعمال می‌کند

## ساختار

```
monitor/
├── main.py              ← FastAPI + WebSocket
├── requirements.txt
├── render.yaml
└── frontend/
    ├── index.html       ← صفحه اصلی
    ├── teacher.html     ← داشبورد معلم
    └── student.html     ← صفحه دانش‌آموز
```
