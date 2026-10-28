package io.github.livsbittt.rosy.cam.ui

import android.graphics.Bitmap
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import io.github.livsbittt.rosy.cam.settings.OverheadServiceRecord
import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Stateless LAN rows only: no discovery, pairing, settings writes, or camera start. */
class CameraLanRowsTest {
    @get:Rule val compose = createComposeRule()
    private var screenDensity = 1f
    private val peer = OverheadServiceRecord("승인 가능한 기기", "peer.local", 8443, "192.0.2.1", peerApproval = true)
    private val legacy = peer.copy(serviceName = "기존 승인 기기", tlsHost = "legacy.local", pairable = true, peerApproval = false)
    private val missing = peer.copy(serviceName = "주소를 찾지 못한 기기", tlsHost = "missing.local", address = null)
    private val unsupported = peer.copy(serviceName = "승인 방식 미확인 기기", tlsHost = "unsupported.local", peerApproval = false)
    private val conflict = peer.copy(serviceName = "주소 충돌 첫 기기", tlsHost = "conflict.local")
    private val other = conflict.copy(serviceName = "주소 충돌 두 번째 기기", address = "192.0.2.2")

    @Test fun narrowReasonsAndSelection() = reasonsAndSelection(320)
    @Test fun wideReasonsAndSelection() = reasonsAndSelection(800)

    private fun reasonsAndSelection(width: Int) {
        val calls = mutableListOf<OverheadServiceRecord>()
        show(width) { CameraLanRows(listOf(missing, unsupported, conflict, other, peer, legacy)) { calls += it } }
        for ((record, reason) in listOf(
            missing to "기기 주소를 확인하지 못했습니다. Wi-Fi를 확인하고 다시 찾으세요.",
            unsupported to "연결 승인을 확인할 수 없습니다. 상대 기기의 연결 화면을 확인하세요.",
            conflict to "같은 이름의 주소가 충돌합니다. 상대 기기의 연결 설정을 확인하세요.",
        )) {
            compose.onNodeWithText(record.name).performScrollTo().assertIsNotEnabled().performTouchInput { click() }
            val message = compose.onAllNodesWithText(reason)[0].performScrollTo().assertIsDisplayed()
            val bounds = message.fetchSemanticsNode().boundsInRoot
            val screen = compose.onNodeWithTag("screen").fetchSemanticsNode().boundsInRoot
            assertTrue("reason must fit the screen", bounds.left >= screen.left && bounds.right <= screen.right)
            capture("$width-${record.tlsHost}")
        }
        compose.onNodeWithText(other.name).performScrollTo().assertIsNotEnabled().performTouchInput { click() }
        compose.runOnIdle { assertTrue(calls.isEmpty()) }
        for (record in listOf(peer, legacy)) {
            val button = compose.onNodeWithText(record.name).performScrollTo().assertIsEnabled()
            val bounds = button.fetchSemanticsNode().boundsInRoot
            assertTrue("button must retain the shared touch target", bounds.height / screenDensity >= 47.5f)
            button.performClick()
        }
        compose.runOnIdle { assertEquals(listOf(peer, legacy), calls) }
    }

    @Test fun reorderKeepsFocusOnTheSameEndpointWithoutSelectingIt() {
        var records by mutableStateOf(listOf(peer, legacy))
        val calls = mutableListOf<OverheadServiceRecord>()
        show(800) { CameraLanRows(records) { calls += it } }
        compose.onNodeWithText(peer.name).performSemanticsAction(SemanticsActions.RequestFocus) { it() }
        compose.onNodeWithText(peer.name).assertIsFocused()
        compose.runOnIdle { records = listOf(legacy, peer) }
        compose.onNodeWithText(peer.name).assertIsFocused()
        compose.onNodeWithText(legacy.name).assertIsNotFocused()
        compose.runOnIdle { assertTrue(calls.isEmpty()) }
        capture("800-reordered-focus")
    }

    @Test fun tabFocusSurvivesReorderWithoutSelectingAnotherEndpoint() {
        var records by mutableStateOf(listOf(peer, legacy))
        val calls = mutableListOf<OverheadServiceRecord>()
        show(800) { CameraLanRows(records) { calls += it } }
        compose.onNodeWithText(peer.name).performSemanticsAction(SemanticsActions.RequestFocus) { it() }
        compose.onNodeWithText(peer.name).performKeyInput { pressKey(Key.Tab) }
        compose.onNodeWithText(legacy.name).assertIsFocused()
        compose.runOnIdle { records = listOf(legacy, peer) }
        compose.onNodeWithText(legacy.name).assertIsFocused()
        compose.onNodeWithText(peer.name).assertIsNotFocused()
        compose.runOnIdle { assertTrue(calls.isEmpty()) }
        capture("800-tab-reordered-focus")
    }

    private fun show(width: Int, content: @Composable () -> Unit) {
        compose.setContent {
            val density = LocalDensity.current.density
            screenDensity = density
            CompositionLocalProvider(LocalDensity provides Density(density, fontScale = 1.3f)) {
                RosyTheme {
                    Column(
                        Modifier.requiredWidth(width.dp).height(800.dp).testTag("screen")
                            .safeDrawingPadding().verticalScroll(rememberScrollState()).padding(RosyMetrics.Space5.dp),
                        verticalArrangement = Arrangement.spacedBy(RosyMetrics.Space3.dp),
                    ) { content() }
                }
            }
        }
    }

    private fun capture(name: String) {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val folder = requireNotNull(context.getExternalFilesDir("native-ui"))
        require(folder.isDirectory || folder.mkdirs())
        File(folder, "$name.png").outputStream().use {
            check(compose.onNodeWithTag("screen").captureToImage().asAndroidBitmap().compress(Bitmap.CompressFormat.PNG, 100, it))
        }
        File(folder, "$name-semantics.txt").writeText(compose.onRoot().printToString())
    }
}
