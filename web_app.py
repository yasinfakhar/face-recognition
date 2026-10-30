"""Host-side web control panel for the face recognition service."""

import asyncio
import csv
import os
import queue
import re
import subprocess
import threading
import time
from datetime import date, datetime

import cv2
import requests
from flask import Flask, Response, jsonify, render_template, request, send_file


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FACES_DIR = os.getenv("FACES_DIR", os.path.join(BASE_DIR, "faces"))
DEFAULT_AUDIO_DIR = os.getenv("AUDIO_DIR", os.path.join(BASE_DIR, "audios"))
DEFAULT_INFERENCE_URL = os.getenv("INFERENCE_URL", "http://127.0.0.1:8000/infer")
INFERENCE_RELOAD_URL = DEFAULT_INFERENCE_URL.rsplit("/", 1)[0] + "/reload"
TTS_VOICE = os.getenv("TTS_VOICE", "en-US-GuyNeural")
INFERENCE_MAX_WIDTH = int(os.getenv("INFERENCE_MAX_WIDTH", "640"))

app = Flask(__name__)


def parse_source(value: str):
    return int(value) if value.strip().isdigit() else value.strip()


def csv_path(report_date: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise ValueError("date must use YYYY-MM-DD format")
    return os.path.join(BASE_DIR, f"{report_date}.csv")


async def _generate_audio(name: str, path: str) -> None:
    import edge_tts

    text = f"Welcome, {name.replace('-', ' ').replace('_', ' ')}"
    await edge_tts.Communicate(text, TTS_VOICE).save(path)


def ensure_audio(name: str, audio_dir: str) -> str:
    """Create the registered person's welcome audio when it is missing."""
    os.makedirs(audio_dir, exist_ok=True)
    for extension in (".mp3", ".wav", ".ogg"):
        existing = os.path.join(audio_dir, f"{name}{extension}")
        if os.path.isfile(existing) and os.path.getsize(existing) > 0:
            return existing

    path = os.path.join(audio_dir, f"{name}.mp3")
    print(f"Generating missing audio for {name}: {path}")
    asyncio.run(_generate_audio(name, path))
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise RuntimeError(f"Audio generation did not create {path}")
    return path


def prepare_registered_assets(audio_dir: str = DEFAULT_AUDIO_DIR) -> list[str]:
    """Ensure every registered face has a usable welcome audio file."""
    if not os.path.isdir(FACES_DIR):
        raise RuntimeError(f"Faces directory does not exist: {FACES_DIR}")

    names = sorted(
        os.path.splitext(filename)[0]
        for filename in os.listdir(FACES_DIR)
        if os.path.isfile(os.path.join(FACES_DIR, filename))
        and os.path.splitext(filename)[1].lower() in {".jpg", ".jpeg", ".png", ".bmp"}
    )
    prepared = []
    failures = []
    for name in dict.fromkeys(names):
        try:
            ensure_audio(name, audio_dir)
            prepared.append(name)
        except Exception as exc:
            failures.append(f"{name}: {exc}")

    if failures:
        raise RuntimeError("Could not prepare registered assets:\n" + "\n".join(failures))

    print(f"Prepared {len(prepared)} registered face audio file(s) in {audio_dir}")
    return prepared


class CaptureManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.capture = None
        self.capture_thread = None
        self.inference_thread = None
        self.inference_ready = threading.Event()
        self.running = False
        self.source = ""
        self.audio_dir = DEFAULT_AUDIO_DIR
        self.audio_player = os.getenv("AUDIO_PLAYER", "ffplay")
        self.inference_url = DEFAULT_INFERENCE_URL
        self.latest_frame = None
        self.latest_frame_id = 0
        self.inference_frame = None
        self.results = []
        self.last_error = ""
        self.recognized = set()
        self.audio_queue = queue.Queue()
        threading.Thread(target=self._audio_loop, daemon=True).start()

    def start(self, source: str, audio_dir: str, audio_player: str = "ffplay"):
        self.stop()
        capture = cv2.VideoCapture(parse_source(source))
        if not capture.isOpened():
            capture.release()
            raise ValueError(f"Could not open video source: {source}")
        with self.lock:
            self.capture = capture
            self.source = source
            self.audio_dir = audio_dir or DEFAULT_AUDIO_DIR
            self.audio_player = audio_player or "ffplay"
            self.running = True
            self.last_error = ""
            self.latest_frame = None
            self.inference_frame = None
            self.results = []
            self.recognized.clear()
            self.capture_thread = threading.Thread(target=self._capture_loop, args=(capture,), daemon=True)
            self.inference_thread = threading.Thread(target=self._inference_loop, args=(capture,), daemon=True)
            self.capture_thread.start()
            self.inference_thread.start()

    def stop(self):
        with self.lock:
            self.running = False
            capture = self.capture
            self.capture = None
            self.latest_frame = None
            self.inference_frame = None
            self.results = []
        self.inference_ready.set()
        if capture is not None:
            capture.release()

    def status(self):
        with self.lock:
            return {
                "running": self.running,
                "source": self.source,
                "audio_dir": self.audio_dir,
                "last_error": self.last_error,
                "recognized": sorted(self.recognized),
            }

    def _capture_loop(self, capture):
        while True:
            with self.lock:
                if not self.running or self.capture is not capture:
                    return
            ok, frame = capture.read()
            if not ok:
                with self.lock:
                    if self.capture is capture:
                        self.last_error = "Video source ended or returned an invalid frame"
                        self.running = False
                capture.release()
                self.inference_ready.set()
                return
            with self.lock:
                if self.capture is not capture:
                    return
                self.inference_frame = frame.copy()
                results = list(self.results)
            self.inference_ready.set()
            self._draw_results(frame, results)
            ok, output = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                with self.lock:
                    if self.running and self.capture is capture:
                        self.latest_frame = output.tobytes()
                        self.latest_frame_id += 1

    def _inference_loop(self, capture):
        session = requests.Session()
        while True:
            self.inference_ready.wait()
            self.inference_ready.clear()
            with self.lock:
                if not self.running or self.capture is not capture:
                    return
                frame = self.inference_frame
            if frame is None:
                continue
            try:
                scale = min(1.0, INFERENCE_MAX_WIDTH / frame.shape[1]) if INFERENCE_MAX_WIDTH > 0 else 1.0
                inference_frame = frame
                if scale < 1.0:
                    inference_frame = cv2.resize(
                        frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
                    )
                encoded_ok, encoded = cv2.imencode(".jpg", inference_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not encoded_ok:
                    raise RuntimeError("Could not encode frame")
                response = session.post(
                    self.inference_url,
                    data=encoded.tobytes(),
                    headers={"Content-Type": "image/jpeg"},
                    timeout=5,
                )
                response.raise_for_status()
                results = response.json().get("faces", [])
                if scale < 1.0:
                    for result in results:
                        result["bbox"] = [round(value / scale) for value in result["bbox"]]
                with self.lock:
                    if self.running and self.capture is capture:
                        self.results = results
                        self.last_error = ""
            except requests.RequestException as exc:
                with self.lock:
                    if self.capture is capture:
                        self.last_error = f"Inference unavailable: {exc}"
            except Exception as exc:
                with self.lock:
                    if self.capture is capture:
                        self.last_error = str(exc)

    def _draw_results(self, frame, results):
        for result in results:
            x1, y1, x2, y2 = result["bbox"]
            name = result["name"]
            score = result["similarity"]
            color = (0, 220, 130) if name != "Unknown" else (0, 165, 255)
            label = f"{name} {score:.2f}" if name != "Unknown" else name
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, label, (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            if name != "Unknown":
                with self.lock:
                    first_seen = name not in self.recognized
                    self.recognized.add(name)
                if first_seen:
                    self._log(name)
                    self.audio_queue.put(name)

    def _log(self, name):
        path = csv_path(date.today().isoformat())
        if os.path.isfile(path):
            with open(path, newline="", encoding="utf-8") as source:
                if any(row.get("name") == name for row in csv.DictReader(source)):
                    return

        exists = os.path.isfile(path) and os.path.getsize(path) > 0
        with open(path, "a", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            if not exists:
                writer.writerow(["timestamp", "name"])
            writer.writerow([datetime.now().isoformat(timespec="seconds"), name])

    def _audio_loop(self):
        while True:
            name = self.audio_queue.get()
            try:
                with self.lock:
                    audio_dir, player = self.audio_dir, self.audio_player
                for extension in (".mp3", ".wav", ".ogg"):
                    path = os.path.join(audio_dir, f"{name}{extension}")
                    if os.path.isfile(path):
                        try:
                            subprocess.run([player, "-nodisp", "-autoexit", path], check=False,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        except OSError as exc:
                            with self.lock:
                                self.last_error = f"Audio player error: {exc}"
                        break
            finally:
                self.audio_queue.task_done()


manager = CaptureManager()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/stream")
def stream():
    def frames():
        last_frame_id = -1
        while True:
            with manager.lock:
                frame = manager.latest_frame
                frame_id = manager.latest_frame_id
                running = manager.running
            if frame and frame_id != last_frame_id:
                last_frame_id = frame_id
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n"
            elif not running:
                time.sleep(0.2)
            else:
                time.sleep(0.005)
    return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/api/status")
def status():
    return jsonify(manager.status())


@app.post("/api/start")
def start():
    data = request.get_json(silent=True) or {}
    try:
        manager.start(data.get("source", "0"), data.get("audio_dir", DEFAULT_AUDIO_DIR), data.get("audio_player", "ffplay"))
        return jsonify(manager.status())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/stop")
def stop():
    manager.stop()
    return jsonify(manager.status())


@app.post("/api/register")
def register():
    name = (request.form.get("name") or "").strip()
    image = request.files.get("image")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return jsonify({"error": "Name may contain only letters, numbers, _ and -"}), 400
    if image is None or not image.filename:
        return jsonify({"error": "An image is required"}), 400
    extension = os.path.splitext(image.filename)[1].lower()
    if extension not in {".jpg", ".jpeg", ".png", ".bmp"}:
        return jsonify({"error": "Use a JPG, PNG, or BMP image"}), 400
    os.makedirs(FACES_DIR, exist_ok=True)
    image.save(os.path.join(FACES_DIR, f"{name}{extension}"))
    with manager.lock:
        audio_dir = manager.audio_dir
    audio_error = None
    try:
        ensure_audio(name, audio_dir)
    except Exception as exc:
        audio_error = str(exc)
    try:
        response = requests.post(INFERENCE_RELOAD_URL, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": f"Face saved, but inference reload failed: {exc}"}), 502
    if audio_error:
        return jsonify({"error": f"Face registered, but welcome audio could not be created: {audio_error}"}), 502
    return jsonify({"message": f"Registered {name}"})


@app.get("/api/report")
def report():
    report_date = request.args.get("date", date.today().isoformat())
    try:
        path = csv_path(report_date)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    rows = []
    if os.path.isfile(path):
        with open(path, newline="", encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
    return jsonify({"date": report_date, "rows": rows, "count": len(rows)})


@app.get("/api/report/download")
def download_report():
    path = csv_path(request.args.get("date", date.today().isoformat()))
    if not os.path.isfile(path):
        return jsonify({"error": "No attendance report for this date"}), 404
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    prepare_registered_assets()
    app.run(host="0.0.0.0", port=int(os.getenv("WEB_PORT", "5000")), threaded=True)
