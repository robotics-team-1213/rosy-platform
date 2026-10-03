package io.github.livsbittt.rosy.cam.camera

import java.nio.file.Files
import org.junit.Assert.*
import org.junit.Test

class FramePhotoStoreTest {
    @Test fun savesOwnedCopyAndRotationAndRejectsStaleFrames() {
        val dir = Files.createTempDirectory("photos").toFile()
        try {
            val store = FramePhotoStore(dir) { bytes, _ -> bytes }
            assertNull(store.save(100))
            val bytes = byteArrayOf(1, 2, 3, 4)
            store.update(bytes, 3, 1280, 720, 90, 100)
            bytes[0] = 99
            val name = store.save(3100)!!
            assertArrayEquals(byteArrayOf(1, 2, 3), dir.resolve(name).readBytes())
            val meta = dir.resolve(name.removeSuffix(".jpg") + ".json").readText()
            assertTrue(meta.contains("\"rotation_degrees\":90"))
            assertTrue(meta.contains("\"width\":1280"))
            assertNull(store.save(3101))
            assertNull(store.save(99))
            store.clear()
            assertNull(store.save(100))
        } finally { dir.deleteRecursively() }
    }

    @Test fun capsPhotosAndLeavesOtherFilesAlone() {
        val dir = Files.createTempDirectory("photos").toFile()
        try {
            dir.resolve("other.jpg").writeText("keep")
            val store = FramePhotoStore(dir) { bytes, _ -> bytes }
            repeat(23) {
                store.update(byteArrayOf(1, 2), 2, 2, 2, 0, it.toLong())
                assertNotNull(store.save(it.toLong()))
            }
            assertEquals(20, dir.listFiles()!!.count { it.name.startsWith("rosy-frame-") && it.extension == "jpg" })
            assertEquals(20, dir.listFiles()!!.count { it.extension == "json" })
            assertEquals("keep", dir.resolve("other.jpg").readText())
            assertFalse(dir.listFiles()!!.any { it.extension == "part" })
        } finally { dir.deleteRecursively() }
    }

    @Test fun refusesInvalidOrUnboundedCopies() {
        val store = FramePhotoStore(Files.createTempDirectory("photos").toFile()) { bytes, _ -> bytes }
        try {
            store.update(ByteArray(3), 4, 2, 2, 0, 0)
            assertNull(store.save(0))
            store.update(ByteArray(FramePhotoStore.MAX_BYTES + 1), FramePhotoStore.MAX_BYTES + 1, 2, 2, 0, 0)
            assertNull(store.save(0))
        } finally { store.directory.deleteRecursively() }
    }
}
