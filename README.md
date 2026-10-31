# Face Recognition

The host process reads video frames with OpenCV and plays audio locally. Docker
only runs the InsightFace inference API, so no camera, X11, or sound device is
passed into the container.

There is also an **Android app** that does the same job entirely on an old
phone, with no server or Docker. See [Mobile app](#mobile-app-android) below.

## Install on the host

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Install `ffplay` on the host for audio playback. For Ubuntu:

```bash
sudo apt install ffmpeg
```

## Run

```bash
./run.sh
```

Open `http://127.0.0.1:5000` in a browser. The UI lets you start a camera,
local video path, or stream URL, choose the host audio folder/player, register
faces, and view or download attendance reports.

At startup, the host scans every image in `faces/` and generates any missing
welcome audio in `audios/` before the web app accepts requests. Startup stops
with the affected names if audio generation fails. The inference container
loads the same face images before it starts serving requests.

The previous command-line client is still available. `--source` accepts a
camera index, local video path, or stream URL:

```bash
python3 main.py --source 1
python3 main.py --source /path/to/video.mp4
python3 main.py --source 'rtsp://user:password@camera/stream'
```

Audio is selected on the host by person name (`audios/<name>.mp3`, `.wav`, or
`.ogg`). Change the source directory or player without editing code:

```bash
AUDIO_DIR=/path/to/audio AUDIO_PLAYER=ffplay ./run.sh
```

The HTTP API is available at `http://127.0.0.1:8000`. To run the host client
without the helper script, start the service with `docker compose up -d` and
run `python3 main.py --source 0`.

Set `INSIGHTFACE_PROVIDER=CPUExecutionProvider` if the Docker host does not
have a usable NVIDIA GPU.

## Inference performance

The host downsizes frames to 640 pixels wide for inference while keeping the
display at the camera's full resolution. Tune this without editing code:

```bash
INFERENCE_MAX_WIDTH=480 DETECTION_SIZE=480 ./run.sh
```

Smaller values increase FPS but can miss small or distant faces. Try 480 first,
then 320 if more speed is needed. Use `INFERENCE_MAX_WIDTH=0` to send full-size
frames. Keep `INSIGHTFACE_PROVIDER=CUDAExecutionProvider` for GPU inference and
confirm the container logs list that provider rather than CPU.

## Mobile app (Android)

The [`mobile/`](mobile/) folder is a phone version of this project. It runs on a
single Android phone (8.0 or newer) with no PC, server, or Docker: the phone's
camera is read continuously, faces are recognised on the device (YuNet
detection and SFace recognition on ONNX Runtime, not InsightFace), and the phone
says "Hello <name>" out loud. A greeting arrives in about a second.

Features:

- Photos in `/sdcard/FaceHello/faces/<Name>/` are the people it knows. New
  photos are picked up automatically.
- An optional `greeting.txt` in a person's folder replaces "Hello <name>" with
  your own text (`{name}` is replaced by their name).
- An option to greet each person at most N times.
- A choice of Android's voice or 8 on-device KittenTTS voices.
- A dated log of who was recognised, on screen and in `/sdcard/FaceHello/log.txt`.
- A web page served by the phone (`http://<phone-ip>:8081`) showing the live
  frame with a box and name around each face.

Quick start (details in [`mobile/README.md`](mobile/README.md)):

1. Install [Android Studio](https://developer.android.com/studio) and turn on
   USB debugging on the phone.
2. Download the voice files once (about 60 MB, not stored in git):

   ```powershell
   cd mobile/android
   .\get-tts.ps1
   ```

3. Open `mobile/android` in Android Studio and press **Run** with the phone
   connected. Or from a terminal (JDK 17 or newer):

   ```powershell
   .\gradlew.bat assembleDebug      # macOS/Linux: ./gradlew assembleDebug
   adb install -r app/build/outputs/apk/debug/app-debug.apk
   ```

4. Put photos on the phone in `/sdcard/FaceHello/faces/<Name>/1.jpg`.
5. Open **Face Hello**, allow the camera and storage permissions, and tap
   **Start**.

There is also a lighter version that runs in Termux with no build tools; it is
described in `mobile/README.md`.
