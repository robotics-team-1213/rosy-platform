package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.settings.PairingUri
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test

class CredentialRenewalTest {
    @Test fun stopRetiresHeldProofBeforeAnyBearer() = runBlocking {
        MockWebServer().use { server ->
            server.start(); val started = CountDownLatch(1); val release = CountDownLatch(1)
            val original = PairingUri(server.hostName, server.port, "old-camera-token", "ceiling_north")
            val provider = CredentialProvider { _ ->
                started.countDown(); release.await(5, TimeUnit.SECONDS)
                CredentialRenewal(original.copy(token = "late-camera-token"), Instant.now().plusSeconds(3600))
            }
            val link = OverheadLink(original, "fixture", "camera", credentialProvider = provider)
            try {
                link.start(); assertTrue(started.await(3, TimeUnit.SECONDS)); assertEquals(0, server.requestCount)
                link.stop(); release.countDown()
                assertNull(server.takeRequest(500, TimeUnit.MILLISECONDS)); assertEquals(0, server.requestCount)
            } finally { release.countDown(); link.stop() }
        }
    }
    @Test fun newerRenewalOwnsUpgradeAndSource() = runBlocking {
        MockWebServer().use { server ->
            server.start(); server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {}))
            val firstStarted = CountDownLatch(1); val secondStarted = CountDownLatch(1)
            val old = CountDownLatch(1); val fresh = CountDownLatch(1); var attempts = 0
            val original = PairingUri(server.hostName, server.port, "old-camera-token", "ceiling_north")
            val provider = CredentialProvider { _ ->
                val index = synchronized(old) { ++attempts }
                if (index == 1) { firstStarted.countDown(); old.await(5, TimeUnit.SECONDS) } else { secondStarted.countDown(); fresh.await(5, TimeUnit.SECONDS) }
                CredentialRenewal(original.copy(token = if (index == 1) "stale-camera-token" else "fresh-camera-token"), Instant.now().plusSeconds(3600))
            }
            val link = OverheadLink(original, "fixture", "camera", credentialProvider = provider)
            try {
                link.start(); assertTrue(firstStarted.await(3, TimeUnit.SECONDS)); link.reconnect(); assertTrue(secondStarted.await(3, TimeUnit.SECONDS))
                old.countDown(); assertNull(server.takeRequest(300, TimeUnit.MILLISECONDS))
                fresh.countDown(); val upgrade = server.takeRequest(3, TimeUnit.SECONDS)!!
                assertEquals("Bearer fresh-camera-token", upgrade.getHeader("Authorization")); assertEquals(1, server.requestCount)
            } finally { old.countDown(); fresh.countDown(); link.stop() }
        }
    }
    @Test fun proofDenialAndRetargetNeverUseOldToken() {
        for (retarget in listOf(false, true)) MockWebServer().use { server ->
            server.start(); val reached = CountDownLatch(1)
            val original = PairingUri(server.hostName, server.port, "old-camera-token", "ceiling_north")
            val provider = CredentialProvider { _ ->
                reached.countDown()
                if (!retarget) throw CredentialDenied()
                CredentialRenewal(original.copy(source = "other_camera"), Instant.now().plusSeconds(3600))
            }
            val link = OverheadLink(original, "fixture", "camera", credentialProvider = provider)
            try {
                link.start(); assertTrue(reached.await(3, TimeUnit.SECONDS)); assertNull(server.takeRequest(300, TimeUnit.MILLISECONDS))
                assertEquals(0, server.requestCount)
            } finally { link.stop() }
        }
    }
}
