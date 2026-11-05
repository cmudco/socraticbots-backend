#!/bin/bash
# Socratic Bots backend entrypoint.
#   web        migrate, then Gunicorn on :8000 (Django's reloading dev server when DEBUG=True)
#   scheduler  run expire_voice_startups every SCHEDULER_INTERVAL_SECONDS (default 60)
#   migrate    run migrations and exit
#   <command>  run anything else, e.g. `python backend/manage.py shell`
set -e

cd /app/backend

if [ "${DEBUG:-False}" != "True" ]; then
    missing=()
    [ -z "${DJANGO_SECRET_KEY:-$SECRET_KEY}" ] && missing+=(DJANGO_SECRET_KEY)
    [ -z "$SSO_JWT_KEY" ] && missing+=(SSO_JWT_KEY)
    [ -z "$DARE_INTERNAL_KEY" ] && missing+=(DARE_INTERNAL_KEY)
    if [ ${#missing[@]} -gt 0 ]; then
        echo "ERROR: set ${missing[*]} in .env (SSO_JWT_KEY and DARE_INTERNAL_KEY must match DARE's)." >&2
        exit 1
    fi
fi

if [ -n "$DB_HOST" ]; then
    echo "Waiting for PostgreSQL at $DB_HOST:${DB_PORT:-5432}..."
    for attempt in $(seq 1 30); do
        python -c "import socket; socket.create_connection(('$DB_HOST', ${DB_PORT:-5432}), timeout=2).close()" 2>/dev/null && break
        if [ "$attempt" -eq 30 ]; then
            echo "ERROR: PostgreSQL not reachable after 30 attempts" >&2
            exit 1
        fi
        sleep 2
    done
fi

case "$1" in
    web)
        python manage.py migrate --noinput
        if [ "${DEBUG:-False}" = "True" ]; then
            exec python manage.py runserver 0.0.0.0:8000
        fi
        exec gunicorn core.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-3}" \
            --timeout 300 \
            --graceful-timeout 30 \
            --access-logfile - \
            --log-level "${LOG_LEVEL:-info}"
        ;;
    scheduler)
        trap 'exit 0' TERM INT
        while true; do
            python manage.py expire_voice_startups || echo "expire_voice_startups failed" >&2
            sleep "${SCHEDULER_INTERVAL_SECONDS:-60}" &
            wait $!
        done
        ;;
    migrate)
        exec python manage.py migrate --noinput
        ;;
    *)
        cd /app
        exec "$@"
        ;;
esac
