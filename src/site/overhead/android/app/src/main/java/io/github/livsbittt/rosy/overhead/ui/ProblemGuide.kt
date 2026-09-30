package io.github.livsbittt.rosy.overhead.ui

import io.github.livsbittt.rosy.overhead.link.LinkError
import io.github.livsbittt.rosy.overhead.link.NetworkFailure
import io.github.livsbittt.rosy.overhead.service.StreamError

/** Operator-facing problem; each maps to one Korean sentence that names the next step. */
enum class Problem {
    NO_WIFI,
    UNREACHABLE,
    REFUSED,
    UNKNOWN_HOST,
    TLS,
    TLS_PIN,
    UNAUTHORIZED,
    REPLACED,
    PROTOCOL_MISMATCH,
    INVALID_CONFIG,
    CLOSED,
    NETWORK_OTHER,
    NOT_PAIRED,
    CAMERA,
    FOREGROUND_DENIED,
}

/** The one button offered next to the message. */
enum class NextStep { OPEN_SETTINGS, NONE }

/**
 * @property detail raw text for the "자세히" disclosure; never shown by default.
 * @property retrying the link keeps reconnecting on its own, so the operator may also just wait.
 */
data class Guidance(val problem: Problem, val step: NextStep, val detail: String?, val retrying: Boolean)

/** Pure mapping from link and session errors to guidance. Wording lives in strings.xml. */
object ProblemGuide {
    /**
     * @param stopped the link gave up (4400/4409 or a fatal 4401) and waits for the operator.
     * @param wifiConnected false when the phone has no Wi-Fi; any transport failure is then blamed on that.
     */
    fun forLink(error: LinkError, stopped: Boolean, wifiConnected: Boolean): Guidance {
        val retrying = !stopped
        return when (error) {
            is LinkError.Network -> {
                val problem = if (!wifiConnected) {
                    Problem.NO_WIFI
                } else {
                    when (error.kind) {
                        NetworkFailure.UNREACHABLE -> Problem.UNREACHABLE
                        NetworkFailure.REFUSED -> Problem.REFUSED
                        NetworkFailure.UNKNOWN_HOST -> Problem.UNKNOWN_HOST
                        NetworkFailure.TLS -> Problem.TLS
                        NetworkFailure.TLS_PIN -> Problem.TLS_PIN
                        NetworkFailure.OTHER -> Problem.NETWORK_OTHER
                    }
                }
                val step = if (problem == Problem.REFUSED || problem == Problem.NETWORK_OTHER) NextStep.NONE else NextStep.OPEN_SETTINGS
                Guidance(problem, step, error.detail, retrying)
            }
            LinkError.Unauthorized -> Guidance(Problem.UNAUTHORIZED, NextStep.OPEN_SETTINGS, "HTTP 401 / close 4401", retrying)
            LinkError.Replaced -> Guidance(Problem.REPLACED, NextStep.OPEN_SETTINGS, "close 4409", retrying)
            LinkError.ProtocolMismatch -> Guidance(Problem.PROTOCOL_MISMATCH, NextStep.NONE, "close 4400", retrying)
            is LinkError.InvalidConfig -> Guidance(Problem.INVALID_CONFIG, NextStep.NONE, error.field, retrying)
            is LinkError.Closed -> Guidance(Problem.CLOSED, NextStep.NONE, "close ${error.code} ${error.reason}".trim(), retrying)
        }
    }

    /**
     * Token and source name are edited in settings, which are read-only while the camera runs,
     * so the button stops the camera first and says so.
     */
    fun stopsCameraFirst(problem: Problem, running: Boolean): Boolean =
        running && (problem == Problem.UNAUTHORIZED || problem == Problem.REPLACED || problem == Problem.TLS_PIN)

    fun forStream(error: StreamError): Guidance = when (error) {
        StreamError.NotPaired -> Guidance(Problem.NOT_PAIRED, NextStep.OPEN_SETTINGS, null, retrying = false)
        is StreamError.Camera -> Guidance(Problem.CAMERA, NextStep.NONE, error.message, retrying = false)
        is StreamError.ForegroundDenied -> Guidance(Problem.FOREGROUND_DENIED, NextStep.NONE, error.message, retrying = false)
    }
}
