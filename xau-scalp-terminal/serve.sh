#!/usr/bin/env bash
# Start (or restart) the XAU/USDT web terminal on the work-host ports.
# Usage: bash serve.sh        -> serves on 12000 + 12001
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TTYD="$DIR/bin/ttyd"

if [ ! -x "$TTYD" ]; then
  echo "downloading ttyd..."
  mkdir -p "$DIR/bin"
  curl -sL -o "$TTYD" "https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64"
  chmod +x "$TTYD"
fi

# self-heal python deps (survives sandbox/home resets)
if ! python3 -c "import rich, websockets, aiohttp, numpy" 2>/dev/null; then
  echo "installing python deps..."
  pip install -q -r "$DIR/requirements.txt"
fi

for PORT in "${@:-12000 12001}"; do :; done
PORTS="${@:-12000 12001}"
for PORT in $PORTS; do
  PID=$(pgrep -f "ttyd -W -p $PORT")
  [ -n "$PID" ] && kill "$PID" 2>/dev/null && sleep 1
  setsid nohup "$TTYD" -W -p "$PORT" --writable python3 "$DIR/terminal.py" \
      > "$DIR/.ttyd_$PORT.log" 2>&1 < /dev/null &
  echo "serving terminal on port $PORT (log: $DIR/.ttyd_$PORT.log)"
done
sleep 2
pgrep -fa "ttyd -W -p" || echo "WARNING: no ttyd process running"
