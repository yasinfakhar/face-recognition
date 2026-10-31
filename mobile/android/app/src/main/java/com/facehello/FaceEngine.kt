package com.facehello

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.nio.FloatBuffer
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

/** One detected face: detector score, box (x, y, w, h) and 5 landmarks (x0, y0, ... x4, y4), all in the bitmap's pixels. */
class Face(val score: Float, val box: FloatArray, val landmarks: FloatArray)

/**
 * YuNet face detection + SFace recognition on ONNX Runtime. Same models and maths as phone/facehello.py.
 */
class FaceEngine(context: Context) {
    private val env = OrtEnvironment.getEnvironment()
    private val det: OrtSession
    private val rec: OrtSession
    private val detInput: String
    private val recInput: String

    init {
        fun session(asset: String): OrtSession {
            val opts = OrtSession.SessionOptions().apply { setIntraOpNumThreads(4) }
            return env.createSession(context.assets.open(asset).readBytes(), opts)
        }
        det = session("models/face_detection_yunet_2023mar.onnx")
        rec = session("models/face_recognition_sface_2021dec.onnx")
        detInput = det.inputNames.first()
        recInput = rec.inputNames.first()
    }

    /** Faces in [bmp], largest first. */
    fun detect(bmp: Bitmap): List<Face> {
        val w = bmp.width
        val h = bmp.height
        val scale = DET_SIZE.toFloat() / max(w, h)
        val nw = (w * scale).roundToInt().coerceAtLeast(1)
        val nh = (h * scale).roundToInt().coerceAtLeast(1)
        val small = if (nw == w && nh == h) bmp else Bitmap.createScaledBitmap(bmp, nw, nh, true)
        val px = IntArray(nw * nh)
        small.getPixels(px, 0, nw, 0, 0, nw, nh)
        if (small !== bmp) small.recycle()

        // BGR, 0-255, zero padding right/bottom (as YuNet expects)
        val plane = DET_SIZE * DET_SIZE
        val input = FloatArray(3 * plane)
        for (y in 0 until nh) {
            for (x in 0 until nw) {
                val p = px[y * nw + x]
                val i = y * DET_SIZE + x
                input[i] = (p and 0xff).toFloat()
                input[plane + i] = ((p shr 8) and 0xff).toFloat()
                input[2 * plane + i] = ((p shr 16) and 0xff).toFloat()
            }
        }

        val boxes = ArrayList<FloatArray>()
        val scores = ArrayList<Float>()
        val marks = ArrayList<FloatArray>()
        OnnxTensor.createTensor(env, FloatBuffer.wrap(input), longArrayOf(1, 3, DET_SIZE.toLong(), DET_SIZE.toLong())).use { tensor ->
            det.run(mapOf(detInput to tensor)).use { out ->
                fun buf(name: String) = (out.get(name).get() as OnnxTensor).floatBuffer
                for (stride in intArrayOf(8, 16, 32)) {
                    val cls = buf("cls_$stride")
                    val obj = buf("obj_$stride")
                    val bbox = buf("bbox_$stride")
                    val kps = buf("kps_$stride")
                    val cols = DET_SIZE / stride
                    for (i in 0 until cols * cols) {
                        val score = sqrt(cls.get(i).coerceIn(0f, 1f) * obj.get(i).coerceIn(0f, 1f))
                        if (score < DET_SCORE) continue
                        val r = i / cols
                        val c = i % cols
                        val cx = (c + bbox.get(i * 4)) * stride
                        val cy = (r + bbox.get(i * 4 + 1)) * stride
                        val bw = exp(bbox.get(i * 4 + 2)) * stride
                        val bh = exp(bbox.get(i * 4 + 3)) * stride
                        boxes.add(floatArrayOf((cx - bw / 2) / scale, (cy - bh / 2) / scale, bw / scale, bh / scale))
                        scores.add(score)
                        val lm = FloatArray(10)
                        for (k in 0 until 5) {
                            lm[2 * k] = (kps.get(i * 10 + 2 * k) + c) * stride / scale
                            lm[2 * k + 1] = (kps.get(i * 10 + 2 * k + 1) + r) * stride / scale
                        }
                        marks.add(lm)
                    }
                }
            }
        }
        return nms(boxes, scores).map { Face(scores[it], boxes[it], marks[it]) }
            .sortedByDescending { it.box[2] * it.box[3] }
    }

    private fun nms(boxes: List<FloatArray>, scores: List<Float>): List<Int> {
        val order = scores.indices.sortedByDescending { scores[it] }.toMutableList()
        val keep = ArrayList<Int>()
        while (order.isNotEmpty()) {
            val i = order.removeAt(0)
            keep.add(i)
            val a = boxes[i]
            order.removeAll { j ->
                val b = boxes[j]
                val iw = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
                val ih = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
                val inter = max(iw, 0f) * max(ih, 0f)
                val union = a[2] * a[3] + b[2] * b[3] - inter
                inter / max(union, 1e-9f) > NMS_IOU
            }
        }
        return keep
    }

