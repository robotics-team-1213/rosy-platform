package io.github.livsbittt.rosy.pilot

/** A revoked shutdown cannot keep discovery blocked or complete a newer display request. */
class PendingScreenSleep {
    private var owner: Long? = null
    val active: Boolean get() = owner != null
    fun begin(generation: Long) { owner = generation }
    fun revoke() { owner = null }
    fun finish(generation: Long): Boolean {
        if (owner != generation) return false
        owner = null
        return true
    }
}
