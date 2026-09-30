package io.github.livsbittt.rosy.cam.settings

import io.github.livsbittt.rosy.cam.Vectors
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingUriTest {
    private val pairing = Vectors.root.getJSONObject("pairing_uris")

    @Test
    fun parsesEveryValidVector() {
        val valid = pairing.getJSONArray("valid")
        assertTrue(valid.length() > 0)
        for (i in 0 until valid.length()) {
            val v = valid.getJSONObject(i)
            val expected = PairingUri(
                host = v.getString("host"),
                port = v.getInt("port"),
                token = v.getString("token"),
                source = v.getString("source"),
                secure = v.optBoolean("secure", false),
                pin = if (v.has("pin")) v.getString("pin") else null,
            )
            assertEquals(v.getString("uri"), PairingUri.Parsed.Valid(expected), PairingUri.parse(v.getString("uri")))
            assertEquals(v.getString("ws_url"), expected.wsUrl)
        }
    }

    @Test
    fun rejectsEveryInvalidVectorWithItsReason() {
        val invalid = pairing.getJSONArray("invalid")
        assertTrue(invalid.length() > 0)
        for (i in 0 until invalid.length()) {
            val v = invalid.getJSONObject(i)
            assertEquals(
                v.getString("uri"),
                PairingUri.Parsed.Invalid(v.getString("reason")),
                PairingUri.parse(v.getString("uri")),
            )
        }
    }

    @Test
    fun sourcePatternMatchesVectors() {
        assertEquals(pairing.getString("source_pattern"), PairingUri.SOURCE_PATTERN.pattern)
    }

    @Test
    fun pinPatternMatchesVectors() {
        assertEquals(pairing.getString("pin_pattern"), PairingUri.PIN_PATTERN.pattern)
    }

    @Test
    fun pinnedPairingRoundTripsAndNeedsTls() {
        val pin = Vectors.root.getJSONObject("cert_pins").getJSONArray("vectors").getJSONObject(0).getString("pin")
        val original = PairingUri("192.168.1.102", 18447, "secret", "ceiling_north", secure = true, pin = pin)
        assertEquals(PairingUri.Parsed.Valid(original), PairingUri.parse(original.toUri()))
        assertTrue(original.toString(), original.toString().contains(pin) && !original.toString().contains("secret"))
        assertEquals("pin", PairingUri.validate("h", 1, "t", "s", secure = false, pin = pin))
        assertNull(PairingUri.validate("h", 1, "t", "s", secure = true, pin = pin))
    }

    @Test
    fun sourceLengthLimitIs32() {
        assertNull(PairingUri.validate("h", 1, "t", "a".repeat(32)))
        assertEquals("source", PairingUri.validate("h", 1, "t", "a".repeat(33)))
    }

    @Test
    fun manualEntryValidationUsesTheSameRules() {
        assertNull(PairingUri.validate("192.0.2.10", 8095, "abc", "overhead-1"))
        assertEquals("host", PairingUri.validate("", 8095, "abc", "overhead-1"))
        assertEquals("host", PairingUri.validate("bad host", 8095, "abc", "overhead-1"))
        assertEquals("port", PairingUri.validate("h", 0, "abc", "overhead-1"))
        assertEquals("port", PairingUri.validate("h", 65536, "abc", "overhead-1"))
        assertEquals("token", PairingUri.validate("h", 8095, "", "overhead-1"))
        assertEquals("source", PairingUri.validate("h", 8095, "abc", "bad source"))
    }

    @Test
    fun missingHostIsRejected() {
        assertEquals(PairingUri.Parsed.Invalid("host"), PairingUri.parse("rosyov://:8095/?t=abc&s=overhead-1"))
    }

    @Test
    fun nonNumericPortIsRejected() {
        assertEquals(PairingUri.Parsed.Invalid("port"), PairingUri.parse("rosyov://h:80a/?t=abc&s=overhead-1"))
    }

    @Test
    fun schemeIsCaseInsensitive() {
        assertEquals(PairingUri.Parsed.Valid(PairingUri("h", 1, "a", "b")), PairingUri.parse("ROSYOV://h:1/?t=a&s=b"))
    }

    @Test
    fun queryWithoutTrailingSlashIsAccepted() {
        assertEquals(PairingUri.Parsed.Valid(PairingUri("h", 1, "a", "b")), PairingUri.parse("rosyov://h:1?t=a&s=b"))
    }

    @Test
    fun badPercentEncodingInTokenIsATokenError() {
        assertEquals(PairingUri.Parsed.Invalid("token"), PairingUri.parse("rosyov://h:1/?t=%zz&s=b"))
    }

    @Test
    fun toUriRoundTrips() {
        val original = PairingUri("site-pc.local", 9000, "x+y &z", "cam-north")
        assertEquals(PairingUri.Parsed.Valid(original), PairingUri.parse(original.toUri()))
    }

    @Test
    fun securePairingSelectsWssAndRoundTripsTlsFlag() {
        val original = PairingUri("fleet-site.local", 443, "secret", "ceiling_north", secure = true)
        assertTrue(original.wsUrl.startsWith("wss://"))
        assertEquals(PairingUri.Parsed.Valid(original), PairingUri.parse(original.toUri()))
    }

    @Test
    fun toStringRedactsTheToken() {
        val text = PairingUri("192.0.2.10", 8095, "s3cret-token", "overhead-1").toString()
        assertTrue(text, !text.contains("s3cret-token"))
        assertTrue(text, text.contains("192.0.2.10") && text.contains("8095") && text.contains("overhead-1"))
        assertTrue(text, text.contains("<redacted>"))
    }
}
