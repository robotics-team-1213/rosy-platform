package io.github.livsbittt.rosy.cam.camera

import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class YPlaneLumaTest {
    @Test fun respectsCropRowPixelStrideAndUnsignedLumaWithoutMovingBuffer() {
        val data = ByteArray(40) { 0 }
        // Crop (1,1)-(3,3), padded 10-byte rows, 2-byte pixels.
        for (row in 1..2) for (col in 1..2) data[row * 10 + col * 2] = 200.toByte()
        val buffer = ByteBuffer.wrap(data)
        buffer.position(3)
        assertEquals(200, YPlaneLuma.mean(buffer, 10, 2, 1, 1, 3, 3))
        assertEquals(3, buffer.position())
    }

    @Test fun rejectsTruncatedOrEmptyPlane() {
        assertNull(YPlaneLuma.mean(ByteBuffer.allocate(2), 10, 2, 1, 1, 3, 3))
        assertNull(YPlaneLuma.mean(ByteBuffer.allocate(20), 10, 1, 1, 1, 1, 2))
    }
}
