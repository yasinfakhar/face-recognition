#!/usr/bin/env python3
"""Say hello to people the phone camera recognises.

Known people: put photos in /sdcard/FaceHello/faces/
    faces/Amin/1.jpg, faces/Amin/2.jpg   (one folder per person), or
    faces/Amin.jpg, faces/Amin2.jpg      (file name = person's name)

Camera: uses IP Webcam (/shot.jpg) if it is running, otherwise takes photos itself
with Termux:API.
Speech: Termux:API (termux-tts-speak).
Models: YuNet (detection) + SFace (recognition), run with onnxruntime.
Viewer: serves the last analysed frame and results on port 8081
(/frame.jpg, /status.json) for viewer.html.
"""
import argparse
import io
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps

BASE = "/sdcard/FaceHello"
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
MATCH_THRESHOLD = 0.363  # SFace cosine-similarity threshold from the OpenCV docs
DET_SIZE = 640
DET_SCORE = 0.8
NMS_IOU = 0.3

# 5-point template SFace/ArcFace faces are aligned to (112x112)
TEMPLATE = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float64,
)


class Models:
    def __init__(self, model_dir):
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        prov = ["CPUExecutionProvider"]
        self.det = ort.InferenceSession(os.path.join(model_dir, "face_detection_yunet_2023mar.onnx"), opts, providers=prov)
        self.rec = ort.InferenceSession(os.path.join(model_dir, "face_recognition_sface_2021dec.onnx"), opts, providers=prov)
        self.det_in = self.det.get_inputs()[0].name
        self.det_out = [o.name for o in self.det.get_outputs()]
        self.rec_in = self.rec.get_inputs()[0].name


def to_rgb(img):
    return np.asarray(ImageOps.exif_transpose(img).convert("RGB"))


def load_image(path, max_side=1280):
    img = Image.open(path)
    img.draft("RGB", (max_side, max_side))  # fast JPEG downscale
    img = ImageOps.exif_transpose(img).convert("RGB")
    img.thumbnail((max_side, max_side))
    return np.asarray(img)


def nms(boxes, scores, iou_thr):
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        x1 = np.maximum(boxes[i, 0], boxes[rest, 0])
        y1 = np.maximum(boxes[i, 1], boxes[rest, 1])
        x2 = np.minimum(boxes[i, 0] + boxes[i, 2], boxes[rest, 0] + boxes[rest, 2])
        y2 = np.minimum(boxes[i, 1] + boxes[i, 3], boxes[rest, 1] + boxes[rest, 3])
        inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        union = boxes[i, 2] * boxes[i, 3] + boxes[rest, 2] * boxes[rest, 3] - inter
        order = rest[inter / np.maximum(union, 1e-9) <= iou_thr]
    return keep


def detect(m, rgb):
    """Return [(score, area, 5x2 landmarks)] sorted by face size, largest first."""
    h, w = rgb.shape[:2]
    scale = DET_SIZE / max(h, w)
    nw, nh = int(round(w * scale)), int(round(h * scale))
    small = np.asarray(Image.fromarray(rgb).resize((nw, nh), Image.BILINEAR))
    canvas = np.zeros((DET_SIZE, DET_SIZE, 3), np.float32)
    canvas[:nh, :nw] = small[:, :, ::-1]  # YuNet expects BGR, 0-255
    blob = canvas.transpose(2, 0, 1)[None]

    out = dict(zip(m.det_out, m.det.run(None, {m.det_in: blob})))
    boxes, scores, marks = [], [], []
    for stride in (8, 16, 32):
        cls, obj = out[f"cls_{stride}"][0, :, 0], out[f"obj_{stride}"][0, :, 0]
        bbox, kps = out[f"bbox_{stride}"][0], out[f"kps_{stride}"][0]
        cols = DET_SIZE // stride
        idx = np.arange(cls.shape[0])
        r, c = idx // cols, idx % cols
        score = np.sqrt(np.clip(cls, 0, 1) * np.clip(obj, 0, 1))
        cx, cy = (c + bbox[:, 0]) * stride, (r + bbox[:, 1]) * stride
        bw, bh = np.exp(bbox[:, 2]) * stride, np.exp(bbox[:, 3]) * stride
        lm = np.stack([(kps[:, 0::2] + c[:, None]) * stride, (kps[:, 1::2] + r[:, None]) * stride], axis=2)
        sel = score >= DET_SCORE
        boxes.append(np.stack([cx - bw / 2, cy - bh / 2, bw, bh], axis=1)[sel])
        scores.append(score[sel])
        marks.append(lm[sel])
    boxes, scores, marks = np.concatenate(boxes), np.concatenate(scores), np.concatenate(marks)
    if not len(scores):
        return []
    keep = nms(boxes, scores, NMS_IOU)
    faces = [(float(scores[i]), float(boxes[i, 2] * boxes[i, 3]), marks[i] / scale, boxes[i] / scale) for i in keep]
    return sorted(faces, key=lambda f: f[1], reverse=True)


