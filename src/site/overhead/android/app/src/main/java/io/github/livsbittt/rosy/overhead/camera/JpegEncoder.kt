package io.github.livsbittt.rosy.overhead.camera

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import androidx.camera.core.ImageProxy
import java.io.ByteArrayOutputStream

/**
 * YUV_420_888 -> NV21 -> JPEG via [YuvImage.compressToJpeg]. Pixels are not rotated (design
 * section 3); the caller reports the sensor rotation in the frame header instead.
 * Not thread-safe: use from the single analyzer thread. Buffers are reused between frames.
 */
class JpegEncoder {
    sealed interface Result {
        /** JPEG bytes are `bytes[0 until length]`, valid until the next [encode] call. */
        class Encoded(val bytes: ByteArray, val length: Int, val width: Int, val height: Int) : Result

        /** The JPEG exceeded `max_bytes`; the frame must be dropped and counted, not sent. */
        data class TooLarge(val length: Int) : Result
    }

    private class ExposedStream : ByteArrayOutputStream(256 * 1024) {
        fun buffer(): ByteArray = buf
    }

    private var nv21 = ByteArray(0)
    private val out = ExposedStream()

    fun encode(image: ImageProxy, quality: Int, maxBytes: Int): Result {
        require(image.format == ImageFormat.YUV_420_888) { "expected YUV_420_888, got ${image.format}" }
        val width = image.width and 1.inv()
        val height = image.height and 1.inv()
        val needed = Nv21.size(width, height)
        if (nv21.size != needed) nv21 = ByteArray(needed)

        val (yPlane, uPlane, vPlane) = image.planes
        // U and V share row and pixel strides in YUV_420_888.
        Nv21.pack(
            width = width,
            height = height,
            y = yPlane.buffer,
            yRowStride = yPlane.rowStride,
            yPixelStride = yPlane.pixelStride,
            u = uPlane.buffer,
            v = vPlane.buffer,
            chromaRowStride = uPlane.rowStride,
            chromaPixelStride = uPlane.pixelStride,
            out = nv21,
        )

        out.reset()
        YuvImage(nv21, ImageFormat.NV21, width, height, null)
            .compressToJpeg(Rect(0, 0, width, height), quality.coerceIn(1, 100), out)
        val length = out.size()
        if (length > maxBytes) return Result.TooLarge(length)
        return Result.Encoded(out.buffer(), length, width, height)
    }
}
