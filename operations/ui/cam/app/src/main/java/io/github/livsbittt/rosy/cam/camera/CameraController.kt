package io.github.livsbittt.rosy.cam.camera

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.os.SystemClock
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.util.Size
import androidx.annotation.OptIn
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.TorchState
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionFilter
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.Observer
import io.github.livsbittt.rosy.cam.link.OverheadConfig
import io.github.livsbittt.rosy.cam.link.OverheadLink
import io.github.livsbittt.rosy.cam.link.SensorInfo
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.abs
import kotlin.math.max

/**
 * Binds CameraX Preview + ImageAnalysis (the chosen back camera, KEEP_ONLY_LATEST, YUV_420_888) to
 * [lifecycleOwner] and feeds admitted frames to [link]:
 * fps limiter -> latest-only gate -> JPEG -> link. Pixels are never rotated.
 * All public methods must be called on the main thread.
 */
class CameraController(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val link: OverheadLink?,
    private val onError: (Throwable) -> Unit,
    private val onLighting: (LightingStatus) -> Unit = {},
    private val onExposure: (ExposureStatus) -> Unit = {},
) {
    private val analysisExecutor: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "overhead-analysis")
    }
    private val encoder = JpegEncoder()
    private val adaptiveQuality = AdaptiveJpegQuality()
    private val main = Handler(Looper.getMainLooper())
    private val lightPolicy = AutoLightPolicy()
    private val lightRequest = LightRequestWindow()
    private var lightRequestDeadline: Runnable? = null
    private val photoStore = FramePhotoStore(java.io.File(context.filesDir, "photos"))
    private val photoExecutor = Executors.newSingleThreadExecutor { r -> Thread(r, "cam-photo") }
    private val photoBusy = AtomicBoolean(false)
    private val lightPending = AtomicBoolean(false)
    private data class LumaSample(val value: Int, val generation: Int, val atMs: Long)
    @Volatile private var latestLuma: LumaSample? = null
    @Volatile private var lastLumaNs = 0L
    @Volatile private var generation = 0
    private var camera: Camera? = null
    private var exposurePolicy: ExposureAssistPolicy? = null
    private var exposureStep = 0.0
    private var exposureEnabled = false
    private var exposureApplied = 0
    private var exposureFailed = false
    private var exposureShown: ExposureStatus? = null
    @Volatile private var measureExposure = false
    @Volatile private var latestStats: StatsSample? = null
    private data class StatsSample(val stats: LumaStats, val generation: Int, val atMs: Long)
    private var torchObserver: Observer<Int>? = null
    private var lighting = LightingStatus()
    private var thermalBlocked = false
    private var torchFailure = false
    private var torchOffFailed = false
    private var torchRequest = 0
    private var requestedTorch: Boolean? = null
    private var torchDeadline: Runnable? = null
    private var torchOffDeadline: Runnable? = null

    /** Set on main when the camera is rebound or quality/width change; consumed on the analysis thread. */
    @Volatile
    private var qualityResetPending = true
    private val limiter = FpsLimiter(OverheadConfig.DEFAULT.fps)
    private val preview = Preview.Builder().build()

    @Volatile
    private var config: OverheadConfig = OverheadConfig.DEFAULT
    private var provider: ProcessCameraProvider? = null
    private var boundWidth = 0

    /** Camera2 id to bind (see [LensSelector]); null binds DEFAULT_BACK_CAMERA. */
    private var cameraId: String? = null

    /** Sensor timestamp base, read once per bind; written on main, read on the analysis thread. */
    @Volatile
    private var timestampSource = CaptureClock.Source.UNAVAILABLE
    private var stopped = false

    fun start(initial: OverheadConfig, initialCameraId: String?) {
        applyValues(initial)
        cameraId = initialCameraId
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            if (stopped) return@addListener
            try {
                provider = future.get()
                bind()
            } catch (e: Exception) {
                Log.e(TAG, "camera provider failed", e)
                onError(e)
            }
        }, ContextCompat.getMainExecutor(context))
    }

    /** Applies an adapter `config`. A width change rebinds the analysis use case. */
    fun applyConfig(newConfig: OverheadConfig) {
        applyValues(newConfig)
        if (link != null && provider != null && newConfig.width != boundWidth) bind()
    }

    /**
     * Switches lens. Rebinding resets adaptive JPEG quality and re-reads the timestamp source
     * and sensor size, exactly as the first bind does. If the new camera cannot be bound, the
     * previous one is bound again and this returns false (the stream goes on); only when that
     * also fails does [onError] end the session.
     */
    fun selectCamera(id: String?): Boolean {
        if (id == cameraId) return true
        val previous = cameraId
        if (provider == null) {
            cameraId = id
            return true
        }
        return when (val outcome = LensSwitch.run(previous, id) { target -> cameraId = target; bindOrThrow() }) {
            LensSwitch.Outcome.Switched -> true
            is LensSwitch.Outcome.RolledBack -> {
                Log.w(TAG, "lens switch to $id failed; back on ${previous ?: "default-back"}", outcome.error)
                false
            }
            is LensSwitch.Outcome.Failed -> {
                Log.e(TAG, "lens switch failed and the previous camera did not rebind", outcome.error)
                onError(outcome.error)
                false
            }
        }
    }

    fun setPreviewSurface(surfaceProvider: Preview.SurfaceProvider?) {
        preview.setSurfaceProvider(surfaceProvider)
    }

    fun setLightRequested(requested: Boolean) {
        if (lighting.requested == requested || stopped) return
        if (requested && (!lighting.supported || thermalBlocked)) { emitLighting(); return }
        lightRequestDeadline?.let(main::removeCallbacks)
        lightRequestDeadline = null
        lightRequest.cancel()
        lighting = lighting.copy(requested = requested, message = null)
        torchFailure = false // An explicit operator toggle may retry a failed camera control.
        torchOffFailed = false
        lightPolicy.reset(SystemClock.elapsedRealtime())
        if (!requested) requestTorch(false, force = true) else {
            lightRequest.start(SystemClock.elapsedRealtime())
            val epoch = generation
            val deadline = Runnable {
                lightRequestDeadline = null
                if (!stopped && generation == epoch) setLightRequested(false)
            }
            lightRequestDeadline = deadline
            main.postDelayed(deadline, LightRequestWindow.DURATION_MS)
            evaluateLight()
        }
        emitLighting()
    }

    /** D-544: bounded AE compensation nudge; default off, 0 whenever it is off or the camera rebinds. */
    fun setExposureAssist(enabled: Boolean) {
        if (stopped) return
        exposureEnabled = enabled
        measureExposure = enabled && exposurePolicy != null
        exposureFailed = false
        if (!enabled) latestStats = null
        evaluateExposure()
    }

    fun setThermalBlocked(blocked: Boolean) {
        if (thermalBlocked == blocked) return
        thermalBlocked = blocked
        evaluateExposure()
        if (blocked) {
            setLightRequested(false)
            requestTorch(false, force = true)
        } else evaluateLight()
        emitLighting()
    }

    /** Saves the current transmitted stream frame, not a separate high-resolution capture. */
    fun savePhoto(onResult: (String?) -> Unit) {
        if (stopped || !photoBusy.compareAndSet(false, true)) { onResult(null); return }
        val epoch = generation
        try {
            photoExecutor.execute {
                val filename = try { photoStore.save(SystemClock.elapsedRealtime()) } catch (error: Exception) {
                    Log.w(TAG, "stream photo save failed", error)
                    null
                }
                main.post {
                    photoBusy.set(false)
                    onResult(if (!stopped && generation == epoch) filename else null)
                }
            }
        } catch (_: RejectedExecutionException) {
            photoBusy.set(false)
            onResult(null)
        }
    }

    fun stop() {
        stopped = true
        releaseLighting()
        preview.setSurfaceProvider(null)
        provider?.unbindAll()
        provider = null
        analysisExecutor.shutdown()
        photoExecutor.shutdown()
    }

    private fun applyValues(newConfig: OverheadConfig) {
        if (newConfig.jpegQuality != config.jpegQuality || newConfig.width != config.width) {
            qualityResetPending = true
        }
        config = newConfig
        limiter.fps = newConfig.fps
    }

    private fun bind() {
        try {
            bindOrThrow()
        } catch (e: Exception) {
            Log.e(TAG, "camera bind failed", e)
            onError(e)
        }
    }

    private fun bindOrThrow() {
        val cameraProvider = provider ?: return
        val target = config
        val selector = selectorForCamera(cameraId)
        run {
            releaseLighting()
            cameraProvider.unbindAll()
            val epoch = generation
            val analysis = if (link == null) null else ImageAnalysis.Builder()
                .setResolutionSelector(selectorFor(target.width))
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                .build()
            analysis?.setAnalyzer(analysisExecutor) { image -> analyze(image, epoch) }
            val camera = if (analysis == null) {
                cameraProvider.bindToLifecycle(lifecycleOwner, selector, preview)
            } else {
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    selector,
                    preview,
                    analysis,
                )
            }
            this.camera = camera
            lighting = lighting.copy(supported = camera.cameraInfo.hasFlashUnit(), torchOn = false,
                dark = false, message = null)
            val range = camera.cameraInfo.exposureState
            exposureStep = range.exposureCompensationStep.toDouble()
            exposureApplied = 0
            exposureShown = null
            exposurePolicy = if (range.isExposureCompensationSupported && exposureStep > 0.0) {
                val limit = minOf((ExposureAssistPolicy.LIMIT_EV / exposureStep).toInt(),
                    range.exposureCompensationRange.upper, -range.exposureCompensationRange.lower)
                val step = maxOf(1, Math.round(ExposureAssistPolicy.STEP_EV / exposureStep).toInt())
                if (limit >= 1) ExposureAssistPolicy(minOf(step, limit), limit) else null
            } else null
            measureExposure = exposureEnabled && exposurePolicy != null
            val observer = Observer<Int> { state ->
                if (stopped || generation != epoch || this.camera !== camera) return@Observer
                lighting = lighting.copy(torchOn = state == TorchState.ON)
                if (state == TorchState.OFF) {
                    torchOffDeadline?.let(main::removeCallbacks)
                    torchOffDeadline = null
                }
                if (lighting.torchOn && (!lighting.requested || thermalBlocked || torchFailure)) {
                    requestTorch(false, force = true)
                } else if (lighting.torchOn && requestedTorch != false) armTorchDeadline(epoch)
                emitLighting()
            }
            torchObserver = observer
            camera.cameraInfo.torchState.observe(lifecycleOwner, observer)
            emitLighting()
            timestampSource = readTimestampSource(camera)
            boundWidth = target.width
            qualityResetPending = true
            analysis?.resolutionInfo?.let { info ->
                link?.sensor = SensorInfo(info.resolution.width, info.resolution.height, info.rotationDegrees)
            }
            Log.i(
                TAG,
                "bound camera ${cameraId ?: "default-back"} analysis at " +
                    "${analysis?.resolutionInfo?.resolution ?: "preview-only"} for width ${target.width}, " +
                    "timestamp source $timestampSource",
            )
        }
    }

    @OptIn(ExperimentalCamera2Interop::class)
    private fun selectorForCamera(id: String?): CameraSelector {
        if (id == null) return CameraSelector.DEFAULT_BACK_CAMERA
        return CameraSelector.Builder()
            .addCameraFilter { infos -> infos.filter { Camera2CameraInfo.from(it).cameraId == id } }
            .build()
    }

    @OptIn(ExperimentalCamera2Interop::class)
    private fun readTimestampSource(camera: Camera): CaptureClock.Source = try {
        CaptureClock.Source.fromCamera2(
            Camera2CameraInfo.from(camera.cameraInfo)
                .getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE),
        )
    } catch (e: IllegalArgumentException) {
        // Not a Camera2-backed CameraInfo: fall back to the heuristic.
        Log.w(TAG, "timestamp source unavailable", e)
        CaptureClock.Source.UNAVAILABLE
    }

    private fun analyze(image: ImageProxy, epoch: Int) {
        try {
            if (stopped || epoch != generation) return
            measureLight(image, epoch)
            val frameLink = link ?: return
            val arrivalMono = System.nanoTime()
            if (!limiter.tryAdmit(arrivalMono)) return
            if (!frameLink.admitFrame()) return
            val captureMono = CaptureClock.toMonotonic(
                source = timestampSource,
                sensorNanos = image.imageInfo.timestamp,
                nowMonoNanos = arrivalMono,
                nowRealtimeNanos = SystemClock.elapsedRealtimeNanos(),
            )
            val rotation = image.imageInfo.rotationDegrees
            val current = config
            if (qualityResetPending) {
                qualityResetPending = false
                adaptiveQuality.reset()
            }
            var quality: Int? = adaptiveQuality.start(current.jpegQuality)
            while (quality != null) {
                when (val result = encoder.encode(image, quality, current.maxBytes)) {
                    is JpegEncoder.Result.TooLarge -> {
                        quality = adaptiveQuality.retryAfterOversize()
                        if (quality == null) {
                            Log.w(TAG, "jpeg ${result.length} B > max_bytes ${current.maxBytes}, dropped")
                            frameLink.countDrop()
                        }
                    }
                    is JpegEncoder.Result.Encoded -> {
                        synchronized(photoStore) {
                            if (epoch == generation) photoStore.update(result.bytes, result.length,
                                result.width, result.height, rotation, SystemClock.elapsedRealtime())
                        }
                        adaptiveQuality.encoded()
                        frameLink.sentQuality = adaptiveQuality.lastFit
                        frameLink.sensor = SensorInfo(result.width, result.height, rotation)
                        frameLink.sendFrame(result.bytes, result.length, result.width, result.height, rotation, captureMono)
                        quality = null
                    }
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "frame processing failed", e)
        } finally {
            image.close()
        }
    }

    private fun measureLight(image: ImageProxy, epoch: Int) {
        val now = System.nanoTime()
        if (now - lastLumaNs < 250_000_000L) return
        lastLumaNs = now
        val plane = image.planes.firstOrNull() ?: return
        val crop = image.cropRect
        if (measureExposure) LumaStats.measure(plane.buffer, plane.rowStride, plane.pixelStride,
            crop.left, crop.top, crop.right, crop.bottom)?.let {
            latestStats = StatsSample(it, epoch, SystemClock.elapsedRealtime())
        }
        val luma = YPlaneLuma.mean(plane.buffer, plane.rowStride, plane.pixelStride,
            crop.left, crop.top, crop.right, crop.bottom) ?: return
        latestLuma = LumaSample(luma, epoch, SystemClock.elapsedRealtime())
        if (!lightPending.compareAndSet(false, true)) return
        main.post {
            lightPending.set(false)
            if (!stopped && epoch == generation) { evaluateLight(); evaluateExposure() }
        }
    }

    private fun evaluateLight() {
        val now = SystemClock.elapsedRealtime()
        if (lighting.requested && !lightRequest.active(now)) {
            setLightRequested(false)
            return
        }
        val sample = latestLuma?.takeIf { it.generation == generation && now - it.atMs in 0..1000 }
        lighting = lighting.copy(dark = sample != null && sample.value <= 28)
        val desired = lightPolicy.update(sample?.value ?: -1, now, lighting.requested,
            lighting.supported, thermalBlocked, lighting.torchOn)
        if (!torchFailure) requestTorch(desired)
        emitLighting()
    }

    private fun evaluateExposure() {
        val policy = exposurePolicy
        val bound = camera
        val now = SystemClock.elapsedRealtime()
        val sample = latestStats?.takeIf { it.generation == generation && now - it.atMs in 0..1000 }
        val target = if (policy == null) 0 else
            policy.update(sample?.stats, now, exposureEnabled && !exposureFailed, thermalBlocked || lighting.torchOn)
        if (bound != null && target != exposureApplied) {
            exposureApplied = target
            try {
                val future = bound.cameraControl.setExposureCompensationIndex(target)
                future.addListener({
                    if (stopped || camera !== bound) return@addListener
                    try { future.get() } catch (error: Exception) {
                        exposureFailed = true
                        Log.w(TAG, "exposure compensation failed", error)
                    }
                }, ContextCompat.getMainExecutor(context))
            } catch (error: Exception) {
                exposureFailed = true
                Log.w(TAG, "exposure compensation unavailable", error)
            }
            Log.i(TAG, "exposure_ev index=$target step=$exposureStep")
        }
        val status = ExposureStatus(policy != null, exposureEnabled, policy?.verdict ?: ExposureVerdict.OK,
            target, if (exposureEnabled) sample?.stats else null)
        val shown = exposureShown
        if (shown == null || shown.supported != status.supported || shown.enabled != status.enabled ||
            shown.verdict != status.verdict || shown.index != status.index) {
            exposureShown = status
            onExposure(status)
        }
    }

    private fun emitLighting() {
        onLighting(lighting.copy(message = when {
            torchFailure -> lighting.message ?: "Camera light control failed"
            thermalBlocked -> "Camera light paused while the phone is hot"
            !lighting.supported -> "This camera has no controllable flash"
            else -> null
        }))
    }

    private fun requestTorch(on: Boolean, force: Boolean = false) {
        val bound = camera ?: return
        if (!on && torchOffFailed) return // Failed off commands require an explicit toggle/rebind, not a frame loop.
        if (!lighting.supported || (on && (thermalBlocked || !lighting.requested || torchFailure))) return
        if (requestedTorch == on || (!force && requestedTorch == null && lighting.torchOn == on)) return
        if (!on) { torchDeadline?.let(main::removeCallbacks); torchDeadline = null }
        val epoch = generation
        val request = ++torchRequest
        requestedTorch = on
        if (on) armTorchDeadline(epoch) // Also bounds a stalled control future/analyzer.
        else armTorchOffDeadline(epoch, bound)
        try {
            val future = bound.cameraControl.enableTorch(on)
            future.addListener({
                if (stopped || generation != epoch || camera !== bound || request != torchRequest) return@addListener
                requestedTorch = null
                try { future.get() } catch (error: Exception) {
                    torchFailure = true
                    if (!on) torchOffFailed = true
                    lighting = lighting.copy(message = "Camera light control failed")
                    Log.w(TAG, "torch command failed", error)
                    if (on) requestTorch(false, force = true) else onError(error)
                }
                if (!on && bound.cameraInfo.torchState.value == TorchState.OFF) {
                    torchOffDeadline?.let(main::removeCallbacks)
                    torchOffDeadline = null
                }
                // Actual LED state comes only from cameraInfo.torchState's observer.
                emitLighting()
            }, ContextCompat.getMainExecutor(context))
        } catch (error: Exception) {
            requestedTorch = null
            torchFailure = true
            if (!on) torchOffFailed = true
            lighting = lighting.copy(message = "Camera light control failed")
            Log.w(TAG, "torch control unavailable", error)
            if (on) requestTorch(false, force = true) else onError(error)
            emitLighting()
        }
    }

    private fun armTorchDeadline(epoch: Int) {
        if (torchDeadline != null) return
        val task = Runnable {
            torchDeadline = null
            if (stopped || generation != epoch) return@Runnable
            // A request ends completely; darkness cannot rearm it.
            setLightRequested(false)
            requestTorch(false, force = true)
        }
        torchDeadline = task
        main.postDelayed(task, 30_000L)
    }

    private fun armTorchOffDeadline(epoch: Int, bound: Camera) {
        torchOffDeadline?.let(main::removeCallbacks)
        val task = Runnable {
            torchOffDeadline = null
            if (stopped || generation != epoch || camera !== bound) return@Runnable
            if (bound.cameraInfo.torchState.value != TorchState.OFF) {
                // A stalled off future must not leave the light on indefinitely.
                onError(IllegalStateException("Camera light did not turn off"))
            }
        }
        torchOffDeadline = task
        main.postDelayed(task, 3000L)
    }

    private fun releaseLighting() {
        lightRequestDeadline?.let(main::removeCallbacks)
        lightRequestDeadline = null
        lightRequest.cancel()
        synchronized(photoStore) { generation++; photoStore.clear() }
        latestLuma = null
        latestStats = null
        exposurePolicy = null
        exposureApplied = 0
        lastLumaNs = 0L
        torchDeadline?.let(main::removeCallbacks)
        torchDeadline = null
        torchOffDeadline?.let(main::removeCallbacks)
        torchOffDeadline = null
        torchRequest++
        requestedTorch = null
        torchFailure = false
        torchOffFailed = false
        camera?.let { old ->
            torchObserver?.let { old.cameraInfo.torchState.removeObserver(it) }
            if (old.cameraInfo.hasFlashUnit()) {
                try {
                    val off = old.cameraControl.enableTorch(false)
                    off.addListener({
                        try { off.get() } catch (error: Exception) { Log.w(TAG, "unbind torch off failed", error) }
                    }, ContextCompat.getMainExecutor(context))
                } catch (error: Exception) { Log.w(TAG, "unbind torch control unavailable", error) }
            }
        }
        camera = null
        torchObserver = null
        lightPolicy.reset(SystemClock.elapsedRealtime())
        lighting = lighting.copy(requested = false, supported = false, torchOn = false, dark = false, message = null)
        emitLighting()
    }

    private companion object {
        const val TAG = "CameraController"

        /**
         * 16:9, long edge closest to [width]. The filter compares long and short edges so the
         * choice does not depend on whether sizes are reported in portrait or landscape.
         */
        fun selectorFor(width: Int): ResolutionSelector {
            val targetLong = width
            val targetShort = width * 9 / 16
            return ResolutionSelector.Builder()
                .setAspectRatioStrategy(AspectRatioStrategy.RATIO_16_9_FALLBACK_AUTO_STRATEGY)
                .setResolutionStrategy(ResolutionStrategy.HIGHEST_AVAILABLE_STRATEGY)
                .setResolutionFilter(ResolutionFilter { sizes: List<Size>, _: Int ->
                    sizes.sortedWith(
                        compareBy<Size>(
                            { abs(max(it.width, it.height) - targetLong) + abs(minOf(it.width, it.height) - targetShort) },
                            { -max(it.width, it.height) },
                        ),
                    )
                })
                .build()
        }
    }
}
