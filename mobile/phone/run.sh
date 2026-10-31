#!/data/data/com.termux/files/usr/bin/bash
# Starts face recognition on the phone. Run in Termux:  bash /sdcard/FaceHello/run.sh
# One-time:  bash /sdcard/FaceHello/run.sh --install   (creates a short command: just type  face )
B=/sdcard/FaceHello
PIDFILE=$HOME/.facehello.pid

if [ "$1" = "--install" ]; then
    printf '#!/data/data/com.termux/files/usr/bin/bash\nexec bash /sdcard/FaceHello/run.sh "$@"\n' > "$PREFIX/bin/face"
    chmod +x "$PREFIX/bin/face"
    echo "Installed. From now on, type  face  in Termux to start. (Delete $PREFIX/bin/face to remove.)"
    exit 0
fi

# Already running? (a second Termux session would otherwise start a duplicate)
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Face recognition is already running in another Termux session."
    exit 0
fi

termux-wake-lock
IP=$(ip -4 addr show wlan0 2>/dev/null | grep -o 'inet [0-9.]*' | cut -d' ' -f2)
[ -z "$IP" ] && IP=$(termux-wifi-connectioninfo 2>/dev/null | grep -o '"ip": *"[0-9.]*"' | grep -o '[0-9]*\.[0-9.]*')
echo "Viewer: open http://${IP:-<phone-ip>}:8081 on any device on this Wi-Fi"
echo $$ > "$PIDFILE"
exec python -W ignore $B/facehello.py "$@"
