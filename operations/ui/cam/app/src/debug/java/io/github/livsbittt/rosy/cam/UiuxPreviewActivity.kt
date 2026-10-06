package io.github.livsbittt.rosy.cam

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.pairing.PairingState
import io.github.livsbittt.rosy.cam.pairing.peer.CameraCaOffer
import io.github.livsbittt.rosy.cam.pairing.peer.CameraPeerState
import io.github.livsbittt.rosy.cam.pairing.peer.CameraPending
import io.github.livsbittt.rosy.cam.ui.CameraPeerScreen
import io.github.livsbittt.rosy.cam.ui.PairingScreen
import io.github.livsbittt.rosy.cam.ui.RosyTheme
import java.time.Instant

/** Synthetic G2 screenshots only. No network, credential storage, or stream controls. */
class UiuxPreviewActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val site = PairableSite("Demo receiver", "demo.local", 443)
        val state = intent.getStringExtra("state") ?: "pair-fingerprint"
        setContent {
            RosyTheme {
                when (state) {
                    "pair-requested" -> PairingScreen(site, PairingState.Requested(site, "demo", "123456", ""), false, {}, {}, {}, {})
                    "pair-fingerprint" -> PairingScreen(site, PairingState.ConfirmFingerprint(site, "Demo receiver", "ceiling_demo", "ABCD-EF12-3456-7890", "demo-credential", ""), false, {}, {}, {}, {})
                    "pair-rejected" -> PairingScreen(site, PairingState.Rejected("unreachable"), false, {}, {}, {}, {})
                    "peer-pending" -> CameraPeerScreen(CameraPeerState.Pending(site, CameraPending("123456", "fleet_demo", Instant.now())), {}, {}, {}, {}, {})
                    "peer-certificate" -> CameraPeerScreen(CameraPeerState.Certificate(site, CameraCaOffer("", "A".repeat(64), "demo.local")), {}, {}, {}, {}, {})
                    "peer-failed" -> CameraPeerScreen(CameraPeerState.Failed(site, false), {}, {}, {}, {}, {})
                    else -> finish()
                }
            }
        }
    }
}
