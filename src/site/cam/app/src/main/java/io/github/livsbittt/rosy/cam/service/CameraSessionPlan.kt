package io.github.livsbittt.rosy.cam.service

import io.github.livsbittt.rosy.cam.settings.PairingUri

/** Camera preview is useful before a server is configured; frame sending requires pairing. */
data class CameraSessionPlan(
    val startCamera: Boolean,
    val sendFrames: Boolean,
) {
    companion object {
        fun from(pairing: PairingUri?): CameraSessionPlan = CameraSessionPlan(
            startCamera = true,
            sendFrames = pairing != null,
        )
    }
}
