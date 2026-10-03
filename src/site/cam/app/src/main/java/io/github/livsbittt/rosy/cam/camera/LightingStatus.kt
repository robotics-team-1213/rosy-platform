package io.github.livsbittt.rosy.cam.camera

/** Actual observed camera LED state, not just a requested torch command. */
data class LightingStatus(
    val supported: Boolean = false,
    val enabled: Boolean = true,
    val torchOn: Boolean = false,
    val dark: Boolean = false,
    val message: String? = null,
)
