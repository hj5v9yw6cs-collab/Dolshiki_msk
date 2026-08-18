#!/bin/sh
# Резервная копия базы и юридического конфига.
#
# Ставится в cron на сервере:
#   0 3 * * *  /opt/dolshiki/deploy/backup.sh >> /var/log/dolshiki-backup.log 2>&1
#
# Копии старше RETENTION_DAYS удаляются. Восстановление: распаковать архив
# в тома контейнера и перезапустить приложение.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/var/backups/dolshiki}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
COMPOSE_DIR="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date +%Y-%m-%d-%H%M)"
ARCHIVE="$BACKUP_DIR/dolshiki-$STAMP.tar.gz"

mkdir -p "$BACKUP_DIR"

# Копируем из работающего контейнера: sqlite отдаёт согласованный снимок
# командой .backup, простое копирование файла на живой базе ненадёжно.
cd "$COMPOSE_DIR"
docker compose exec -T app sh -c '
  set -e
  rm -rf /tmp/backup && mkdir -p /tmp/backup
  if [ -f data/app.db ]; then
    python -c "
import sqlite3
source = sqlite3.connect(\"data/app.db\")
target = sqlite3.connect(\"/tmp/backup/app.db\")
source.backup(target)
target.close(); source.close()
"
  fi
  cp -r config /tmp/backup/config
  tar -czf - -C /tmp/backup .
' > "$ARCHIVE"

if [ ! -s "$ARCHIVE" ]; then
  echo "$(date): ОШИБКА — архив пустой, копия не создана" >&2
  rm -f "$ARCHIVE"
  exit 1
fi

# Проверяем, что архив читается: битая копия хуже отсутствующей,
# потому что создаёт ложное спокойствие.
tar -tzf "$ARCHIVE" > /dev/null

find "$BACKUP_DIR" -name 'dolshiki-*.tar.gz' -mtime "+$RETENTION_DAYS" -delete

echo "$(date): копия готова — $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"
