"""Host-side video loop.

Video capture, display, logging, and audio playback intentionally stay outside
Docker. The container is used only as an inference service.
"""

import argparse
import csv
import os
import queue
import subprocess
import threading
from datetime import datetime

import cv2
import requests


DEFAULT_INFERENCE_URL = "http://127.0.0.1:8000/infer"
DEFAULT_AUDIO_DIR = "audios"
recognized_people = set()
voice_queue = queue.Queue()


def daily_csv_path() -> str:
    return f"{datetime.now():%Y-%m-%d}.csv"


def log_recognized_name(name: str) -> None:
    path = daily_csv_path()
    if os.path.isfile(path):
        with open(path, newline="", encoding="utf-8") as csvfile:
            if any(row.get("name") == name for row in csv.DictReader(csvfile)):
                return

    exists = os.path.isfile(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if not exists:
            writer.writerow(["timestamp", "name"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), name])


def play_audio(name: str, audio_dir: str, player: str) -> None:
    for extension in (".mp3", ".wav", ".ogg"):
        path = os.path.join(audio_dir, f"{name}{extension}")
        if os.path.isfile(path):
            try:
                subprocess.run(
                    [player, "-nodisp", "-autoexit", path],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as exc:
                print(f"Could not start audio player {player}: {exc}")
            return
    print(f"No audio found for {name} in {audio_dir}")


def audio_worker(audio_dir: str, player: str) -> None:
    while True:
        name = voice_queue.get()
        try:
            if name is None:
                return
            play_audio(name, audio_dir, player)
        finally:
            voice_queue.task_done()


def source_value(value: str):
    return int(value) if value.isdigit() else value


def infer(session: requests.Session, url: str, frame, max_width: int) -> list[dict]:
    scale = min(1.0, max_width / frame.shape[1]) if max_width > 0 else 1.0
    inference_frame = frame
    if scale < 1.0:
        inference_frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", inference_frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise RuntimeError("Could not encode video frame")
    response = session.post(
        url,
        data=encoded.tobytes(),
        headers={"Content-Type": "image/jpeg"},
        timeout=5,
    )
    response.raise_for_status()
    faces = response.json().get("faces", [])
    if scale < 1.0:
        for face in faces:
            face["bbox"] = [round(value / scale) for value in face["bbox"]]
    return faces


def main() -> None:
    parser = argparse.ArgumentParser(description="Host video client for Docker face inference")
    parser.add_argument("--source", default=os.getenv("VIDEO_SOURCE", "0"),
                        help="Camera index, video path, or stream URL")
    parser.add_argument("--inference-url", default=os.getenv("INFERENCE_URL", DEFAULT_INFERENCE_URL))
    parser.add_argument("--inference-max-width", type=int,
                        default=int(os.getenv("INFERENCE_MAX_WIDTH", "640")),
                        help="Downscale inference frames to this width; 0 disables resizing")
    parser.add_argument("--audio-dir", default=os.getenv("AUDIO_DIR", DEFAULT_AUDIO_DIR))
    parser.add_argument("--audio-player", default=os.getenv("AUDIO_PLAYER", "ffplay"))
    args = parser.parse_args()

    cap = cv2.VideoCapture(source_value(args.source))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video source: {args.source}")

    worker = threading.Thread(target=audio_worker, args=(args.audio_dir, args.audio_player), daemon=True)
    worker.start()
    session = requests.Session()
    print(f"Reading video on host from {args.source}; inference: {args.inference_url}")
    print("Press 'q' to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Video source ended or returned an invalid frame")
                break

            try:
                faces = infer(session, args.inference_url, frame, args.inference_max_width)
            except requests.RequestException as exc:
                cv2.putText(frame, f"Inference unavailable: {exc}", (20, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
                faces = []

            for result in faces:
                x1, y1, x2, y2 = result["bbox"]
                name = result["name"]
                similarity = result["similarity"]
                label = f"{name} {similarity:.2f}" if name != "Unknown" else name
                color = (0, 255, 0) if name != "Unknown" else (0, 165, 255)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, label, (x1, max(y1 - 10, 20)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

                if name != "Unknown" and name not in recognized_people:
                    recognized_people.add(name)
                    log_recognized_name(name)
                    voice_queue.put(name)

            cv2.imshow("Webcam Face Recognition", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()
        voice_queue.put(None)


if __name__ == "__main__":
    main()
