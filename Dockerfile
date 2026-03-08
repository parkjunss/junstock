FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 컨테이너 실행 시 기본 명령 (compose에서 각자 덮어쓰기 하므로 상관없음)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]