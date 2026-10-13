package io.github.livsbittt.rosy.cam.pairing.peer

import io.github.livsbittt.rosy.cam.pairing.PairableSite
import okhttp3.tls.HeldCertificate
import org.junit.Assert.*
import org.junit.Test
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.time.Instant
import javax.crypto.KeyGenerator

class CameraRelationshipVaultTest {
    private class Memory : CameraVaultStorage {
        val rows = mutableMapOf<String, String>()
        override fun get(id: String) = rows[id]
        override fun endpointKeys() = rows.keys.map { it.removePrefix("fence|") }.toSet()
        override fun write(id: String, value: String, remove: Set<String>) { rows[id] = value; remove.forEach { rows.remove(it) } }
    }
    private val aes = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    private val publicKey = CameraProof.encodeKey(KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair().public)
    private val ca = HeldCertificate.Builder().certificateAuthority(0).commonName("fixture CA").build().certificatePem()
    private val site = PairableSite("Fixture site", "fleet.local", 8443, "192.168.1.10")
    private fun row(expiry: Instant? = null) = CameraRelationship(CameraRelationshipVault.origin(site), "fleet-test", publicKey,
        "cam_test", CameraProof.fingerprint(publicKey), "A".repeat(32), 0, "ceiling_north", expiry == null, expiry, ca)

    @Test fun encryptedApprovalAndSourceSurviveOfflineDhcpAndFiniteCredentialExpiry() {
        val memory = Memory(); val vault = CameraRelationshipVault(memory) { aes }
        vault.remember(site, row(), vault.fence(site))
        assertFalse(memory.rows.values.joinToString().contains("ceiling_north"))
        assertFalse(memory.rows.values.joinToString().contains(publicKey))
        val restarted = CameraRelationshipVault(memory) { aes }
        assertEquals(row(), restarted.read(site.copy(address = "192.168.1.99")))
        assertTrue(restarted.read(site)!!.validAt(Instant.parse("2099-01-01T00:00:00Z")))
        assertEquals("ceiling_north", restarted.read(site)!!.sourceId)
    }
    @Test fun temporaryAuthorizationIsRetainedButCannotBePromotedToPersistent() {
        val memory = Memory(); val vault = CameraRelationshipVault(memory) { aes }
        vault.remember(site, row(Instant.EPOCH), vault.fence(site)); val bytes = memory.rows.toMap()
        assertFalse(vault.read(site)!!.validAt(Instant.now())); assertEquals(bytes, memory.rows)
        assertThrows(IllegalArgumentException::class.java) { row(Instant.EPOCH).copy(persistent = true) }
        assertThrows(IllegalArgumentException::class.java) { row().copy(sourceId = "../robot") }
    }
    @Test fun explicitLocalForgetFencesLateCompletionAndOldAddressEvenAfterNewConsent() {
        val memory = Memory(); val vault = CameraRelationshipVault(memory) { aes }; val old = vault.fence(site)
        vault.remember(site, row(), old); vault.erase(site.copy(address = "192.168.1.99"))
        assertNull(vault.read(site)); assertThrows(IllegalArgumentException::class.java) { vault.remember(site, row(), old) }
        vault.remember(site, row().copy(id = "B".repeat(32)), vault.fence(site))
        assertThrows(IllegalArgumentException::class.java) { vault.remember(site, row(), old) }
        assertEquals("B".repeat(32), vault.read(site)!!.id)
    }
    @Test fun KeystoreOrCipherFailureNeverDeletesApprovalAndLiteralIpCannotRetargetIt() {
        val memory = Memory(); val vault = CameraRelationshipVault(memory) { aes }
        vault.remember(site, row(), vault.fence(site)); val bytes = memory.rows.toMap()
        val unavailable = CameraRelationshipVault(memory) { throw IllegalStateException("keystore unavailable") }
        assertThrows(IllegalStateException::class.java) { unavailable.read(site) }; assertEquals(bytes, memory.rows)
        assertThrows(IllegalArgumentException::class.java) { vault.read(site.copy(tlsHost = "192.168.1.99")) }
        val slot = memory.rows.keys.single(); memory.rows[slot] = memory.rows[slot]!!.dropLast(4) + "AAAA"
        val corrupt = memory.rows.toMap()
        assertThrows(Exception::class.java) { vault.read(site) }; assertEquals(corrupt, memory.rows)
    }
    @Test fun endpointBudgetNeverEvictsApprovalOrForgetTombstones() {
        val memory = Memory(); val vault = CameraRelationshipVault(memory) { aes }
        for (n in 0 until 64) {
            val selected = site.copy(tlsHost = "fleet-$n.local")
            vault.remember(selected, row().copy(origin = CameraRelationshipVault.origin(selected)), vault.fence(selected))
        }
        val overflow = site.copy(tlsHost = "fleet-overflow.local")
        assertThrows(IllegalArgumentException::class.java) { vault.remember(overflow, row().copy(origin = CameraRelationshipVault.origin(overflow)), vault.fence(overflow)) }
        vault.erase(site.copy(tlsHost = "fleet-0.local")); assertEquals(64, memory.endpointKeys().size)
        assertNotNull(vault.read(site.copy(tlsHost = "fleet-63.local")))
        assertThrows(IllegalArgumentException::class.java) { vault.remember(overflow, row().copy(origin = CameraRelationshipVault.origin(overflow)), vault.fence(overflow)) }
    }
}
