package io.github.livsbittt.rosy.pilot

class ProxyGuard(private val authority: String, private val capability: String,
    private val cookieName: String = "rosy-shell") {
    fun permits(headers: Map<String, String>): Boolean {
        if (headers["host"] != authority) return false
        val origin = headers["origin"]
        if (origin != null && origin != "http://$authority") return false
        val cookies = headers["cookie"].orEmpty().split(';').map { it.trim() }
        return cookies.any { it == "$cookieName=$capability" }
    }
    companion object {
        fun allowedPath(path: String): Boolean = !path.contains("..") && !path.contains('\\') &&
            (path == "/pilot" || path.startsWith("/pilot/") || path.startsWith("/common/") ||
             path in setOf("/api/account/session", "/api/account/logout") || path.startsWith("/api/v1/") || path.startsWith("/ws/"))
    }
}

/** D-789: the bundled Pilot may open WHEP only to the site media origin CORE itself names; media never passes this proxy. */
object PilotCsp {
    private val host = Regex("^[A-Za-z0-9.-]{1,253}$")   // shortcut: no IPv6 literal, add one if a site uses it

    /** The https origin in CORE's own /pilot `connect-src`, rebuilt from validated parts; anything else is refused. */
    fun mediaOrigin(corePolicy: String?): String? {
        val connect = corePolicy?.split(';')?.map { it.trim() }?.firstOrNull { it.startsWith("connect-src ") } ?: return null
        for (token in connect.split(' ').drop(1)) {
            if (!token.startsWith("https://")) continue
            val uri = runCatching { java.net.URI(token) }.getOrNull() ?: continue
            val name = uri.host ?: continue
            if (uri.scheme != "https" || uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null ||
                uri.rawPath !in setOf("", "/") || !host.matches(name) || (uri.port != -1 && uri.port !in 1..65535)) continue
            return "https://$name" + if (uri.port == -1) "" else ":${uri.port}"
        }
        return null
    }

    fun header(mediaOrigin: String?): String {
        val media = mediaOrigin?.let { " $it" }.orEmpty()
        return "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'$media; " +
            "worker-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    }
}
