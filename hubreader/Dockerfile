# syntax=docker/dockerfile:1.7
FROM python:3.12.8-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install fastapi==0.149.0 starlette==1.9.0 uvicorn==0.54.0 && useradd --system --uid 10010 hubreader
WORKDIR /app
COPY main.py rules.py ./
USER hubreader
EXPOSE 8743
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8743", "--ssl-keyfile", "/tls/key.pem", "--ssl-certfile", "/tls/cert.pem", "--no-server-header", "--workers", "1"]
