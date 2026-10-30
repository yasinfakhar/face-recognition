"""Docker-side InsightFace HTTP inference service."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import onnxruntime as ort

ort.preload_dlls()

from insightface.app import FaceAnalysis


THRESHOLD = float(os.getenv("FACE_THRESHOLD", "0.5"))
FACES_DIR = os.getenv("FACES_DIR", "/app/faces")
PORT = int(os.getenv("INFERENCE_PORT", "8000"))
DETECTION_SIZE = int(os.getenv("DETECTION_SIZE", "640"))
PROVIDERS = [os.getenv("INSIGHTFACE_PROVIDER", "CUDAExecutionProvider")]
CTX_ID = 0 if PROVIDERS[0] == "CUDAExecutionProvider" else -1

if PROVIDERS[0] not in ort.get_available_providers():
    raise RuntimeError(
        f"Requested {PROVIDERS[0]}, but ONNX Runtime only provides "
        f"{ort.get_available_providers()}"
    )

print(f"Loading InsightFace model with providers={PROVIDERS}")
app = FaceAnalysis(name="buffalo_s", providers=PROVIDERS)
app.prepare(ctx_id=CTX_ID, det_size=(DETECTION_SIZE, DETECTION_SIZE))


def cosine_similarity(first, second) -> float:
    denominator = np.linalg.norm(first) * np.linalg.norm(second)
    return float(np.dot(first, second) / denominator) if denominator else 0.0


def load_known_faces() -> list[tuple[str, np.ndarray]]:
    known = []
    for filename in sorted(os.listdir(FACES_DIR)):
        path = os.path.join(FACES_DIR, filename)
        if not os.path.isfile(path) or os.path.splitext(filename)[1].lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
            continue
        image = cv2.imread(path)
        if image is None:
            print(f"Skipping unreadable face image: {path}")
            continue
        faces = app.get(image)
        if faces:
            known.append((os.path.splitext(filename)[0], faces[0].embedding))
        else:
            print(f"No face found in: {path}")
    return known


KNOWN_FACES = load_known_faces()
print(f"Loaded {len(KNOWN_FACES)} known faces")


def recognize(embedding):
    best_name, best_score = "Unknown", 0.0
    for name, known_embedding in KNOWN_FACES:
        score = cosine_similarity(embedding, known_embedding)
        if score > best_score:
            best_name, best_score = name, score
    return (best_name, best_score) if best_score > THRESHOLD else ("Unknown", best_score)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_json({"status": "ok", "known_faces": len(KNOWN_FACES)})
        else:
            self.send_error(404)

    def do_POST(self):
        global KNOWN_FACES
        if self.path == "/reload":
            KNOWN_FACES = load_known_faces()
            self.send_json({"status": "ok", "known_faces": len(KNOWN_FACES)})
            return
        if self.path != "/infer":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            frame = cv2.imdecode(np.frombuffer(self.rfile.read(length), np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("request body is not a valid JPEG frame")
            results = []
            for face in app.get(frame):
                name, similarity = recognize(face.embedding)
                results.append({
                    "bbox": [int(value) for value in face.bbox.astype(int)],
                    "name": name,
                    "similarity": round(similarity, 4),
                })
            self.send_json({"faces": results})
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=400)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Inference server listening on 0.0.0.0:{PORT}")
    server.serve_forever()
