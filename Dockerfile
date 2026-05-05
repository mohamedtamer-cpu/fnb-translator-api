FROM python:3.10-slim

WORKDIR /app

# نسخ ملف المتطلبات أولاً
COPY requirements.txt .

# تثبيت المكتبات
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي الملفات
COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]