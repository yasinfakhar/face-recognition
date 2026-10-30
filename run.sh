#!/bin/sh
set -eu

# Activate conda environment
. $(conda info --base)/etc/profile.d/conda.sh
conda activate face-recognition

# Docker only receives JPEG frames. The host retains camera/display/audio access.
docker compose up -d inference
trap 'docker compose stop inference' EXIT

python3 web_app.py "$@"
