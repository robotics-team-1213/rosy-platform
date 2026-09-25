package io.github.livsbittt.rosy.overhead.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.wifi.WifiManager
import android.os.Build
import android.os.PowerManager
import android.util.Log
import androidx.camera.core.Preview
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleService
import androidx.lifecycle.lifecycleScope
import io.github.livsbittt.rosy.overhead.BuildConfig
import io.github.livsbittt.rosy.overhead.MainActivity
import io.github.livsbittt.rosy.overhead.R
import io.github.livsbittt.rosy.overhead.camera.CameraController
import io.github.livsbittt.rosy.overhead.link.LinkState
import io.github.livsbittt.rosy.overhead.link.LinkStatus
import io.github.livsbittt.rosy.overhead.link.OverheadConfig
import io.github.livsbittt.rosy.overhead.link.OverheadLink
import io.github.livsbittt.rosy.overhead.settings.SettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Why streaming could not run, apart from link errors (those live in [LinkStatus.error]). */
sealed interface StreamError {
    data object NotPaired : StreamError
    data class Camera(val message: String) : StreamError
    data class ForegroundDenied(val message: String) : StreamError
}

data class StreamState(
    val running: Boolean = false,
    /** "host:port · source" of the current or last session. */
    val target: String? = null,
    val link: LinkStatus = LinkStatus(),
    val error: StreamError? = null,
)

/**
 * Foreground camera service (design section 5) that owns the camera and link for one session.
 * It must be started while the activity is visible (Android 14 while-in-use rule for camera
 * foreground services). Holds a partial wake lock and a Wi-Fi lock so power saving does not
 * add latency spikes. Close 4400/4409 or a camera failure end the session.
 */
class StreamService : LifecycleService() {
    private var link: OverheadLink? = null
    private var camera: CameraController? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var sessionActive = false

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        super.onStartCommand(intent, flags, startId)
        when (intent?.action) {
            ACTION_START -> {
                if (!enterForeground()) return START_NOT_STICKY
                if (!sessionActive) beginSession()
            }
            ACTION_STOP -> endSession()
            else -> if (!sessionActive) stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        releaseSession()
        super.onDestroy()
    }

    private fun enterForeground(): Boolean {
        ensureChannel()
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
        } else {
            0
        }
        return try {
            ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(LinkState.CONNECTING), type)
            true
        } catch (e: RuntimeException) {
            // ForegroundServiceStartNotAllowedException or SecurityException (camera permission missing).
            Log.e(TAG, "startForeground refused", e)
            _state.value = StreamState(error = StreamError.ForegroundDenied(e.message ?: e.javaClass.simpleName))
            stopSelf()
            false
        }
    }

    private fun beginSession() {
        sessionActive = true
        _state.value = StreamState(running = true)
        lifecycleScope.launch {
            val pairing = SettingsStore(applicationContext).pairing.first()
            if (pairing == null) {
                _state.value = StreamState(error = StreamError.NotPaired)
                endSession()
                return@launch
            }
            if (!sessionActive) return@launch
            acquireLocks()
            val newLink = OverheadLink(pairing, BuildConfig.VERSION_NAME, "${Build.MANUFACTURER} ${Build.MODEL}")
            val newCamera = CameraController(this@StreamService, this@StreamService, newLink) { e ->
                _state.update { it.copy(error = StreamError.Camera(e.message ?: e.javaClass.simpleName)) }
                endSession()
            }
            link = newLink
            camera = newCamera
            _state.update { it.copy(target = "${pairing.host}:${pairing.port} · ${pairing.source}") }
            newLink.start()
            newCamera.start(OverheadConfig.DEFAULT)

            launch { previewSurface.collect { newCamera.setPreviewSurface(it) } }
            launch {
                newLink.status.map { it.config }.distinctUntilChanged().collect { newCamera.applyConfig(it) }
            }
            launch {
                newLink.status.map { it.state }.distinctUntilChanged().collect { updateNotification(it) }
            }
            launch {
                newLink.status.collect { status ->
                    _state.update { it.copy(link = status) }
                    if (status.stopped) endSession()
                }
            }
        }
    }

    /** Ends the session, keeps the last status and error for the UI, and stops the service. */
    private fun endSession() {
        releaseSession()
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun releaseSession() {
        if (!sessionActive) return
        sessionActive = false
        camera?.stop()
        camera = null
        val lastLink = link
        link = null
        lastLink?.stop()
        wakeLock?.takeIf { it.isHeld }?.release()
        wakeLock = null
        wifiLock?.takeIf { it.isHeld }?.release()
        wifiLock = null
        _state.update { current ->
            current.copy(running = false, link = lastLink?.status?.value ?: current.link)
        }
    }

    private fun acquireLocks() {
        val power = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "rosy-overhead:stream").apply {
            setReferenceCounted(false)
            acquire()
        }
        val wifi = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            WifiManager.WIFI_MODE_FULL_LOW_LATENCY
        } else {
            @Suppress("DEPRECATION")
            WifiManager.WIFI_MODE_FULL_HIGH_PERF
        }
        wifiLock = wifi.createWifiLock(mode, "rosy-overhead:stream").apply {
            setReferenceCounted(false)
            acquire()
        }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(CHANNEL_ID, getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW)
        manager.createNotificationChannel(channel)
    }

    private fun buildNotification(linkState: LinkState): Notification {
        val openApp = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stop = PendingIntent.getService(
            this,
            1,
            Intent(this, StreamService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val text = when (linkState) {
            LinkState.STREAMING -> R.string.state_streaming
            LinkState.CONNECTING -> R.string.state_connecting
            LinkState.DISCONNECTED -> R.string.state_disconnected
        }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_camera)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(text))
            .setContentIntent(openApp)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .addAction(0, getString(R.string.action_stop), stop)
            .build()
    }

    private fun updateNotification(linkState: LinkState) {
        if (!sessionActive) return
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, buildNotification(linkState))
    }

    companion object {
        private const val TAG = "StreamService"
        private const val CHANNEL_ID = "stream"
        private const val NOTIFICATION_ID = 1
        const val ACTION_START = "io.github.livsbittt.rosy.overhead.action.START"
        const val ACTION_STOP = "io.github.livsbittt.rosy.overhead.action.STOP"

        private val _state = MutableStateFlow(StreamState())

        /** Process-wide session state for the UI. */
        val state: StateFlow<StreamState> = _state.asStateFlow()

        /** Preview surface of the visible screen; null while the activity is stopped. */
        val previewSurface = MutableStateFlow<Preview.SurfaceProvider?>(null)

        /** Call only from a visible activity after CAMERA is granted. */
        fun start(context: Context) {
            ContextCompat.startForegroundService(
                context,
                Intent(context, StreamService::class.java).setAction(ACTION_START),
            )
        }

        fun stop(context: Context) {
            context.startService(Intent(context, StreamService::class.java).setAction(ACTION_STOP))
        }
    }
}
