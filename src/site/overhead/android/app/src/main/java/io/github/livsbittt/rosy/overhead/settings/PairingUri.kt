package io.github.livsbittt.rosy.overhead.settings

import io.github.livsbittt.rosy.overhead.link.Protocol
import java.net.URLDecoder
import java.net.URLEncoder

/**
 * Pairing target from `rosyov://<host>:<port>/?t=<token>&s=<source>` (D-261 6) or manual entry.
 * Parsed by hand so it runs on the JVM without android.net.Uri.
 */
data class PairingUri(
    val host: String,
    val port: Int,
    val token: String,
    val source: String,
) {
    sealed interface Parsed {
        data class Valid(val pairing: PairingUri) : Parsed
        data class Invalid(val reason: String) : Parsed
    }

    val wsUrl: String get() = "ws://${hostForUrl(host)}:$port${Protocol.WS_PATH}"

    /** Never prints the token: pairings end up in logs and crash reports. */
    override fun toString(): String = "PairingUri(host=$host, port=$port, token=<redacted>, source=$source)"

    fun toUri(): String = "$SCHEME://${hostForUrl(host)}:$port/?t=${encode(token)}&s=${encode(source)}"

    companion object {
        const val SCHEME = "rosyov"
        val SOURCE_PATTERN = Regex("^[A-Za-z0-9_-]{1,32}$")
        private val HOST_PATTERN = Regex("^[A-Za-z0-9._:-]+$")

        fun parse(uri: String): Parsed {
            val trimmed = uri.trim()
            val schemeEnd = trimmed.indexOf("://")
            if (schemeEnd < 0 || !trimmed.substring(0, schemeEnd).equals(SCHEME, ignoreCase = true)) {
                return Parsed.Invalid("scheme")
            }
            val rest = trimmed.substring(schemeEnd + 3)
            val authorityEnd = rest.indexOfAny(charArrayOf('/', '?', '#')).let { if (it < 0) rest.length else it }
            val authority = rest.substring(0, authorityEnd)
            val queryStart = rest.indexOf('?', authorityEnd)
            val query = if (queryStart < 0) "" else rest.substring(queryStart + 1).substringBefore('#')

            val (host, portText) = splitAuthority(authority) ?: return Parsed.Invalid("host")
            if (host.isEmpty()) return Parsed.Invalid("host")
            if (portText == null || portText.isEmpty() || !portText.all { it.isDigit() } || portText.length > 5) {
                return Parsed.Invalid("port")
            }
            val port = portText.toInt()

            val params = mutableMapOf<String, String>()
            for (pair in query.split('&')) {
                if (pair.isEmpty()) continue
                val key = pair.substringBefore('=')
                if (key !in params) params[key] = pair.substringAfter('=', "")
            }
            val token = decode(params["t"]) ?: return Parsed.Invalid("token")
            val source = decode(params["s"]) ?: return Parsed.Invalid("source")

            val reason = validate(host, port, token, source)
            return if (reason == null) Parsed.Valid(PairingUri(host, port, token, source)) else Parsed.Invalid(reason)
        }

        /** Shared rules for deep links and manual entry. Returns the failing field, or null when valid. */
        fun validate(host: String, port: Int, token: String, source: String): String? = when {
            host.isEmpty() || !HOST_PATTERN.matches(host) -> "host"
            port !in 1..65535 -> "port"
            token.isEmpty() -> "token"
            !SOURCE_PATTERN.matches(source) -> "source"
            else -> null
        }

        /** Returns host and port text; handles `[v6]:port`. Null when the authority is malformed. */
        private fun splitAuthority(authority: String): Pair<String, String?>? {
            if (authority.startsWith("[")) {
                val close = authority.indexOf(']')
                if (close < 0) return null
                val host = authority.substring(1, close)
                val after = authority.substring(close + 1)
                return host to (if (after.startsWith(":")) after.substring(1) else null)
            }
            val colon = authority.lastIndexOf(':')
            if (colon < 0) return authority to null
            return authority.substring(0, colon) to authority.substring(colon + 1)
        }

        private fun decode(value: String?): String? {
            if (value == null) return null
            return try {
                URLDecoder.decode(value, "UTF-8")
            } catch (e: IllegalArgumentException) {
                null
            }
        }

        private fun encode(value: String): String = URLEncoder.encode(value, "UTF-8")

        private fun hostForUrl(host: String): String = if (host.contains(':')) "[$host]" else host
    }
}
