package io.github.livsbittt.rosy.pilot

import android.content.Context
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView

/** Tablet navigation and device rows share the established Pilot palette and 48dp targets. */
class PilotViews(private val context: Context) {
    fun surface() = LinearLayout(context).apply {
        orientation = LinearLayout.VERTICAL
        setBackgroundColor(PilotColors.background)
        fitsSystemWindows = true
    }
    fun dp(value: Int) = (value * context.resources.displayMetrics.density).toInt()
    fun label(text: String, size: Float = RosyMetrics.TextBody, quiet: Boolean = false) = TextView(context).apply {
        this.text = text; textSize = size; setTextColor(if (quiet) PilotColors.muted else PilotColors.foreground)
        background = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_focused), fill(PilotColors.pressed, true))
            addState(intArrayOf(), fill(android.graphics.Color.TRANSPARENT))
        }
        setPadding(0, dp(RosyMetrics.Space1.toInt()), 0, dp(RosyMetrics.Space1.toInt()))
    }
    private fun fill(color: Int, focus: Boolean = false) = GradientDrawable().apply {
        setColor(color); cornerRadius = dp(RosyMetrics.RadiusButton.toInt()).toFloat()
        if (focus) setStroke(dp(RosyMetrics.FocusRingWidth.toInt()), PilotColors.foreground)
    }
    fun button(text: String, primary: Boolean = false, action: () -> Unit) = Button(context).apply {
        this.text = text; isAllCaps = false; textSize = RosyMetrics.TextLabel; minimumHeight = dp(RosyMetrics.TargetSecondary.toInt())
        setPadding(dp(RosyMetrics.InsetButton.toInt()), dp(RosyMetrics.Space2.toInt()), dp(RosyMetrics.InsetButton.toInt()), dp(RosyMetrics.Space2.toInt()))
        val ink = if (primary) PilotColors.background else PilotColors.foreground
        setTextColor(android.content.res.ColorStateList(arrayOf(intArrayOf(android.R.attr.state_enabled), intArrayOf()), intArrayOf(ink, PilotColors.muted)))
        val icon = when (text) { "다시 찾기" -> R.drawable.ic_refresh; "로봇 목록" -> R.drawable.ic_back; "화면 끄기" -> R.drawable.ic_screen_off; "태블릿", "기기·연결" -> R.drawable.ic_tablet; else -> null }
        icon?.let { setCompoundDrawablesRelativeWithIntrinsicBounds(context.getDrawable(it)?.mutate()?.apply { setTint(ink) }, null, null, null) }
        compoundDrawablePadding = dp(RosyMetrics.Space2.toInt())
        background = StateListDrawable().apply {
            addState(intArrayOf(-android.R.attr.state_enabled), fill(PilotColors.disabled))
            addState(intArrayOf(android.R.attr.state_focused), fill(if (primary) PilotColors.foreground else PilotColors.pressed, true))
            addState(intArrayOf(android.R.attr.state_pressed), fill(if (primary) PilotColors.muted else PilotColors.pressed))
            addState(intArrayOf(), fill(if (primary) PilotColors.foreground else PilotColors.background))
        }
        setOnClickListener { action() }
    }
    fun replaceRobots(container: LinearLayout, status: View, content: () -> Unit) {
        val focused = (0 until container.childCount).map(container::getChildAt).firstOrNull { it.hasFocus() }?.tag
        container.removeAllViews()
        content()
        if (focused != null) {
            val replacement = (0 until container.childCount).map(container::getChildAt)
                .firstOrNull { it.tag == focused && it.isEnabled }
            if (replacement?.requestFocus() != true) {
                status.isFocusableInTouchMode = true
                status.requestFocus()
            }
        }
    }
    fun robot(candidate: Candidate, enabled: Boolean, action: () -> Unit): View = LinearLayout(context).apply {
        tag = Triple(candidate.host, candidate.port, candidate.secure)
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dp(RosyMetrics.Space4.toInt()), dp(RosyMetrics.Space4.toInt()), dp(RosyMetrics.Space4.toInt()), dp(RosyMetrics.Space4.toInt())); minimumHeight = dp(RosyMetrics.TargetSecondary.toInt())
        background = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_focused), fill(PilotColors.pressed, true))
            addState(intArrayOf(android.R.attr.state_pressed), fill(PilotColors.pressed))
            addState(intArrayOf(), fill(PilotColors.disabled))
        }
        if (context.resources.configuration.screenWidthDp >= 480) {
            addView(ImageView(context).apply { setImageResource(R.drawable.ic_robot); imageTintList = android.content.res.ColorStateList.valueOf(PilotColors.muted); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO }, LinearLayout.LayoutParams(dp(28), dp(28)).apply { marginEnd = dp(RosyMetrics.Space4.toInt()) })
        }
        val title = candidate.name.ifBlank { candidate.robotId.ifBlank { "Rosy" } }
        val copy = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
        copy.addView(label(title, RosyMetrics.TextTitle).apply { typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL); breakStrategy = android.text.Layout.BREAK_STRATEGY_BALANCED })
        copy.addView(label(if (!enabled) "연결 보류 · 목록을 다시 찾거나 태블릿 상태를 확인하세요" else candidate.robotId.ifBlank { "로봇 · 같은 Wi-Fi" }, RosyMetrics.TextLabel, true))
        addView(copy, LinearLayout.LayoutParams(0, -2, 1f))
        addView(label(if (enabled) "연결" else "보류", RosyMetrics.TextBody).apply { setPadding(dp(RosyMetrics.Space4.toInt()), 0, 0, 0) })
        addView(ImageView(context).apply { setImageResource(R.drawable.ic_back); rotation = 180f; imageTintList = android.content.res.ColorStateList.valueOf(PilotColors.muted); importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO }, LinearLayout.LayoutParams(dp(20), dp(20)).apply { marginStart = dp(RosyMetrics.Space3.toInt()) })
        isEnabled = enabled; isClickable = enabled; isFocusable = enabled
        contentDescription = "$title, ${if (enabled) "연결" else "연결 보류"}"
        setOnClickListener { if (isEnabled) action() }
    }
}
