plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.kotlin.compose) apply false
}

val outputRoot = providers.gradleProperty("rosy.buildRoot")
if (outputRoot.isPresent) allprojects { layout.buildDirectory.set(file("${outputRoot.get()}/${project.name}")) }
