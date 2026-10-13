package io.github.livsbittt.rosy.pilot

/** Existing robot displays group their eight-character code as XXXX-XXXX. */
object PairingCode {
    fun normalize(input: String): String = input.filterNot { it == '-' || it.isWhitespace() }.uppercase(java.util.Locale.ROOT).also {
        require(Regex("[0-9A-Z]{8}").matches(it)) { "eight-character pairing code required" }
    }
}

class PairingRejected(val status: Int) : IllegalStateException("pair approval HTTP $status")
