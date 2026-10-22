package io.github.livsbittt.rosy.cam.ui

import android.graphics.Bitmap
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.printToString
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.link.LinkError
import io.github.livsbittt.rosy.cam.link.LinkStatus
import io.github.livsbittt.rosy.cam.service.StreamState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.File

/** Emulator layout and Compose semantics checks; spoken TalkBack output needs a human check. */
class StreamRecoveryTest {
    @get:Rule val compose = createComposeRule()

    @Test fun compactRunningRecovery() = checkRecovery(320, running = true)
    @Test fun phoneStoppedRecovery() = checkRecovery(390, running = false)
    @Test fun wideRunningRecovery() = checkRecovery(800, running = true)

    private fun checkRecovery(width: Int, running: Boolean) {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val calls = mutableListOf<String>()
        var density = 0f
        compose.setContent {
            density = LocalDensity.current.density
            CompositionLocalProvider(LocalDensity provides Density(density, fontScale = 1.3f)) {
                RosyTheme {
                    Box(Modifier.requiredWidth(width.dp).height(800.dp).testTag("screen")) {
                        StreamScreen(
                            state = StreamState(
                                running = running,
                                link = LinkStatus(error = LinkError.Unauthorized, stopped = true),
                            ),
                            siteLink = null,
                            rejectedHost = null,
                            droppedTlsHost = null,
                            lan = null,
                            localError = null,
                            onStart = { error("Recovery must not start a camera") },
                            onStop = { calls += "stop" },
                            onOpenSettings = { calls += "settings" },
                        )
                    }
                }
            }
        }
        val recoveryText = context.getString(
            if (running) R.string.button_stop_and_open_settings else R.string.button_open_settings,
        )
        val detailText = context.getString(R.string.button_details)
        val hideText = context.getString(R.string.button_details_hide)
        val rawDetail = "HTTP 401 / close 4401"
        compose.onNodeWithText(rawDetail).assertDoesNotExist()
        for (label in listOf(recoveryText, detailText)) {
            val button = compose.onNodeWithText(label).performScrollTo().assertIsDisplayed().assertHasClickAction()
            val bounds = button.fetchSemanticsNode().boundsInRoot
            val screen = compose.onNodeWithTag("screen").fetchSemanticsNode().boundsInRoot
            assertEquals("Declared screen width", width.toFloat(), screen.width / density, 1f)
            assertTrue("$label must be at least 48dp high", bounds.height / density >= 47.5f)
            assertTrue("$label must be at least 48dp wide", bounds.width / density >= 47.5f)
            assertTrue("$label must fit screen width", bounds.left >= screen.left && bounds.right <= screen.right)
        }
        capture("${width}-${running}-collapsed")
        compose.onNodeWithText(detailText).performScrollTo().performClick()
        compose.onNodeWithText(rawDetail).performScrollTo().assertIsDisplayed()
        capture("${width}-${running}-expanded")
        compose.onNodeWithText(hideText).performScrollTo().performClick()
        compose.onNodeWithText(rawDetail).assertDoesNotExist()
        compose.onNodeWithText(recoveryText).performScrollTo().performClick()
        compose.runOnIdle {
            assertEquals(if (running) listOf("stop", "settings") else listOf("settings"), calls)
        }
    }

    private fun capture(name: String) {
        val cache = InstrumentationRegistry.getInstrumentation().targetContext.cacheDir
        File(cache, "$name-semantics.txt").writeText(compose.onRoot().printToString())
        File(cache, "$name.png").outputStream().use {
            check(compose.onNodeWithTag("screen").captureToImage().asAndroidBitmap().compress(Bitmap.CompressFormat.PNG, 100, it))
        }
    }
}
