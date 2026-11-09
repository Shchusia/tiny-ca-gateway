#!/usr/bin/env bash
# Run the integration suite against every adapter and server mode.
#
# Environment:
#   PORT=8000        port the demo servers listen on
#   TOKEN=           bearer token (must match CA_API_TOKEN in examples/.env)
#   TIMEOUT=30       seconds to wait for a server to become ready
#   ONLY=            run only backends whose label contains this substring
#   CLEAN=0          1 = remove demo certificates and databases first
#   COVERAGE=0       1 = run servers under coverage.py and write coverage.xml
#   RUN="uv run"     command prefix; RUN= uses the interpreter on PATH
#
# Each server is started in its own session and stopped by process group, so
# workers and reloaders never outlive their run.  Every server also writes a
# signed audit log, whose hash chain and signatures are verified afterwards.
set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PORT=${PORT:-8000}
TOKEN=${TOKEN:-}
TIMEOUT=${TIMEOUT:-30}
ONLY=${ONLY:-}
CLEAN=${CLEAN:-0}
COVERAGE=${COVERAGE:-0}
RUN=${RUN-uv run}
LOG_DIR=${LOG_DIR:-$(mktemp -d)}
mkdir -p "$LOG_DIR"
SUMMARY="$LOG_DIR/summary.txt"
: > "$SUMMARY"

PY="$RUN python"
if [ "$COVERAGE" = 1 ]; then
  export COVERAGE_RCFILE="$ROOT/pyproject.toml"
  export COVERAGE_FILE="$ROOT/.coverage"
  rm -f "$ROOT"/.coverage "$ROOT"/.coverage.*
  PY="$RUN python -m coverage run"
fi

AUDIT_KEY="$LOG_DIR/audit.key"
$RUN python - "$AUDIT_KEY" <<'PY'
import sys
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

key = ec.generate_private_key(ec.SECP256R1())
with open(sys.argv[1], "wb") as fh:
    fh.write(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
PY

verify_audit() {
  $RUN python - "$1" "$AUDIT_KEY" <<'PY'
import sys
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from tiny_ca import AuditLog

with open(sys.argv[2], "rb") as fh:
    public_key = load_pem_private_key(fh.read(), password=None).public_key()
count = AuditLog.verify(sys.argv[1], public_key)
assert count > 0, "audit log is empty"
print(f"  audit log: {count} signed entries verified")
PY
}

for fw in fastapi flask aiohttp django; do
  cp "$ROOT/examples/.env" "$ROOT/examples/$fw/.env"
  if [ "$CLEAN" = 1 ]; then
    rm -rf "$ROOT/examples/$fw/certs" "$ROOT/examples/$fw"/*.db
  fi
done

stop_server() {
  local pid=$1
  kill -TERM -- "-$pid" 2>/dev/null || return 0
  for _ in $(seq 1 20); do
    kill -0 -- "-$pid" 2>/dev/null || return 0
    sleep 0.5
  done
  kill -KILL -- "-$pid" 2>/dev/null || true
}

run_backend() {
  local label=$1 dir=$2 cmd=$3
  if [ -n "$ONLY" ] && [[ "$label" != *"$ONLY"* ]]; then
    return
  fi
  local slug
  slug=$(echo "$label" | tr -c 'A-Za-z0-9' '-')
  local log="$LOG_DIR/$slug.log"
  export AUDIT_LOG_PATH="$LOG_DIR/$slug.audit.jsonl" AUDIT_LOG_KEY="$AUDIT_KEY"

  echo ""
  echo "=== $label ==="
  if curl -s --max-time 1 "http://localhost:$PORT/" > /dev/null; then
    echo "  port $PORT is already in use; refusing to test a foreign server"
    echo "FAIL $label (port busy)" >> "$SUMMARY"
    return
  fi
  (cd "$dir" && exec setsid bash -c "$cmd") > "$log" 2>&1 &
  local pid=$!

  local ready=0
  for i in $(seq 1 "$TIMEOUT"); do
    if curl -sf --max-time 1 "http://localhost:$PORT/api/v1/ca/cert" > /dev/null; then
      echo "  ready in ${i}s"
      ready=1
      break
    fi
    sleep 1
  done

  if [ "$ready" = 0 ]; then
    echo "  did not start within ${TIMEOUT}s; last log lines:"
    tail -5 "$log" | sed 's/^/    /'
    echo "SKIP $label" >> "$SUMMARY"
  else
    local args=(--base-url "http://localhost:$PORT")
    [ -n "$TOKEN" ] && args+=(--token "$TOKEN")
    if (cd "$ROOT/tests" && $RUN python ca_integration_test.py "${args[@]}") \
      && verify_audit "$AUDIT_LOG_PATH"; then
      echo "PASS $label" >> "$SUMMARY"
    else
      echo "FAIL $label" >> "$SUMMARY"
    fi
  fi

  stop_server "$pid"
  wait "$pid" 2>/dev/null
  sleep 1
}

EX="$ROOT/examples"

run_backend "FastAPI dev (python)" "$EX/fastapi" "$PY demo-fastapi.py"
run_backend "FastAPI prod (uvicorn, 1 worker)" "$EX/fastapi" \
  "$PY -m uvicorn demo-fastapi:app --host 0.0.0.0 --port $PORT --workers 1"

run_backend "Flask dev (python)" "$EX/flask" "$PY demo-flask.py"
run_backend "Flask prod (gunicorn, 1 worker)" "$EX/flask" \
  "$PY -m gunicorn 'demo-flask:create_app()' -b 0.0.0.0:$PORT --workers 1"

run_backend "aiohttp dev (python)" "$EX/aiohttp" "$PY demo-aiohttp.py"
run_backend "aiohttp prod (gunicorn + aiohttp worker)" "$EX/aiohttp" \
  "$PY -m gunicorn 'demo-aiohttp:app' -k aiohttp.GunicornWebWorker --bind 0.0.0.0:$PORT --workers 1"

(cd "$EX/django" && $RUN python manage.py migrate --run-syncdb -v 0 > /dev/null 2>&1)
run_backend "Django dev (runserver)" "$EX/django" \
  "$PY manage.py runserver $PORT --noreload"
run_backend "Django asgi (uvicorn, 1 worker)" "$EX/django" \
  "$PY -m uvicorn ca_project.asgi:application --workers 1 --host 0.0.0.0 --port $PORT"
run_backend "Django wsgi (gunicorn, 1 worker)" "$EX/django" \
  "$PY -m gunicorn ca_project.wsgi:application -b 0.0.0.0:$PORT --workers 1"

echo ""
echo "=== SUMMARY (logs: $LOG_DIR) ==="
sed 's/^/  /' "$SUMMARY"
passed=$(grep -c '^PASS' "$SUMMARY")
total=$(wc -l < "$SUMMARY")
echo "  passed $passed of $total"

if [ "$COVERAGE" = 1 ]; then
  (cd "$ROOT" && $RUN python -m coverage combine -q && \
    $RUN python -m coverage report && $RUN python -m coverage xml -q)
fi

[ "$passed" = "$total" ] && [ "$total" -gt 0 ]
