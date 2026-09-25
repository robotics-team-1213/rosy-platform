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

    fun hex(s: String): ByteArray = ByteArray(s.length / 2) { i ->
        s.substring(2 * i, 2 * i + 2).toInt(16).toByte()
    }

    fun toHex(bytes: ByteArray): String = bytes.joinToString("") { "%02x".format(it.toInt() and 0xFF) }
}
