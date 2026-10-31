# Face Hello

Turn an old Android phone into a small "door camera" that recognises people and says **"Hello <name>"** out loud.
Everything runs on the phone: no cloud, no server, no account.

Built and tested on a Galaxy S7 (Android 8). The Android app greets within about a second; the Termux version takes
about 4 seconds per camera frame.

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

## Build and run the Android app

**You need**
- A PC with **Android Studio** (it brings the JDK and the Android SDK). Built with Android Studio 2026.2, Android Gradle
  Plugin 9.5 and Gradle 9.8.2; the first build downloads Gradle and the libraries, so be online.
- An Android phone, Android 8.0 or newer, 64-bit ARM (almost every phone since 2016), with **USB debugging** on
  (Settings > About phone > tap "Build number" 7 times, then Developer options > USB debugging).
- About 300 MB of free space on the phone (the app is about 130 MB).

**1. Get the voice files (once).** They are about 60 MB, so they are not in git. In the `android` folder run:

```powershell
.\get-tts.ps1
```

It downloads the sherpa-onnx runtime and the KittenTTS model from github.com/k2-fsa/sherpa-onnx into
`app/libs` and `app/src/main/assets/tts`. (On macOS/Linux download the two files named in the script by hand.)
It uses KittenTTS v0.2 nano: the newer 0.8 models need a runtime (sherpa-onnx 2.x) that no longer includes the
espeak-ng converter they depend on.

**2. Build it.** Either:
- **Android Studio:** File > Open > the `android` folder, wait for the Gradle sync, plug in the phone and press **Run**.
  This builds and installs in one go, so you can skip step 3.
- **Terminal** (needs JDK 17 or newer; Android Studio's is at `C:\Program Files\Android\Android Studio\jbr`):

  ```powershell
  cd android
  .\gradlew.bat assembleDebug        # macOS/Linux: ./gradlew assembleDebug
  ```

  The APK is `android/app/build/outputs/apk/debug/app-debug.apk`.

**3. Install it** (only if you built from the terminal):

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Or copy the APK to the phone and open it (allow "install unknown apps" when asked).

**4. Add the people.** Put photos on the phone in `/sdcard/FaceHello/faces/<Name>/1.jpg`, one folder per person
(details in "Add the people it should recognise" below). Changes are picked up within about 10 seconds.

**5. Run it.** Open **Face Hello**, allow the camera and storage permissions, and tap **Start**. A notification shows
while it runs, and it keeps working with the screen off. Open the address shown in the app
(for example `http://192.168.1.20:8081`) from any device on the same Wi-Fi to watch the camera with a box around each
face. Tap **Stop** to end it.

Tips: plug the phone in, give it a longer screen timeout, and in the phone's battery settings set Face Hello to
"Unrestricted". The camera button switches between the back and front camera.

### What the app screen offers

The app screen has:

- **"Limit greetings to [2] times per person"**: tick the box and set the number to greet each person at most that
  many times. The count starts again whenever you press Stop and then Start.
- **Use Android's built-in voice (faster)**: tick it to greet with the phone's normal text-to-speech, which starts
  instantly. Leave it unticked to use one of the 8 [KittenTTS](https://github.com/KittenML/KittenTTS) voices from the
  list below it: they sound nicer and run on the phone with no internet, but a short greeting takes about 1-2 seconds
  to generate on an old phone, and the first one after starting is slower while the model loads. **Test voice** plays a
  sample with whichever is selected.
- **Recent identifications**: every time someone is recognised (at most once a minute per person) a line with the
  date and time is added on screen and appended to `/sdcard/FaceHello/log.txt`, for example
  `2026-10-31 09:41:12  Sara  (0.54)`. The number is how sure the match was.

The rest of this guide describes the Termux version, which needs no PC or build tools.

## Termux version: what you need

- An Android phone with a camera, on Wi-Fi (tested on Android 8; Termux itself supports Android 7 and newer)
- The **Termux** and **Termux:API** apps, **both from F-Droid** (not the Play Store: that version is outdated)
  - https://f-droid.org/packages/com.termux/
  - https://f-droid.org/packages/com.termux.api/
- About 300 MB of free space and an internet connection for the one-time setup

## Termux version: setup (once)

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

**Custom greeting (optional):** put a text file called `greeting.txt` in a person's folder and the phone says that text
instead of "Hello <name>". `{name}` is replaced by their name. The file is read each time, so edits apply immediately.

```
faces/Sara/greeting.txt     ->  Good morning {name}, your coffee is ready.
```

Photo file names do not matter (`1.jpg`, `me.png`, ...). JPG, PNG and WebP all work.
(Loose files such as `faces/sara.jpg` also work, using the file name as the name, but folders are the tidy way.)

Tips: use a clear, front-facing photo with one face, good light, no sunglasses. Two or three photos per person
(different light or with and without glasses) make it more reliable. New photos are picked up within about 10 seconds,
no restart needed.

## Termux version: use it

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
| `--max-greetings 2` | Greet each person at most 2 times, then stay quiet (default `0` = no limit) |
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
