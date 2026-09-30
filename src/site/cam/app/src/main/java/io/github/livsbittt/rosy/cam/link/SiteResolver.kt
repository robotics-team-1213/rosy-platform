package io.github.livsbittt.rosy.cam.link

import android.util.Log
import io.github.livsbittt.rosy.cam.settings.SiteLink
import java.net.InetAddress
import java.net.UnknownHostException
import java.security.cert.X509Certificate
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.Dns
import okhttp3.internal.tls.OkHostnameVerifier

/** One resolved `_rosy-overhead._tcp` advertisement that passed the D-370 TXT rule. */
data class SiteSighting(val serviceName: String, val tlsHost: String, val port: Int, val addresses: List<InetAddress>)

/** The mDNS side of [SiteResolver]; `settings/NsdSiteBrowser.kt` on the phone, a fake in tests. */
fun interface SiteBrowser {
    /**
     * Browses `_rosy-overhead._tcp` and returns every accepted sighting for which [match] is true, seen from
     * the start until [timeoutMs] passes or shortly after the first match. Empty when none showed up.
     * Blocks the calling thread (OkHttp calls [Dns.lookup] on its own threads).
     */
    fun browse(timeoutMs: Long, match: (SiteSighting) -> Boolean): List<SiteSighting>
}

/** How the next connection reaches the site. */
sealed interface SiteRoute {
    /** mDNS showed [SiteSighting.tlsHost]; dial its addresses, verify TLS against `tls_host`. */
    data class Discovered(val sighting: SiteSighting) : SiteRoute

    /**
     * Dial the pairing link's IP ("수동 주소"). [afterBrowse]: mDNS was searched for `tls_host` and showed
     * nothing (so a failure here is also `not_discovered`); false for a link that knows only its IP.
     */
    data class Manual(val address: InetAddress, val afterBrowse: Boolean = true) : SiteRoute

    /** Neither mDNS nor a manual address: D-391 `not_discovered`. */
    data class NotDiscovered(val tlsHost: String) : SiteRoute

    /**
     * The same `tls_host` answered from disjoint address sets (D-370 5.3): no automatic choice.
     * [serviceNames] are the advertising instances, for the log.
     */
    data class Conflict(
        val tlsHost: String,
        val addresses: List<InetAddress>,
        val serviceNames: List<String> = emptyList(),
    ) : SiteRoute

    /** `tls_host` is not an mDNS name; the system resolver handles it, then [manual] if it cannot (review m4). */
    data class SystemDns(val manual: InetAddress? = null) : SiteRoute
}

/** mDNS did not show the site's `tls_host` on this network within the browse timeout (D-391 1). */
class SiteNotDiscoveredException(val tlsHost: String) :
    UnknownHostException("$MARKER: $tlsHost was not seen via mDNS on this Wi-Fi") {
    companion object {
        const val MARKER = "rosy-not-discovered"
    }
}

/** The site's `tls_host` was advertised from more than one address (D-370 5.3 `conflict`). */
class SiteConflictException(val tlsHost: String, val addresses: List<InetAddress>) :
    UnknownHostException("$MARKER: $tlsHost is advertised from ${addresses.joinToString { it.hostAddress.orEmpty() }}") {
    companion object {
        const val MARKER = "rosy-site-conflict"
    }
}

/**
 * Finds the site of [link] on every (re)connect (D-341 13, D-391 1). Order: mDNS for `tls_host`, then the
 * link's `manual_host`, then `not_discovered`. A discovery is reused for [cacheMs] and dropped by [invalidate]
 * after a failed attempt. Nothing here is persisted: the address is never the saved dial target.
 *
 * mDNS is used only for a pinned link (review m3): the pinned CA is what makes an advertised address safe to
 * dial, so an unpinned `.local` link goes straight to its manual address or `not_discovered`.
 */
