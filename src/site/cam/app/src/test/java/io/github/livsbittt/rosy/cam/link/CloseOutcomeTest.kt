package io.github.livsbittt.rosy.cam.link

import io.github.livsbittt.rosy.cam.Vectors
import io.github.livsbittt.rosy.cam.ui.NextStep
import io.github.livsbittt.rosy.cam.ui.Problem
import io.github.livsbittt.rosy.cam.ui.ProblemGuide
import org.junit.Assert.assertEquals
import org.junit.Test

/** One table for every server close the camera knows: error, stop-or-retry, and whether it asks to re-pair. */
class CloseOutcomeTest {
    private data class Row(
        val code: Int,
        val reason: String,
        val error: LinkError,
        val fatal: Boolean,
        val problem: Problem,
        val step: NextStep,
    )

    private val rows = listOf(
        Row(4400, "proto must be 'rosy-overhead/1'", LinkError.ProtocolMismatch, true, Problem.PROTOCOL_MISMATCH, NextStep.NONE),
        Row(4400, "no hello", LinkError.Busy(4400, "no hello"), false, Problem.BUSY, NextStep.NONE),
        Row(4400, "", LinkError.Busy(4400, ""), false, Problem.BUSY, NextStep.NONE),
        Row(1013, "busy", LinkError.Busy(1013, "busy"), false, Problem.BUSY, NextStep.NONE),
        Row(4503, "credential state unknown", LinkError.CredentialUnknown, false, Problem.SITE_CHECKING, NextStep.NONE),
        Row(4401, "token is not authorized for source", LinkError.Unauthorized, true, Problem.UNAUTHORIZED, NextStep.OPEN_SETTINGS),
        Row(4409, "replaced by new connection", LinkError.Replaced, true, Problem.REPLACED, NextStep.OPEN_SETTINGS),
    )

    @Test
    fun everyKnownCloseMapsToItsOutcome() {
        for (row in rows) {
            val label = "close ${row.code} '${row.reason}'"
            val (error, fatal) = OverheadLink.closeOutcome(row.code, row.reason)
            assertEquals(label, row.error, error)
            assertEquals(label, row.fatal, fatal)
            val guidance = ProblemGuide.forLink(error, stopped = fatal, wifiConnected = true)
            assertEquals(label, row.problem, guidance.problem)
            // OPEN_SETTINGS is the re-pair prompt: only final credential or name problems show it.
            assertEquals(label, row.step, guidance.step)
            assertEquals(label, !row.fatal, guidance.retrying)
        }
    }

    @Test
    fun credentialUnknownCodeMatchesTheSharedVectors() {
        assertEquals(Vectors.root.getJSONObject("close_codes").getInt("credential_unknown"), Protocol.CLOSE_CREDENTIAL_UNKNOWN)
    }
}
