#!/bin/sh
set -e
cd /app 2>/dev/null || true
exec "$@"