class SiteResolver(
    private val link: SiteLink,
    private val browser: SiteBrowser,
    private val nowMs: () -> Long = { System.nanoTime() / 1_000_000 },
    private val browseTimeoutMs: Long = BROWSE_TIMEOUT_MS,
    private val cacheMs: Long = CACHE_MS,
) {
    private class Cached(val route: SiteRoute.Discovered, val atMs: Long)

    /** Lock-free, so [invalidate] on OkHttp's callback thread never waits for a browse (review m2). */
    private val cached = AtomicReference<Cached?>(null)

    /** Serializes lookups only (one NSD browse at a time); [invalidate] never takes it. */
    private val lookupLock = Any()

    private val _route = MutableStateFlow<SiteRoute?>(null)

    /** The route of the last lookup, for the screen ("수동 주소" label, diagnosis). */
    val route: StateFlow<SiteRoute?> = _route.asStateFlow()

    /** Route for the next connection. Blocks for up to the browse timeout. */
    fun resolve(): SiteRoute = synchronized(lookupLock) {
        val result = lookup()
        _route.value = result
        result
    }

    /** Forget the cached discovery; the next [resolve] browses again. Call after a failed connection. */
    fun invalidate() {
        cached.set(null)
    }

    /**
     * For a pinned link that knows only `manual_host`: the one advertisement at that IP, as a candidate name.
     * Null when none or more than one answers there. The advertisement is unauthenticated, so the caller saves
     * the name only after [leafCovers] confirms it on a live pinned handshake to `manual_host` (review M2).
     */
    fun learnTlsHost(): SiteSighting? {
        if (link.tlsHost != null || link.caPin == null) return null
        val manual = manualAddress() ?: return null
        return browser.browse(browseTimeoutMs) { manual in it.addresses }.singleOrNull()
    }

    /** `manual_host` as an address, or null when absent or not a literal (never throws, review M1). */
    private fun manualAddress(): InetAddress? = link.manualHost?.let(::literal)

    private fun lookup(): SiteRoute {
        val manual = manualAddress()
        val tlsHost = link.tlsHost ?: return manual?.let { SiteRoute.Manual(it, afterBrowse = false) }
            ?: SiteRoute.NotDiscovered(link.manualHost.orEmpty())
        if (!isMdnsName(tlsHost)) return SiteRoute.SystemDns(manual)
        // Unpinned: nothing would authenticate an advertised address (review m3).
        if (link.caPin == null) {
            return manual?.let { SiteRoute.Manual(it, afterBrowse = false) } ?: SiteRoute.NotDiscovered(tlsHost)
        }
        cached.get()?.let { if (nowMs() - it.atMs < cacheMs) return it.route }
        val sightings = browser.browse(browseTimeoutMs) { sameHost(it.tlsHost, tlsHost) }
            .filter { it.addresses.isNotEmpty() }
        if (sightings.isNotEmpty()) {
            conflict(tlsHost, sightings)?.let { return it }
            val preferred = sightings.firstOrNull { it.serviceName == link.siteName } ?: sightings.first()
            return SiteRoute.Discovered(preferred).also { cached.set(Cached(it, nowMs())) }
        }
        manual?.let { return SiteRoute.Manual(it) }
        return SiteRoute.NotDiscovered(tlsHost)
    }

    /**
     * A conflict needs two advertisements with no address in common (review m5). Overlapping sets, such as one
     * instance seen with IPv4 only and again with IPv4 + IPv6, are the same host.
     */
    private fun conflict(tlsHost: String, sightings: List<SiteSighting>): SiteRoute.Conflict? {
        val disjoint = sightings.any { a -> sightings.any { b -> a.addresses.none { it in b.addresses } } }
        if (!disjoint) return null
        val names = sightings.map { it.serviceName }.distinct()
        Log.w(TAG, "conflict: $tlsHost advertised by $names at ${sightings.map { s -> s.addresses.map { it.hostAddress } }}")
        return SiteRoute.Conflict(tlsHost, sightings.flatMap { it.addresses }.distinct(), names)
    }

    companion object {
        /** D-391 1 "정해진 시간": how long a browse may look for the site before `not_discovered`. */
        const val BROWSE_TIMEOUT_MS = 5_000L
        const val CACHE_MS = 30_000L
        private const val TAG = "SiteResolver"

        fun isMdnsName(host: String): Boolean = host.trimEnd('.').lowercase().endsWith(".local")

        /**
         * True when [leaf], the peer of a live handshake that already passed the pinned site CA, names [host]
         * in its SAN (OkHttp's own hostname rules). This is what lets an advertised name be saved (review M2).
         */
        fun leafCovers(host: String, leaf: X509Certificate?): Boolean =
            leaf != null && OkHostnameVerifier.verify(host.trimEnd('.'), leaf)

        private fun sameHost(a: String, b: String): Boolean =
            a.trim().trimEnd('.').equals(b.trim().trimEnd('.'), ignoreCase = true)

        /** A strict IP literal to an address without any lookup; null for anything else. */
        private fun literal(ip: String): InetAddress? =
            if (SiteLink.isIpLiteral(ip)) runCatching { InetAddress.getByName(ip) }.getOrNull() else null
    }
}

/**
 * OkHttp [Dns] that answers [tlsHost] from [resolver], so the URL, SNI and hostname check keep `tls_host`
 * while TCP goes to the address mDNS found (Android cannot resolve `*.local` through DNS). Every other
 * name goes to [fallback].
 */
class SiteDns(
    private val tlsHost: String,
    private val resolver: SiteResolver,
    private val fallback: Dns = Dns.SYSTEM,
) : Dns {
    override fun lookup(hostname: String): List<InetAddress> {
        if (!hostname.trimEnd('.').equals(tlsHost.trimEnd('.'), ignoreCase = true)) return fallback.lookup(hostname)
        // Never let a resolver bug escape as a RuntimeException on OkHttp's thread; it becomes a lookup failure.
        val route = try {
            resolver.resolve()
        } catch (e: RuntimeException) {
            throw UnknownHostException("site lookup failed for $tlsHost: $e")
        }
        return when (route) {
            is SiteRoute.Discovered -> route.sighting.addresses
            is SiteRoute.Manual -> listOf(route.address)
            is SiteRoute.NotDiscovered -> throw SiteNotDiscoveredException(tlsHost)
            is SiteRoute.Conflict -> throw SiteConflictException(tlsHost, route.addresses)
            is SiteRoute.SystemDns -> try {
                fallback.lookup(hostname)
            } catch (e: UnknownHostException) {
                // A non-.local name that DNS cannot answer here: the manual address, if any (review m4).
                route.manual?.let { listOf(it) } ?: throw e
            }
        }
    }
}
