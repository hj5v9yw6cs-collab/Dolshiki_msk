# Образ приложения: API, калькулятор и рабочий кабинет в одном контейнере.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY widget/ ./widget/
COPY admin/ ./admin/

WORKDIR /app/backend

# Данные и юридический конфиг живут в томах, а не в образе:
# при обновлении версии база и правки юриста остаются на месте.
VOLUME ["/app/backend/data", "/app/backend/config"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# Один рабочий процесс: при 30 делах в месяц этого с запасом, а SQLite и
# счётчик обращений в памяти рассчитаны именно на один процесс.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
