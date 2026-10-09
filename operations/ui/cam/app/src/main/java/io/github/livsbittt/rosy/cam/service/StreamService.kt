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
import io.github.livsbittt.rosy.cam.camera.ExposureStatus
import io.github.livsbittt.rosy.cam.camera.LightingStatus
import io.github.livsbittt.rosy.cam.camera.LensChoice
import io.github.livsbittt.rosy.cam.camera.LensPick
import io.github.livsbittt.rosy.cam.camera.LensProbe
import io.github.livsbittt.rosy.cam.camera.LensSelector
import io.github.livsbittt.rosy.cam.camera.TuningStatus
import io.github.livsbittt.rosy.cam.health.DeviceHealth
import io.github.livsbittt.rosy.cam.health.DeviceHealthMonitor
import io.github.livsbittt.rosy.cam.health.HealthText
import io.github.livsbittt.rosy.cam.link.LinkState
import io.github.livsbittt.rosy.cam.link.LinkStatus
import io.github.livsbittt.rosy.cam.link.OverheadConfig
import io.github.livsbittt.rosy.cam.link.OverheadLink
import io.github.livsbittt.rosy.cam.pairing.peer.CameraPeerManager
import io.github.livsbittt.rosy.cam.pairing.peer.CameraCredentialProvider
import io.github.livsbittt.rosy.cam.link.SiteResolver
import io.github.livsbittt.rosy.cam.link.SiteRoute
import io.github.livsbittt.rosy.cam.settings.NsdSiteBrowser
import io.github.livsbittt.rosy.cam.settings.SettingsStore
import io.github.livsbittt.rosy.cam.ui.LensText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.distinctUntilChangedBy
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import java.time.Instant
import java.io.FileDescriptor
import java.io.PrintWriter

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
    /** Lens in use while a session runs; null when stopped or when no back camera was found. */
    val lens: LensPick? = null,
    /** True when this phone has a back camera wider than the default one. */
    val wideAvailable: Boolean = false,
    /** The last live lens change failed and the previous lens is still streaming. */
    val lensSwitchFailed: Boolean = false,
    /** How the last connect reached the site (mDNS, "수동 주소", not found); null before the first lookup. */
    val route: SiteRoute? = null,
    val lighting: LightingStatus = LightingStatus(),
    val exposure: ExposureStatus = ExposureStatus(),
    /** D-589: who sets the camera now (Vision, local, off, heat hold) and what it runs with. */
    val tuning: TuningStatus = TuningStatus(),
    val photoSaving: Boolean = false,
    val photoName: String? = null,
    val photoFailed: Boolean = false,
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

    override fun onCreate() {
        super.onCreate()
        activeService = this
    }

    /** Parent of every collector of one session; cancelled when the session is released. */
    private var sessionJob: Job? = null

    // Last notification inputs, so a lens change can redraw it without waiting for the link.
    private var shownLinkState = LinkState.CONNECTING
    private var shownPreviewOnly = false
    private var shownHealth: DeviceHealth? = null

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
        if (activeService === this) activeService = null
        super.onDestroy()
    }

    /** Shell diagnostics expose observed camera state, never the site link or credentials. */
    override fun dump(fd: FileDescriptor, writer: PrintWriter, args: Array<out String>) {
        val current = _state.value
        val light = current.lighting
        writer.println("rosy_cam_state={\"running\":${current.running},\"light_supported\":${light.supported}," +
            "\"light_requested\":${light.requested},\"torch_on\":${light.torchOn},\"dark\":${light.dark}," +
            "\"light_limited\":${light.message != null},\"photo_saving\":${current.photoSaving}," +
            "\"photo_saved\":${current.photoName != null},\"photo_failed\":${current.photoFailed}}")
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
        sessionJob = lifecycleScope.launch {
            val store = SettingsStore(applicationContext)
            val siteLink = store.siteLink.first()
            val development = store.development.first()
            if (development != null && siteLink != null) {
                val expiry = minOf(development.expiresAt, Instant.parse(siteLink.expiresAt))
                launch {
                    delay(java.time.Duration.between(Instant.now(), expiry).toMillis().coerceAtLeast(0))
                    try { store.revokeDevelopment() } finally { endSession() }
                }
            }
            val pairing = siteLink?.toPairing()
            // D-391 1: the site's address is looked up on every (re)connect, never taken from the saved record.
            val resolver = siteLink?.let { SiteResolver(it, NsdSiteBrowser(applicationContext)) }
            val peer = store.peerSnapshot()
            if (peer.link != siteLink) { endSession(); return@launch }
            val relationship = try { CameraPeerManager.requiredRelationship(siteLink, peer.relationshipId) }
                catch (_: io.github.livsbittt.rosy.cam.link.CredentialDenied) {
                    _state.update { it.copy(link = io.github.livsbittt.rosy.cam.link.LinkStatus(error = io.github.livsbittt.rosy.cam.link.LinkError.Unauthorized, stopped = true)) }
                    endSession(); return@launch
                }
            val renewal = if (siteLink != null && resolver != null && relationship != null)
                CameraCredentialProvider(CameraPeerManager(applicationContext), siteLink, relationship, resolver) else null
            val plan = CameraSessionPlan.from(pairing)
            val backCameras = try {
                LensProbe.backCameras(applicationContext)
            } catch (e: Exception) {
                Log.w(TAG, "lens probe failed; binding the default back camera", e)
                emptyList()
            }
            val lensSetting = LensChoice.orDefault(store.lens.first())
            val pick = LensSelector.pick(backCameras, lensSetting)
            pick?.let { Log.i(TAG, "lens ${lensSetting.wire} -> ${it.kind.wire} ${LensProbe.describe(it.camera)} fellBack=${it.fellBack}") }
            if (!sessionActive) return@launch
            acquireLocks()
            val monitor = DeviceHealthMonitor(this@StreamService).also { it.start() }
            healthMonitor = monitor
            // Battery temperature moves in tenths; the notification only follows whole degrees.
            val notificationHealth = monitor.health.distinctUntilChangedBy { it?.notificationKey }
            launch { monitor.health.collect { h -> _state.update { it.copy(health = h) } } }
            val newLink = if (plan.sendFrames && pairing != null) {
                OverheadLink(pairing, BuildConfig.VERSION_NAME, "${Build.MANUFACTURER} ${Build.MODEL}", resolver, credentialProvider = renewal)
                    .also { it.lens = LensSelector.helloLens(pick) }
            } else null
            if (newLink != null && resolver != null && siteLink != null) {
                launch { resolver.route.collect { r -> _state.update { it.copy(route = r) } } }
                // A link that only knows its manual IP learns the site's tls_host once, for the next session.
                if (siteLink.tlsHost == null) {
                    // "수동 주소" at once; no browse without a tls_host. Never crash the Main dispatcher (review M1).
                    runCatching { resolver.resolve() }.onFailure { Log.w(TAG, "manual route lookup failed", it) }
                    launch(Dispatchers.IO) {
                        val seen = resolver.learnTlsHost() ?: return@launch
                        // The advert is unauthenticated: save its name only when the pinned handshake to
                        // manual_host presents a leaf that covers it (review M2).
                        val leaf = newLink.peerLeaf.filterNotNull().first()
                        if (SiteResolver.leafCovers(seen.tlsHost, leaf)) {
                            Log.i(TAG, "learned tls_host ${seen.tlsHost} at ${siteLink.manualHost}")
                            store.learnTlsHost(siteLink, seen.tlsHost, seen.serviceName)
                        } else {
                            Log.w(TAG, "advertised ${seen.tlsHost} at ${siteLink.manualHost} is not in the site certificate; not learned")
                        }
                    }
                }
            }
            val newCamera = CameraController(
                this@StreamService, this@StreamService, newLink,
                onError = { e ->
                    _state.update { it.copy(error = StreamError.Camera(e.message ?: e.javaClass.simpleName)) }
                    endSession()
                },
                onLighting = { status -> if (sessionActive) _state.update { it.copy(lighting = status) } },
                onExposure = { status -> if (sessionActive) _state.update { it.copy(exposure = status) } },
                onTuning = { status -> if (sessionActive) _state.update { it.copy(tuning = status) } },
            )
            link = newLink
            camera = newCamera
            launch {
                monitor.health.collect { health ->
                    newCamera.setThermalStatus(health?.thermalStatus ?: DeviceHealth.THERMAL_UNKNOWN)
                    newCamera.setThermalBlocked(
                        (health?.thermalStatus ?: -1) >= 3 ||
                            (health?.temperatureC ?: 0.0) >= DeviceHealth.HOT_BATTERY_C,
                    )
                }
            }
            _state.update {
                it.copy(
                    target = pairing?.let { p -> "${p.host}:${p.port} · ${p.source}" },
                    previewOnly = !plan.sendFrames,
                    lens = pick,
                    wideAvailable = LensSelector.hasWide(backCameras),
                )
            }
            if (!plan.sendFrames) {
                launch { notificationHealth.collect { updateNotification(LinkState.DISCONNECTED, previewOnly = true, health = it) } }
            }
            newLink?.start()
            newCamera.start(OverheadConfig.DEFAULT, pick?.camera?.id)
            newCamera.setExposureAssist(store.autoExposure.first())
            launch { store.recognitionExposure.distinctUntilChanged().collect { newCamera.setRecognitionTuning(it) } }

            // Lens changes from the settings screen apply live: rebind, then a fresh hello.
            launch {
                store.lens.map(LensChoice::orDefault).distinctUntilChanged().collect { choice ->
                    val next = LensSelector.pick(backCameras, choice) ?: return@collect
                    val current = _state.value.lens
                    if (current == next) return@collect
                    Log.i(TAG, "lens change ${choice.wire} -> ${LensProbe.describe(next.camera)}")
                    val switched = current?.camera?.id == next.camera.id || newCamera.selectCamera(next.camera.id)
                    if (!sessionActive) return@collect
                    if (!switched) {
                        // The previous lens is bound again: keep its state and hello.
                        _state.update { it.copy(lensSwitchFailed = true) }
                        return@collect
                    }
                    _state.update { it.copy(lens = next, lensSwitchFailed = false) }
                    newLink?.let { l ->
                        l.lens = LensSelector.helloLens(next)
                        l.reconnect()
                    }
                    refreshNotification()
                }
            }

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
        sessionJob?.cancel()
        sessionJob = null
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
            current.copy(running = false, previewOnly = false, health = null, lens = null, lensSwitchFailed = false,
                photoSaving = false, lighting = LightingStatus(), exposure = ExposureStatus(), tuning = TuningStatus(),
                link = lastLink?.status?.value ?: current.link)
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
            _state.value.lens?.let { LensText.line(resources, it) }?.let { add(it) }
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
        shownLinkState = linkState
        shownPreviewOnly = previewOnly
        shownHealth = health
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIFICATION_ID, buildNotification(linkState, previewOnly, health))
    }

    private fun refreshNotification() = updateNotification(shownLinkState, shownPreviewOnly, shownHealth)

    companion object {
        private const val TAG = "StreamService"
        private const val CHANNEL_ID = "stream"
        private const val NOTIFICATION_ID = 1
        const val ACTION_START = "io.github.livsbittt.rosy.cam.action.START"
        const val ACTION_STOP = "io.github.livsbittt.rosy.cam.action.STOP"

        private val _state = MutableStateFlow(StreamState())
        private var activeService: StreamService? = null

        /** Local activity controls only; no exported command receiver. */
        fun requestLight(requested: Boolean) {
            activeService?.camera?.setLightRequested(requested)
        }

        /** D-544: persists the operator's choice and applies it to the running camera. */
        fun setExposureAssist(enabled: Boolean) {
            val service = activeService ?: return
            service.lifecycleScope.launch { SettingsStore(service.applicationContext).saveAutoExposure(enabled) }
            service.camera?.setExposureAssist(enabled)
        }

        fun savePhoto() {
            val service = activeService ?: return
            val controller = service.camera ?: return
            if (!service.sessionActive || _state.value.photoSaving) return
            _state.update { it.copy(photoSaving = true, photoFailed = false) }
            controller.savePhoto { name ->
                if (service.camera === controller && service.sessionActive) {
                    _state.update { it.copy(photoSaving = false, photoFailed = name == null,
                        photoName = name ?: it.photoName) }
                }
            }
        }

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
