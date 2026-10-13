plugins {
    id("com.android.application") version "8.7.2" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
}
val outputRoot = providers.gradleProperty("rosy.buildRoot").orElse("X:/DevTemp/rosy-pilot-d432/build")
allprojects { layout.buildDirectory.set(file("${outputRoot.get()}/${project.name}")) }
