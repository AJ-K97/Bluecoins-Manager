#!/bin/bash

# Configuration
CONTAINER_NAME="bluecoins_db"
DB_User="bluecoins_user"
BACKUP_DIR="./backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
FILENAME="$BACKUP_DIR/bluecoins_backup_$TIMESTAMP.sql"

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

# Perform Backup
echo "Starting backup of $CONTAINER_NAME..."
docker exec -t $CONTAINER_NAME pg_dump -U $DB_User bluecoins_db > "$FILENAME"

if [ $? -eq 0 ]; then
    echo "✅ Backup successful: $FILENAME"
    # Optional: Delete backups older than 7 days
    find "$BACKUP_DIR" -type f -name "*.sql" -mtime +7 -delete
else
    echo "❌ Backup failed!"
    exit 1
fi
