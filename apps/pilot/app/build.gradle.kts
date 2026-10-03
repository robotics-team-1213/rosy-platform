plugins { id("com.android.application"); id("org.jetbrains.kotlin.android") }
val shared = tasks.register<Sync>("sharedContracts") {
    from("../../../src/site/cam/app/src/main/java")
    include("**/settings/LinkPolicy.kt", "**/settings/DiscoveryBudget.kt", "**/settings/SiteLink.kt",
        "**/settings/SiteLinkRecord.kt", "**/settings/PairingUri.kt", "**/settings/OverheadServiceRecord.kt",
        "**/pairing/Pairing.kt", "**/link/PinnedTrust.kt", "**/link/Protocol.kt")
    into(layout.buildDirectory.dir("generated/shared-contracts"))
}
val sharedAssetNames = ((groovy.json.JsonSlurper().parse(file("../../../src/hmi/web_common/shared-assets.json")) as Map<*, *>)["shared_assets"] as Map<*, *>).keys.map { it.toString() }
val screens = tasks.register<Sync>("bundleScreens") {
    from("../../../src/hmi/pilot") {
        include("index.html", "styles.css", "manifest.webmanifest", "*.js", "drivers/**/*.js", "screens/**/*.js", "widgets/**/*.js")
        into("pilot")
    }
    from("../../../src/hmi/web_common") { include(sharedAssetNames); into("common") }
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
    sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/pilot-assets"))
    testOptions {
        unitTests.isReturnDefaultValues = true
        unitTests.all {
            it.systemProperty("rosy.discovery.vectors", rootProject.file("../../test/fixtures/protocol/discovery-txt.v1.json").absolutePath)
            it.systemProperty("rosy.pilot.assets", layout.buildDirectory.dir("generated/pilot-assets").get().asFile.absolutePath)
        }
    }
}
tasks.named("preBuild") { dependsOn(shared, screens) }
dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("org.nanohttpd:nanohttpd:2.3.1")
    implementation("org.nanohttpd:nanohttpd-websocket:2.3.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
}
