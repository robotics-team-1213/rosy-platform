package io.github.livsbittt.rosy.cam.camera

import java.nio.ByteBuffer

/** Sparse unsigned Y-plane mean; uses absolute reads and never mutates the plane buffer. */
object YPlaneLuma {
    fun mean(buffer: ByteBuffer, rowStride: Int, pixelStride: Int,
             left: Int, top: Int, right: Int, bottom: Int): Int? {
        if (rowStride <= 0 || pixelStride <= 0 || left < 0 || top < 0 || right <= left || bottom <= top) return null
        val last = (bottom - 1).toLong() * rowStride + (right - 1).toLong() * pixelStride
        if (last >= buffer.limit() || last < 0) return null
        val stepX = maxOf(1, (right - left) / 32)
        val stepY = maxOf(1, (bottom - top) / 24)
        var sum = 0L
        var count = 0
        for (y in top until bottom step stepY) for (x in left until right step stepX) {
            sum += buffer.get(y * rowStride + x * pixelStride).toInt() and 255
            count++
        }
        return if (count == 0) null else (sum / count).toInt()
    }
}
