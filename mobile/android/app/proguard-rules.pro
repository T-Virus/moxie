# R8 混淆保留规则（release 包）
# 目标：Java 侧尽量混淆，但 Chaquopy 与 WebView 的反射入口必须保留，否则运行即崩。

# Chaquopy 通过反射启动 Python 引擎、加载 .pyc 与原生库
-keep class com.chaquo.python.** { *; }
-dontwarn com.chaquo.python.**

# WebView 的 JavaScript 接口按方法名反射调用（Native.xxx）
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keep class com.mobit.writer.MainActivity { *; }
-keep class com.mobit.writer.MainActivity$* { *; }

# 原生方法按名查找
-keepclasseswithmembernames class * {
    native <methods>;
}

# 崩溃栈只保留文件名，不暴露原始路径
-renamesourcefileattribute SourceFile
