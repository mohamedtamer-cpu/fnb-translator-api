# 1. هنستخدم نسخة بايثون خفيفة مجهزة
FROM python:3.10-slim

# 2. تسطيب المتصفح (Chromium) اللي Selenium محتاجه جوه الـ Docker
RUN apt-get update && apt-get install -y \
    chromium-driver \
    chromium \
    && rm -rf /var/lib/apt/lists/*

# 3. تحديد فولدر الشغل جوه الحاوية
WORKDIR /app

# 4. نقل قائمة المكتبات وتسطيبها
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. نقل الكود بتاعك كله للفولدر
COPY . .

# 6. فتح البورت بتاع Streamlit
EXPOSE 8501

# 7. الأمر النهائي لتشغيل البرنامج
CMD ["streamlit", "run", "tranlaste.py", "--server.port=8501", "--server.address=0.0.0.0"]