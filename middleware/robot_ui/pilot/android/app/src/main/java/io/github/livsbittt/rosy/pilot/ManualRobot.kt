package io.github.livsbittt.rosy.pilot

import io.github.livsbittt.rosy.cam.settings.SiteLink
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import java.net.Inet4Address
import java.net.InetAddress

object ManualRobot {
    fun parse(text: String): Candidate {
        require(text.length <= 256)
        val url = requireNotNull(text.trim().toHttpUrlOrNull())
        // shortcut: manual entry is HTTP LAN IPv4 only; TLS robots use the existing hostname/CA approval flow.
        require(!url.isHttps)
        require(url.username.isEmpty() && url.password.isEmpty() && url.encodedPath == "/" &&
            url.query == null && url.fragment == null)
        require(SiteLink.isIpLiteral(url.host))
        val address = InetAddress.getByName(url.host)
        require(address is Inet4Address && address.isSiteLocalAddress)
        return Candidate(url.host, url.port, listOf(url.host), "${url.host}:${url.port}", secure = url.isHttps)
    }
}
