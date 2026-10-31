package com.facehello

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat

class MainActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private lateinit var status: TextView
    private lateinit var address: TextView
    private lateinit var front: Button
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

    private val permissions = arrayOf(Manifest.permission.CAMERA, Manifest.permission.READ_EXTERNAL_STORAGE)

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
