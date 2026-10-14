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
    }

    @Test
    fun linkFollowsTheStream() {
        assertEquals(R.string.state_stopped, CamBar.from(StreamState(), null).link)
        assertEquals(R.string.state_connecting, CamBar.from(running(LinkState.CONNECTING), null).link)
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

    @Test
    fun noScreenDrawsItsOwnTitle() {
        val drawing = ui.listFiles { file -> file.extension == "kt" && "typography.headlineSmall" in file.readText() }!!
        assertEquals(listOf("CamBar.kt"), drawing.map { it.name })
    }

    @Test
    fun theActivityPutsOneBarAboveEveryScreenAndATitleUnderIt() {
        assertEquals(1, Regex("""\bCamAppBar\(""").findAll(activity).count())
        val titles = Regex("""\bCamPath\(""").findAll(activity).count()
        val screens = Regex("""\b(CameraLanScreen|CameraPeerScreen|PairingScreen|SettingsScreen|StreamScreen)\(""").findAll(activity).count()
        assertEquals(5, screens)
        assertEquals(screens, titles)
    }

    @Test
    fun theBarHasNoCommandSeat() {
        val bar = File(ui, "CamBar.kt").readText()
        assertFalse(Regex("""Button\(|clickable|onClick""").containsMatchIn(bar))
    }
}
