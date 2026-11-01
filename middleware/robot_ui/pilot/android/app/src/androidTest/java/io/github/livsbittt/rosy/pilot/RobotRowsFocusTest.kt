package io.github.livsbittt.rosy.pilot

import android.content.Intent
import android.graphics.Rect
import android.graphics.Bitmap
import android.graphics.Canvas
import android.view.KeyEvent
import android.view.View
import android.view.ViewTreeObserver
import android.widget.Button
import androidx.test.platform.app.InstrumentationRegistry
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.io.File
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.Rule
import org.junit.rules.TestName

/** Input focus is exercised on Android Views; this does not assert TalkBack focus. */
class RobotRowsFocusTest {
    @get:Rule val testName = TestName()
    private var capture = 0
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

    private fun visible(target: () -> View) {
        instrumentation.runOnMainSync {
            val view = target()
            assertTrue(view.hasFocus())
            val bounds = Rect()
            assertTrue(view.getGlobalVisibleRect(bounds))
            assertEquals(view.width, bounds.width())
            assertEquals(view.height, bounds.height())
            val decor = activity.window.decorView
            val insets = requireNotNull(decor.rootWindowInsets)
            assertTrue("focus is under the status bar", bounds.top >= insets.systemWindowInsetTop)
            assertTrue("focus is under the navigation bar", bounds.bottom <= decor.height - insets.systemWindowInsetBottom)
            assertTrue("focus is under the left system bar", bounds.left >= insets.systemWindowInsetLeft)
            assertTrue("focus is under the right system bar", bounds.right <= decor.width - insets.systemWindowInsetRight)
            assertEquals(0, activity.selections)
        }
        val frame = CountDownLatch(1)
        instrumentation.runOnMainSync {
            val decor = activity.window.decorView
            decor.viewTreeObserver.registerFrameCommitCallback { frame.countDown() }
            decor.invalidate()
        }
        assertTrue("focused frame was not drawn", frame.await(5, TimeUnit.SECONDS))
        instrumentation.waitForIdleSync()
        val bitmap = requireNotNull(instrumentation.uiAutomation.takeScreenshot())
        val folder = requireNotNull(activity.getExternalFilesDir("native-ui"))
        require(folder.isDirectory || folder.mkdirs())
        File(folder, "${testName.methodName}-${++capture}.png").outputStream().use {
            check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it))
        }
    }

    @Test fun primaryAndQuietButtonsShowFocusWithoutActivatingTheirActions() {
        var clicks = 0
        lateinit var primary: Button
        lateinit var quiet: Button
        instrumentation.runOnMainSync {
            val views = PilotViews(activity)
            activity.robots.removeAllViews()
            primary = views.button("다시 찾기", primary = true) { clicks++ }
            quiet = views.button("보조 조작 · 시험") { clicks++ }
            activity.robots.addView(primary)
            activity.robots.addView(quiet)
            activity.outside.requestFocus()
        }
        visible { activity.outside }
        assertEquals("primary default fill", PilotColors.foreground, backgroundColor(primary, center = true))
        assertEquals(PilotColors.background, primary.currentTextColor)
        instrumentation.runOnMainSync { quiet.requestFocus() }
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_UP)
        instrumentation.waitForIdleSync()
        visible { primary }
        assertEquals("primary focus ring", PilotColors.foreground, backgroundColor(primary))
        assertEquals("focus changes the fill, not just its outer size", PilotColors.pressed, backgroundColor(primary, center = true))
        assertEquals(PilotColors.foreground, primary.currentTextColor)
        assertEquals(PilotColors.foreground, primary.compoundDrawableTintList!!.getColorForState(primary.drawableState, 0))
        instrumentation.sendKeyDownUpSync(KeyEvent.KEYCODE_DPAD_DOWN)
        instrumentation.waitForIdleSync()
        visible { quiet }
        assertEquals("quiet focus ring", PilotColors.foreground, backgroundColor(quiet))
        assertEquals("blur restores primary fill", PilotColors.foreground, backgroundColor(primary, center = true))
        assertEquals(PilotColors.background, primary.currentTextColor)
        instrumentation.runOnMainSync { primary.isEnabled = false }
        visible { quiet }
        assertEquals("disabled fill keeps precedence", PilotColors.disabled, backgroundColor(primary))
        assertEquals(PilotColors.muted, primary.currentTextColor)
        instrumentation.runOnMainSync { assertEquals(0, clicks) }
    }

    private fun backgroundColor(view: View, center: Boolean = false): Int {
        var color = 0
        instrumentation.runOnMainSync {
            assertTrue(view.width > 0 && view.height > 0)
            val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.background.draw(Canvas(bitmap))
            val inset = maxOf(1, PilotViews(activity).dp(RosyMetrics.FocusRingWidth.toInt()) / 2)
            color = bitmap.getPixel(if (center) view.width / 2 else inset, view.height / 2)
            bitmap.recycle()
        }
        return color
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

    @Test fun movingTheFocusedRowBelowALongListKeepsTheWholeRowVisible() {
        val added = (0 until 20).map { first.copy(host = "fixture-$it.local") to true }
        render(listOf(other to true) + added)
        focusRow(0)
        render(added + (other to true))
        visible { activity.robots.getChildAt(added.size) }
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
