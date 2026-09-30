package io.github.livsbittt.rosy.ceilingcamera.ui

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element

/**
 * D-370 3항: the adaptive launcher icon is a copy of src/hmi/web_common/icons/ceiling-camera.svg.
 * Paths, stroke widths and colours must stay equal; the monochrome layer is the same geometry in one colour.
 */
class LauncherIconParityTest {
    private data class Shape(val path: String, val colour: String, val strokeWidth: String?)

    private val iconsDir: File by lazy {
        File(System.getProperty("rosy.icons.dir") ?: error("system property rosy.icons.dir is not set (see app/build.gradle.kts)"))
    }
    private val res = File("src/main/res")

    private fun xml(file: File) = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
        .newDocumentBuilder().parse(file).documentElement

    private fun Element.paths(): List<Element> = getElementsByTagName("path").let { nodes ->
        List(nodes.length) { nodes.item(it) as Element }
    }

    private fun svgShapes(): Pair<String, List<Shape>> {
        val paths = xml(File(iconsDir, "ceiling-camera.svg")).paths()
        val background = paths.first { it.getAttribute("id") == "background" }.getAttribute("fill")
        val shapes = paths.filter { it.getAttribute("id") != "background" }.map {
            val stroke = it.getAttribute("stroke").takeIf { value -> value.isNotEmpty() && value != "none" }
            Shape(it.getAttribute("d"), (stroke ?: it.getAttribute("fill")).lowercase(),
                stroke?.let { _ -> it.getAttribute("stroke-width") })
        }
        return background.lowercase() to shapes
    }

    private fun drawableShapes(name: String): List<Shape> = xml(File(res, "drawable/$name.xml")).paths().map {
        val attr = { key: String -> it.getAttributeNS(ANDROID, key) }
        val stroke = attr("strokeColor").takeIf { value -> value.isNotEmpty() }
        Shape(attr("pathData"), argbToRgb(stroke ?: attr("fillColor")), stroke?.let { _ -> attr("strokeWidth") })
    }

    @Test
    fun foregroundMatchesTheSvgGlyphAndBrandDot() {
        val (_, svg) = svgShapes()
        assertTrue("SVG has no glyph paths", svg.size >= 2)
        assertEquals(svg, drawableShapes("ic_launcher_foreground"))
    }

    @Test
    fun monochromeIsTheSameGeometryInOneColour() {
        val (_, svg) = svgShapes()
        val mono = drawableShapes("ic_launcher_monochrome")
        assertEquals(svg.map { it.copy(colour = "#ffffff") }, mono)
    }

    @Test
    fun backgroundIsTheGroundToken() {
        val (background, _) = svgShapes()
        val colour = xml(File(res, "values/ic_launcher_background.xml")).getElementsByTagName("color").item(0) as Element
        assertEquals("ic_launcher_background", colour.getAttribute("name"))
        assertEquals(background, argbToRgb(colour.textContent.trim()))
    }

    @Test
    fun adaptiveIconsUseAllThreeLayersAndTheManifestPointsAtThem() {
        for (name in listOf("ic_launcher", "ic_launcher_round")) {
            val icon = xml(File(res, "mipmap-anydpi-v26/$name.xml"))
            assertEquals("adaptive-icon", icon.tagName)
            val layers = listOf("background", "foreground", "monochrome").associateWith { tag ->
                (icon.getElementsByTagName(tag).item(0) as Element).getAttributeNS(ANDROID, "drawable")
            }
            assertEquals(
                mapOf(
                    "background" to "@color/ic_launcher_background",
                    "foreground" to "@drawable/ic_launcher_foreground",
                    "monochrome" to "@drawable/ic_launcher_monochrome",
                ),
                layers,
            )
        }
        val application = xml(File("src/main/AndroidManifest.xml")).getElementsByTagName("application").item(0) as Element
        assertEquals("@mipmap/ic_launcher", application.getAttributeNS(ANDROID, "icon"))
        assertEquals("@mipmap/ic_launcher_round", application.getAttributeNS(ANDROID, "roundIcon"))
    }

    private companion object {
        const val ANDROID = "http://schemas.android.com/apk/res/android"

        /** "#FFrrggbb" or "#rrggbb" to "#rrggbb"; the launcher layers are opaque. */
        fun argbToRgb(value: String): String {
            val hex = value.removePrefix("#").lowercase()
            return when (hex.length) {
                8 -> { assertEquals("launcher colours must be opaque", "ff", hex.take(2)); "#" + hex.drop(2) }
                6 -> "#$hex"
                else -> error("unexpected colour $value")
            }
        }
    }
}
