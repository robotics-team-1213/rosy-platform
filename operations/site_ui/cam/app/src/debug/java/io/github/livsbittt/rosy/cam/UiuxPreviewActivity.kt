package io.github.livsbittt.rosy.cam

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.pairing.PairingState
import io.github.livsbittt.rosy.cam.pairing.peer.CameraCaOffer
import io.github.livsbittt.rosy.cam.pairing.peer.CameraPeerState
import io.github.livsbittt.rosy.cam.pairing.peer.CameraPending
import io.github.livsbittt.rosy.cam.ui.CamAppBar
import io.github.livsbittt.rosy.cam.ui.CamBar
import io.github.livsbittt.rosy.cam.ui.CamPath
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
                Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).safeDrawingPadding()) {
                    CamAppBar(CamBar(site.serviceName, R.string.state_stopped))
                    CamPath(stringResource(if (state.startsWith("pair-")) R.string.pairing_title else R.string.peer_title))
                    when (state) {
                        "pair-requested" -> PairingScreen(site, PairingState.Requested(site, "demo", "123456", ""), false, {}, {}, {}, {})
                        "pair-fingerprint" -> PairingScreen(site, PairingState.ConfirmFingerprint(site, "Demo receiver", "ceiling_demo", "ABCD-EF12-3456-7890", "demo-credential", ""), false, {}, {}, {}, {})
                        "pair-rejected" -> PairingScreen(site, PairingState.Rejected(intent.getStringExtra("reason") ?: "unreachable"), false, {}, {}, {}, {})
                        "peer-pending" -> CameraPeerScreen(CameraPeerState.Pending(site, CameraPending("123456", "fleet_demo", Instant.now())), {}, {}, {}, {}, {})
                        "peer-certificate" -> CameraPeerScreen(CameraPeerState.Certificate(site, CameraCaOffer("", "A".repeat(64), "demo.local")), {}, {}, {}, {}, {})
                        "peer-failed" -> CameraPeerScreen(CameraPeerState.Failed(site, false), {}, {}, {}, {}, {})
                        else -> finish()
                    }
                }
            }
        }
    }
}
