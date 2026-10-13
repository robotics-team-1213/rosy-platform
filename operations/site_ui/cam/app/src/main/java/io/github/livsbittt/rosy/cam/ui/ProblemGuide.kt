package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.link.LinkError
import io.github.livsbittt.rosy.cam.link.NetworkFailure
import io.github.livsbittt.rosy.cam.link.SiteRoute
import io.github.livsbittt.rosy.cam.service.StreamError

/** Operator-facing problem; each maps to one Korean sentence that names the next step. */
enum class Problem {
    NO_WIFI,
    UNREACHABLE,
    REFUSED,
    UNKNOWN_HOST,
    TLS,
    TLS_PIN,
    /** D-391 `not_discovered`: the site is not advertised on this Wi-Fi (often a same-SSID other network). */
    NOT_DISCOVERED,
    /** D-370 5.3 `conflict`: the site name is advertised from more than one address. */
    SITE_CONFLICT,
    UNAUTHORIZED,
    /** Close 4403: valid credential, not allowed here. Final; the site operator must allow it (no re-pair). */
    FORBIDDEN,
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
 * @property manualFailure with [Problem.NOT_DISCOVERED]: mDNS found nothing and the "수동 주소" fallback then
 *   failed this way too ([Problem.UNREACHABLE], [Problem.REFUSED] or [Problem.NETWORK_OTHER]); null otherwise.
 */
data class Guidance(
    val problem: Problem,
    val step: NextStep,
    val detail: String?,
    val retrying: Boolean,
    val manualFailure: Problem? = null,
)

/** Pure mapping from link and session errors to guidance. Wording lives in strings.xml. */
object ProblemGuide {
    /**
     * @param stopped the link gave up (4400/4409 or a fatal 4401) and waits for the operator.
     * @param wifiConnected false when the phone has no Wi-Fi; any transport failure is then blamed on that.
     * @param route how the failed attempt reached the site. After an empty mDNS browse a transport failure
     *   on the manual address is reported as `not_discovered` first (D-391 1), with that failure attached.
     */
    fun forLink(error: LinkError, stopped: Boolean, wifiConnected: Boolean, route: SiteRoute? = null): Guidance {
        val retrying = !stopped
        return when (error) {
            is LinkError.Network -> {
                val manualFailure = when (error.kind) {
                    NetworkFailure.UNREACHABLE -> Problem.UNREACHABLE
                    NetworkFailure.REFUSED -> Problem.REFUSED
                    NetworkFailure.OTHER -> Problem.NETWORK_OTHER
                    else -> null
                }
                if (wifiConnected && manualFailure != null && route is SiteRoute.Manual && route.afterBrowse) {
                    return Guidance(Problem.NOT_DISCOVERED, NextStep.OPEN_SETTINGS, error.detail, retrying, manualFailure)
                }
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
            // Re-pairing cannot help: the token is fine, the site does not allow this camera (rosy-00, 2026-10-01).
            LinkError.Forbidden -> Guidance(Problem.FORBIDDEN, NextStep.NONE, "close 4403", retrying)
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
        OTHER_SUBNET,

        /** Same subnet as at pairing time: the site PC or its mDNS advertisement is off, or multicast is blocked. */
        SAME_SUBNET,

        /** The subnet at pairing time or now is unknown. */
        UNKNOWN,
    }

    /** First line of the not-found message; it must agree with the [NotDiscoveredHint] line under it. */
    enum class NotDiscoveredHeadline {
        /** "사이트가 이 Wi-Fi에서 보이지 않습니다 — 같은 이름의 다른 Wi-Fi일 수 있습니다" */
        OTHER_WIFI,

        /** "사이트가 자동 찾기(mDNS)에 보이지 않습니다": same network as at pairing, so not an SSID mix-up. */
        MDNS_SILENT,
    }

    fun notDiscoveredHeadline(hint: NotDiscoveredHint): NotDiscoveredHeadline =
        if (hint == NotDiscoveredHint.SAME_SUBNET) NotDiscoveredHeadline.MDNS_SILENT else NotDiscoveredHeadline.OTHER_WIFI

    /**
     * @param current the Wi-Fi now (null or no subnet: unknown).
     * @param pairingSubnet the subnet saved at pairing time, diagnostic only.
     */
    fun notDiscoveredHint(current: LanSnapshot?, pairingSubnet: String?): NotDiscoveredHint {
        val now = current?.subnet ?: return NotDiscoveredHint.UNKNOWN
        val then = pairingSubnet ?: return NotDiscoveredHint.UNKNOWN
        return if (now == then) NotDiscoveredHint.SAME_SUBNET else NotDiscoveredHint.OTHER_SUBNET
    }

    fun forStream(error: StreamError): Guidance = when (error) {
        StreamError.NotPaired -> Guidance(Problem.NOT_PAIRED, NextStep.OPEN_SETTINGS, null, retrying = false)
        is StreamError.Camera -> Guidance(Problem.CAMERA, NextStep.NONE, error.message, retrying = false)
        is StreamError.ForegroundDenied -> Guidance(Problem.FOREGROUND_DENIED, NextStep.NONE, error.message, retrying = false)
    }
}
