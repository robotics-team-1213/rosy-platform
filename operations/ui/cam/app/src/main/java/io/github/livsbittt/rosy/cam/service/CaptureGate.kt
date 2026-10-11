package io.github.livsbittt.rosy.cam.service

/**
 * When the sensor runs and when JPEG leaves the phone (D-691).
 *
 * [wanted] is Vision's `demand.wanted`. Null means this connection has not said:
 * an older Vision never sends demand, so after [LEGACY_GRACE_MS] the phone sends
 * as it did before. False stops the uplink. The sensor still runs while the
 * operator is looking at the preview, so the ceiling camera can be aimed, but
 * those frames are not sent. Severe heat stops both, even while a Rosy is
 * watching and even while the operator is aiming (D-691).
 */
data class CaptureGate(val cameraOn: Boolean, val sendFrames: Boolean) {
    companion object {
        const val LEGACY_GRACE_MS = 2_000L

        fun decide(
            paired: Boolean,
            wanted: Boolean?,
            previewVisible: Boolean,
            legacyStream: Boolean,
            thermalPause: Boolean = false,
        ): CaptureGate {
            if (thermalPause) return CaptureGate(cameraOn = false, sendFrames = false)
            if (!paired) return CaptureGate(cameraOn = true, sendFrames = false)
            if (wanted == null) {
                return if (legacyStream) CaptureGate(cameraOn = true, sendFrames = true)
                else CaptureGate(cameraOn = previewVisible, sendFrames = false)
            }
            if (wanted) return CaptureGate(cameraOn = true, sendFrames = true)
            return CaptureGate(cameraOn = previewVisible, sendFrames = false)
        }
    }
}
