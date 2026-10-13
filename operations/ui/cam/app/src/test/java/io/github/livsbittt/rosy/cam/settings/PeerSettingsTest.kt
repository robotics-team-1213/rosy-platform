package io.github.livsbittt.rosy.cam.settings

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import io.github.livsbittt.rosy.cam.pairing.peer.CameraConnection
import io.github.livsbittt.rosy.cam.pairing.peer.CameraProof
import io.github.livsbittt.rosy.cam.pairing.peer.CameraRelationship
import java.io.File
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import okhttp3.tls.HeldCertificate
import org.junit.Assert.*
import org.junit.Test

class PeerSettingsTest {
    @Test fun markedCredentialCannotBecomeLegacyWithoutItsBinding() {
        val link = SiteLink("fixture", "site.local", 8443, "sha256/" + "A".repeat(43), "fixture-camera-token", "ceiling_north", true,
            credentialId = "cam-peer-" + "C".repeat(24))
        val owner = io.github.livsbittt.rosy.cam.pairing.peer.CameraPeerManager
        assertThrows(io.github.livsbittt.rosy.cam.link.CredentialDenied::class.java) { owner.requiredRelationship(link, null) }
        assertThrows(io.github.livsbittt.rosy.cam.link.CredentialDenied::class.java) { owner.requiredRelationship(link, "malformed") }
        assertThrows(io.github.livsbittt.rosy.cam.link.CredentialDenied::class.java) { owner.requiredRelationship(null, "A".repeat(32)) }
        assertEquals("A".repeat(32), owner.requiredRelationship(link, "A".repeat(32)))
        assertNull(owner.requiredRelationship(link.copy(credentialId = "cred-legacy"), null))
    }
    @Test fun legacyRollbackPreservesRememberedProofBinding() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val file = File(System.getProperty("java.io.tmpdir"), UUID.randomUUID().toString() + ".preferences_pb")
        val settings = SettingsStore(PreferenceDataStoreFactory.create(scope = scope) { file })
        try {
            val original = SiteLink("fixture", "site.local", 8443, "sha256/" + "A".repeat(43), "fixture-camera-token", "ceiling_north", true,
                credentialId = "cam-peer-" + "C".repeat(24))
            val accepted = approval(original); settings.installPeer(accepted, settings.peerSnapshot()) { true }
            val legacy = original.copy(token = "legacy-camera-token", credentialId = null)
            val previous = settings.replace(legacy)
            settings.restore(previous, legacy)
            assertEquals(original, settings.peerSnapshot().link)
            assertEquals(accepted.relationship.id, settings.peerSnapshot().relationshipId)
        } finally { scope.cancel() }
    }
    @Test fun legacyRollbackCannotUndoNewerSameValueChoice() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val file = File(System.getProperty("java.io.tmpdir"), UUID.randomUUID().toString() + ".preferences_pb")
        val settings = SettingsStore(PreferenceDataStoreFactory.create(scope = scope) { file })
        try {
            val original = SiteLink("fixture", "site.local", 8443, "sha256/" + "A".repeat(43), "fixture-camera-token", "ceiling_north", true,
                credentialId = "cam-peer-" + "C".repeat(24))
            settings.installPeer(approval(original), settings.peerSnapshot()) { true }
            val legacy = original.copy(token = "legacy-camera-token", credentialId = null)
            val previous = settings.replace(legacy)
            settings.save(legacy.toPairing())
            assertEquals(legacy, settings.peerSnapshot().link)
            settings.restore(previous, legacy)
            assertEquals(legacy, settings.peerSnapshot().link); assertNull(settings.peerSnapshot().relationshipId)
        } finally { scope.cancel() }
    }
    private fun approval(link: SiteLink): CameraConnection {
        val keys = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
        val public = CameraProof.encodeKey(keys.public)
        val ca = HeldCertificate.Builder().certificateAuthority(0).commonName("fixture").build()
        val relationship = CameraRelationship("https://site.local:8443", "fleet-" + CameraProof.fingerprint(public).take(32), public,
            "cam_fixture", CameraProof.fingerprint(public), "A".repeat(32), 0, link.source, true, null, ca.certificatePem())
        return CameraConnection(link, relationship, "0")
    }
    @Test fun newerManualWriteIncludingSameValueFencesOldCredentialCommit() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val file = File(System.getProperty("java.io.tmpdir"), UUID.randomUUID().toString() + ".preferences_pb")
        val settings = SettingsStore(PreferenceDataStoreFactory.create(scope = scope) { file })
        try {
            val original = SiteLink("fixture", "site.local", 8443, "sha256/" + "A".repeat(43), "fixture-camera-token", "ceiling_north", true)
            settings.replace(original); val selected = settings.peerSnapshot()
            settings.replace(original)
            val outcome = runCatching { settings.installPeer(approval(original.copy(token = "late-camera-token")), selected) { true } }
            assertTrue(outcome.isFailure); assertEquals(original, settings.peerSnapshot().link)
            assertNull(settings.peerSnapshot().relationshipId)
        } finally { scope.cancel() }
    }
    @Test fun localForgetClearsOnlyOwnedCredentialAndLateCompletionCannotResurrect() = runBlocking {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val file = File(System.getProperty("java.io.tmpdir"), UUID.randomUUID().toString() + ".preferences_pb")
        val settings = SettingsStore(PreferenceDataStoreFactory.create(scope = scope) { file })
        try {
            val link = SiteLink("fixture", "site.local", 8443, "sha256/" + "A".repeat(43), "fixture-camera-token", "ceiling_north", true,
                expiresAt = Instant.now().plusSeconds(3600).toString())
            settings.installPeer(approval(link), settings.peerSnapshot()) { true }
            val pending = settings.peerSnapshot()
            settings.forgetPeer("https://other.local:8443"); assertEquals(link, settings.peerSnapshot().link)
            settings.forgetPeer("https://site.local:8443"); assertNull(settings.peerSnapshot().link)
            assertTrue(runCatching { settings.installPeer(approval(link), pending) { true } }.isFailure)
            assertNull(settings.peerSnapshot().link)
        } finally { scope.cancel() }
    }
}
