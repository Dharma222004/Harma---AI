package ai.harma.app.device

import android.content.Context
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager

/**
 * Native hardware torch controller with verified state callback
 */
class FlashlightController(private val context: Context) {

    private val cameraManager = context.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
    private var isTorchOn = false
    private var primaryCameraId: String? = null

    init {
        try {
            cameraManager?.cameraIdList?.firstOrNull { id ->
                val characteristics = cameraManager.getCameraCharacteristics(id)
                val hasFlash = characteristics.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
                val facing = characteristics.get(CameraCharacteristics.LENS_FACING)
                hasFlash && facing == CameraCharacteristics.LENS_FACING_BACK
            }?.let { primaryCameraId = it }

            cameraManager?.registerTorchCallback(object : CameraManager.TorchCallback() {
                override fun onTorchModeChanged(cameraId: String, enabled: Boolean) {
                    super.onTorchModeChanged(cameraId, enabled)
                    if (cameraId == primaryCameraId) {
                        isTorchOn = enabled
                    }
                }
            }, null)
        } catch (e: Exception) {
            // Flashlight hardware not accessible or missing
        }
    }

    fun isAvailable(): Boolean = primaryCameraId != null

    fun getStatus(): Boolean = isTorchOn

    fun setTorch(enable: Boolean): Result<Boolean> {
        val camId = primaryCameraId ?: return Result.failure(IllegalStateException("No camera with flash available"))
        val cm = cameraManager ?: return Result.failure(IllegalStateException("Camera service unavailable"))

        return try {
            cm.setTorchMode(camId, enable)
            isTorchOn = enable
            Result.success(enable)
        } catch (e: CameraAccessException) {
            Result.failure(e)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
