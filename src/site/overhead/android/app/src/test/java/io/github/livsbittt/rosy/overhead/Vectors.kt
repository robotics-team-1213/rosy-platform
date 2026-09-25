package io.github.livsbittt.rosy.overhead

import java.io.File
import org.json.JSONObject

/** Loads the shared rosy-overhead/1 vectors (src/site/overhead/protocol/vectors.json). */
object Vectors {
    val root: JSONObject by lazy {
        val path = System.getProperty("rosy.overhead.vectors")
            ?: error("system property rosy.overhead.vectors is not set (see app/build.gradle.kts)")
        JSONObject(File(path).readText(Charsets.UTF_8))
    }

    /** Vector hex is grouped by header field with spaces; compare and decode without them. */
    fun compactHex(s: String): String = s.filterNot { it.isWhitespace() }

    fun hex(s: String): ByteArray = compactHex(s).let { h ->
        ByteArray(h.length / 2) { i -> h.substring(2 * i, 2 * i + 2).toInt(16).toByte() }
    }

    fun toHex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it.toInt() and 0xFF) }
}
