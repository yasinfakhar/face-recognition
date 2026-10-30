import asyncio
import csv
import os
import subprocess
import threading
import queue
from datetime import datetime

import cv2
import edge_tts
import insightface
import numpy as np
from insightface.app import FaceAnalysis

# Initialize face analysis model
app = FaceAnalysis(name='buffalo_s', providers=['CUDAExecutionProvider'])  # Use 'CUDAExecutionProvider' for GPU
app.prepare(ctx_id=0)  # ctx_id=-1 for CPU, 0 for GPU

cv2.namedWindow("Webcam Face Recognition", cv2.WINDOW_NORMAL)

# Global list to keep track of recognized people
recognized_people = []

# Queue and worker for background voice playback
voice_queue: "queue.Queue[str]" = queue.Queue()
voice_worker_started = False

THRESHOLD = 0.5
AUDIOS_DIR = "audios"
TTS_VOICE = "en-US-GuyNeural"  # High-quality male voice; alternatives: en-US-JennyNeural, en-GB-SoniaNeural


def _daily_csv_path() -> str:
    """Return the CSV file path for today's recognition log."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return f"{date_str}.csv"


def log_recognized_name(name: str) -> None:
    """Append a recognized name with timestamp to today's CSV log."""
    csv_path = _daily_csv_path()
    if os.path.isfile(csv_path):
        with open(csv_path, newline="", encoding="utf-8") as csvfile:
            if any(row.get("name") == name for row in csv.DictReader(csvfile)):
                return

    file_exists = os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0
    with open(csv_path, "a", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        if not file_exists:
            writer.writerow(["timestamp", "name"])
        writer.writerow([datetime.now().isoformat(timespec="seconds"), name])


async def _generate_audio_async(name: str, output_path: str) -> None:
    """
    Generate an audio file for the given name using edge-tts.

    Uses Microsoft Edge's neural TTS engine for high-quality voice synthesis.
    The generated audio is saved as an MP3 file.

    Args:
        name: The person's name to synthesize as speech.
        output_path: The file path where the audio will be saved.
    """
    # Create a welcome message for the person
    text = f"Welcome, {name.replace('-', ' ').replace('_', ' ')}"
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(output_path)


def generate_audio_for_name(name: str) -> str:
    """
    Generate an audio file for a person's name if it doesn't exist.

    Checks if an audio file already exists in the audios directory.
    If not, generates one using edge-tts with high-quality neural voice.

    Args:
        name: The person's name (derived from image filename).

    Returns:
        The path to the audio file (existing or newly created).
    """
    os.makedirs(AUDIOS_DIR, exist_ok=True)
    audio_path = os.path.join(AUDIOS_DIR, f"{name}.mp3")

    if os.path.isfile(audio_path):
        print(f"Audio file already exists: {audio_path}")
        return audio_path

    print(f"Generating audio for: {name}")
    try:
        asyncio.run(_generate_audio_async(name, audio_path))
        print(f"Audio generated: {audio_path}")
    except Exception as e:
        print(f"Failed to generate audio for {name}: {e}")

    return audio_path


def get_face_embedding(image_path):
    """Extract face embedding from an image"""
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")
    
    faces = app.get(img)
    
    if len(faces) < 1:
        raise ValueError("No faces detected in the image")
    if len(faces) > 1:
        print("Warning: Multiple faces detected. Using first detected face")
    
    return faces[0].embedding

def compare_faces(emb1, emb2, threshold=THRESHOLD): # Adjust this threshold according to your usecase.
    """Compare two embeddings using cosine similarity"""
    similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
    return similarity, similarity > threshold

def load_known_faces(folder_path):
    """
    Load all images from folder_path and compute their face embeddings.

    The person name is inferred from the filename without extension.
    For each person, generates a TTS audio file if one doesn't exist.

    Args:
        folder_path: Path to the directory containing face images.

    Returns:
        A list of (name, embedding) tuples for all successfully processed faces.
    """
    known_embeddings = []
    names_processed = set()

    # First pass: collect all valid image files and extract names
    image_files = []
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if not os.path.isfile(file_path):
            continue
        name, ext = os.path.splitext(filename)
        if ext.lower() not in [".jpg", ".jpeg", ".png", ".bmp"]:
            continue
        image_files.append((name, file_path))

    # Generate audio files for all unique names first
    print("Generating audio files for all persons...")
    for name, _ in image_files:
        if name not in names_processed:
            generate_audio_for_name(name)
            names_processed.add(name)

    # Now process face embeddings
    print("Processing face embeddings...")
    for name, file_path in image_files:
        try:
            emb = get_face_embedding(file_path)
            known_embeddings.append((name, emb))
        except Exception as e:
            print(f"Error processing {file_path}: {e}")

    return known_embeddings

def recognize_face(face_embedding, known_embeddings, threshold=THRESHOLD):
    """Recognize a face by comparing its embedding to known embeddings.

    Returns (best_name, best_similarity). If no match, best_name is "Unknown".
    """
    best_name = "Unknown"
    best_similarity = 0.0
    for name, known_emb in known_embeddings:
        similarity, is_same = compare_faces(face_embedding, known_emb, threshold=threshold)
        if similarity > best_similarity and is_same:
            best_similarity = similarity
            best_name = name
    return best_name, best_similarity


def _play_voice_file(name: str) -> None:
    """
    Play the audio file corresponding to the given name.

    Looks for an audio file in the audios directory named "{name}.mp3"
    and plays it using ffplay. If the file doesn't exist, attempts to
    generate it on-the-fly using TTS.

    Args:
        name: The person's name whose audio file should be played.
    """
    audio_path = os.path.join(AUDIOS_DIR, f"{name}.mp3")

    # Generate audio if it doesn't exist
    if not os.path.isfile(audio_path):
        print(f"Audio file not found for {name}, generating...")
        generate_audio_for_name(name)

    if not os.path.isfile(audio_path):
        print(f"Failed to create audio file for {name}")
        return

    try:
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", audio_path],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        print(f"Failed to play voice for {name} from {audio_path}: {exc}")


def _voice_worker() -> None:
    """Background worker that sequentially plays queued voice messages.

    Consumes names from the global voice_queue and plays the corresponding
    MP3 files one by one. This keeps audio playback off the main camera loop
    thread while preserving the order of announcements.
    """
    while True:
        name = voice_queue.get()
        if name is None:
            # Sentinel value to stop the worker if ever needed.
            break
        _play_voice_file(name)
        voice_queue.task_done()


def play_welcome_sound(name: str) -> None:
    """Queue the welcome voice for the recognized person.

    Adds the person's name to the global voice queue so that their MP3 is
    played in the background by the voice worker. This call is non-blocking
    for the main camera loop.
    """
    voice_queue.put(name)

def main():
    """Run real-time face recognition on webcam using InsightFace."""
    faces_folder = "faces"  # relative to this script
    if not os.path.isdir(faces_folder):
        raise FileNotFoundError(f"Faces folder not found: {faces_folder}")

    global voice_worker_started

    print(f"Loading known faces from {faces_folder}...")
    known_embeddings = load_known_faces(faces_folder)
    if not known_embeddings:
        print("No valid face images found in faces folder.")

    # Start the background voice worker exactly once.
    if not voice_worker_started:
        worker_thread = threading.Thread(target=_voice_worker, daemon=True)
        worker_thread.start()
        voice_worker_started = True

    cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam")

    print("Press 'q' to quit.")
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        faces = app.get(frame)
        for face in faces:
            bbox = face.bbox.astype(int)
            x1, y1, x2, y2 = bbox
            emb = face.embedding

            name, similarity = recognize_face(emb, known_embeddings)
            label = f"{name} {similarity:.2f}" if name != "Unknown" else name

            if name != "Unknown":
                if name not in recognized_people:
                    recognized_people.append(name)
                    log_recognized_name(name)
                    play_welcome_sound(name)

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        cv2.imshow("Webcam Face Recognition", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
