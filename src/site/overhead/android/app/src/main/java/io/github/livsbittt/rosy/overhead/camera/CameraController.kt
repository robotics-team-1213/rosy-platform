package io.github.livsbittt.rosy.overhead.camera

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.os.SystemClock
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
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionFilter
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import io.github.livsbittt.rosy.overhead.link.OverheadConfig
import io.github.livsbittt.rosy.overhead.link.OverheadLink
import io.github.livsbittt.rosy.overhead.link.SensorInfo
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.abs
import kotlin.math.max

/**
 * Binds CameraX Preview + ImageAnalysis (back camera, KEEP_ONLY_LATEST, YUV_420_888) to
 * [lifecycleOwner] and feeds admitted frames to [link]:
 * fps limiter -> latest-only gate -> JPEG -> link. Pixels are never rotated.
 * All public methods must be called on the main thread.
 */
class CameraController(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val link: OverheadLink,
    private val onError: (Throwable) -> Unit,
) {
    private val analysisExecutor: ExecutorService = Executors.newSingleThreadExecutor { r ->
        Thread(r, "overhead-analysis")
    }
    private val encoder = JpegEncoder()
    private val limiter = FpsLimiter(OverheadConfig.DEFAULT.fps)
    private val preview = Preview.Builder().build()

    @Volatile
    private var config: OverheadConfig = OverheadConfig.DEFAULT
    private var provider: ProcessCameraProvider? = null
    private var boundWidth = 0

    /** Sensor timestamp base, read once per bind; written on main, read on the analysis thread. */
    @Volatile
    private var timestampSource = CaptureClock.Source.UNAVAILABLE
    private var stopped = false

    fun start(initial: OverheadConfig) {
        applyValues(initial)
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
        if (provider != null && newConfig.width != boundWidth) bind()
    }

    fun setPreviewSurface(surfaceProvider: Preview.SurfaceProvider?) {
        preview.setSurfaceProvider(surfaceProvider)
    }

    fun stop() {
        stopped = true
        preview.setSurfaceProvider(null)
        provider?.unbindAll()
        provider = null
        analysisExecutor.shutdown()
    }

    private fun applyValues(newConfig: OverheadConfig) {
        config = newConfig
        limiter.fps = newConfig.fps
    }

    private fun bind() {
        val cameraProvider = provider ?: return
        val target = config
        val analysis = ImageAnalysis.Builder()
            .setResolutionSelector(selectorFor(target.width))
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
            .build()
        analysis.setAnalyzer(analysisExecutor, ::analyze)
        try {
            cameraProvider.unbindAll()
            val camera = cameraProvider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
            timestampSource = readTimestampSource(camera)
            boundWidth = target.width
            analysis.resolutionInfo?.let { info ->
                link.sensor = SensorInfo(info.resolution.width, info.resolution.height, info.rotationDegrees)
            }
            Log.i(
                TAG,
                "bound analysis at ${analysis.resolutionInfo?.resolution} for width ${target.width}, " +
                    "timestamp source $timestampSource",
            )
        } catch (e: Exception) {
            Log.e(TAG, "camera bind failed", e)
            onError(e)
        }
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

    private fun analyze(image: ImageProxy) {
        try {
            val arrivalMono = System.nanoTime()
            if (!limiter.tryAdmit(arrivalMono)) return
            if (!link.admitFrame()) return
            val captureMono = CaptureClock.toMonotonic(
                source = timestampSource,
                sensorNanos = image.imageInfo.timestamp,
                nowMonoNanos = arrivalMono,
                nowRealtimeNanos = SystemClock.elapsedRealtimeNanos(),
            )
            val rotation = image.imageInfo.rotationDegrees
            val current = config
            when (val result = encoder.encode(image, current.jpegQuality, current.maxBytes)) {
                is JpegEncoder.Result.TooLarge -> {
                    Log.w(TAG, "jpeg ${result.length} B > max_bytes ${current.maxBytes}, dropped")
                    link.countDrop()
                }
                is JpegEncoder.Result.Encoded -> {
                    link.sensor = SensorInfo(result.width, result.height, rotation)
                    link.sendFrame(result.bytes, result.length, result.width, result.height, rotation, captureMono)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "frame processing failed", e)
        } finally {
            image.close()
        }
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
