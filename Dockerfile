FROM python:3.11-slim

WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 패키지 설치 (캐시 활용을 위해 먼저 복사)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# 앱 코드 복사
COPY . .

# 재설치 (소스 반영)
RUN pip install --no-cache-dir .

# data 디렉토리 생성 (SQLite용)
RUN mkdir -p /app/data

# Cloud Run은 PORT 환경변수를 제공 (기본 8080)
ENV PORT=8080

EXPOSE ${PORT}

CMD uvicorn bookips.app:app --host 0.0.0.0 --port ${PORT}
