package io.github.livsbittt.rosy.cam.camera

import android.annotation.SuppressLint
import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraMetadata
import android.util.Log
import androidx.annotation.OptIn
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.camera2.interop.ExperimentalCamera2Interop
import androidx.camera.core.CameraInfo
import androidx.camera.core.CameraSelector
import androidx.camera.lifecycle.ProcessCameraProvider
import io.github.livsbittt.rosy.cam.link.HelloLens
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Reads the back cameras CameraX can bind, as [LensCandidate]s for [LensSelector]. */
object LensProbe {
    private const val TAG = "LensProbe"

    /** Back cameras in CameraX order (the first is what DEFAULT_BACK_CAMERA binds). Needs no permission. */
    suspend fun backCameras(context: Context): List<LensCandidate> {
        val provider = withContext(Dispatchers.IO) { ProcessCameraProvider.getInstance(context).get() }
        return provider.availableCameraInfos
            .filter { it.lensFacing == CameraSelector.LENS_FACING_BACK }
            .mapNotNull(::candidate)
            .also { list -> Log.i(TAG, "back cameras: " + list.joinToString { describe(it) }) }
    }

    /** "id=2 f=2.2mm hfov=104.1 physical" for logs. */
    fun describe(c: LensCandidate): String =
        "id=${c.id} f=${c.focalMm}mm hfov=${c.hfovDeg?.let { "%.1f".format(java.util.Locale.ROOT, it) }} " +
            (if (c.logical) "logical" else "physical")

    /** The optional hello.lens for [pick]; null when the lens reports no focal length or FOV. */
    fun helloLens(pick: LensPick?): HelloLens? {
        val camera = pick?.camera ?: return null
        val focal = camera.focalMm ?: return null
        val hfov = camera.hfovDeg ?: return null
        return HelloLens(pick.kind.wire, focal.toDouble(), hfov)
    }

    @SuppressLint("InlinedApi") // LOGICAL_MULTI_CAMERA is API 28; older phones never report it.
    @OptIn(ExperimentalCamera2Interop::class)
    private fun candidate(info: CameraInfo): LensCandidate? = try {
        val c2 = Camera2CameraInfo.from(info)
        val size = c2.getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_PHYSICAL_SIZE)
        val caps = c2.getCameraCharacteristic(CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES) ?: IntArray(0)
        LensCandidate(
            id = c2.cameraId,
            focalLengthsMm = c2.getCameraCharacteristic(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
                ?.toList().orEmpty(),
            sensorWidthMm = size?.width,
            sensorHeightMm = size?.height,
            logical = CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_LOGICAL_MULTI_CAMERA in caps,
        )
    } catch (e: IllegalArgumentException) {
        // Not a Camera2-backed CameraInfo.
        Log.w(TAG, "camera characteristics unavailable", e)
        null
    }
}
