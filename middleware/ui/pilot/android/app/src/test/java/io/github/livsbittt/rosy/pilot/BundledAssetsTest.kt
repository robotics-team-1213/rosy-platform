package io.github.livsbittt.rosy.pilot

import java.io.File
import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.Assert.*
import org.junit.Test

class BundledAssetsTest {
    private val directory = File(System.getProperty("rosy.pilot.assets"))
    @Test fun canonicalUiAndImportsAreBundled() {
        for (path in listOf("pilot/index.html", "pilot/app.js", "pilot/link.js", "pilot/screens/drive.js", "pilot/widgets/joint_jog.js",
            "pilot/screens/arm.js", "pilot/screens/compose.js", "pilot/widgets/gripper.js", "pilot/arm-stick.js", "pilot/controls.js", "pilot/drivers/omx_sim.js",
            "common/ui.js", "common/theme.js", "common/tokens.css", "common/components.css", "common/icons/pilot.svg")) {
            assertTrue("missing APK asset $path", File(directory, path).isFile)
        }
        assertFalse(File(directory, "pilot/AGENTS.md").exists())
        assertFalse(File(directory, "pilot/logs.md").exists())
    }
    @Test fun offlineUiNeedsNoRobotHostedScreenOrNetwork() {
        val dials = java.util.concurrent.atomic.AtomicInteger()
        val connection = object : PilotConnection {
            override val target = RobotTarget("rosy_01", "unavailable.local", 8080, "private-token-value")
            override val secure = true
            override fun authorized() = false
            override fun client() = OkHttpClient.Builder().dns(object : okhttp3.Dns {
                override fun lookup(hostname: String): List<java.net.InetAddress> { dials.incrementAndGet(); throw java.net.UnknownHostException("offline") }
            }).build()
        }
        val proxy = PilotProxy(connection, BundledAssets { File(directory, it).takeIf { file -> file.isFile }?.readBytes() }, {})
        try {
            proxy.start(5000, false)
            for (path in listOf("/pilot", "/pilot/assets/app.js", "/common/tokens.css")) {
                OkHttpClient().newCall(Request.Builder().url(proxy.origin + path).header("Cookie", "rosy-shell=${proxy.capability}").build())
                    .execute().use { assertEquals(200, it.code); assertTrue(it.body!!.bytes().isNotEmpty()) }
            }
            assertEquals(0, dials.get())
            OkHttpClient().newCall(Request.Builder().url(proxy.origin + "/api/v1/system/info").header("Cookie", "rosy-shell=${proxy.capability}").build())
                .execute().use { assertEquals(403, it.code) }
        } finally { proxy.stop() }
    }
    @Test fun traversalNeverSelectsBundledOrRemoteFiles() {
        for (path in listOf("/pilot/assets/../../secret", "/common/%2e%2e/secret", "/common/..\\secret")) assertNull(BundledPath.asset(path))
    }
}
