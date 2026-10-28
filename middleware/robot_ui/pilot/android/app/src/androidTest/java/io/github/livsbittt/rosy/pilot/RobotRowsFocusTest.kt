package io.github.livsbittt.rosy.pilot

import android.content.Intent
import android.graphics.Rect
import android.view.KeyEvent
import android.view.View
import android.view.ViewTreeObserver
import androidx.test.platform.app.InstrumentationRegistry
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
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
        render(listOf(first to true, other to true, insecure to true))
        instrumentation.runOnMainSync {
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

    private fun render(rows: List<Pair<Candidate, Boolean>>) {
        val layout = CountDownLatch(1)
        instrumentation.runOnMainSync {
            activity.robots.viewTreeObserver.addOnGlobalLayoutListener(object : ViewTreeObserver.OnGlobalLayoutListener {
                override fun onGlobalLayout() {
                    activity.robots.viewTreeObserver.removeOnGlobalLayoutListener(this)
                    layout.countDown()
                }
            })
            activity.render(rows)
        }
        assertTrue("robot rows were not laid out", layout.await(5, TimeUnit.SECONDS))
        instrumentation.waitForIdleSync()
    }

    private fun focusRow(index: Int) = instrumentation.runOnMainSync {
        assertTrue(activity.robots.getChildAt(index).requestFocus())
    }

    private fun visible(target: () -> View) = instrumentation.runOnMainSync {
        val view = target()
        assertTrue(view.hasFocus())
        assertTrue(view.getGlobalVisibleRect(Rect()))
        assertEquals(0, activity.selections)
    }

    @Test fun reorderAndAddKeepsTheEndpointRatherThanTheNameOrPosition() {
        render(listOf(insecure to true, other to true, first to true, first.copy(host = "new.local") to true))
        visible { activity.robots.getChildAt(1) }
        render(listOf(other to true, first to true, insecure to true))
        visible { activity.robots.getChildAt(0) }
    }

    @Test fun removingDisablingAndEmptyingTheFocusedListUsesItsStatus() {
        render(listOf(first to true, insecure to true))
        visible { activity.status }
        render(listOf(first to true, other to true))
        focusRow(1)
        render(listOf(first to true, other to false))
        visible { activity.status }
        focusRow(0)
        render(emptyList())
        visible { activity.status }
    }

    @Test fun changingAnyEndpointPartUsesStatusInsteadOfAnotherConnection() {
        for (changed in listOf(other.copy(host = "new.local"), other.copy(port = 9443), other.copy(secure = false))) {
            render(listOf(other to true))
            focusRow(0)
            render(listOf(changed to true))
            visible { activity.status }
        }
    }

    @Test fun focusOutsideTheListAndInitialRenderingAreNotRedirected() {
        instrumentation.runOnMainSync { activity.outside.requestFocus() }
        render(listOf(first to true))
        visible { activity.outside }
        render(emptyList())
        visible { activity.outside }
    }
}
