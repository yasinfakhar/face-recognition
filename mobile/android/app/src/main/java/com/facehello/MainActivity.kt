package com.facehello

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.text.InputType
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.Spinner
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.widget.doAfterTextChanged

class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private lateinit var address: TextView
    private lateinit var front: Button
    private lateinit var logView: TextView
    private lateinit var voiceStatus: TextView
    private var running = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (24 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
        }
        root.addView(TextView(this).apply { text = "Face Hello"; textSize = 26f })
        status = TextView(this).apply { textSize = 16f; setPadding(0, pad / 2, 0, pad / 2) }
        address = TextView(this).apply { textSize = 16f; setPadding(0, 0, 0, pad) }
        root.addView(status)
        root.addView(address)

        val toggle = Button(this).apply { text = "Start" }
        toggle.setOnClickListener {
            if (running) {
                stopService(Intent(this, FaceService::class.java)); running = false; toggle.text = "Start"
            } else {
                requestAndStart()
                toggle.text = "Stop"
            }
        }
        root.addView(toggle)

        front = Button(this)
        front.setOnClickListener {
            val prefs = getSharedPreferences("facehello", Context.MODE_PRIVATE)
            prefs.edit().putBoolean("front", !prefs.getBoolean("front", false)).apply()
            updateFrontLabel()
            if (running) { // restart so the other camera is used
                stopService(Intent(this, FaceService::class.java))
                handler.postDelayed({ startService() }, 800)
            }
        }
        root.addView(front)
        // Optional limit: greet each person at most N times (counted until the app is stopped and started again)
        val prefs = getSharedPreferences("facehello", Context.MODE_PRIVATE)
        val limitBox = CheckBox(this).apply {
            text = "Limit greetings to"
            isChecked = prefs.getBoolean("limit_on", false)
            setOnCheckedChangeListener { _, on -> prefs.edit().putBoolean("limit_on", on).apply() }
        }
        val limitCount = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_NUMBER
            setText(prefs.getInt("limit_n", 2).toString())
            minEms = 3
            doAfterTextChanged { text ->
                text?.toString()?.toIntOrNull()?.let { prefs.edit().putInt("limit_n", it).apply() }
            }
        }
        root.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, pad / 2, 0, 0)
            addView(limitBox)
            addView(limitCount)
            addView(TextView(this@MainActivity).apply { text = " times per person" })
        })
        // Voice for the greetings: Android's own (fast) voice, or one of the 8 KittenTTS voices (nicer, slower)
        val voiceSpinner = Spinner(this).apply {
            adapter = ArrayAdapter(this@MainActivity, android.R.layout.simple_spinner_item, Voice.CHOICES)
                .also { it.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item) }
            setSelection(Voice.kittenVoice(this@MainActivity))
            isEnabled = !Voice.useAndroid(this@MainActivity)
            onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
                override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                    prefs.edit().putInt("kitten_voice", position).apply()
                }
                override fun onNothingSelected(parent: AdapterView<*>?) {}
            }
        }
        root.addView(CheckBox(this).apply {
            text = "Use Android's built-in voice (faster)"
            isChecked = Voice.useAndroid(this@MainActivity)
            setPadding(0, pad / 2, 0, 0)
            setOnCheckedChangeListener { _, on ->
                prefs.edit().putBoolean("use_android", on).apply()
                voiceSpinner.isEnabled = !on
                Voice.preload(this@MainActivity)
            }
        })
        root.addView(TextView(this).apply { text = "KittenTTS voice"; setPadding(0, pad / 3, 0, 0) })
        root.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(voiceSpinner, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(Button(this@MainActivity).apply {
                text = "Test voice"
                setOnClickListener { Voice.speak(this@MainActivity, "Hello, this is a test of the greeting voice.") }
            })
        })
        voiceStatus = TextView(this).apply { textSize = 13f }
        root.addView(voiceStatus)
        root.addView(TextView(this).apply {
            text = "\nRecent identifications (all saved in /sdcard/FaceHello/log.txt):"
            setPadding(0, pad / 2, 0, 0)
        })
        logView = TextView(this).apply { textSize = 14f; typeface = Typeface.MONOSPACE }
        root.addView(logView)
        root.addView(TextView(this).apply {
            text = "\nPhotos go in /sdcard/FaceHello/faces/<Name>/1.jpg. The phone says \"Hello <Name>\" when it recognises them."
            gravity = Gravity.START
        })
        setContentView(root)
        updateFrontLabel()
        tick()
    }

    private fun updateFrontLabel() {
        val isFront = getSharedPreferences("facehello", Context.MODE_PRIVATE).getBoolean("front", false)
        front.text = if (isFront) "Camera: front (tap to switch)" else "Camera: back (tap to switch)"
    }

    private val permissions = arrayOf(
        Manifest.permission.CAMERA,
        Manifest.permission.READ_EXTERNAL_STORAGE,
        Manifest.permission.WRITE_EXTERNAL_STORAGE, // for the identification log
    )

    private fun requestAndStart() {
        if (permissions.all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }) startService()
        else requestPermissions(permissions, 1)
    }

    override fun onRequestPermissionsResult(requestCode: Int, perms: Array<out String>, results: IntArray) {
        if (results.isNotEmpty() && results.all { it == PackageManager.PERMISSION_GRANTED }) startService()
        else status.text = "Camera and storage permissions are needed."
    }

    private fun startService() {
        ContextCompat.startForegroundService(this, Intent(this, FaceService::class.java))
        running = true
    }

    private fun tick() {
        status.text = FaceState.summary
        voiceStatus.text = Voice.status
        logView.text = FaceState.log.take(8).joinToString("\n").ifEmpty { "Nobody identified yet." }
        address.text = "Viewer: http://${wifiAddress()}:${FaceService.PORT}"
        handler.postDelayed({ tick() }, 1000)
    }

    @Suppress("DEPRECATION")
    private fun wifiAddress(): String {
        val ip = (applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager).connectionInfo.ipAddress
        return if (ip == 0) "<phone-ip>" else "${ip and 0xff}.${ip shr 8 and 0xff}.${ip shr 16 and 0xff}.${ip shr 24 and 0xff}"
    }

    override fun onDestroy() {
        handler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }
}
