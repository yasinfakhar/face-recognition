package com.facehello

import android.content.Context
import fi.iki.elonen.NanoHTTPD
import java.io.ByteArrayInputStream

/** Serves the viewer page, the latest analysed frame and the recognition status on the local network. */
class ViewerServer(private val context: Context, port: Int) : NanoHTTPD(port) {
    override fun serve(session: IHTTPSession): Response {
        val response = when (session.uri) {
            "/", "/viewer.html" -> newFixedLengthResponse(
                Response.Status.OK, "text/html; charset=utf-8",
                context.assets.open("viewer.html").use { it.readBytes() }.toString(Charsets.UTF_8),
            )
            "/status.json" -> newFixedLengthResponse(Response.Status.OK, "application/json", FaceState.statusJson)
            "/frame.jpg" -> {
                val jpg = FaceState.frameJpeg()
                if (jpg.isEmpty()) newFixedLengthResponse(Response.Status.NOT_FOUND, MIME_PLAINTEXT, "no frame yet")
                else newFixedLengthResponse(Response.Status.OK, "image/jpeg", ByteArrayInputStream(jpg), jpg.size.toLong())
            }
            else -> newFixedLengthResponse(Response.Status.NOT_FOUND, MIME_PLAINTEXT, "not found")
        }
        response.addHeader("Access-Control-Allow-Origin", "*")
        response.addHeader("Cache-Control", "no-store")
        return response
    }
}
