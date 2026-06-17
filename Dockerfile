# 두루런 백엔드 (FastAPI) - pip 기반
FROM python:3.11-slim

# 작업 디렉터리
WORKDIR /app

# 시스템 패키지 (asyncpg 빌드 등에 필요할 수 있는 최소 도구)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 파이썬 출력 버퍼링 끄기 (로그 즉시 출력)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 의존성 먼저 설치 (레이어 캐시 활용: 코드만 바뀌면 재설치 안 함)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사
COPY ./app ./app
COPY alembic.ini .
COPY ./alembic ./alembic

# FastAPI 실행 (8000 포트)
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
