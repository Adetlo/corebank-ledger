#!/bin/sh
# Apply pending migrations, then exec the server (PID 1 forwarding signals).
set -eu

if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "Applying database migrations..."
  alembic upgrade head
fi

exec "$@"
