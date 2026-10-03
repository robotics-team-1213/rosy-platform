package io.github.livsbittt.rosy.cam.settings

/**
 * The saved site connection in the D-391 1 shape (`site_name`, `tls_host`, `port`, CA, `role`, credential,
 * `expires_at`). Pure JVM.
 *
 * - No resolved IP is ever the dial target: the address of [tlsHost] is looked up through mDNS on every
 *   (re)connect (`link/SiteResolver.kt`), and TLS checks [tlsHost] against the pinned site CA.
 * - [manualHost] is the IP a `rosyov://` link carried. It is the labelled fallback "수동 주소", used only when
 *   mDNS finds nothing, and the site certificate must then carry that IP as a SAN.
 * - [caPin] is the D-341 9 pin (`sha256/…` of the site CA). This app has no `ca_pem` yet; the pairing
 *   client (D-391 4항 4단계) will add it. Links printed before the CA-only rule may still hold a leaf pin.
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
    /** D-391 1 `credential_id` of a credential from `rosy-pair/1` (D-341 8); null for a pasted link's token. */
    val credentialId: String? = null,
) {
    /** The URL host: [tlsHost] whenever it is known, so SNI and hostname checks use it; else [manualHost]. */
    val dialHost: String get() = tlsHost ?: manualHost ?: ""

    /** Connection input for [io.github.livsbittt.rosy.cam.link.OverheadLink] and the settings form. */
    fun toPairing(): PairingUri = PairingUri(dialHost, port, token, source, secure, caPin)

    /** Never prints the token. */
    override fun toString(): String =
        "SiteLink(siteName=$siteName, tlsHost=$tlsHost, port=$port, caPin=$caPin, token=<redacted>, source=$source, " +
            "secure=$secure, manualHost=$manualHost, role=$role, expiresAt=$expiresAt, pairingSubnet=$pairingSubnet, " +
            "credentialId=$credentialId)"

    companion object {
        /** D-370 2 role name of this app in TXT `role` and the site-link record. */
        const val ROLE = "overhead-camera"

        private val IPV4 = Regex("^(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)(\\.(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)){3}$")
        private val HEX_GROUP = Regex("^[0-9A-Fa-f]{1,4}$")

        /**
         * True only for a well-formed IPv4 or IPv6 literal (no zone id); never resolves anything. A host that
         * carries a port ("192.168.1.5:8443") is not a literal: it would reach InetAddress.getByName as a bad
         * address (review M1).
         */
        fun isIpLiteral(host: String): Boolean = IPV4.matches(host) || isIpv6Literal(host)

        private fun isIpv6Literal(host: String): Boolean {
            if (!host.contains(':')) return false
            val halves = host.split("::")
            if (halves.size > 2) return false
            fun groups(part: String): List<String> = if (part.isEmpty()) emptyList() else part.split(':')
            val all = groups(halves[0]) + (if (halves.size == 2) groups(halves[1]) else emptyList())
            // An embedded IPv4 tail counts as two groups and must come last.
            val v4Tail = all.lastOrNull()?.let { IPV4.matches(it) } == true
            val hexGroups = if (v4Tail) all.dropLast(1) else all
            if (!hexGroups.all { HEX_GROUP.matches(it) }) return false
            val count = hexGroups.size + if (v4Tail) 2 else 0
            return if (halves.size == 2) count <= 7 else count == 8
        }

        /**
         * A pairing entered in settings or from a `rosyov://` link, and the migration of a pairing saved before
         * D-391 (keys `host`/`port`/`token`/`source`/`secure`/`pin`): an IP host becomes [manualHost], a DNS name
         * becomes [tlsHost]. [previous] keeps what the new input cannot carry when it belongs to the same site
         * (same pin): the learned [tlsHost] under an IP link, the site name, and the pairing-time subnet.
         * [manualHost] never carries over: it is the saved link's own IP or nothing.
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
                tlsHost = if (ip) previous?.tlsHost?.takeIf { sameSite } else normalizeHost(host),
                port = pairing.port,
                caPin = pairing.pin,
                token = pairing.token,
                source = pairing.source,
                secure = pairing.secure,
                // Only the link being saved supplies manual_host: a name link clears a stale IP (2026-10-01 tablet).
                manualHost = if (ip) host else null,
                pairingSubnet = pairingSubnet ?: previous?.pairingSubnet?.takeIf { sameSite },
            )
        }

        /**
         * The failing field, or null when [link] may be saved and dialled. `tls_host` must be one label plus
         * `.local` (D-391 1, same rule as the shared site-link vector): it is only ever found through mDNS.
         * This checks the stored, canonical form (lower case, no trailing dot or spaces); user input is made
         * canonical by [from], so only [entryReason] is tolerant.
         */
        fun validate(link: SiteLink): String? {
            if (link.tlsHost == null && link.manualHost == null) return "host"
            link.tlsHost?.let { if (!isTlsHost(it)) return "tls_host" }
            link.manualHost?.let { if (!isIpLiteral(it)) return "manual_host" }
            if (link.role != ROLE) return "role"
            return PairingUri.validate(link.dialHost, link.port, link.token, link.source, link.secure, link.caPin)
        }

        /**
         * A pairing as the settings form or a deep link would save it; null when it may be saved. Tolerant of
         * case, spaces and a trailing root dot, because [from] makes the host canonical first.
         */
        fun entryReason(pairing: PairingUri): String? = validate(from(pairing))

        private val TLS_HOST = Regex("^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.local$")

        /** Exactly the canonical form: one lower-case label + `.local`, no trailing dot or spaces. */
        fun isTlsHost(host: String): Boolean = TLS_HOST.matches(host)

        /** Canonical host as stored: trimmed, lower-cased, trailing root dot removed (D-370 TXT rule). */
        fun normalizeHost(host: String): String = host.trim().lowercase().trimEnd('.')
    }
}
