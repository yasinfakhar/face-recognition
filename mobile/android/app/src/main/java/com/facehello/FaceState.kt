package com.facehello

import android.graphics.Bitmap
import java.io.ByteArrayOutputStream

/** Latest results, shared between the recognition service, the web server and the screen. */
object FaceState {
    @Volatile var statusJson: String = """{"ts":0,"faces":[],"events":[],"known":[]}"""
    @Volatile var frame: Bitmap? = null
    @Volatile var summary: String = "Stopped"

    fun frameJpeg(): ByteArray {
        val bmp = frame ?: return ByteArray(0)
        return ByteArrayOutputStream().also { bmp.compress(Bitmap.CompressFormat.JPEG, 75, it) }.toByteArray()
    }
}
