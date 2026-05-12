# ModuFlow AI 자세 분석 서버 — Cloud Run 배포용 이미지
FROM python:3.11-slim

# OpenCV 런타임이 필요로 하는 시스템 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 모델 파일은 src 의 부모 디렉토리에 위치해야 한다
# (test_pose_8.py 가 __file__ 기준 "../pose_landmarker_lite.task" 로 로드)
COPY pose_landmarker_lite.task .
COPY src/ ./src/

# Cloud Run 은 PORT 환경변수로 수신 포트를 주입한다 (기본 8080)
ENV PORT=8080
EXPOSE 8080

# pose_server 모듈을 src 디렉토리 기준으로 로드
CMD ["sh", "-c", "uvicorn pose_server:app --host 0.0.0.0 --port ${PORT} --app-dir src"]
