package io.github.livsbittt.rosy.overhead.camera

import java.nio.ByteBuffer
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class Nv21Test {
    /** Builds a plane of [rows] x [cols] samples with the given strides; padding bytes are 0x7F. */
    private fun plane(rows: Int, cols: Int, rowStride: Int, pixelStride: Int, value: (Int, Int) -> Int): ByteBuffer {
        // Like real camera buffers, the last row is not padded out to the full row stride.
        val size = (rows - 1) * rowStride + (cols - 1) * pixelStride + 1
        val bytes = ByteArray(size) { 0x7F }
        for (r in 0 until rows) for (c in 0 until cols) bytes[r * rowStride + c * pixelStride] = value(r, c).toByte()
        return ByteBuffer.wrap(bytes)
    }

    private fun expected(width: Int, height: Int): ByteArray {
        val out = ByteArray(width * height * 3 / 2)
        var i = 0
        for (r in 0 until height) for (c in 0 until width) out[i++] = (r * 16 + c).toByte()
        for (r in 0 until height / 2) for (c in 0 until width / 2) {
            out[i++] = (200 + r * 4 + c).toByte() // V first in NV21
            out[i++] = (100 + r * 4 + c).toByte()
        }
        return out
    }

    private fun convert(width: Int, height: Int, yRowStride: Int, cRowStride: Int, cPixelStride: Int): ByteArray {
        val y = plane(height, width, yRowStride, 1) { r, c -> r * 16 + c }
        val u = plane(height / 2, width / 2, cRowStride, cPixelStride) { r, c -> 100 + r * 4 + c }
        val v = plane(height / 2, width / 2, cRowStride, cPixelStride) { r, c -> 200 + r * 4 + c }
        val out = ByteArray(Nv21.size(width, height))
        Nv21.pack(width, height, y, yRowStride, 1, u, v, cRowStride, cPixelStride, out)
        return out
    }

    @Test
    fun tightPlanarPlanes() {
        assertArrayEquals(expected(4, 4), convert(4, 4, yRowStride = 4, cRowStride = 2, cPixelStride = 1))
    }

    @Test
    fun paddedRowsAreSkipped() {
        assertArrayEquals(expected(6, 4), convert(6, 4, yRowStride = 8, cRowStride = 8, cPixelStride = 1))
    }

    @Test
    fun semiPlanarPixelStrideTwo() {
        assertArrayEquals(expected(8, 4), convert(8, 4, yRowStride = 8, cRowStride = 8, cPixelStride = 2))
    }

    @Test
    fun paddedSemiPlanar() {
        assertArrayEquals(expected(6, 6), convert(6, 6, yRowStride = 16, cRowStride = 16, cPixelStride = 2))
    }

    @Test
    fun bufferPositionsAreNotConsumed() {
        val y = plane(2, 2, 2, 1) { _, _ -> 1 }
        val u = plane(1, 1, 1, 1) { _, _ -> 2 }
        val v = plane(1, 1, 1, 1) { _, _ -> 3 }
        Nv21.pack(2, 2, y, 2, 1, u, v, 1, 1, ByteArray(6))
        assertEquals(0, y.position())
        assertEquals(0, u.position())
    }

    @Test
    fun sizeIsOneAndAHalfBytesPerPixel() {
        assertEquals(1280 * 720 * 3 / 2, Nv21.size(1280, 720))
    }
}
