package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.link.LinkState
import io.github.livsbittt.rosy.cam.link.LinkStatus
import io.github.livsbittt.rosy.cam.service.StreamState
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** D-741 3 on a camera sender: the bar names the target and the link, and every title stands under it. */
class CamBarTest {
    private fun link(siteName: String?, tlsHost: String?, manualHost: String? = null) =
        SiteLink(siteName, tlsHost, 8443, null, "token", "overhead-1", true, manualHost)

    private fun running(state: LinkState, transmitting: Boolean = true) =
        StreamState(running = true, link = LinkStatus(state = state), transmitting = transmitting)

    @Test
    fun targetIsTheSiteNameThenTheHostAndNothingBeforePairing() {
        assertNull(CamBar.from(StreamState(), null).target)
        assertEquals("Demo site", CamBar.from(StreamState(), link("Demo site", "demo.local")).target)
        assertEquals("demo.local", CamBar.from(StreamState(), link(null, "demo.local")).target)
        assertEquals("manual-host", CamBar.from(StreamState(), link(null, null, "manual-host")).target)
        // A blank name is no name: it falls through instead of leaving an empty target.
        assertEquals("demo.local", CamBar.from(StreamState(), link(" ", "demo.local")).target)
        assertEquals("manual-host", CamBar.from(StreamState(), link("", " ", "manual-host")).target)
        assertNull(CamBar.from(StreamState(), link("", null)).target)
    }

    @Test
    fun linkFollowsTheStream() {
        assertEquals(R.string.state_stopped, CamBar.from(StreamState(), null).link)
        assertEquals(R.string.state_connecting, CamBar.from(running(LinkState.CONNECTING), null).link)
        assertEquals(R.string.state_disconnected, CamBar.from(running(LinkState.DISCONNECTED), null).link)
        assertEquals(R.string.state_streaming, CamBar.from(running(LinkState.STREAMING), null).link)
        assertEquals(R.string.state_standby, CamBar.from(running(LinkState.STREAMING, transmitting = false), null).link)
        assertEquals(R.string.state_preview_only, CamBar.from(running(LinkState.STREAMING).copy(previewOnly = true), null).link)
        assertEquals(R.string.state_thermal_pause,
            CamBar.from(running(LinkState.STREAMING).copy(previewOnly = true, thermalPause = true), null).link)
        // A link state left from the last run does not show while the camera is off.
        assertEquals(R.string.state_stopped, CamBar.from(running(LinkState.STREAMING).copy(running = false), null).link)
    }

    @Test
    fun onlyTheLostLinkIsACaution() {
        assertTrue(CamBar.from(running(LinkState.DISCONNECTED), null).caution)
        for (state in listOf(StreamState(), running(LinkState.CONNECTING), running(LinkState.STREAMING))) {
            assertFalse(CamBar.from(state, null).caution)
        }
    }

    private val ui = File("src/main/java/io/github/livsbittt/rosy/cam/ui")
    private val activity = File("src/main/java/io/github/livsbittt/rosy/cam/MainActivity.kt").readText()

    /** Layout has no JVM test here, so these three read the source for the one mistake each names. */
    @Test
    fun eachTitledScreenHasOneTitleUnderTheBarAndTheStreamScreenHasNone() {
        assertEquals(1, Regex("""\bCamAppBar\(""").findAll(activity).count())
        val titled = mapOf(
            "CameraPeerScreen" to "peer_title", "PairingScreen" to "pairing_title",
            "CameraLanScreen" to "lan_title", "SettingsScreen" to "settings_title",
        )
        for ((screen, title) in titled) {
            val call = Regex("""CamPath\(stringResource\(R\.string\.$title\)\)\s+$screen\(""")
            assertEquals("$screen directly under its title", 1, call.findAll(activity).count())
        }
        assertEquals(titled.size, Regex("""\bCamPath\(""").findAll(activity).count())
        // A title above the preview would take its height on a landscape phone.
        assertEquals(1, Regex("""\} else \{\s+StreamScreen\(""").findAll(activity).count())
    }

    @Test
    fun noScreenRepeatsATitleTheActivityDraws() {
        val titles = Regex("""R\.string\.(peer|pairing|lan|settings)_title\b""")
        val repeating = ui.listFiles { file -> file.extension == "kt" && titles.containsMatchIn(file.readText()) }!!
        assertEquals(emptyList<String>(), repeating.map { it.name })
    }

    @Test
    fun theBarTakesNoCallbackAndDrawsNoControl() {
        val bar = File(ui, "CamBar.kt").readText()
        assertTrue("fun CamAppBar(bar: CamBar) {" in bar)
        assertFalse(Regex("""Button\(|clickable|onClick""").containsMatchIn(bar))
    }
}
