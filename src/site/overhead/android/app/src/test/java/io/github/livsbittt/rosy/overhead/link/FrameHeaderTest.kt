package io.github.livsbittt.rosy.overhead.link

import io.github.livsbittt.rosy.overhead.Vectors
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class FrameHeaderTest {
    private val headers = Vectors.root.getJSONObject("frame_headers")

    @Test
    fun sizeMatchesVectors() {
        assertEquals(Vectors.root.getInt("header_size"), FrameHeader.SIZE)
    }

    @Test
    fun packMatchesEveryValidVector() {
        val valid = headers.getJSONArray("valid")
        assertTrue(valid.length() > 0)
        for (i in 0 until valid.length()) {
            val v = valid.getJSONObject(i)
            val header = FrameHeader(
                seq = v.getLong("seq"),
                ageMs = v.getLong("age_ms"),
                width = v.getInt("width"),
                height = v.getInt("height"),
                rotationDeg = v.getInt("rotation_deg"),
            )
            assertEquals(v.getString("name"), v.getString("hex"), Vectors.toHex(header.pack()))
        }
    }

    @Test
    fun parseRoundTripsEveryValidVector() {
        val valid = headers.getJSONArray("valid")
        for (i in 0 until valid.length()) {
            val v = valid.getJSONObject(i)
            val result = FrameHeader.parse(Vectors.hex(v.getString("hex")))
            val expected = FrameHeader(
                v.getLong("seq"), v.getLong("age_ms"), v.getInt("width"),
                v.getInt("height"), v.getInt("rotation_deg"),
            )
            assertEquals(v.getString("name"), FrameHeader.Parsed.Valid(expected), result)
        }
    }

    @Test
    fun parseRejectsEveryInvalidVectorWithItsReason() {
        val invalid = headers.getJSONArray("invalid")
        assertTrue(invalid.length() > 0)
        for (i in 0 until invalid.length()) {
            val v = invalid.getJSONObject(i)
            val result = FrameHeader.parse(Vectors.hex(v.getString("hex")))
            assertEquals(v.getString("name"), FrameHeader.Parsed.Invalid(v.getString("reason")), result)
        }
    }

    @Test
    fun parseReadsOnlyTheHeaderOfAFullFrame() {
        val header = FrameHeader(7, 12, 1280, 720, 0)
        val frame = header.pack() + byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte())
        assertEquals(FrameHeader.Parsed.Valid(header), FrameHeader.parse(frame))
    }

    @Test
    fun rotationValuesMatchVectors() {
        val rotations = Vectors.root.getJSONArray("rotation_values")
        val fromVectors = (0 until rotations.length()).map { rotations.getInt(it) }.toSet()
        assertEquals(fromVectors, FrameHeader.ROTATIONS)
    }

    @Test
    fun seqWrapsAtTwoToThe32() {
        assertEquals(1L, FrameHeader.nextSeq(0L))
        assertEquals(0L, FrameHeader.nextSeq(0xFFFF_FFFFL))
    }

    @Test
    fun ageIsClampedToU32() {
        assertEquals(0L, FrameHeader.clampU32(-5L))
        assertEquals(0xFFFF_FFFFL, FrameHeader.clampU32(1L shl 40))
        assertEquals(57L, FrameHeader.clampU32(57L))
    }

    @Test
    fun writeIntoPrefixesAnExistingBuffer() {
        val header = FrameHeader(1842, 57, 1280, 720, 0)
        val buffer = ByteArray(FrameHeader.SIZE + 2)
        header.writeInto(buffer)
        assertEquals(Vectors.toHex(header.pack()), Vectors.toHex(buffer.copyOf(FrameHeader.SIZE)))
    }

    @Test(expected = IllegalArgumentException::class)
    fun packRejectsBadRotation() {
        FrameHeader(0, 0, 1280, 720, 45).pack()
    }

    @Test(expected = IllegalArgumentException::class)
    fun packRejectsZeroHeight() {
        FrameHeader(0, 0, 1280, 0, 0).pack()
    }

    @Test(expected = IllegalArgumentException::class)
    fun packRejectsSeqAboveU32() {
        FrameHeader(1L shl 32, 0, 1280, 720, 0).pack()
    }
}
