package io.github.livsbittt.rosy.overhead.link

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * rosy-overhead/1 binary frame header (design section 3): little-endian `<4sIIHHHH`,
 * magic `ROF1`, seq u32, age_ms u32, width u16, height u16, rotation_deg u16, reserved u16.
 * The JPEG bytes follow directly. u32 fields are held as Long so seq can wrap at 2^32.
 *
 * Pure Kotlin: no android.* imports, verified against protocol/vectors.json on the JVM.
 */
data class FrameHeader(
    val seq: Long,
    val ageMs: Long,
    val width: Int,
    val height: Int,
    val rotationDeg: Int,
) {
    sealed interface Parsed {
        data class Valid(val header: FrameHeader) : Parsed
        data class Invalid(val reason: String) : Parsed
    }

    /** Writes the 20 header bytes at the start of [target]; the caller appends the JPEG after them. */
    fun writeInto(target: ByteArray) {
        require(target.size >= SIZE) { "target shorter than $SIZE bytes" }
        require(seq in 0..U32_MAX) { "seq out of u32 range: $seq" }
        require(ageMs in 0..U32_MAX) { "age_ms out of u32 range: $ageMs" }
        require(width in 1..U16_MAX && height in 1..U16_MAX) { "size out of range: ${width}x$height" }
        require(rotationDeg in ROTATIONS) { "rotation must be one of $ROTATIONS: $rotationDeg" }
        ByteBuffer.wrap(target, 0, SIZE).order(ByteOrder.LITTLE_ENDIAN).apply {
            put(MAGIC)
            putInt(seq.toInt())
            putInt(ageMs.toInt())
            putShort(width.toShort())
            putShort(height.toShort())
            putShort(rotationDeg.toShort())
            putShort(0)
        }
    }

    fun pack(): ByteArray = ByteArray(SIZE).also { writeInto(it) }

    companion object {
        const val SIZE = 20
        const val U32_MAX = 0xFFFF_FFFFL
        private const val U16_MAX = 0xFFFF
        private val MAGIC = byteArrayOf('R'.code.toByte(), 'O'.code.toByte(), 'F'.code.toByte(), '1'.code.toByte())
        val ROTATIONS: Set<Int> = setOf(0, 90, 180, 270)

        /** Parses the header at the start of [bytes] (a full frame is fine). */
        fun parse(bytes: ByteArray): Parsed {
            if (bytes.size < SIZE) return Parsed.Invalid("short")
            for (i in MAGIC.indices) {
                if (bytes[i] != MAGIC[i]) return Parsed.Invalid("magic")
            }
            val buf = ByteBuffer.wrap(bytes, 4, SIZE - 4).order(ByteOrder.LITTLE_ENDIAN)
            val seq = buf.int.toLong() and U32_MAX
            val age = buf.int.toLong() and U32_MAX
            val width = buf.short.toInt() and U16_MAX
            val height = buf.short.toInt() and U16_MAX
            val rotation = buf.short.toInt() and U16_MAX
            val reserved = buf.short.toInt() and U16_MAX
            if (reserved != 0) return Parsed.Invalid("reserved")
            if (rotation !in ROTATIONS) return Parsed.Invalid("rotation")
            if (width == 0 || height == 0) return Parsed.Invalid("size")
            return Parsed.Valid(FrameHeader(seq, age, width, height, rotation))
        }

        fun nextSeq(seq: Long): Long = (seq + 1) and U32_MAX

        fun clampU32(value: Long): Long = value.coerceIn(0, U32_MAX)
    }
}
