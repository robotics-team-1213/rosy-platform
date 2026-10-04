package io.github.livsbittt.rosy.pilot

fun interface BundledAssets { fun read(path: String): ByteArray? }

class AssetBundle(private val assets: android.content.res.AssetManager) : BundledAssets {
    override fun read(path: String): ByteArray? = try { assets.open(path).use { MainActivity.readLimited(it, 2 * 1024 * 1024) } } catch (_: java.io.IOException) { null }
}

object BundledPath {
    fun asset(uri: String): String? = when {
        uri == "/pilot" || uri == "/pilot/" -> "pilot/index.html"
        uri.startsWith("/pilot/assets/") -> "pilot/" + uri.removePrefix("/pilot/assets/")
        uri.startsWith("/common/") -> "common/" + uri.removePrefix("/common/")
        else -> null
    }?.takeIf { !it.contains("..") && !it.contains('\\') && !it.contains('%') }
    fun mime(path: String) = when (path.substringAfterLast('.')) {
        "html" -> "text/html; charset=utf-8"
        "js" -> "application/javascript"
        "css" -> "text/css"
        "svg" -> "image/svg+xml"
        "webmanifest" -> "application/manifest+json"
        else -> "application/octet-stream"
    }
}