def similarity_transform(src, dst):
    """Least-squares similarity transform (Umeyama) mapping src points onto dst; 2x3 matrix."""
    sm, dm = src.mean(0), dst.mean(0)
    s, d = src - sm, dst - dm
    u, sig, vt = np.linalg.svd(d.T @ s / len(src))
    flip = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        flip[1, 1] = -1
    rot = u @ flip @ vt
    scale = (sig * np.diag(flip)).sum() / s.var(0).sum()
    t = dm - scale * rot @ sm
    return np.hstack([scale * rot, t[:, None]])


def embed(m, rgb, landmarks):
    mat = similarity_transform(landmarks.astype(np.float64), TEMPLATE)
    inv = np.linalg.inv(np.vstack([mat, [0, 0, 1]]))[:2]
    crop = Image.fromarray(rgb).transform((112, 112), Image.AFFINE, tuple(inv.flatten()), Image.BILINEAR)
    blob = np.asarray(crop, np.float32).transpose(2, 0, 1)[None]  # RGB, 0-255, no mean/std
    feat = m.rec.run(None, {m.rec_in: blob})[0][0]
    return feat / np.linalg.norm(feat)


def person_name(path, faces_dir):
    parts = os.path.relpath(path, faces_dir).split(os.sep)
    if len(parts) > 1:
        raw = parts[0]
    else:
        raw = re.sub(r"[\s_\-]*\d+$", "", os.path.splitext(parts[0])[0]) or parts[0]
    # "ali_karimi" / "ali-karimi" / "ALI KARIMI" all become "Ali Karimi" (also read aloud this way)
    return " ".join(raw.replace("_", " ").replace("-", " ").split()).title()


def greeting_for(faces_dir, name):
    """faces/<Name>/greeting.txt if it exists ("{name}" is replaced by the name), else "Hello <name>"."""
    try:
        for folder in os.listdir(faces_dir):
            if os.path.isdir(os.path.join(faces_dir, folder)) and person_name(os.path.join(faces_dir, folder, "x"), faces_dir) == name:
                for f in os.listdir(os.path.join(faces_dir, folder)):
                    if f.lower() == "greeting.txt":
                        with open(os.path.join(faces_dir, folder, f), encoding="utf-8") as fh:
                            text = fh.read().strip()
                        if text:
                            return text.replace("{name}", name)
    except OSError:
        pass
    return f"Hello {name}"


def list_images(faces_dir):
    found = {}
    for root, _, files in os.walk(faces_dir):
        for f in files:
            if f.lower().endswith(IMG_EXT):
                p = os.path.join(root, f)
                found[p] = os.path.getmtime(p)
    return found


def enroll(m, faces_dir):
    known = {}
    images = list_images(faces_dir)
    for path in images:
        try:
            rgb = load_image(path)
        except Exception as e:
            print(f"  skip (unreadable): {path} ({e})")
            continue
        faces = detect(m, rgb)
        if not faces:
            print(f"  skip (no face found): {path}")
            continue
        known.setdefault(person_name(path, faces_dir), []).append(embed(m, rgb, faces[0][2]))
    print("Known people:", {n: len(v) for n, v in known.items()} or "none", flush=True)
    return known, images


def identify(known, feat):
    best_name, best_score = None, -1.0
    for name, feats in known.items():
        for k in feats:
            s = float(feat @ k)
            if s > best_score:
                best_name, best_score = name, s
    return (best_name, best_score) if best_score >= MATCH_THRESHOLD else (None, best_score)


IPWEBCAM_URL = "http://127.0.0.1:8080/shot.jpg"
CAM_FILE = os.path.expanduser("~/facehello_cam.jpg")


