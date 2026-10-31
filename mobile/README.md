# Face Hello

Turn an old Android phone into a small "door camera" that recognises people and says **"Hello <name>"** out loud.
Everything runs on the phone: no cloud, no server, no account.

Built and tested on a Galaxy S7 (Android 8). Recognition takes about 4 seconds per camera frame.

```
android/  the Android app (fast: a greeting within about a second)
phone/    the Termux version (no build tools needed, but about 4 s per frame)
laptop/   optional Windows shortcuts for the Termux version
```

## Which one?

| | Android app (`android/`) | Termux version (`phone/`) |
|---|---|---|
| Speed | about 3 frames per second | about 1 frame every 4 s |
| Setup | build the APK once (needs Android Studio), install it | copy a folder, run one command in Termux |
| Start | tap the app, then Start | type `face` in Termux |

Both read the same photos in `/sdcard/FaceHello/faces/` and show the same viewer page on port 8081. Do not run both
at once: they would fight over the camera.

### Android app

1. Open the `android` folder in Android Studio and press **Run** with the phone connected. Or from a terminal:
   `gradlew assembleDebug` (needs a JDK and the Android SDK) and install `app/build/outputs/apk/debug/app-debug.apk`.
2. Put photos in `/sdcard/FaceHello/faces/<Name>/1.jpg` (see "Add the people" below).
3. Open the app, allow the camera and storage permissions, tap **Start**. Open the viewer address it shows from any
   device on the same Wi-Fi. It keeps running in the background with a notification.

The rest of this guide describes the Termux version.

## What you need

- An Android phone with a camera, on Wi-Fi (tested on Android 8; Termux itself supports Android 7 and newer)
- The **Termux** and **Termux:API** apps, **both from F-Droid** (not the Play Store: that version is outdated)
  - https://f-droid.org/packages/com.termux/
  - https://f-droid.org/packages/com.termux.api/
- About 300 MB of free space and an internet connection for the one-time setup

## Setup (once)

1. **Install Termux and Termux:API** from F-Droid. Open Termux:API once, then allow it to use the camera:
   Android Settings > Apps > Termux:API > Permissions > Camera.
2. **Copy the `phone` folder to the phone** and rename it to `FaceHello`, so it ends up at
   `/sdcard/FaceHello` (the main storage, next to Downloads and DCIM). Use a USB cable, Bluetooth or any file manager.
   If you got this project from someone else, delete any photos inside its `faces` folder first: those are their friends, not yours.
3. **Open Termux** and run these two commands. Accept the storage permission popup when asked.

   ```bash
   termux-setup-storage
   bash /sdcard/FaceHello/setup.sh
   ```

   This installs Python and the face models. It takes a few minutes and needs a connection.
   Wait until it prints `SETUP OK`.
4. **Create the short command** (once):

   ```bash
   bash /sdcard/FaceHello/run.sh --install
   ```

## Add the people it should recognise

Make **one folder per person** inside `/sdcard/FaceHello/faces/`. **The folder name is the name it says.**
Put that person's photos in it:

```
faces/
  Sara/
    1.jpg            ->  "Hello Sara"
    2.jpg            (a second photo of Sara, optional)
  Ali Karimi/
    1.png            ->  "Hello Ali Karimi"
```

Photo file names do not matter (`1.jpg`, `me.png`, ...). JPG, PNG and WebP all work.
(Loose files such as `faces/sara.jpg` also work, using the file name as the name, but folders are the tidy way.)

Tips: use a clear, front-facing photo with one face, good light, no sunglasses. Two or three photos per person
(different light or with and without glasses) make it more reliable. New photos are picked up within about 10 seconds,
no restart needed.

## Use it

In Termux, type:

```bash
face
```

It starts the camera, prints an address like `http://192.168.1.20:8081`, and says "Hello <name>" when it
recognises someone (at most once a minute per person). Press **Ctrl+C** in Termux to stop.

**Watch what it sees:** open that address in any browser on the same Wi-Fi (laptop, another phone).
You get the live camera frame with a box around each face: green with the name if it knows them, amber "Unknown" if not,
plus the match score and a log of greetings. If you lose the address, type `face` again and read it, or check the phone's
Wi-Fi settings.

## Options

Add these after `face`, for example `face --camera 1 --threshold 0.3`:

| Option | Meaning |
|---|---|
| `--camera 1` | Use the front camera (default `0`, the back camera) |
| `--threshold 0.3` | Lower = easier to match but more mistakes (default `0.363`). Use this if it does not recognise you |
| `--cooldown 120` | Seconds before greeting the same person again (default 60) |
| `--no-speech` | Print only, do not speak |

## Troubleshooting

- **"Unable to locate package" or "None of the mirrors are accessible" during setup:** run
  `bash /sdcard/FaceHello/setup.sh` again. Setup talks to the package servers directly; a flaky connection is the usual cause.
- **It never recognises me:** open the viewer. If there is no box at all, the camera cannot see your face
  (light, distance, angle). If the box is amber with a score just below `0.363`, lower `--threshold`
  or add another photo.
- **No camera image / errors about the camera:** make sure Termux:API has the camera permission and that no other
  app (for example a camera or IP Webcam stream) is using the camera.
- **No sound:** check the phone's volume and that a text-to-speech engine is installed (Android Settings > Language & input).
- **It stops when the screen turns off:** `face` takes a wake lock, but some phones also need Termux excluded from
  battery optimisation (Settings > Battery > Termux > Unrestricted).
- **Faces look sideways in the viewer:** nothing to fix: the script rotates frames automatically.

## Optional: start it from a Windows PC

With USB debugging on and the phone plugged in, double-click `laptop/start.bat`. It copies the latest files to the
phone, starts everything and opens the viewer. `laptop/stop.bat` stops it. This needs
[adb (platform-tools)](https://developer.android.com/tools/releases/platform-tools) installed.

## Privacy

Photos and recognition stay on the phone. The only network traffic is the viewer page on your own Wi-Fi, which has **no
password**, so anyone on the same network can open it and see the camera. Only use it on a network you trust, and
only add photos of people who are fine with it.
