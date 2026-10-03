plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "io.github.livsbittt.rosy.cam"
    compileSdk = 35

    defaultConfig {
        applicationId = "io.github.livsbittt.rosy.cam"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    testOptions {
        // OverheadLink logs through android.util.Log; on the JVM those stubs return defaults.
        unitTests.isReturnDefaultValues = true
        unitTests.all {
            // Shared rosy-overhead/1 vectors, also read by the Python adapter tests.
            it.systemProperty(
                "rosy.overhead.vectors",
                rootProject.file("../../../test/fixtures/protocol/overhead-ingest.v1.json").absolutePath,
            )
            // D-370 shared DNS-SD TXT vectors, also read by the Python discovery parsers.
            it.systemProperty(
                "rosy.discovery.vectors",
                rootProject.file("../../../test/fixtures/protocol/discovery-txt.v1.json").absolutePath,
            )
            // D-391 shared vectors, also read by core_common failure_class / site_link.
            it.systemProperty(
                "rosy.failure.vectors",
                rootProject.file("../../../test/fixtures/protocol/failure-classes.v1.json").absolutePath,
            )
            it.systemProperty(
                "rosy.sitelink.vectors",
                rootProject.file("../../../test/fixtures/protocol/site-link.v1.json").absolutePath,
            )
            it.systemProperty(
                "rosy.linkpolicy.vectors",
                rootProject.file("../../../test/fixtures/protocol/link-policy.v1.json").absolutePath,
            )
            // D-341 rosy-pair/1 shared vectors, also read by core_common pairing (Fleet, Vision).
            it.systemProperty(
                "rosy.pairing.vectors",
                rootProject.file("../../../test/fixtures/protocol/pairing.v1.json").absolutePath,
            )
            // D-370 icon sources; LauncherIconParityTest compares the launcher drawables to them.
            it.systemProperty(
                "rosy.icons.dir",
                rootProject.file("../../hmi/web_common/icons").absolutePath,
            )
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.service)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.camera.core)
    implementation(libs.androidx.camera.camera2)
    implementation(libs.androidx.camera.lifecycle)
    implementation(libs.androidx.camera.view)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.coroutines.android)

    testImplementation(libs.junit)
    testImplementation(libs.org.json)
    testImplementation(libs.okhttp.mockwebserver)
    // HeldCertificate: a throwaway site CA and leaf for the pinned-trust tests.
    testImplementation(libs.okhttp.tls)
}
