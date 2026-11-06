package io.github.livsbittt.rosy.cam.service

import android.Manifest
import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.core.content.ContextCompat
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/** D-981: reopen the link only for a paired phone that may use the camera and is not already streaming. */
internal fun shouldAutoStart(paired: Boolean, cameraGranted: Boolean, running: Boolean): Boolean =
    paired && cameraGranted && !running

/** D-981: after a boot or an app update, reopen the link so the next D-691 `demand` reaches the phone. */
class AutoStartReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED && intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        val app = context.applicationContext
        WirelessDebugging.keepOn(app)
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val camera = ContextCompat.checkSelfPermission(app, Manifest.permission.CAMERA) ==
                    PackageManager.PERMISSION_GRANTED
                val paired = SettingsStore(app).siteLink.first() != null
                if (shouldAutoStart(paired, camera, StreamService.state.value.running)) {
                    // Needs the SYSTEM_ALERT_WINDOW app-op from `rosy_cam_screen.py auto-wake-setup`; without it Android drops this.
                    app.startActivity(Intent(app, AutoStartActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                }
            } finally {
                pending.finish()
            }
        }
    }
}

/**
 * The visible moment the Android 14 while-in-use rule asks of a camera service. It is not exported and draws
 * nothing, so the lock screen shows no app screen; it never dismisses the keyguard.
 */
class AutoStartActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        }
    }

    override fun onResume() {
        super.onResume()
        StreamService.start(this)
        finish()
    }
}

/** Android drops wireless debugging on a Wi-Fi change; the site timer's ADB recovery needs it back. */
object WirelessDebugging {
    private const val ADB_WIFI_ENABLED = "adb_wifi_enabled"

    /** Works only after `auto-wake-setup` granted WRITE_SECURE_SETTINGS; pairing keys still gate every ADB peer. */
    fun keepOn(context: Context) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.WRITE_SECURE_SETTINGS) !=
            PackageManager.PERMISSION_GRANTED
        ) return
        runCatching {
            if (Settings.Global.getInt(context.contentResolver, ADB_WIFI_ENABLED, 0) != 1) {
                Settings.Global.putInt(context.contentResolver, ADB_WIFI_ENABLED, 1)
            }
        }
    }
}
