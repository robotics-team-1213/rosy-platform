package io.github.livsbittt.rosy.cam.camera

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

/** One bounded owned stream-frame copy; disk/rotation work runs on the photo executor. */
class FramePhotoStore(
    val directory: File,
    private val rotate: (ByteArray, Int) -> ByteArray = ::rotateJpeg,
) {
    private data class Frame(val jpeg: ByteArray, val width: Int, val height: Int,
                             val rotation: Int, val atMs: Long)
    private var latest: Frame? = null

    @Synchronized fun update(bytes: ByteArray, length: Int, width: Int, height: Int,
                             rotation: Int, atMs: Long) {
        if (length !in 1..minOf(bytes.size, MAX_BYTES) || width <= 0 || height <= 0 ||
            rotation !in listOf(0, 90, 180, 270)) return
        latest = Frame(bytes.copyOf(length), width, height, rotation, atMs)
    }

    @Synchronized fun clear() { latest = null }

    fun save(nowMs: Long): String? {
        val frame = synchronized(this) { latest } ?: return null
        if (nowMs - frame.atMs !in 0..MAX_AGE_MS) return null
        if (!directory.isDirectory && !directory.mkdirs()) return null
        val stem = "rosy-frame-${System.currentTimeMillis()}-${UUID.randomUUID()}"
        val jpeg = directory.resolve("$stem.jpg")
        val meta = directory.resolve("$stem.json")
        val jpegPart = directory.resolve("$stem.jpg.part")
        val metaPart = directory.resolve("$stem.json.part")
        try {
            val photo = rotate(frame.jpeg, frame.rotation)
            check(photo.isNotEmpty()) { "Empty photo encoding" }
            val swapped = frame.rotation == 90 || frame.rotation == 270
            val metadata = "{\"source\":\"stream_snapshot\",\"width\":${frame.width}," +
                "\"height\":${frame.height},\"rotation_degrees\":${frame.rotation}," +
                "\"saved_rotation_degrees\":0,\"saved_width\":${if (swapped) frame.height else frame.width}," +
                "\"saved_height\":${if (swapped) frame.width else frame.height},\"encoded_monotonic_ms\":${frame.atMs}}\n"
            writeSynced(jpegPart, photo)
            writeSynced(metaPart, metadata.toByteArray(Charsets.UTF_8))
            Files.move(metaPart.toPath(), meta.toPath(), StandardCopyOption.ATOMIC_MOVE)
            Files.move(jpegPart.toPath(), jpeg.toPath(), StandardCopyOption.ATOMIC_MOVE)
            prune(jpeg)
            return jpeg.name
        } catch (error: Exception) {
            jpeg.delete()
            meta.delete()
            throw error
        } finally {
            jpegPart.delete()
            metaPart.delete()
        }
    }

    private fun prune(newest: File) {
        val photos = directory.listFiles()?.filter { it.isFile && PHOTO_NAME.matches(it.name) }
            ?.sortedWith(compareBy<File>({ it.lastModified() }, { it.name })) ?: return
        photos.filter { it != newest }.take(maxOf(0, photos.size - 20)).forEach {
            it.delete()
            directory.resolve(it.name.removeSuffix(".jpg") + ".json").delete()
        }
    }

    companion object {
        const val MAX_BYTES = 2 * 1024 * 1024
        const val MAX_AGE_MS = 3000L
        private val PHOTO_NAME = Regex("rosy-frame-[0-9]+-[0-9a-f-]+\\.jpg")

        private fun writeSynced(file: File, bytes: ByteArray) {
            FileOutputStream(file).use { it.write(bytes); it.fd.sync() }
        }

        private fun rotateJpeg(bytes: ByteArray, degrees: Int): ByteArray {
            if (degrees == 0) return bytes
            val original = requireNotNull(BitmapFactory.decodeByteArray(bytes, 0, bytes.size)) { "JPEG decode failed" }
            var rotated: Bitmap? = null
            try {
                val matrix = Matrix().apply { postRotate(degrees.toFloat()) }
                val rendered = Bitmap.createBitmap(original, 0, 0, original.width, original.height, matrix, true)
                rotated = rendered
                return ByteArrayOutputStream().use { output ->
                    check(rendered.compress(Bitmap.CompressFormat.JPEG, 95, output)) { "Photo encoding failed" }
                    output.toByteArray()
                }
            } finally {
                if (rotated !== original) rotated?.recycle()
                original.recycle()
            }
        }
    }
}
