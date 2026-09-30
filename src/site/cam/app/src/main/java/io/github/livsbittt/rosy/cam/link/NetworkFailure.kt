package io.github.livsbittt.rosy.cam.link

import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException

/** What a failed WebSocket attempt says about the path to the receiver. Pure JVM; no Android types. */
enum class NetworkFailure {
    /** Connect timed out or there is no route: wrong subnet, PC off, or address changed. */
    UNREACHABLE,

    /** The PC answered with a reset: it is up but nothing listens on the port. */
    REFUSED,

    /** The host name did not resolve (for example a `.local` name off the site LAN). */
    UNKNOWN_HOST,

    /** TLS handshake or certificate failure on a `wss://` pairing. */
    TLS,

    OTHER,
    ;

    companion object {
        /**
         * Walks the cause chain; the first specific signal wins. A bare [ConnectException]
         * counts as unreachable only when nothing in the chain is more specific, because
         * OkHttp wraps the socket's "Connection refused" in its own ConnectException.
         */
        fun classify(error: Throwable): NetworkFailure {
            val chain = generateSequence(error) { it.cause }.take(MAX_DEPTH).toList()
            chain.firstNotNullOfOrNull(::specific)?.let { return it }
            return if (chain.any { it is ConnectException }) UNREACHABLE else OTHER
        }

        private fun specific(t: Throwable): NetworkFailure? {
            val message = t.message.orEmpty()
            return when {
                t is SSLException -> TLS
                t is UnknownHostException -> UNKNOWN_HOST
                t is SocketTimeoutException -> UNREACHABLE
                t is NoRouteToHostException -> UNREACHABLE
                message.contains("ECONNREFUSED") || message.contains("Connection refused", ignoreCase = true) -> REFUSED
                message.contains("ENETUNREACH") || message.contains("EHOSTUNREACH") -> UNREACHABLE
                message.contains("ETIMEDOUT") -> UNREACHABLE
                else -> null
            }
        }

        private const val MAX_DEPTH = 8
    }
}
