package io.github.livsbittt.rosy.cam.service

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
import io.github.livsbittt.rosy.cam.BuildConfig
import io.github.livsbittt.rosy.cam.MainActivity
import io.github.livsbittt.rosy.cam.R
import io.github.livsbittt.rosy.cam.camera.CameraController
import io.github.livsbittt.rosy.cam.health.DeviceHealth
import io.github.livsbittt.rosy.cam.health.DeviceHealthMonitor
import io.github.livsbittt.rosy.cam.health.HealthText
import io.github.livsbittt.rosy.cam.link.LinkState
import io.github.livsbittt.rosy.cam.link.LinkStatus
import io.github.livsbittt.rosy.cam.link.OverheadConfig
import io.github.livsbittt.rosy.cam.link.OverheadLink
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.distinctUntilChangedBy
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
    val previewOnly: Boolean = false,
    /** "host:port · source" of the current or last session. */
    val target: String? = null,
    val link: LinkStatus = LinkStatus(),
    val error: StreamError? = null,
    /** Battery and heat while a session runs; null when stopped. */
    val health: DeviceHealth? = null,
)

/**
 * Foreground camera service (design section 5) that owns the camera and link for one session.
 * CameraX is bound to this service's lifecycle, not the activity's, so capture continues with
 * the screen off or locked; only the preview surface follows the activity (verified on a
 * Galaxy S21, Android 15, 2026-09-30: locked, dozing and forced deep idle kept 3 fps).
 * It must be started while the activity is visible (Android 14 while-in-use rule for camera
 * foreground services). Holds a partial wake lock and a Wi-Fi lock so power saving does not
 * add latency spikes. Close 4400/4409 or a camera failure end the session.
 */
class StreamService : LifecycleService() {
    private var link: OverheadLink? = null
    private var camera: CameraController? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var healthMonitor: DeviceHealthMonitor? = null
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
            val plan = CameraSessionPlan.from(pairing)
            if (!sessionActive) return@launch
            acquireLocks()
            val monitor = DeviceHealthMonitor(this@StreamService).also { it.start() }
            healthMonitor = monitor
            // Battery temperature moves in tenths; the notification only follows whole degrees.
            val notificationHealth = monitor.health.distinctUntilChangedBy { it?.notificationKey }
            launch { monitor.health.collect { h -> _state.update { it.copy(health = h) } } }
            val newLink = if (plan.sendFrames && pairing != null) {
                OverheadLink(pairing, BuildConfig.VERSION_NAME, "${Build.MANUFACTURER} ${Build.MODEL}")
            } else null
            val newCamera = CameraController(this@StreamService, this@StreamService, newLink) { e ->
                _state.update { it.copy(error = StreamError.Camera(e.message ?: e.javaClass.simpleName)) }
                endSession()
            }
            link = newLink
            camera = newCamera
            _state.update {
                it.copy(
                    target = pairing?.let { p -> "${p.host}:${p.port} · ${p.source}" },
                    previewOnly = !plan.sendFrames,
                )
            }
            if (!plan.sendFrames) {
                launch { notificationHealth.collect { updateNotification(LinkState.DISCONNECTED, previewOnly = true, health = it) } }
            }
            newLink?.start()
            newCamera.start(OverheadConfig.DEFAULT)

            launch { previewSurface.collect { newCamera.setPreviewSurface(it) } }
            newLink?.let { activeLink ->
                launch {
                    activeLink.status.map { it.config }.distinctUntilChanged().collect { newCamera.applyConfig(it) }
                }
                launch {
                    activeLink.status.map { it.state }.distinctUntilChanged()
                        .combine(notificationHealth) { linkState, health -> linkState to health }
                        .collect { (linkState, health) -> updateNotification(linkState, health = health) }
                }
                launch {
                    activeLink.status.collect { status ->
                        _state.update { it.copy(link = status) }
                        if (status.stopped) endSession()
                    }
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
        healthMonitor?.stop()
        healthMonitor = null
        _state.update { current ->
            current.copy(running = false, previewOnly = false, health = null, link = lastLink?.status?.value ?: current.link)
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

    private fun buildNotification(linkState: LinkState, previewOnly: Boolean = false, health: DeviceHealth? = null): Notification {
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
        val text = if (previewOnly) R.string.state_preview_only else when (linkState) {
            LinkState.STREAMING -> R.string.state_streaming
            LinkState.CONNECTING -> R.string.state_connecting
            LinkState.DISCONNECTED -> R.string.state_disconnected
        }
        // Warnings first: the collapsed notification shows one line.
        val lines = buildList {
            health?.let { h -> h.warnings.forEach { add(HealthText.warning(resources, it, h)) } }
            add(getString(text))
            health?.let { add(HealthText.line(resources, it)) }
        }
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_camera)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(lines.first())
            .setStyle(NotificationCompat.BigTextStyle().bigText(lines.joinToString("\n")))
            .setContentIntent(openApp)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .addAction(0, getString(R.string.action_stop), stop)
            .build()
    }

    private fun updateNotification(linkState: LinkState, previewOnly: Boolean = false, health: DeviceHealth? = null) {
        if (!sessionActive) return
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, buildNotification(linkState, previewOnly, health))
    }

    companion object {
        private const val TAG = "StreamService"
        private const val CHANNEL_ID = "stream"
        private const val NOTIFICATION_ID = 1
        const val ACTION_START = "io.github.livsbittt.rosy.cam.action.START"
        const val ACTION_STOP = "io.github.livsbittt.rosy.cam.action.STOP"

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
