package io.github.livsbittt.rosy.pilot

import android.content.Intent
import android.graphics.Rect
import android.view.KeyEvent
import android.view.View
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/** Input focus is exercised on Android Views; this does not assert TalkBack focus. */
class RobotRowsFocusTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private lateinit var activity: RobotRowsFixtureActivity
    private val first = Candidate("fixture.local", 8443, listOf("127.0.0.1"), "같은 이름", "duplicate")
    private val other = first.copy(port = 8444)
    private val insecure = first.copy(secure = false)

    @Before fun open() {
        val intent = Intent(instrumentation.targetContext, RobotRowsFixtureActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        activity = instrumentation.startActivitySync(intent) as RobotRowsFixtureActivity
        instrumentation.runOnMainSync {
            activity.render(listOf(first to true, other to true, insecure to true))
            activity.robots.getChildAt(0).isFocusableInTouchMode = true
            activity.robots.getChildAt(0).requestFocus()
        }
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_DOWN)
        instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync { assertTrue(activity.robots.getChildAt(1).hasFocus()) }
    }

    @After fun close() {
        if (::activity.isInitialized) instrumentation.runOnMainSync { activity.finish() }
    }

    private fun visible(view: View) {
        assertTrue(view.hasFocus())
        assertTrue(view.getGlobalVisibleRect(Rect()))
        assertEquals(0, activity.selections)
    }

    @Test fun reorderAndAddKeepsTheEndpointRatherThanTheNameOrPosition() {
        instrumentation.runOnMainSync {
            activity.render(listOf(insecure to true, other to true, first to true, first.copy(host = "new.local") to true))
            visible(activity.robots.getChildAt(1))
            activity.render(listOf(other to true, first to true, insecure to true))
            visible(activity.robots.getChildAt(0))
        }
    }

    @Test fun removingDisablingAndEmptyingTheFocusedListUsesItsStatus() {
        instrumentation.runOnMainSync {
            activity.render(listOf(first to true, insecure to true))
            visible(activity.status)
            activity.render(listOf(first to true, other to true))
            activity.robots.getChildAt(1).requestFocus()
            activity.render(listOf(first to true, other to false))
            visible(activity.status)
            activity.robots.getChildAt(0).requestFocus()
            activity.render(emptyList())
            visible(activity.status)
        }
    }

    @Test fun changingAnyEndpointPartUsesStatusInsteadOfAnotherConnection() {
        instrumentation.runOnMainSync {
            for (changed in listOf(other.copy(host = "new.local"), other.copy(port = 9443), other.copy(secure = false))) {
                activity.render(listOf(other to true))
                activity.robots.getChildAt(0).requestFocus()
                activity.render(listOf(changed to true))
                visible(activity.status)
            }
        }
    }

    @Test fun focusOutsideTheListAndInitialRenderingAreNotRedirected() {
        instrumentation.runOnMainSync {
            activity.outside.requestFocus()
            activity.render(listOf(first to true))
            visible(activity.outside)
            activity.render(emptyList())
            visible(activity.outside)
        }
    }
}
