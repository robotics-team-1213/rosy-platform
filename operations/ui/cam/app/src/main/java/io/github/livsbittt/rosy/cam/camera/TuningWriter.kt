package io.github.livsbittt.rosy.cam.camera

/** How one camera-control call ended. A newer call to the same control cancels an older one; that is not a failure. */
enum class WriteOutcome { OK, CANCELLED, FAILED }

/** The camera controls the writer drives; [done] is called once, on the writer's thread. */
interface CameraPort {
    fun setEv(index: Int, done: (WriteOutcome) -> Unit)
    fun setOptions(settings: CameraSettings, done: (WriteOutcome) -> Unit)
    fun clearOptions(done: (WriteOutcome) -> Unit)
}

/**
 * D-589 S2: what has been written to the bound camera and what it confirmed, the calls in flight, and whether a
 * `camera_state` may be reported. Pure and single-threaded (the controller's main thread).
 *
 * - [bind] starts a new epoch: answers to calls of an older bind are dropped, so they neither unbalance [inFlight]
 *   nor overwrite [confirmed]. It also clears the Camera2 interop options, which CameraX keeps per camera id across
 *   unbind and rebind, so the camera really matches the default [written].
 * - A control that failed is not called again until [clearFailures] or the next [bind].
 * - `frames` is a count of capture results. A lock needs at least one capture after the last exposure change
 *   ([drive] write, [touch] or [bind]); after a bind the settle clock starts at the first capture.
 */
class TuningWriter(private val onSettled: () -> Unit = {}) {
    var written = CameraSettings()
        private set
    var confirmed = CameraSettings()
        private set
    var inFlight = 0
        private set
    var evFailed = false
        private set
    var optionsFailed = false
        private set

    private var port: CameraPort? = null
    private var epoch = 0
    private var changedAtMs: Long? = null
    private var framesAtChange = 0L
    private var atGoal = true

    /** True when bound, nothing is in flight and the last [drive] reached its goal (no lock still settling). */
    val readyToReport: Boolean get() = port != null && inFlight == 0 && atGoal

    fun bind(camera: CameraPort, frames: Long) {
        epoch++
        port = camera
        written = CameraSettings()
        confirmed = CameraSettings()
        inFlight = 0
        evFailed = false
        optionsFailed = false
        changedAtMs = null
        framesAtChange = frames
        atGoal = true
        call({ camera.clearOptions(it) }, onOk = {}, onFail = { optionsFailed = true })
    }

    fun unbind() {
        epoch++
        port = null
        inFlight = 0
    }

    /** An exposure change the writer did not make (the torch went on or off): locks wait to settle again. */
    fun touch(nowMs: Long, frames: Long) {
        changedAtMs = nowMs
        framesAtChange = frames
    }

    fun clearFailures() {
        evFailed = false
        optionsFailed = false
    }

    /** Writes the next step toward [goal] (see [RecognitionTuning.step]). */
    fun drive(goal: CameraSettings, nowMs: Long, frames: Long) {
        val camera = port ?: return
        val framed = frames > framesAtChange
        if (changedAtMs == null && framed) changedAtMs = nowMs // first capture after bind
        val next = RecognitionTuning.step(written, confirmed, goal, changedAtMs, nowMs, framed)
        atGoal = next == goal
        if (next == written) return
        val prev = written
        written = next
        if (next.ev != prev.ev || next.fpsRange != prev.fpsRange || next.antibanding != prev.antibanding) touch(nowMs, frames)
        if (next.ev != prev.ev && !evFailed) {
            call({ camera.setEv(next.ev, it) }, onOk = { confirmed = confirmed.copy(ev = next.ev) }, onFail = { evFailed = true })
        }
        if (next.copy(ev = 0) != prev.copy(ev = 0) && !optionsFailed) {
            call({ camera.setOptions(next, it) }, onOk = { confirmed = next.copy(ev = confirmed.ev) },
                onFail = { optionsFailed = true })
        }
    }

    private fun call(start: ((WriteOutcome) -> Unit) -> Unit, onOk: () -> Unit, onFail: () -> Unit) {
        val mine = epoch
        inFlight++
        var answered = false
        start { outcome ->
            if (mine != epoch || answered) return@start
            answered = true
            inFlight--
            when (outcome) {
                WriteOutcome.OK -> onOk()
                WriteOutcome.FAILED -> onFail()
                WriteOutcome.CANCELLED -> Unit
            }
            onSettled()
        }
    }
}
