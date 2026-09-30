package io.github.livsbittt.rosy.overhead.settings

import io.github.livsbittt.rosy.overhead.link.Protocol
import java.net.URLDecoder
import java.net.URLEncoder

/**
 * Pairing target from `rosyov://<host>:<port>/?t=<token>&s=<source>[&tls=1[&pin=sha256/<b64url>]]`
 * (D-261 6) or manual entry. Parsed by hand so it runs on the JVM without android.net.Uri.
 *
 * [pin] is the SHA-256 of one certificate's DER in the chain the site serves (D-341 9; see
 * `link/PinnedTrust.kt`). With a pin the link trusts only that certificate; without one a
 * `wss://` link keeps the system trust store. A pin requires `tls=1`.
 */
data class PairingUri(
    val host: String,
    val port: Int,
    val token: String,
    val source: String,
    val secure: Boolean = false,
    val pin: String? = null,
) {
    sealed interface Parsed {
        data class Valid(val pairing: PairingUri) : Parsed
        data class Invalid(val reason: String) : Parsed
    }

    val wsUrl: String get() = "${if (secure) "wss" else "ws"}://${hostForUrl(host)}:$port${Protocol.WS_PATH}"

    /** Never prints the token: pairings end up in logs and crash reports. */
    override fun toString(): String = "PairingUri(host=$host, port=$port, token=<redacted>, source=$source, pin=$pin)"

    fun toUri(): String = "$SCHEME://${hostForUrl(host)}:$port/?t=${encode(token)}&s=${encode(source)}" +
        (if (secure) "&tls=1" else "") + (pin?.let { "&pin=$it" } ?: "")

    companion object {
        const val SCHEME = "rosyov"
        val SOURCE_PATTERN = Regex("^[A-Za-z0-9_-]{1,32}$")
        val PIN_PATTERN = Regex("^sha256/[A-Za-z0-9_-]{43}$")
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
            val tls = params["tls"] ?: "0"
            if (tls !in setOf("0", "1")) return Parsed.Invalid("tls")
            val pin = params["pin"]?.let { decode(it) ?: return Parsed.Invalid("pin") }

            val reason = validate(host, port, token, source, tls == "1", pin)
            return if (reason == null) {
                Parsed.Valid(PairingUri(host, port, token, source, secure = tls == "1", pin = pin))
            } else Parsed.Invalid(reason)
        }

        /** Shared rules for deep links and manual entry. Returns the failing field, or null when valid. */
        fun validate(
            host: String,
            port: Int,
            token: String,
            source: String,
            secure: Boolean = false,
            pin: String? = null,
        ): String? = when {
            host.isEmpty() || !HOST_PATTERN.matches(host) -> "host"
            port !in 1..65535 -> "port"
            token.isEmpty() -> "token"
            !SOURCE_PATTERN.matches(source) -> "source"
            pin != null && (!secure || !PIN_PATTERN.matches(pin)) -> "pin"
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
