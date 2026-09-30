package io.github.livsbittt.rosy.cam.settings

/**
 * The DataStore key layout of [SiteLink], as pure code so migration and writes are tested on the JVM
 * (review m9). Values are String, Int (`port`) or Boolean (`secure`); [SettingsStore] maps them to typed keys.
 *
 * A pairing saved before D-391 has `host` and `pin` instead of the site-link keys. It is read through
 * [SiteLink.from] (IP host -> `manual_host`, name -> `tls_host`), and every write removes both old keys.
 */
object SiteLinkPrefs {
    // Before D-391: one dialled host (IP or name) and the pin.
    const val LEGACY_HOST = "host"
    const val LEGACY_PIN = "pin"

    // D-391 1 site-link fields.
    const val SITE_NAME = "site_name"
    const val TLS_HOST = "tls_host"
    const val MANUAL_HOST = "manual_host"
    const val CA_PIN = "ca_pin"
    const val ROLE = "role"
    const val EXPIRES_AT = "expires_at"
    const val PAIRING_SUBNET = "pairing_subnet"
    const val PORT = "port"
    const val TOKEN = "token"
    const val SOURCE = "source"
    const val SECURE = "secure"

    /** The saved link from stored [values] (key name to value), or null when none or invalid. */
    fun decode(values: Map<String, Any?>): SiteLink? {
        fun text(key: String): String? = values[key] as? String
        val port = values[PORT] as? Int ?: return null
        val token = text(TOKEN) ?: return null
        val source = text(SOURCE) ?: return null
        val secure = values[SECURE] as? Boolean ?: false
        // An old key present means an app before D-391 wrote last; it wins over any site-link keys.
        val legacyHost = text(LEGACY_HOST)
        val link = if (legacyHost != null) {
            SiteLink.from(PairingUri(legacyHost, port, token, source, secure, text(LEGACY_PIN)))
        } else {
            SiteLink(
                siteName = text(SITE_NAME),
                tlsHost = text(TLS_HOST),
                port = port,
                caPin = text(CA_PIN),
                token = token,
                source = source,
                secure = secure,
                manualHost = text(MANUAL_HOST),
                role = text(ROLE) ?: SiteLink.ROLE,
                expiresAt = text(EXPIRES_AT),
                pairingSubnet = text(PAIRING_SUBNET),
            )
        }
        return link.takeIf { SiteLink.validate(it) == null }
    }

    /**
     * Every key a write touches: the value to store, or null to remove it. The old `host`/`pin` keys are always
     * removed, and an absent optional field removes its key (a new pairing without a pin must not keep the
     * previous site's pin).
     */
    fun encode(link: SiteLink): Map<String, Any?> = linkedMapOf(
        LEGACY_HOST to null,
        LEGACY_PIN to null,
        TLS_HOST to link.tlsHost,
        MANUAL_HOST to link.manualHost,
        SITE_NAME to link.siteName,
        CA_PIN to link.caPin,
        EXPIRES_AT to link.expiresAt,
        PAIRING_SUBNET to link.pairingSubnet,
        ROLE to link.role,
        PORT to link.port,
        TOKEN to link.token,
        SOURCE to link.source,
        SECURE to link.secure,
    )
}
