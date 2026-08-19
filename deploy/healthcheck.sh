#!/bin/sh
# Проверка, что система жива, и сообщение в Telegram, если нет.
#
# В cron каждые пять минут:
#   */5 * * * *  /opt/dolshiki/deploy/healthcheck.sh >> /var/log/dolshiki-health.log 2>&1
#
# Сообщение отправляется один раз на падение, а не каждые пять минут:
# иначе чат превращается в поток одинаковых строк и его отключают.
# Когда система поднимется, придёт отдельное сообщение о восстановлении.
set -eu

COMPOSE_DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="/var/lib/dolshiki-health.state"
DISK_LIMIT_PERCENT="${DISK_LIMIT_PERCENT:-85}"

cd "$COMPOSE_DIR"

# Токен и чат берём из того же файла, что и приложение.
if [ -f ../backend/.env ]; then
  TELEGRAM_BOT_TOKEN="$(grep -E '^TELEGRAM_BOT_TOKEN=' ../backend/.env | cut -d= -f2- || true)"
  TELEGRAM_CHAT_ID="$(grep -E '^TELEGRAM_CHAT_ID=' ../backend/.env | cut -d= -f2- || true)"
fi

notify() {
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ] || return 0
  curl -s -m 15 -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
    -d "chat_id=$TELEGRAM_CHAT_ID" -d "text=$1" > /dev/null || true
}

was_down=0
[ -f "$STATE" ] && was_down="$(cat "$STATE")"

if docker compose exec -T app python -c "
import urllib.request, sys
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=8).status == 200 else 1)
" > /dev/null 2>&1; then
  if [ "$was_down" = "1" ]; then
    notify "✅ dolshikirf.ru снова отвечает"
    echo "$(date '+%F %T'): восстановилось"
  fi
  echo 0 > "$STATE"
else
  if [ "$was_down" != "1" ]; then
    notify "⛔️ dolshikirf.ru не отвечает. Проверьте: docker compose ps"
    echo "$(date '+%F %T'): НЕ ОТВЕЧАЕТ"
  fi
  echo 1 > "$STATE"
  # Пытаемся поднять сами: чаще всего этого достаточно.
  docker compose up -d > /dev/null 2>&1 || true
fi

# Документы растут, и место кончается тихо. Предупреждаем заранее.
USED="$(df --output=pcent / | tail -1 | tr -dc '0-9')"
if [ "$USED" -ge "$DISK_LIMIT_PERCENT" ]; then
  notify "⚠️ На сервере занято ${USED}% диска. Скоро перестанут сохраняться документы и копии."
  echo "$(date '+%F %T'): диск занят ${USED}%"
fi