def grab_http(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        raw = r.read()
    return to_rgb(Image.open(io.BytesIO(raw)))


def grab_camera(cam_id):
    """Take a photo with Termux:API (needs the camera free, i.e. IP Webcam not streaming)."""
    subprocess.run(["termux-camera-photo", "-c", str(cam_id), CAM_FILE], check=True, timeout=30)
    img = Image.open(CAM_FILE)
    img.draft("RGB", (1280, 1280))  # fast JPEG downscale; the photo is ~12 MP
    return to_rgb(img)


def grab(source, cam_id):
    """source: 'auto' (IP Webcam if running, else the phone camera), 'camera', or a URL."""
    if source == "camera":
        return grab_camera(cam_id)
    if source == "auto":
        try:
            with urllib.request.urlopen(IPWEBCAM_URL, timeout=2) as r:
                return to_rgb(Image.open(io.BytesIO(r.read())))
        except OSError:
            return grab_camera(cam_id)
    return grab_http(source)


LATEST = {"jpg": b"", "status": {"ts": 0, "faces": [], "events": [], "known": []}}
VIEWER_HTML = {"path": ""}


class ViewerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/frame.jpg":
            body, ctype = LATEST["jpg"], "image/jpeg"
        elif path == "/status.json":
            body, ctype = json.dumps(LATEST["status"]).encode(), "application/json"
        elif path in ("/", "/viewer.html") and os.path.exists(VIEWER_HTML["path"]):
            with open(VIEWER_HTML["path"], "rb") as f:
                body, ctype = f.read(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def start_viewer_server(port):
    server = ThreadingHTTPServer(("0.0.0.0", port), ViewerHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print(f"Viewer feed on port {port}", flush=True)


def say(text, speak):
    print(text, flush=True)
    if speak:
        try:
            subprocess.Popen(["termux-tts-speak", text])
        except FileNotFoundError:
            pass


class FrameGrabber:
    """Captures frames in the background so the next photo is taken while the last one is analysed."""

    def __init__(self, source, cam_id, interval):
        self.source, self.cam_id, self.interval = source, cam_id, interval
        self.cond = threading.Condition()
        self.seq, self.frame = 0, None
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            try:
                frame = grab(self.source, self.cam_id)
            except Exception as e:  # camera hiccups shouldn't kill the watcher
                print("error:", e, flush=True)
                time.sleep(3)
                continue
            with self.cond:
                self.seq, self.frame = self.seq + 1, frame
                self.cond.notify_all()
            time.sleep(self.interval)

    def next_frame(self, last_seq, timeout=15):
        """Block until a frame newer than last_seq exists; returns (seq, frame) or (last_seq, None)."""
        with self.cond:
            self.cond.wait_for(lambda: self.seq > last_seq, timeout)
            return (self.seq, self.frame) if self.seq > last_seq else (last_seq, None)


def main():
    global MATCH_THRESHOLD
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--source", default="auto",
                    help="'auto' (IP Webcam if running, else phone camera), 'camera', or an image URL")
    ap.add_argument("--camera", type=int, default=0, help="phone camera for camera mode: 0 = back, 1 = front")
    ap.add_argument("--interval", type=float, default=0.2, help="seconds to pause between captures")
    ap.add_argument("--cooldown", type=float, default=60, help="seconds before greeting the same person again")
    ap.add_argument("--no-speech", action="store_true", help="print only, no text-to-speech")
    ap.add_argument("--test", metavar="IMAGE", help="identify faces in one image file and exit")
    ap.add_argument("--port", type=int, default=8081, help="port for the viewer feed")
    ap.add_argument("--threshold", type=float, default=MATCH_THRESHOLD, help="min similarity to count as a match")
    args = ap.parse_args()
    MATCH_THRESHOLD = args.threshold

    faces_dir = os.path.join(args.base, "faces")
    os.makedirs(faces_dir, exist_ok=True)
    m = Models(os.path.join(args.base, "models"))
    known, snapshot = enroll(m, faces_dir)

    if args.test:
        rgb = load_image(args.test)
        for score, _, lm, _ in detect(m, rgb):
            print(identify(known, embed(m, rgb, lm)), f"(detector {score:.2f})")
        return

    VIEWER_HTML["path"] = os.path.join(args.base, "viewer.html")
    start_viewer_server(args.port)
    rot = 0
    last_greeted = {}
    events = []
    last_scan = time.time()
    grabber = FrameGrabber(args.source, args.camera, args.interval)
    seq = 0
    print(f"Watching {args.source} ... Ctrl+C to stop", flush=True)
    while True:
        try:
            seq, frame = grabber.next_frame(seq)
            if frame is None:
                continue
            if time.time() - last_scan > 10:
                last_scan = time.time()
                current = list_images(faces_dir)
                if current != snapshot:
                    print("Faces folder changed, re-enrolling")
                    known, snapshot = enroll(m, faces_dir)

            # The phone camera may be sideways: try the last working rotation first, then the others.
            found = None
            for k in [rot] + [r for r in (0, -1, 1, 2) if r != rot]:
                upright = np.ascontiguousarray(np.rot90(frame, k))
                faces = detect(m, upright)
                if faces:
                    found = (k, upright, faces)
                    break
            if found:
                rot, frame, faces = found
            else:
                frame, faces = np.ascontiguousarray(np.rot90(frame, rot)), []
            buf = io.BytesIO()
            Image.fromarray(frame).save(buf, "JPEG", quality=80)
            raw = buf.getvalue()
            results = []
            for score, _, lm, box in faces:
                name, sim = identify(known, embed(m, frame, lm))
                results.append({"name": name, "similarity": round(sim, 3), "detector": round(score, 2),
                                "box": [round(float(v)) for v in box]})
                if name and time.time() - last_greeted.get(name, 0) > args.cooldown:
                    last_greeted[name] = time.time()
                    text = greeting_for(faces_dir, name)
                    events = ([{"ts": time.time(), "text": text}] + events)[:20]
                    say(text, not args.no_speech)
            LATEST["jpg"] = raw
            LATEST["status"] = {"ts": time.time(), "width": frame.shape[1], "height": frame.shape[0],
                                "faces": results, "events": events, "known": sorted(known),
                                "threshold": MATCH_THRESHOLD}
        except KeyboardInterrupt:
            break
        except Exception as e:  # camera hiccups shouldn't kill the watcher
            print("error:", e, flush=True)
            time.sleep(3)


if __name__ == "__main__":
    main()
