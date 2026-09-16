package sk.lanmusic.update

import com.hierynomus.msdtyp.AccessMask
import com.hierynomus.mserref.NtStatus
import com.hierynomus.mssmb2.SMB2CreateDisposition
import com.hierynomus.mssmb2.SMB2ShareAccess
import com.hierynomus.mssmb2.SMBApiException
import com.hierynomus.smbj.SMBClient
import com.hierynomus.smbj.auth.AuthenticationContext
import com.hierynomus.smbj.share.DiskShare
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException
import java.util.EnumSet

private const val MANIFEST_NAME = "latest.json"

/** Reads updates straight off the Synology SMB share. */
class SmbUpdateSource : UpdateSource {

    override suspend fun fetchManifest(cfg: UpdateConfig): UpdateManifest? =
        withContext(Dispatchers.IO) {
            withShare(cfg) { share ->
                val text = try {
                    openRead(share, cfg.remotePath(MANIFEST_NAME)).use {
                        it.readBytes().toString(Charsets.UTF_8)
                    }
                } catch (e: SMBApiException) {
                    // No latest.json means "nothing published yet", not an
                    // error — the login itself already succeeded to get here.
                    if (e.status == NtStatus.STATUS_OBJECT_NAME_NOT_FOUND ||
                        e.status == NtStatus.STATUS_OBJECT_PATH_NOT_FOUND
                    ) null else throw e
                }
                text?.let { UpdateManifest.parse(it) }
            }
        }

    override suspend fun downloadApk(
        cfg: UpdateConfig,
        name: String,
        target: File,
        onProgress: (Float) -> Unit,
    ) = withContext(Dispatchers.IO) {
        withShare(cfg) { share ->
            val remote = cfg.remotePath(name)
            val total = runCatching {
                share.getFileInformation(remote).standardInformation.endOfFile
            }.getOrDefault(0L)

            openRead(share, remote).use { input ->
                target.outputStream().use { output ->
                    val buf = ByteArray(64 * 1024)
                    var copied = 0L
                    while (true) {
                        val n = input.read(buf)
                        if (n <= 0) break
                        output.write(buf, 0, n)
                        copied += n
                        if (total > 0) onProgress(copied.toFloat() / total)
                    }
                }
            }
            onProgress(1f)
        }
    }

    private fun openRead(share: DiskShare, name: String) =
        share.openFile(
            name,
            EnumSet.of(AccessMask.GENERIC_READ),
            null,
            SMB2ShareAccess.ALL,
            SMB2CreateDisposition.FILE_OPEN,
            null,
        ).inputStream

    /** Connect, authenticate, run [block], always tear the connection down. */
    private fun <T> withShare(cfg: UpdateConfig, block: (DiskShare) -> T): T = try {
        SMBClient().connect(cfg.host).use { conn ->
            val session = conn.authenticate(
                // Empty domain rather than null: some servers reject a null
                // NTLM domain outright, which looks like a wrong password.
                AuthenticationContext(cfg.username, cfg.password.toCharArray(), "")
            )
            (session.connectShare(cfg.share) as DiskShare).use(block)
        }
    } catch (e: SMBApiException) {
        // Translate NT status codes so the settings dialog can tell the user
        // which of password / permissions / paths is actually wrong.
        throw IOException(friendlyStatus(e, cfg), e)
    }

    private fun friendlyStatus(e: SMBApiException, cfg: UpdateConfig): String = when (e.status) {
        NtStatus.STATUS_LOGON_FAILURE ->
            "NAS odmietol prihlásenie — zlé meno alebo heslo."
        NtStatus.STATUS_PASSWORD_EXPIRED ->
            "NAS vyžaduje zmenu hesla účtu — v DSM vypni „vyžadovať zmenu hesla pri prvom prihlásení“."
        NtStatus.STATUS_ACCOUNT_DISABLED ->
            "Účet je v DSM zakázaný."
        NtStatus.STATUS_ACCESS_DENIED ->
            "Prihlásenie prešlo, ale účet nemá právo čítať share „${cfg.share}“."
        NtStatus.STATUS_BAD_NETWORK_NAME ->
            "Share „${cfg.share}“ na NASe neexistuje."
        NtStatus.STATUS_OBJECT_NAME_NOT_FOUND, NtStatus.STATUS_OBJECT_PATH_NOT_FOUND ->
            "Priečinok alebo súbor sa nenašiel (skontroluj priečinok „${cfg.folder}“)."
        else -> "NAS odmietol požiadavku: ${e.status}"
    }
}
