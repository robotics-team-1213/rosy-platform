package io.github.livsbittt.rosy.pilot

import android.app.Activity
import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.ScrollView

/** Synthetic candidate rows for native G2 width captures; no discovery, pairing, or robot connection. */
class UiuxPreviewActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val views = PilotViews(this)
        val compact = resources.configuration.screenWidthDp < 720
        val root = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setBackgroundColor(PilotColors.background) }
        if (!compact) root.addView(View(this), LinearLayout.LayoutParams(views.dp(260), -1))
        val list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(views.dp(if (compact) 16 else 24), views.dp(16), views.dp(if (compact) 16 else 40), views.dp(16))
        }
        root.addView(list, if (compact) LinearLayout.LayoutParams(-1, -1) else LinearLayout.LayoutParams(0, -1, 1f))
        list.addView(views.label("로봇 선택", 28f))
        list.addView(views.label("2대 발견 · 연결할 로봇을 선택하세요.", 16f, true))
        val rows = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        list.addView(ScrollView(this).apply { addView(rows) }, LinearLayout.LayoutParams(-1, 0, 1f))
        val candidate = Candidate("demo.local", 443, listOf("192.0.2.1"), "Pinky Pro 작업 로봇", "rosy_03")
        rows.addView(views.robot(candidate, true) {}, LinearLayout.LayoutParams(-1, -2))
        rows.addView(views.robot(candidate.copy(name = "Pinky Pro 연결 보류"), false) {}, LinearLayout.LayoutParams(-1, -2))
        setContentView(root)
    }
}
