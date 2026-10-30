#!/data/data/com.termux/files/usr/bin/bash
# One-time setup. Run inside Termux:  bash /sdcard/FaceHello/setup.sh
# Uses apt-get directly: pkg's mirror check fails on some networks.
set -e
B=/sdcard/FaceHello
exec > >(tee $B/setup.log) 2>&1

APT="apt-get -y -o Dpkg::Options::=--force-confnew"
$APT update
$APT install python python-numpy python-pillow python-onnxruntime termux-api curl

mkdir -p $B/models $B/faces
Z=https://github.com/opencv/opencv_zoo/raw/main/models
[ -s $B/models/face_detection_yunet_2023mar.onnx ] || \
  curl -fL -o $B/models/face_detection_yunet_2023mar.onnx $Z/face_detection_yunet/face_detection_yunet_2023mar.onnx
[ -s $B/models/face_recognition_sface_2021dec.onnx ] || \
  curl -fL -o $B/models/face_recognition_sface_2021dec.onnx $Z/face_recognition_sface/face_recognition_sface_2021dec.onnx

python -c "import onnxruntime, numpy, PIL; print('onnxruntime', onnxruntime.__version__)"
ls -l $B/models
echo "SETUP OK. Run: python $B/facehello.py"
