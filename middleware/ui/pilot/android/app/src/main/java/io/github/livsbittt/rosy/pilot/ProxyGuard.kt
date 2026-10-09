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
             path.startsWith("/api/v1/") || path.startsWith("/ws/"))
    }
}
