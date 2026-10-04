package io.github.livsbittt.rosy.pilot

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import javax.crypto.KeyGenerator

class PeerRelationshipVaultTest {
    private class Memory : PeerVaultStorage {
        val rows = mutableMapOf<String, String>()
        override fun get(id: String) = rows[id]
        override fun endpointKeys() = rows.keys.map { it.removePrefix("fence|") }.toSet()
        override fun write(id: String, value: String, remove: Set<String>) { rows[id] = value; remove.forEach { rows.remove(it) } }
    }
    private val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    private val publicKey = PeerProof.encodeKey(KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair().public)
    private val first = Candidate("robot.local", 8443, listOf("192.168.1.10"), robotId = "rosy_01")
    private fun row(expires: Instant? = null) = PeerRelationship(PeerRelationshipVault.origin(first), "rosy_01", publicKey,
        "pilot_test", "a".repeat(64), "A".repeat(32), "operator", 0, expires == null, expires)
    @Test fun encryptedApprovalSurvivesLongOfflineDhcpAndExpiredLoginIndependently() {
        val memory = Memory(); val vault = PeerRelationshipVault(memory) { key }
        vault.remember(first, row(), vault.fence(first))
        assertFalse(memory.rows.values.joinToString().contains(publicKey))
        val afterReboot = PeerRelationshipVault(memory) { key }
        assertEquals(row(), afterReboot.read(first.copy(addresses = listOf("192.168.1.99"))))
        assertTrue(afterReboot.read(first)!!.validAt(Instant.parse("2099-01-01T00:00:00Z")))
    }
    @Test fun temporaryIssuerExpiryIsRetainedAndCannotBecomeDurable() {
        val memory = Memory(); val vault = PeerRelationshipVault(memory) { key }; val expired = row(Instant.EPOCH)
        vault.remember(first, expired, vault.fence(first)); val bytes = memory.rows.toMap()
        assertFalse(vault.read(first)!!.validAt(Instant.now())); assertEquals(bytes, memory.rows)
        assertThrows(IllegalArgumentException::class.java) { expired.copy(persistent = true) }
    }
    @Test fun forgettingFencesOldCompletionAndOldAddressCannotResurrectAfterNewApproval() {
        val memory = Memory(); val vault = PeerRelationshipVault(memory) { key }; val oldTicket = vault.fence(first)
        vault.remember(first, row(), oldTicket)
        vault.erase(first.copy(addresses = listOf("192.168.1.99")))
        assertNull(vault.read(first)); assertThrows(IllegalArgumentException::class.java) { vault.remember(first, row(), oldTicket) }
        vault.remember(first, row().copy(id = "B".repeat(32)), vault.fence(first))
        assertThrows(IllegalArgumentException::class.java) { vault.remember(first, row(), oldTicket) }
        assertEquals("B".repeat(32), vault.read(first)!!.id)
    }
    @Test fun conflictIdentityOrCryptoFailureNeverDeletesEncryptedApproval() {
        val memory = Memory(); val vault = PeerRelationshipVault(memory) { key }
        vault.remember(first, row(), vault.fence(first)); val bytes = memory.rows.toMap()
        assertThrows(IllegalArgumentException::class.java) { vault.read(first.copy(robotId = "rosy_02")) }
        val locked = PeerRelationshipVault(memory) { throw IllegalStateException("keystore locked") }
        assertThrows(IllegalStateException::class.java) { locked.read(first) }; assertEquals(bytes, memory.rows)
        assertThrows(IllegalArgumentException::class.java) { vault.read(first.copy(secure = false)) }
    }
    @Test fun boundedStorageRetainsExistingRecordsAndForgetFencesInsteadOfEvictingThem() {
        val memory = Memory(); val vault = PeerRelationshipVault(memory) { key }
        for (index in 0 until 64) {
            val endpoint = first.copy(host = "robot-$index.local")
            vault.remember(endpoint, row().copy(origin = PeerRelationshipVault.origin(endpoint)), vault.fence(endpoint))
        }
        val overflow = first.copy(host = "robot-overflow.local")
        assertThrows(IllegalArgumentException::class.java) { vault.remember(overflow, row().copy(origin = PeerRelationshipVault.origin(overflow)), vault.fence(overflow)) }
        val original = first.copy(host = "robot-0.local"); vault.erase(original)
        assertEquals(64, memory.endpointKeys().size)
        assertNotNull(vault.read(first.copy(host = "robot-63.local")))
        assertThrows(IllegalArgumentException::class.java) { vault.remember(overflow, row().copy(origin = PeerRelationshipVault.origin(overflow)), vault.fence(overflow)) }
    }
}
