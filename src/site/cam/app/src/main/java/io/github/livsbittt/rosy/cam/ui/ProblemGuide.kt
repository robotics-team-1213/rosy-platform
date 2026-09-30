package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.link.LinkError
import io.github.livsbittt.rosy.cam.link.NetworkFailure
import io.github.livsbittt.rosy.cam.service.StreamError

/** Operator-facing problem; each maps to one Korean sentence that names the next step. */
enum class Problem {
    NO_WIFI,
    UNREACHABLE,
    REFUSED,
    UNKNOWN_HOST,
    TLS,
    TLS_PIN,
    /** D-390 `not_discovered`: the site is not advertised on this Wi-Fi (often a same-SSID other network). */
    NOT_DISCOVERED,
    /** D-370 5.3 `conflict`: the site name is advertised from more than one address. */
    SITE_CONFLICT,
    UNAUTHORIZED,
    REPLACED,
    PROTOCOL_MISMATCH,
    BUSY,
    SITE_CHECKING,
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
                        NetworkFailure.NOT_DISCOVERED -> Problem.NOT_DISCOVERED
                        NetworkFailure.CONFLICT -> Problem.SITE_CONFLICT
                        NetworkFailure.OTHER -> Problem.NETWORK_OTHER
                    }
                }
                val step = when (problem) {
                    Problem.REFUSED, Problem.NETWORK_OTHER, Problem.SITE_CONFLICT -> NextStep.NONE
                    else -> NextStep.OPEN_SETTINGS
                }
                Guidance(problem, step, error.detail, retrying)
            }
            LinkError.Unauthorized -> Guidance(Problem.UNAUTHORIZED, NextStep.OPEN_SETTINGS, "HTTP 401 / close 4401", retrying)
            LinkError.Replaced -> Guidance(Problem.REPLACED, NextStep.OPEN_SETTINGS, "close 4409", retrying)
            LinkError.ProtocolMismatch -> Guidance(Problem.PROTOCOL_MISMATCH, NextStep.NONE, "close 4400", retrying)
            LinkError.CredentialUnknown -> Guidance(Problem.SITE_CHECKING, NextStep.NONE, "close 4503", retrying)
            is LinkError.Busy -> Guidance(Problem.BUSY, NextStep.NONE, "close ${error.code} ${error.reason}".trim(), retrying)
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

    /** Which second sentence follows "사이트가 이 Wi-Fi에서 보이지 않습니다". */
    enum class NotDiscoveredHint {
        /** The Wi-Fi subnet differs from the one at pairing time: same SSID, another AP or hotspot. */
        OTHER_NETWORK,

        /** Same subnet as at pairing time: the site PC or its mDNS advertisement is off, or multicast is blocked. */
        SAME_NETWORK,

        /** The subnet at pairing time or now is unknown. */
        UNKNOWN,
    }

    /**
     * @param current the Wi-Fi now (null or no subnet: unknown).
     * @param pairingSubnet the subnet saved at pairing time, diagnostic only.
     */
    fun notDiscoveredHint(current: LanSnapshot?, pairingSubnet: String?): NotDiscoveredHint {
        val now = current?.subnet ?: return NotDiscoveredHint.UNKNOWN
        val then = pairingSubnet ?: return NotDiscoveredHint.UNKNOWN
        return if (now == then) NotDiscoveredHint.SAME_NETWORK else NotDiscoveredHint.OTHER_NETWORK
    }

    fun forStream(error: StreamError): Guidance = when (error) {
        StreamError.NotPaired -> Guidance(Problem.NOT_PAIRED, NextStep.OPEN_SETTINGS, null, retrying = false)
        is StreamError.Camera -> Guidance(Problem.CAMERA, NextStep.NONE, error.message, retrying = false)
        is StreamError.ForegroundDenied -> Guidance(Problem.FOREGROUND_DENIED, NextStep.NONE, error.message, retrying = false)
    }
}
