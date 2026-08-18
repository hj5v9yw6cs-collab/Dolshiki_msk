#!/bin/sh
# Резервное копирование.
#
# Два режима, потому что данные разные по природе:
#
#   daily  — база и юридический конфиг. Меняются каждый день, весят мало.
#            Храним 30 копий.
#   full   — то же плюс файлы дел (паспорта, ДДУ, экспертизы). Меняются
#            редко, весят много. Храним 4 копии.
#
# В cron:
#   0 3 * * *  /opt/dolshiki/deploy/backup.sh daily >> /var/log/dolshiki-backup.log 2>&1
#   0 4 * * 0  /opt/dolshiki/deploy/backup.sh full  >> /var/log/dolshiki-backup.log 2>&1
#
# Копии лежат на том же сервере. Если сервер пропадёт — пропадут и они,
# поэтому раз в неделю забирайте архив к себе:
#   scp root@СЕРВЕР:/var/backups/dolshiki/dolshiki-full-*.tar.gz .
set -eu

MODE="${1:-daily}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/dolshiki}"
DAILY_KEEP="${DAILY_KEEP:-30}"
FULL_KEEP="${FULL_KEEP:-4}"
COMPOSE_DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y-%m-%d-%H%M)"

case "$MODE" in
  daily|full) ;;
  *) echo "Использование: $0 [daily|full]" >&2; exit 2 ;;
esac

ARCHIVE="$BACKUP_DIR/dolshiki-$MODE-$STAMP.tar.gz"
mkdir -p "$BACKUP_DIR"

cd "$COMPOSE_DIR"

# Снимок базы делаем средствами SQLite: копирование файла на работающей
# базе даёт несогласованную копию, которая может не открыться.
docker compose exec -T app sh -c "
  set -e
  rm -rf /tmp/backup && mkdir -p /tmp/backup
  if [ -f data/app.db ]; then
    python -c \"
import sqlite3
source = sqlite3.connect('data/app.db')
target = sqlite3.connect('/tmp/backup/app.db')
source.backup(target)
target.close(); source.close()
\"
  fi
  cp -r config /tmp/backup/config
  if [ '$MODE' = 'full' ] && [ -d data/cases ]; then
    cp -r data/cases /tmp/backup/cases
  fi
  tar -czf - -C /tmp/backup .
  rm -rf /tmp/backup
" > "$ARCHIVE"

if [ ! -s "$ARCHIVE" ]; then
  echo "$(date): ОШИБКА — архив пустой, копия не создана" >&2
  rm -f "$ARCHIVE"
  exit 1
fi

# Битая копия хуже отсутствующей: она создаёт ложное спокойствие.
if ! tar -tzf "$ARCHIVE" > /dev/null 2>&1; then
  echo "$(date): ОШИБКА — архив не читается, удалён" >&2
  rm -f "$ARCHIVE"
  exit 1
fi

# База должна быть внутри — иначе смысла в копии нет.
if ! tar -tzf "$ARCHIVE" | grep -q "app.db"; then
  echo "$(date): ПРЕДУПРЕЖДЕНИЕ — в архиве нет базы. Приложение запущено?" >&2
fi

if [ "$MODE" = "full" ]; then
  KEEP="$FULL_KEEP"
else
  KEEP="$DAILY_KEEP"
fi

# Удаляем лишние копии этого же режима, оставляя KEEP самых свежих.
ls -1t "$BACKUP_DIR"/dolshiki-"$MODE"-*.tar.gz 2>/dev/null | tail -n "+$((KEEP + 1))" | while read -r old; do
  rm -f "$old"
done

SIZE="$(du -h "$ARCHIVE" | cut -f1)"
FREE="$(df -h "$BACKUP_DIR" | awk 'NR==2 {print $4}')"
echo "$(date): копия $MODE готова — $ARCHIVE ($SIZE). Свободно на диске: $FREE"
