package sk.lanmusic.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.core.content.FileProvider
import java.io.File

private const val APK_MIME = "application/vnd.android.package-archive"

/** Hands a downloaded APK to the system installer. */
class ApkInstaller(private val context: Context) {

    /** Android 8+ requires per-app consent before it will open the installer. */
    fun canInstall(): Boolean =
        context.packageManager.canRequestPackageInstalls()

    /** Sends the user to the "allow from this source" settings screen. */
    fun requestPermission() {
        val intent = Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:${context.packageName}"),
        ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    fun install(file: File) {
        val uri = FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            file,
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, APK_MIME)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }
}
