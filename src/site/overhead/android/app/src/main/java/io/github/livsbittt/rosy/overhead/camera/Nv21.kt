package io.github.livsbittt.rosy.overhead.camera

import java.nio.ByteBuffer

/**
 * Packs YUV_420_888 planes into NV21 (Y plane, then interleaved V/U), honouring each plane's
 * row stride and pixel stride. Pure Kotlin so the stride handling is JVM-tested.
 * Buffer positions are left untouched (absolute reads only).
 */
object Nv21 {
    fun size(width: Int, height: Int): Int = width * height + 2 * (width / 2) * (height / 2)

    fun pack(
        width: Int,
        height: Int,
        y: ByteBuffer,
        yRowStride: Int,
        yPixelStride: Int,
        u: ByteBuffer,
        v: ByteBuffer,
        chromaRowStride: Int,
        chromaPixelStride: Int,
        out: ByteArray,
    ) {
        require(out.size >= size(width, height)) { "output too small for ${width}x$height" }
        var o = 0
        if (yPixelStride == 1) {
            val rowView = y.duplicate()
            for (row in 0 until height) {
                rowView.position(row * yRowStride)
                rowView.get(out, o, width)
                o += width
            }
        } else {
            for (row in 0 until height) {
                val base = row * yRowStride
                for (col in 0 until width) out[o++] = y.get(base + col * yPixelStride)
            }
        }
        val chromaWidth = width / 2
        val chromaHeight = height / 2
        for (row in 0 until chromaHeight) {
            val base = row * chromaRowStride
            for (col in 0 until chromaWidth) {
                val index = base + col * chromaPixelStride
                out[o++] = v.get(index)
                out[o++] = u.get(index)
            }
        }
    }
}
