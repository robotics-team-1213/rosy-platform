package io.github.livsbittt.rosy.cam.camera

/**
 * A live lens change that must not end the stream: bind [next]; if that throws, bind [previous]
 * again. Only when the old camera cannot be bound either is the failure fatal. Pure JVM.
 */
object LensSwitch {
    sealed interface Outcome {
        data object Switched : Outcome

        /** [next] failed; [previous] is bound again and streaming continues. */
        data class RolledBack(val error: Throwable) : Outcome

        /** Neither camera could be bound; the session cannot continue. */
        data class Failed(val error: Throwable) : Outcome
    }

    fun run(previous: String?, next: String?, bind: (String?) -> Unit): Outcome {
        val switchError = try {
            bind(next)
            return Outcome.Switched
        } catch (e: Exception) {
            e
        }
        return try {
            bind(previous)
            Outcome.RolledBack(switchError)
        } catch (e: Exception) {
            Outcome.Failed(e)
        }
    }
}
