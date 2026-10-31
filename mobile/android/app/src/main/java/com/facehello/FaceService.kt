package com.facehello

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors

/** Keeps the camera open, recognises faces on every frame and says hello. Runs as a foreground service. */
class FaceService : LifecycleService() {
    private val analysisExecutor = Executors.newSingleThreadExecutor()
    private val worker = Executors.newSingleThreadExecutor()
    private var engine: FaceEngine? = null
    private var server: ViewerServer? = null
    private var wakeLock: PowerManager.WakeLock? = null

    @Volatile private var known: Map<String, List<FloatArray>> = emptyMap()
    @Volatile private var enrolling = false
    private var lastSignature = ""
    private var lastScan = 0L
    private var lastAnalysis = 0L
    private var extraRot = 0        // extra rotation if the phone is mounted sideways
    private var emptyFrames = 0
    private val lastGreeted = HashMap<String, Long>()
    private val greetCount = HashMap<String, Int>()
    private val lastLogged = HashMap<String, Long>()
    private val events = ArrayList<Pair<Double, String>>()
    private val facesDir = File(FACES_DIR)

    override fun onCreate() {
        super.onCreate()
        startForeground(1, buildNotification())
        wakeLock = (getSystemService(Context.POWER_SERVICE) as PowerManager)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "facehello:service").apply { acquire() }
        Voice.preload(this)
        FaceState.summary = "Loading models..."
        worker.execute {
            try {
                server = ViewerServer(this, PORT).also { it.start() }
                engine = FaceEngine(this)
                enrollNow()
                ContextCompat.getMainExecutor(this).execute { bindCamera() }
            } catch (e: Exception) {
                Log.e(TAG, "startup failed", e)
                FaceState.summary = "Error: ${e.message}"
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        return START_STICKY
    }

    override fun onDestroy() {
        ProcessCameraProvider.getInstance(this).get().unbindAll()
        server?.stop()
        wakeLock?.release()
        analysisExecutor.shutdownNow()
        worker.shutdownNow()
        FaceState.summary = "Stopped"
        super.onDestroy()
    }

    private fun buildNotification(): Notification {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel(CHANNEL, "Face Hello", NotificationManager.IMPORTANCE_LOW))
        return Notification.Builder(this, CHANNEL)
            .setContentTitle("Face Hello is running")
            .setContentText("Watching the camera")
            .setSmallIcon(android.R.drawable.ic_menu_camera)
            .build()
    }

    private fun enrollNow() {
        enrolling = true
        try {
            FaceState.summary = "Reading photos..."
            val signature = FaceEngine.signature(facesDir)
            known = engine!!.enroll(facesDir)
            lastSignature = signature
            Log.i(TAG, "known people: ${known.mapValues { it.value.size }}")
        } finally {
            enrolling = false
        }
    }

    private fun bindCamera() {
        val front = getSharedPreferences("facehello", MODE_PRIVATE).getBoolean("front", false)
        val analysis = ImageAnalysis.Builder()
            .setTargetResolution(Size(640, 480))
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
            .build()
        analysis.setAnalyzer(analysisExecutor) { analyze(it) }
        val providerFuture = ProcessCameraProvider.getInstance(this)
        providerFuture.addListener({
            val provider = providerFuture.get()
            provider.unbindAll()
            provider.bindToLifecycle(
                this,
                if (front) CameraSelector.DEFAULT_FRONT_CAMERA else CameraSelector.DEFAULT_BACK_CAMERA,
                analysis,
            )
        }, ContextCompat.getMainExecutor(this))
    }

    private fun analyze(image: ImageProxy) {
        try {
            val now = SystemClock.elapsedRealtime()
            if (now - lastAnalysis < MIN_GAP_MS) return
            lastAnalysis = now

            var bmp = image.toBitmap()
            val rotation = image.imageInfo.rotationDegrees
            if (rotation != 0) bmp = FaceEngine.rotate(bmp, rotation.toFloat())

            if (now - lastScan > 10_000 && !enrolling) {
                lastScan = now
                if (FaceEngine.signature(facesDir) != lastSignature) {
                    Log.i(TAG, "faces folder changed, re-enrolling")
                    worker.execute { enrollNow() }
                }
            }
            process(bmp, now)
        } catch (e: Exception) {
            Log.e(TAG, "analyze failed", e)
        } finally {
            image.close()
        }
    }

    private fun rotated(bmp: Bitmap, degrees: Int) = if (degrees == 0) bmp else FaceEngine.rotate(bmp, degrees.toFloat())

