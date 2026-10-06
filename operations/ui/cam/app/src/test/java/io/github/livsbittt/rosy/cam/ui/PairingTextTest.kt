package io.github.livsbittt.rosy.cam.ui

import io.github.livsbittt.rosy.cam.pairing.PairingState
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingTextTest {
    @Test fun onlyTrustOrUnsettledCredentialFailuresUseCriticalAlarm() {
        for (reason in listOf("unreachable", "busy", "rejected")) {
            assertFalse(PairingText.critical(PairingState.Rejected(reason)))
        }
        assertFalse(PairingText.critical(PairingState.Expired("confirm_deadline")))
        for (reason in listOf("fingerprint_mismatch", "leaf_san", "bad_reply")) {
            assertTrue(PairingText.critical(PairingState.Rejected(reason)))
        }
        assertTrue(PairingText.critical(PairingState.Rejected("unreachable", "pending-credential")))
        assertTrue(PairingText.critical(PairingState.Expired("confirm_deadline", "pending-credential")))
    }
}
