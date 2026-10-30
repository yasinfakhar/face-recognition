# Face Recognition

The host process reads video frames with OpenCV and plays audio locally. Docker
only runs the InsightFace inference API, so no camera, X11, or sound device is
passed into the container.

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
