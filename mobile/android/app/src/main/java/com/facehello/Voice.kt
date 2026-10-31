package com.facehello

import android.content.Context
import android.content.res.AssetManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.util.Log
import com.k2fsa.sherpa.onnx.OfflineTts
import com.k2fsa.sherpa.onnx.OfflineTtsConfig
import com.k2fsa.sherpa.onnx.OfflineTtsKittenModelConfig
import com.k2fsa.sherpa.onnx.OfflineTtsModelConfig
import java.io.File
import java.util.concurrent.Executors

/**
 * Speaks greetings. Choice 0 = Android's built-in voice; choices 1..8 = the eight KittenTTS 0.8 voices
 * (run on-device with sherpa-onnx). Falls back to Android's voice if KittenTTS cannot load.
 */
object Voice {
    /** The 8 KittenTTS voices. Their order (male/female pairs) is our best reading of the model files. */
    val CHOICES = listOf("1 - Jasper", "2 - Bella", "3 - Bruno", "4 - Luna", "5 - Hugo", "6 - Rosie", "7 - Leo", "8 - Kiki")

    @Volatile var status = ""   // shown in the app
    private const val TAG = "FaceHello"
    // KittenTTS v0.2 nano. The newer 0.8 models need sherpa-onnx 2.x, which no longer includes the espeak-ng
    // phoneme converter they depend on, so this runs on sherpa-onnx 1.13.8 which still does.
    private const val MODEL_DIR = "kitten-nano-en-v0_2-fp16"
    private val executor = Executors.newSingleThreadExecutor()
    private var kitten: OfflineTts? = null
    private var kittenFailed = false
    private var android: TextToSpeech? = null
    private var androidReady = false

    private fun prefs(context: Context) = context.getSharedPreferences("facehello", Context.MODE_PRIVATE)

    /** True when the "Use Android's built-in voice" box is ticked: instant, but a plainer voice. */
    fun useAndroid(context: Context) = prefs(context).getBoolean("use_android", false)

    /** Which KittenTTS voice (0..7) is chosen in the list. */
    fun kittenVoice(context: Context) = prefs(context).getInt("kitten_voice", 0).coerceIn(0, CHOICES.size - 1)

    /** Gets the chosen voice ready in the background so the first greeting is not delayed. */
    fun preload(context: Context) {
        val app = context.applicationContext
        executor.execute {
            if (useAndroid(app)) {
                status = "Using Android's built-in voice"
                ensureAndroid(app)
            } else {
                loadKitten(app)
            }
        }
    }

    fun speak(context: Context, text: String) {
        val app = context.applicationContext
        executor.execute {
            try {
                if (!useAndroid(app)) {
                    val tts = loadKitten(app)
                    if (tts != null) { playKitten(tts, text, kittenVoice(app)); return@execute }
                }
                speakAndroid(app, text)
            } catch (e: Exception) {
                Log.e(TAG, "speaking failed, using the Android voice", e)
                try { speakAndroid(app, text) } catch (_: Exception) {}
            }
        }
    }

    private var pending: String? = null

    private fun ensureAndroid(app: Context) {
        if (android != null) return
        android = TextToSpeech(app) { code ->
            androidReady = code == TextToSpeech.SUCCESS
            if (androidReady) pending?.let { android?.speak(it, TextToSpeech.QUEUE_ADD, null, "hello"); pending = null }
        }
    }

    private fun speakAndroid(app: Context, text: String) {
        ensureAndroid(app)
        if (androidReady) android?.speak(text, TextToSpeech.QUEUE_ADD, null, "hello") else pending = text
    }

    private fun loadKitten(app: Context): OfflineTts? {
        kitten?.let { return it }
        if (kittenFailed) return null
        return try {
            status = "Loading KittenTTS..."
            val started = SystemClock.elapsedRealtime()
            val dir = File(app.filesDir, "tts/$MODEL_DIR")
            if (!File(dir, ".copied").exists()) {
                copyAsset(app.assets, "tts/$MODEL_DIR", dir)
                File(dir, ".copied").writeText("ok")
            }
            val model = OfflineTtsKittenModelConfig(
                model = "$dir/model.fp16.onnx", voices = "$dir/voices.bin", tokens = "$dir/tokens.txt",
                dataDir = "$dir/espeak-ng-data", lengthScale = 1.0f,
            )
            val config = OfflineTtsConfig(
                model = OfflineTtsModelConfig(kitten = model, numThreads = 4, debug = false, provider = "cpu"),
                maxNumSentences = 1,
            )
            OfflineTts(null, config).also {
                kitten = it
                status = "KittenTTS ready (loaded in ${SystemClock.elapsedRealtime() - started} ms)"
            }
        } catch (e: Throwable) {
            Log.e(TAG, "KittenTTS failed to load", e)
            kittenFailed = true
            status = "KittenTTS failed: ${e.message}. Using the Android voice."
            null
        }
    }

    private fun playKitten(tts: OfflineTts, text: String, speakerId: Int) {
        val started = SystemClock.elapsedRealtime()
        val audio = tts.generate(text, speakerId, 1.0f)
        val took = SystemClock.elapsedRealtime() - started
        val seconds = audio.samples.size.toFloat() / audio.sampleRate
        status = "KittenTTS: %.1f s of speech made in %d ms".format(seconds, took)
        if (audio.samples.isEmpty()) return

        val track = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build(),
            )
            .setAudioFormat(
                AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_FLOAT).setSampleRate(audio.sampleRate)
                    .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build(),
            )
            .setBufferSizeInBytes(audio.samples.size * 4)
            .setTransferMode(AudioTrack.MODE_STATIC)
            .build()
        track.write(audio.samples, 0, audio.samples.size, AudioTrack.WRITE_BLOCKING)
        track.play()
        Thread.sleep((seconds * 1000).toLong() + 250)   // keep the queue in order: next greeting waits for this one
        track.release()
    }

    private fun copyAsset(assets: AssetManager, path: String, target: File) {
        val children = assets.list(path)
        if (children.isNullOrEmpty()) {
            target.parentFile?.mkdirs()
            assets.open(path).use { input -> target.outputStream().use { input.copyTo(it) } }
        } else {
            target.mkdirs()
            for (child in children) copyAsset(assets, "$path/$child", File(target, child))
        }
    }
}
