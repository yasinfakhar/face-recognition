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

    androidResources { noCompress += listOf("onnx", "bin") }
    // 64-bit ARM phones only (the S7 and nearly everything since); also avoids duplicate x86 libraries
    packaging { jniLibs { excludes += listOf("lib/x86/**", "lib/x86_64/**", "lib/armeabi-v7a/**") } }
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
    // KittenTTS runtime (sherpa-onnx with espeak-ng); fetch it with get-tts.ps1. The "static-link" build avoids clashing
    // with the ONNX Runtime used for face recognition.
    implementation(files("libs/sherpa-onnx-static-link-onnxruntime-1.13.8.aar"))
}