    private fun process(bmp: Bitmap, startedAt: Long) {
        val eng = engine ?: return
        var frame = rotated(bmp, extraRot)
        var faces = eng.detect(frame)
        if (faces.isEmpty()) {
            // If the phone is mounted sideways nothing is found: now and then try the other orientations.
            if (++emptyFrames % 6 == 0) {
                for (r in intArrayOf(0, 90, 270, 180)) {
                    if (r == extraRot) continue
                    val candidate = rotated(bmp, r)
                    val found = eng.detect(candidate)
                    if (found.isNotEmpty()) {
                        extraRot = r; frame = candidate; faces = found
                        break
                    }
                }
            }
        } else {
            emptyFrames = 0
        }

        val people = known
        val results = JSONArray()
        for (face in faces) {
            val feat = eng.embed(frame, face)
            var best: String? = null
            var bestScore = -1f
            for ((name, feats) in people) {
                for (k in feats) {
                    var s = 0f
                    for (i in feat.indices) s += feat[i] * k[i]
                    if (s > bestScore) { bestScore = s; best = name }
                }
            }
            val name = if (bestScore >= FaceEngine.MATCH_THRESHOLD) best else null
            results.put(JSONObject().apply {
                put("name", name ?: JSONObject.NULL)
                put("similarity", Math.round(bestScore * 1000) / 1000.0)
                put("detector", Math.round(face.score * 100) / 100.0)
                put("box", JSONArray(face.box.map { Math.round(it) }))
            })
            if (name != null) {
                logIdentification(name, bestScore)
                greet(name)
            }
        }

        val ts = System.currentTimeMillis() / 1000.0
        FaceState.frame = frame
        FaceState.statusJson = JSONObject().apply {
            put("ts", ts)
            put("width", frame.width)
            put("height", frame.height)
            put("faces", results)
            put("events", JSONArray().also { arr -> events.forEach { arr.put(JSONObject().put("ts", it.first).put("text", it.second)) } })
            put("known", JSONArray(people.keys.sorted()))
            put("threshold", FaceEngine.MATCH_THRESHOLD.toDouble())
        }.toString()
        FaceState.summary = "Running: ${people.size} people known, ${SystemClock.elapsedRealtime() - startedAt} ms per frame" +
            if (enrolling) " (reading photos...)" else ""
    }

    /** Records when a person was recognised (at most once a minute per person), in the app and in LOG_FILE. */
    private fun logIdentification(name: String, similarity: Float) {
        val now = SystemClock.elapsedRealtime()
        if (now - (lastLogged[name] ?: -LOG_GAP_MS) < LOG_GAP_MS) return
        lastLogged[name] = now
        val line = "${SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.US).format(Date())}  $name  (${"%.2f".format(Locale.US, similarity)})"
        FaceState.log.add(0, line)
        while (FaceState.log.size > 50) FaceState.log.removeAt(FaceState.log.size - 1)
        try {
            File(LOG_FILE).apply { parentFile?.mkdirs() }.appendText(line + "\n")
        } catch (e: Exception) {
            Log.e(TAG, "could not write $LOG_FILE", e)
        }
    }

    private fun greet(name: String) {
        // Optional limit from the app screen: at most N greetings per person until the service is restarted
        val prefs = getSharedPreferences("facehello", MODE_PRIVATE)
        if (prefs.getBoolean("limit_on", false) && (greetCount[name] ?: 0) >= prefs.getInt("limit_n", 2)) return
        val now = SystemClock.elapsedRealtime()
        if (now - (lastGreeted[name] ?: -COOLDOWN_MS) < COOLDOWN_MS) return
        lastGreeted[name] = now
        greetCount[name] = (greetCount[name] ?: 0) + 1
        val text = FaceEngine.greetingFor(facesDir, name)
        events.add(0, System.currentTimeMillis() / 1000.0 to text)
        while (events.size > 20) events.removeAt(events.size - 1)
        Voice.speak(this, text)
    }

    companion object {
        const val FACES_DIR = "/sdcard/FaceHello/faces"
        const val LOG_FILE = "/sdcard/FaceHello/log.txt"
        private const val LOG_GAP_MS = 60_000L     // log the same person at most once a minute
        const val PORT = 8081
        private const val TAG = "FaceHello"
        private const val CHANNEL = "facehello"
        private const val MIN_GAP_MS = 150L        // at most ~6 analysed frames per second, to spare the battery
        private const val COOLDOWN_MS = 60_000L    // greet the same person at most once a minute
    }
}
