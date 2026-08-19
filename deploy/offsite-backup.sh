#!/bin/sh
# Отправка резервной копии за пределы сервера, в шифрованном виде.
#
# В cron после ночного бэкапа:
#   30 4 * * 0  /opt/dolshiki/deploy/offsite-backup.sh >> /var/log/dolshiki-backup.log 2>&1
#
# Зачем: копии лежат на том же сервере, что и данные. Пропадёт сервер —
# пропадут и они. Шифруем до отправки: в архиве паспорта и договоры
# клиентов, и хранилище провайдера не должно уметь их прочитать.
#
# Что нужно настроить один раз:
#   1. Пароль шифрования в /opt/dolshiki/deploy/.env.offsite:
#        BACKUP_PASSPHRASE=длинная-случайная-строка
#      Тот же пароль сохранить в менеджере паролей. Без него копия — мусор.
#   2. Доступ к хранилищу (S3-совместимое: Selectel, VK, Яндекс):
#        S3_ENDPOINT=https://s3.storage.selcloud.ru
#        S3_BUCKET=dolshiki-backup
#        AWS_ACCESS_KEY_ID=...
#        AWS_SECRET_ACCESS_KEY=...
#   3. Установить клиент: apt install -y awscli
set -eu

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/dolshiki}"

[ -f "$DIR/.env.offsite" ] || { echo "Нет $DIR/.env.offsite — смотрите комментарий в начале файла."; exit 1; }
. "$DIR/.env.offsite"

: "${BACKUP_PASSPHRASE:?не задан BACKUP_PASSPHRASE}"
: "${S3_BUCKET:?не задан S3_BUCKET}"
: "${S3_ENDPOINT:?не задан S3_ENDPOINT}"

LATEST="$(ls -1t "$BACKUP_DIR"/dolshiki-full-*.tar.gz 2>/dev/null | head -1)"
[ -n "$LATEST" ] || { echo "Полной копии нет — сначала backup.sh full"; exit 1; }

NAME="$(basename "$LATEST").enc"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
umask 077

# AES-256 с выводом ключа из пароля. Расшифровать потом:
#   openssl enc -d -aes-256-cbc -pbkdf2 -in файл.enc -out архив.tar.gz
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt \
  -pass "pass:$BACKUP_PASSPHRASE" -in "$LATEST" -out "$TMP"

aws --endpoint-url "$S3_ENDPOINT" s3 cp "$TMP" "s3://$S3_BUCKET/$NAME"

SIZE="$(du -h "$TMP" | cut -f1)"
echo "$(date '+%F %T'): копия $NAME ($SIZE) отправлена в $S3_BUCKET"
