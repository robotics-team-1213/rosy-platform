package io.github.livsbittt.rosy.overhead.link

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
        /** Walks the cause chain; the first recognised exception wins. */
        fun classify(error: Throwable): NetworkFailure {
            var t: Throwable? = error
            var depth = 0
            while (t != null && depth < MAX_DEPTH) {
                fromOne(t)?.let { return it }
                t = t.cause
                depth++
            }
            return OTHER
        }

        private fun fromOne(t: Throwable): NetworkFailure? {
            val message = t.message.orEmpty()
            return when {
                t is SSLException -> TLS
                t is UnknownHostException -> UNKNOWN_HOST
                t is SocketTimeoutException -> UNREACHABLE
                t is NoRouteToHostException -> UNREACHABLE
                message.contains("ECONNREFUSED") || message.contains("Connection refused", ignoreCase = true) -> REFUSED
                message.contains("ENETUNREACH") || message.contains("EHOSTUNREACH") -> UNREACHABLE
                message.contains("ETIMEDOUT") -> UNREACHABLE
                t is ConnectException -> UNREACHABLE
                else -> null
            }
        }

        private const val MAX_DEPTH = 8
    }
}
