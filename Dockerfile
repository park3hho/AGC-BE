# syntax=docker/dockerfile:1
#   ★ 이 줄이 있어야 아래 pip 캐시 마운트(--mount=type=cache)가 동작한다. 지우지 말 것.
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
# pip 캐시를 빌드 사이에 남긴다 — requirements.txt 한 줄만 고쳐도 재다운로드하지 않게.
#   캐시 마운트는 이미지에 포함되지 않으므로 이미지 크기는 그대로다.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore -r requirements.txt

# main/ 안의 코드만 /app 으로 — import 는 /app(= main/) 기준
COPY main/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
