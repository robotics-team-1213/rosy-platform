package io.github.livsbittt.rosy.ceilingcamera.link

import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import org.junit.Assert.assertEquals
import org.junit.Test

class NetworkFailureTest {
    @Test
    fun connectTimeoutAfterASubnetChangeIsUnreachable() {
        // Real S21 text from 2026-09-29 after the Wi-Fi subnet changed.
        val e = SocketTimeoutException(
            "failed to connect to /192.168.1.102 (port 8095) from /10.152.115.244 (port 40000) after 5000ms",
        )
        assertEquals(NetworkFailure.UNREACHABLE, NetworkFailure.classify(e))
    }

    @Test
    fun refusedWhenNothingListens() {
        val e = ConnectException("failed to connect to /10.0.0.2 (port 8095) after 5000ms: isConnected failed: ECONNREFUSED (Connection refused)")
        assertEquals(NetworkFailure.REFUSED, NetworkFailure.classify(e))
    }

    @Test
    fun noRouteAndNetUnreachableAreUnreachable() {
        assertEquals(NetworkFailure.UNREACHABLE, NetworkFailure.classify(NoRouteToHostException("No route to host")))
        assertEquals(
            NetworkFailure.UNREACHABLE,
            NetworkFailure.classify(ConnectException("failed to connect: connect failed: ENETUNREACH (Network is unreachable)")),
        )
    }

    @Test
    fun unknownHostAndTls() {
        assertEquals(NetworkFailure.UNKNOWN_HOST, NetworkFailure.classify(UnknownHostException("site-pc.local")))
        assertEquals(NetworkFailure.TLS, NetworkFailure.classify(SSLHandshakeException("Trust anchor for certification path not found.")))
    }

    @Test
    fun looksThroughWrappers() {
        val wrapped = IOException("upgrade failed", SSLHandshakeException("bad cert"))
        assertEquals(NetworkFailure.TLS, NetworkFailure.classify(wrapped))
    }

    @Test
    fun okHttpWrappedRefusalIsRefusedNotUnreachable() {
        val wrapped = ConnectException("Failed to connect to /10.0.0.2:8095").apply {
            initCause(ConnectException("Connection refused: connect"))
        }
        assertEquals(NetworkFailure.REFUSED, NetworkFailure.classify(wrapped))
        assertEquals(NetworkFailure.UNREACHABLE, NetworkFailure.classify(ConnectException("Failed to connect to /10.0.0.2:8095")))
    }

    @Test
    fun unrecognisedIsOther() {
        assertEquals(NetworkFailure.OTHER, NetworkFailure.classify(IOException("canceled")))
        assertEquals(NetworkFailure.OTHER, NetworkFailure.classify(IOException()))
    }
}
