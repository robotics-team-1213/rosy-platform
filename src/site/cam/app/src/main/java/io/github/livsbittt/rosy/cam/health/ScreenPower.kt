package io.github.livsbittt.rosy.cam.health

import android.app.Activity
import android.app.admin.DeviceAdminReceiver
import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.view.WindowManager

/** Only force-lock is requested. No password, wipe, accessibility, or global settings privilege. */
class ScreenLockReceiver : DeviceAdminReceiver()

class ScreenPower(private val activity: Activity) {
    private val policy = activity.getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager
    private val receiver = ComponentName(activity, ScreenLockReceiver::class.java)

    /** Without approval, stop holding the display awake and let the OS sleep timer turn it off. */
    fun sleep(askPermission: Boolean = false): Boolean {
        activity.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        activity.window.decorView.keepScreenOn = false
        activity.window.attributes = activity.window.attributes.apply { screenBrightness = 0f }
        if (approved() && runCatching { policy.lockNow() }.isSuccess) return true
        if (askPermission) runCatching {
            activity.startActivityForResult(Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN).apply {
                putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, receiver)
                putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, "화면을 꺼서 기기의 발열과 전력 사용을 줄입니다.")
            }, REQUEST_SCREEN_LOCK)
        }
        return false
    }

    fun approved(): Boolean = runCatching { policy.isAdminActive(receiver) }.getOrDefault(false)
    fun restore() {
        activity.window.attributes = activity.window.attributes.apply {
            screenBrightness = WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
        }
    }

    companion object { const val REQUEST_SCREEN_LOCK = 8128 }
}
