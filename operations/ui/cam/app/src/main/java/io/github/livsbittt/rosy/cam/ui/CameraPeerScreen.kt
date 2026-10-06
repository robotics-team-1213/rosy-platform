package io.github.livsbittt.rosy.cam.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import io.github.livsbittt.rosy.cam.pairing.PairableSite
import io.github.livsbittt.rosy.cam.pairing.peer.CameraPeerState
import io.github.livsbittt.rosy.cam.settings.OverheadServerDiscovery
import io.github.livsbittt.rosy.cam.settings.OverheadServiceRecord

/** LAN list is the normal entry; manual/deep-link settings remain explicit compatibility actions. */
@Composable
fun CameraLanScreen(onSelect: (OverheadServiceRecord) -> Unit, onSettings: () -> Unit, onCurrent: (() -> Unit)?,
    remembered: List<PairableSite>, onRemembered: (PairableSite) -> Unit) {
    val context = LocalContext.current
    var records by remember { mutableStateOf(emptyList<OverheadServiceRecord>()) }
    var scanning by remember { mutableStateOf(true) }
    var wifi by remember { mutableStateOf(false) }
    var scan by remember { mutableIntStateOf(0) }
    DisposableEffect(scan) {
        val discovery = OverheadServerDiscovery(context) { found, _, busy, connected -> records = found; scanning = busy; wifi = connected }
        discovery.start(); onDispose { discovery.stop() }
    }
    Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("영상 받을 기기", style = MaterialTheme.typography.headlineSmall)
        Text("같은 Wi-Fi의 기기를 선택하세요. 처음 연결할 때만 상대 화면에서 승인합니다.")
        if (!wifi) Text("Wi-Fi에 연결한 뒤 다시 찾으세요.")
        else if (records.isEmpty()) Text(if (scanning) "기기를 찾고 있습니다…" else "발견한 기기가 없습니다. 상대 기기의 연결 화면을 확인하세요.")
        records.forEach { record ->
            val conflict = records.any { it !== record && it.tlsHost == record.tlsHost && it.port == record.port && it.address != record.address }
            OutlinedButton(onClick = { onSelect(record) }, enabled = !conflict && record.address != null && (record.peerApproval || record.pairable), modifier = Modifier.fillMaxWidth()) {
                Column { Text(record.name); Text(record.tlsHost); if (conflict) Text("같은 이름의 주소가 충돌합니다.") }
            }
        }
        remembered.filter { saved -> records.none { it.tlsHost == saved.tlsHost && it.port == saved.port } }.forEach { saved ->
            OutlinedButton(onClick = { onRemembered(saved) }, modifier = Modifier.fillMaxWidth()) {
                Column { Text(saved.tlsHost); Text("승인 기록 유지 · 다시 연결 확인") }
            }
        }
        OutlinedButton(onClick = { records = emptyList(); scan++ }, modifier = Modifier.fillMaxWidth()) { Text("다시 찾기") }
        onCurrent?.let { TextButton(onClick = it, modifier = Modifier.fillMaxWidth()) { Text("연결 기록 · 촬영 화면") } }
        TextButton(onClick = onSettings, modifier = Modifier.fillMaxWidth()) { Text("기존 연결 · 수동 설정") }
    }
}

@Composable
fun CameraPeerScreen(state: CameraPeerState, onCertificate: (Boolean) -> Unit, onCancel: () -> Unit,
    onRetry: (PairableSite) -> Unit, onDone: () -> Unit, onForget: (PairableSite) -> Unit) {
    var forgetting by remember { mutableStateOf<PairableSite?>(null) }
    Column(Modifier.fillMaxSize().safeDrawingPadding().verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("기기 연결", style = MaterialTheme.typography.headlineSmall)
        when (state) {
            is CameraPeerState.Connecting -> { Text(state.site.serviceName); Text("연결을 확인하고 있습니다…") }
            is CameraPeerState.Pending -> {
                Text(state.site.serviceName); Text(state.pending.code, style = MaterialTheme.typography.displaySmall)
                Text("상대 화면에서 이 요청을 승인하세요. 이 표시는 요청을 찾는 용도이며 인증서 확인 값이 아닙니다.")
            }
            is CameraPeerState.Certificate -> {
                Text(state.site.serviceName); Text("상대 기기의 연결 화면에 표시된 인증서 확인 값과 같을 때만 연결하세요.")
                Text(state.offer.sha256.chunked(8).joinToString(" "))
                Button(onClick = { onCertificate(true) }, modifier = Modifier.fillMaxWidth()) { Text("같은 값 · 연결") }
                OutlinedButton(onClick = { onCertificate(false) }, modifier = Modifier.fillMaxWidth()) { Text("다른 값 · 중단") }
            }
            is CameraPeerState.Connected -> {
                Text("연결 기록을 저장했습니다. 촬영은 시작 버튼을 눌러 시작합니다.")
                Button(onClick = onDone, modifier = Modifier.fillMaxWidth()) { Text("촬영 화면") }
                TextButton(onClick = { forgetting = state.site }, modifier = Modifier.fillMaxWidth()) { Text("이 앱의 연결 기록 지우기") }
            }
            is CameraPeerState.Failed -> {
                Text(state.site.serviceName); Text("연결을 확인할 수 없습니다. 상대 기기의 승인 상태와 Wi-Fi를 확인하고 다시 시도하세요.")
                if (state.retained) Text("이 앱의 승인 기록은 유지했습니다. 상대가 연결을 해제했다면 새 승인이 필요합니다.")
                Button(onClick = { onRetry(state.site) }, modifier = Modifier.fillMaxWidth()) { Text("다시 연결") }
                TextButton(onClick = { forgetting = state.site }, modifier = Modifier.fillMaxWidth()) { Text("이 앱의 연결 기록 지우기") }
            }
            is CameraPeerState.Forgetting -> Text("이 앱의 연결 기록을 지우고 있습니다…")
            CameraPeerState.Idle -> Unit
        }
        TextButton(onClick = onCancel, enabled = state !is CameraPeerState.Forgetting, modifier = Modifier.fillMaxWidth()) { Text("목록으로") }
    }
    forgetting?.let { site -> AlertDialog(onDismissRequest = { forgetting = null }, title = { Text("이 앱의 연결 기록 지우기") },
        text = { Text("${site.serviceName}\n${site.tlsHost}\n이 앱에 저장한 연결만 지웁니다. 상대 기기의 승인을 해제하지는 않습니다.") },
        confirmButton = { TextButton(onClick = { forgetting = null; onForget(site) }) { Text("기록 지우기") } },
        dismissButton = { TextButton(onClick = { forgetting = null }) { Text("유지") } }) }
}
