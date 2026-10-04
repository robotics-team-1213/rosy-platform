plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val nativePalette = tasks.register("generateNativePalette") {
    val canonical = file("../../../../../shared/web/tokens.css")
    val generated = layout.buildDirectory.dir("generated/pilot-palette")
    val resources = layout.buildDirectory.dir("generated/pilot-palette-res")
    inputs.file(canonical); outputs.dir(generated); outputs.dir(resources)
    doLast {
        val dark = Regex(""":root,\s*\[data-theme="dark"\]\s*\{([^}]+)\}""").find(canonical.readText())?.groupValues?.get(1)
            ?: error("Canonical dark palette is missing")
        val roles = linkedMapOf("background" to "ground", "foreground" to "ink", "muted" to "ink-quiet",
            "rose" to "brand-rose", "card" to "ground-card", "pressed" to "ground-card-2", "disabled" to "ground-soft")
        val colors = roles.mapValues { (_, token) ->
            val color = Regex("--${Regex.escape(token)}:\\s*#([a-fA-F0-9]{6});").find(dark)?.groupValues?.get(1)
                ?: error("Canonical native token --$token is missing")
            color.uppercase()
        }
        val declarations = roles.map { (role, token) -> "    val $role = 0xFF${colors.getValue(role)}.toInt() // --$token" }
        val output = generated.get().file("io/github/livsbittt/rosy/pilot/PilotColors.kt").asFile
        output.parentFile.mkdirs()
        output.writeText("package io.github.livsbittt.rosy.pilot\n\n// Generated from canonical web_common/tokens.css; do not edit.\nobject PilotColors {\n" + declarations.joinToString("\n") + "\n}\n")
        val xml = resources.get().file("values/palette.xml").asFile
        xml.parentFile.mkdirs()
        xml.writeText("<resources>\n" + colors.entries.joinToString("\n") { (role, color) -> "    <color name=\"rosy_$role\">#$color</color>" } + "\n</resources>\n")
    }
}
val shared = tasks.register<Sync>("sharedContracts") {
    from("../../../../../operations/ui/cam/app/src/main/java")
    include("**/settings/LinkPolicy.kt", "**/settings/DiscoveryBudget.kt", "**/settings/SiteLink.kt",
        "**/settings/SiteLinkRecord.kt", "**/settings/PairingUri.kt", "**/settings/OverheadServiceRecord.kt",
        "**/pairing/Pairing.kt", "**/link/PinnedTrust.kt", "**/link/Protocol.kt",
        "**/health/DeviceHealth.kt", "**/health/ScreenCoolingPolicy.kt", "**/health/ScreenPower.kt")
    into(layout.buildDirectory.dir("generated/shared-contracts"))
}
val sharedScreenResources = tasks.register<Sync>("sharedScreenResources") {
    from("../../../../../operations/ui/cam/app/src/main/res") { include("xml/screen_lock_policy.xml") }
    into(layout.buildDirectory.dir("generated/screen-resources"))
}
val sharedAssetNames = ((groovy.json.JsonSlurper().parse(file("../../../../../shared/web/shared-assets.json")) as Map<*, *>)["shared_assets"] as Map<*, *>).keys.map { it.toString() }
val screens = tasks.register<Sync>("bundleScreens") {
    from("../../../../../middleware/ui/pilot") {
        include("index.html", "styles.css", "manifest.webmanifest", "*.js", "drivers/**/*.js", "screens/**/*.js", "widgets/**/*.js")
        into("pilot")
    }
    from("../../../../../shared/web") { include(sharedAssetNames); into("common") }
    into(layout.buildDirectory.dir("generated/pilot-assets"))
}
android {
    namespace = "io.github.livsbittt.rosy.pilot"
    compileSdk = 35
    defaultConfig {
        applicationId = "io.github.livsbittt.rosy.pilot"
        minSdk = 26; targetSdk = 35
        versionCode = 1; versionName = "0.1.0"
    }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    sourceSets.getByName("main").java.srcDir(layout.buildDirectory.dir("generated/shared-contracts"))
    sourceSets.getByName("main").java.srcDir(layout.buildDirectory.dir("generated/pilot-palette"))
    sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/pilot-assets"))
    sourceSets.getByName("main").res.srcDir(layout.buildDirectory.dir("generated/screen-resources"))
    sourceSets.getByName("main").res.srcDir(layout.buildDirectory.dir("generated/pilot-palette-res"))
    testOptions {
        unitTests.isReturnDefaultValues = true
        unitTests.all {
            it.inputs.dir(layout.buildDirectory.dir("generated/pilot-assets"))
            it.systemProperty("rosy.discovery.vectors", rootProject.file("../../../../test/fixtures/protocol/discovery-txt.v1.json").absolutePath)
            it.systemProperty("rosy.pilot.assets", layout.buildDirectory.dir("generated/pilot-assets").get().asFile.absolutePath)
        }
    }
}
tasks.named("preBuild") { dependsOn(shared, screens, sharedScreenResources, nativePalette) }
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.nanohttpd:nanohttpd:2.3.1")
    implementation("org.nanohttpd:nanohttpd-websocket:2.3.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
}
