package io.github.livsbittt.rosy.pilot

import android.app.Activity
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Debug-only synthetic rows: no discovery, account, connection, or robot commands. */
class RobotRowsFixtureActivity : Activity() {
    lateinit var robots: LinearLayout
    lateinit var status: TextView
    lateinit var outside: Button
    private lateinit var views: PilotViews
    var selections = 0
        private set

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        views = PilotViews(this)
        val root = views.surface()
        status = views.label("로봇 목록 상태")
        robots = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        outside = views.button("다른 제어") { }
        root.addView(status)
        root.addView(ScrollView(this).apply { addView(robots) }, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(outside)
        setContentView(root)
    }

    fun render(rows: List<Pair<Candidate, Boolean>>) {
        views.replaceRobots(robots, status) {
            rows.forEach { (candidate, enabled) ->
                robots.addView(views.robot(candidate, enabled) { selections++ })
            }
        }
    }
}