    /** L2-normalised 128-d SFace embedding of [face], aligned to the standard 112x112 template. */
    fun embed(bmp: Bitmap, face: Face): FloatArray {
        val src = face.landmarks
        var smx = 0.0; var smy = 0.0; var dmx = 0.0; var dmy = 0.0
        for (k in 0 until 5) {
            smx += src[2 * k]; smy += src[2 * k + 1]
            dmx += TEMPLATE[2 * k]; dmy += TEMPLATE[2 * k + 1]
        }
        smx /= 5; smy /= 5; dmx /= 5; dmy /= 5
        // least-squares similarity transform: dst = [a -b; b a] * src + t
        var a = 0.0; var b = 0.0; var den = 0.0
        for (k in 0 until 5) {
            val sx = src[2 * k] - smx; val sy = src[2 * k + 1] - smy
            val dx = TEMPLATE[2 * k] - dmx; val dy = TEMPLATE[2 * k + 1] - dmy
            a += sx * dx + sy * dy
            b += sx * dy - sy * dx
            den += sx * sx + sy * sy
        }
        a /= den; b /= den
        val tx = dmx - (a * smx - b * smy)
        val ty = dmy - (b * smx + a * smy)
        val det2 = a * a + b * b

        val w = bmp.width
        val h = bmp.height
        val px = IntArray(w * h)
        bmp.getPixels(px, 0, w, 0, 0, w, h)
        val plane = SF_SIZE * SF_SIZE
        val input = FloatArray(3 * plane)
        for (y in 0 until SF_SIZE) {
            for (x in 0 until SF_SIZE) {
                val vx = x - tx
                val vy = y - ty
                val sxp = (a * vx + b * vy) / det2   // inverse map: output pixel -> source pixel
                val syp = (-b * vx + a * vy) / det2
                val x0 = Math.floor(sxp).toInt()
                val y0 = Math.floor(syp).toInt()
                val fx = (sxp - x0).toFloat()
                val fy = (syp - y0).toFloat()
                var r = 0f; var g = 0f; var bl = 0f
                for (dy in 0..1) {
                    for (dx in 0..1) {
                        val xx = x0 + dx
                        val yy = y0 + dy
                        if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue
                        val wgt = (if (dx == 0) 1 - fx else fx) * (if (dy == 0) 1 - fy else fy)
                        val p = px[yy * w + xx]
                        r += wgt * ((p shr 16) and 0xff)
                        g += wgt * ((p shr 8) and 0xff)
                        bl += wgt * (p and 0xff)
                    }
                }
                val i = y * SF_SIZE + x
                input[i] = r             // RGB order, 0-255, no mean/std
                input[plane + i] = g
                input[2 * plane + i] = bl
            }
        }
        OnnxTensor.createTensor(env, FloatBuffer.wrap(input), longArrayOf(1, 3, SF_SIZE.toLong(), SF_SIZE.toLong())).use { tensor ->
            rec.run(mapOf(recInput to tensor)).use { out ->
                val buf = (out.get(0) as OnnxTensor).floatBuffer
                val feat = FloatArray(buf.remaining())
                buf.get(feat)
                var norm = 0f
                for (v in feat) norm += v * v
                norm = sqrt(norm)
                for (i in feat.indices) feat[i] /= norm
                return feat
            }
        }
    }

    /** Reads the photos in the faces folder (one folder per person, or loose files) and returns name -> embeddings. */
    fun enroll(facesDir: File): Map<String, List<FloatArray>> {
        val known = LinkedHashMap<String, MutableList<FloatArray>>()
        for (file in listImages(facesDir)) {
            val bmp = decode(file) ?: continue
            val face = detect(bmp).firstOrNull()
            if (face != null) known.getOrPut(personName(file, facesDir)) { ArrayList() }.add(embed(bmp, face))
            bmp.recycle()
        }
        return known
    }

    private fun decode(file: File): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, bounds)
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= 1280) sample *= 2
        val bmp = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
        val degrees = try {
            when (ExifInterface(file.path).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
                ExifInterface.ORIENTATION_ROTATE_90 -> 90f
                ExifInterface.ORIENTATION_ROTATE_180 -> 180f
                ExifInterface.ORIENTATION_ROTATE_270 -> 270f
                else -> 0f
            }
        } catch (e: Exception) { 0f }
        return if (degrees == 0f) bmp else rotate(bmp, degrees)
    }

    companion object {
        const val MATCH_THRESHOLD = 0.363f   // SFace cosine-similarity threshold from the OpenCV docs
        private const val DET_SIZE = 640
        private const val DET_SCORE = 0.8f
        private const val NMS_IOU = 0.3f
        private const val SF_SIZE = 112
        private val IMG_EXT = setOf("jpg", "jpeg", "png", "bmp", "webp")

        // 5-point template SFace/ArcFace faces are aligned to (112x112)
        private val TEMPLATE = doubleArrayOf(
            38.2946, 51.6963, 73.5318, 51.5014, 56.0252, 71.7366, 41.5493, 92.3655, 70.7299, 92.2041,
        )

        fun rotate(bmp: Bitmap, degrees: Float): Bitmap =
            Bitmap.createBitmap(bmp, 0, 0, bmp.width, bmp.height, Matrix().apply { postRotate(degrees) }, true)

        fun listImages(dir: File): List<File> =
            dir.walkTopDown().filter { it.isFile && it.extension.lowercase() in IMG_EXT }.sortedBy { it.path }.toList()

        /** A signature that changes whenever photos are added, removed or replaced. */
        fun signature(dir: File): String = listImages(dir).joinToString("|") { "${it.path}:${it.lastModified()}:${it.length()}" }

        /** "ali_karimi" / "ali-karimi" / "ALI KARIMI" -> "Ali Karimi"; a folder name or a loose file name. */
        fun personName(file: File, facesDir: File): String {
            val rel = file.relativeTo(facesDir).path.split(File.separatorChar)
            val raw = if (rel.size > 1) rel[0] else file.nameWithoutExtension.replace(Regex("[\\s_\\-]*\\d+$"), "").ifEmpty { file.nameWithoutExtension }
            return raw.replace('_', ' ').replace('-', ' ').trim().split(Regex("\\s+")).joinToString(" ") {
                it.lowercase().replaceFirstChar { c -> c.uppercase() }
            }
        }
    }
}
