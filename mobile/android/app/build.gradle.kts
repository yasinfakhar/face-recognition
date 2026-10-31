plugins {
    id("com.android.application")
}

android {
    namespace = "com.facehello"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.facehello"
        minSdk = 26
        // 28 keeps plain /sdcard file access, so the app can read the same /sdcard/FaceHello/faces folder as the Termux version
        targetSdk = 28
        versionCode = 1
        versionName = "1.0"
        ndk { abiFilters += listOf("arm64-v8a") }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    androidResources { noCompress += "onnx" }
    lint { abortOnError = false }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.exifinterface:exifinterface:1.3.7")
    implementation("androidx.lifecycle:lifecycle-service:2.8.7")
    implementation("androidx.camera:camera-core:1.3.4")
    implementation("androidx.camera:camera-camera2:1.3.4")
    implementation("androidx.camera:camera-lifecycle:1.3.4")
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.20.0")
    implementation("org.nanohttpd:nanohttpd:2.3.1")
}
