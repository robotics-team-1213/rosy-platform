package io.github.livsbittt.rosy.cam.camera

import java.nio.ByteBuffer

/** D-544: highlight/shadow fractions and mean of the field area (Y plane, inset 10 %). */
data class LumaStats(val clip: Double, val crush: Double, val mean: Double) {
    companion object {
        const val CLIP_LEVEL = 247
        const val CRUSH_LEVEL = 16

        /** Sparse, absolute-read sample like [YPlaneLuma]; null on a bad crop or a truncated plane. */
        fun measure(buffer: ByteBuffer, rowStride: Int, pixelStride: Int,
                    left: Int, top: Int, right: Int, bottom: Int): LumaStats? {
            val insetX = (right - left) / 10
            val insetY = (bottom - top) / 10
            val l = left + insetX
            val r = right - insetX
            val t = top + insetY
            val b = bottom - insetY
            if (rowStride <= 0 || pixelStride <= 0 || left < 0 || top < 0 || r <= l || b <= t) return null
            val last = (b - 1).toLong() * rowStride + (r - 1).toLong() * pixelStride
            if (last >= buffer.limit() || last < 0) return null
            val stepX = maxOf(1, (r - l) / 32)
            val stepY = maxOf(1, (b - t) / 24)
            var sum = 0L
            var clip = 0
            var crush = 0
            var count = 0
            for (y in t until b step stepY) for (x in l until r step stepX) {
                val v = buffer.get(y * rowStride + x * pixelStride).toInt() and 255
                sum += v
                if (v >= CLIP_LEVEL) clip++
                if (v <= CRUSH_LEVEL) crush++
                count++
            }
            if (count == 0) return null
            return LumaStats(clip.toDouble() / count, crush.toDouble() / count, sum.toDouble() / count)
        }
    }
}
