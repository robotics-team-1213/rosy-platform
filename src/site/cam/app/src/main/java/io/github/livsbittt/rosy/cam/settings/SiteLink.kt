package io.github.livsbittt.rosy.cam.settings

/**
 * The saved site connection in the D-390 1 shape (`site_name`, `tls_host`, `port`, CA, `role`, credential,
 * `expires_at`). Pure JVM.
 *
 * - No resolved IP is ever the dial target: the address of [tlsHost] is looked up through mDNS on every
 *   (re)connect (`link/SiteResolver.kt`), and TLS checks [tlsHost] against the pinned site CA.
 * - [manualHost] is the IP a `rosyov://` link carried. It is the labelled fallback "수동 주소", used only when
 *   mDNS finds nothing, and the site certificate must then carry that IP as a SAN.
 * - [caPin] is the D-341 9 pin (`sha256/…` of the site CA). This app has no `ca_pem` yet; the pairing
 *   client (D-390 4항 4단계) will add it. Links printed before the CA-only rule may still hold a leaf pin.
 * - [pairingSubnet] is diagnostic only ("same SSID, different network"); it is never dialled.
 */
data class SiteLink(
    val siteName: String?,
    val tlsHost: String?,
    val port: Int,
    val caPin: String?,
    val token: String,
    val source: String,
    val secure: Boolean,
    val manualHost: String? = null,
    val role: String = ROLE,
    val expiresAt: String? = null,
    val pairingSubnet: String? = null,
) {
    /** The URL host: [tlsHost] whenever it is known, so SNI and hostname checks use it; else [manualHost]. */
    val dialHost: String get() = tlsHost ?: manualHost ?: ""

    /** Connection input for [io.github.livsbittt.rosy.cam.link.OverheadLink] and the settings form. */
    fun toPairing(): PairingUri = PairingUri(dialHost, port, token, source, secure, caPin)

    /** Never prints the token. */
    override fun toString(): String =
        "SiteLink(siteName=$siteName, tlsHost=$tlsHost, port=$port, caPin=$caPin, token=<redacted>, source=$source, " +
            "secure=$secure, manualHost=$manualHost, role=$role, expiresAt=$expiresAt, pairingSubnet=$pairingSubnet)"

    companion object {
        /** D-370 2 role name of this app in TXT `role` and the site-link record. */
        const val ROLE = "overhead-camera"

        private val IPV4 = Regex("^(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)(\\.(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)){3}$")
        private val IPV6 = Regex("^[0-9A-Fa-f:.]+$")

        /** True for an IPv4 or IPv6 literal; never resolves anything. */
        fun isIpLiteral(host: String): Boolean = IPV4.matches(host) || (host.contains(':') && IPV6.matches(host))

        /**
         * A pairing entered in settings or from a `rosyov://` link, and the migration of a pairing saved before
         * D-390 (keys `host`/`port`/`token`/`source`/`secure`/`pin`): an IP host becomes [manualHost], a DNS name
         * becomes [tlsHost]. [previous] keeps what the new input cannot carry: the other host kind when it
         * belongs to the same site (same pin), the site name, and the pairing-time subnet.
         */
        fun from(
            pairing: PairingUri,
            siteName: String? = null,
            pairingSubnet: String? = null,
            previous: SiteLink? = null,
        ): SiteLink {
            val host = pairing.host.trim()
            val ip = isIpLiteral(host)
            val sameSite = previous != null && previous.caPin != null && previous.caPin == pairing.pin
            return SiteLink(
                siteName = siteName ?: previous?.siteName?.takeIf { sameSite },
                tlsHost = if (ip) previous?.tlsHost?.takeIf { sameSite } else host.lowercase().trimEnd('.'),
                port = pairing.port,
                caPin = pairing.pin,
                token = pairing.token,
                source = pairing.source,
                secure = pairing.secure,
                manualHost = if (ip) host else previous?.manualHost?.takeIf { sameSite },
                pairingSubnet = pairingSubnet ?: previous?.pairingSubnet?.takeIf { sameSite },
            )
        }

        /** The failing field, or null when [link] may be saved and dialled. */
        fun validate(link: SiteLink): String? {
            if (link.tlsHost == null && link.manualHost == null) return "host"
            link.tlsHost?.let { if (isIpLiteral(it)) return "tls_host" }
            link.manualHost?.let { if (!isIpLiteral(it)) return "manual_host" }
            if (link.role != ROLE) return "role"
            return PairingUri.validate(link.dialHost, link.port, link.token, link.source, link.secure, link.caPin)
        }
    }
}
