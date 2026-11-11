package com.mobit.writer;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.util.Base64;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.DownloadListener;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLDecoder;

/**
 * 墨写手机端：内嵌 Python 引擎 + 本机 HTTP 服务 + WebView 界面。
 *
 * 全部功能（拆解 / 改编 / 正文生成 / 审查 / 封面 / 导出）都在手机本地运行，
 * 不依赖电脑，也不需要配置服务器地址。
 */
public class MainActivity extends Activity {

    private static final String TAG = "MoBiT";
    private static final String PREFS = "mobit";
    private static final String KEY_ASSET_VERSION = "asset_version";
    private static final String APP_URL = "http://127.0.0.1:8765";
    private static final int PORT = 8765;
    private static final int REQ_FILE = 1001;
    private static final int REQ_WRITE = 1002;

    private WebView web;
    private FrameLayout root;
    private View splash;
    private TextView splashTip;
    private SharedPreferences prefs;
    private ValueCallback<Uri[]> fileCallback;
    private long lastBackAt = 0;
    private volatile boolean pageLoaded = false;
    private String pythonError = "";
    private View errorBox;
    private final Handler ui = new Handler(Looper.getMainLooper());

    /* ---------------------------------------------------------------- 生命周期 */

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        setupWindow();

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#F7F8FA"));
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#F7F8FA"));
        web.setVisibility(View.INVISIBLE);
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        splash = buildSplash();
        root.addView(splash, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        setupWebView();
        boot();

        if (Build.VERSION.SDK_INT <= 28 &&
                checkSelfPermission(android.Manifest.permission.WRITE_EXTERNAL_STORAGE)
                        != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{android.Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_WRITE);
        }
    }

    private void setupWindow() {
        Window w = getWindow();
        w.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        w.setStatusBarColor(Color.parseColor("#F8F7F3"));
        w.setNavigationBarColor(Color.parseColor("#F8F7F3"));
        View decor = w.getDecorView();
        int flags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
        if (Build.VERSION.SDK_INT >= 26) flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        decor.setSystemUiVisibility(flags);
    }

    /** 启动页：与桌面端一致的品牌图标 + 墨写 + 引擎启动进度 */
    private View buildSplash() {
        FrameLayout box = new FrameLayout(this);
        GradientDrawable bg = new GradientDrawable(
                GradientDrawable.Orientation.TL_BR,
                new int[]{Color.parseColor("#F9F8F4"), Color.parseColor("#EDF4EF")});
        box.setBackground(bg);

        LinearLayout center = new LinearLayout(this);
        center.setOrientation(LinearLayout.VERTICAL);
        center.setGravity(Gravity.CENTER_HORIZONTAL);
        FrameLayout.LayoutParams clp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        clp.gravity = Gravity.CENTER;
        clp.leftMargin = dp(32);
        clp.rightMargin = dp(32);
        box.addView(center, clp);

        /* 图标卡片：直接使用与桌面端、启动器一致的品牌图标 */
        FrameLayout iconCard = new FrameLayout(this);
        GradientDrawable cardBg = new GradientDrawable();
        cardBg.setColor(Color.WHITE);
        cardBg.setCornerRadius(dp(28));
        iconCard.setBackground(cardBg);
        iconCard.setElevation(dp(10));
        LinearLayout.LayoutParams ilp = new LinearLayout.LayoutParams(dp(104), dp(104));
        center.addView(iconCard, ilp);

        ImageView icon = new ImageView(this);
        try {
            icon.setImageResource(getApplicationInfo().icon);
        } catch (Exception e) {
            icon.setImageResource(R.mipmap.ic_launcher);
        }
        icon.setScaleType(ImageView.ScaleType.FIT_CENTER);
        FrameLayout.LayoutParams iilp = new FrameLayout.LayoutParams(dp(78), dp(78));
        iilp.gravity = Gravity.CENTER;
        iconCard.addView(icon, iilp);

        TextView name = new TextView(this);
        name.setText("墨写");
        name.setTextColor(Color.parseColor("#15211D"));
        name.setTextSize(TypedValue.COMPLEX_UNIT_SP, 25);
        name.setTypeface(name.getTypeface(), android.graphics.Typeface.BOLD);
        name.setLetterSpacing(0.08f);
        name.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams nlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        nlp.topMargin = dp(22);
        center.addView(name, nlp);

        TextView tag = new TextView(this);
        tag.setText("AI 小说工作台");
        tag.setTextColor(Color.parseColor("#7C8781"));
        tag.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        tag.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams tlp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        tlp.topMargin = dp(7);
        center.addView(tag, tlp);

        ProgressBar bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setIndeterminate(true);
        if (Build.VERSION.SDK_INT >= 21) {
            bar.setIndeterminateTintList(ColorStateList.valueOf(Color.parseColor("#0F766E")));
        }
        LinearLayout.LayoutParams blp = new LinearLayout.LayoutParams(dp(92), dp(4));
        blp.topMargin = dp(30);
        center.addView(bar, blp);

        splashTip = new TextView(this);
        splashTip.setText("正在启动本地引擎…");
        splashTip.setTextColor(Color.parseColor("#98A29C"));
        splashTip.setTextSize(TypedValue.COMPLEX_UNIT_SP, 11.5f);
        splashTip.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams lp2 = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp2.topMargin = dp(14);
        center.addView(splashTip, lp2);

        center.setAlpha(0f);
        center.animate().alpha(1f).setDuration(420).start();
        return box;
    }

    private int dp(float v) {
        return (int) (v * getResources().getDisplayMetrics().density + .5f);
    }

    private void setupWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setTextZoom(100);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= 29) s.setForceDark(WebSettings.FORCE_DARK_OFF);
        if (Build.VERSION.SDK_INT >= 30) s.setForceDark(WebSettings.FORCE_DARK_OFF);
        CookieManager.getInstance().setAcceptCookie(true);

        web.addJavascriptInterface(new Bridge(), "Native");

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleUrl(request.getUrl());
            }

            @SuppressWarnings("deprecation")
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(Uri.parse(url));
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                injectHelpers();
                if (!pageLoaded) {
                    pageLoaded = true;
                    web.setAlpha(0f);
                    web.setVisibility(View.VISIBLE);
                    web.animate().alpha(1f).setDuration(260).start();
                    if (splash != null) {
                        splash.animate().alpha(0f).setDuration(220)
                                .withEndAction(new Runnable() {
                                    @Override
                                    public void run() {
                                        if (splash != null) splash.setVisibility(View.GONE);
                                    }
                                }).start();
                    }
                }
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame() && !pageLoaded) {
                    // 服务还没起来：等轮询线程继续重试，不在这里报错
                    Log.w(TAG, "main frame error while booting: " + error);
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                             FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = callback;
                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                String type = "*/*";
                String[] accept = params == null ? null : params.getAcceptTypes();
                /* accept 可能写成扩展名（.zip/.md）或 MIME：按扩展名映射出真正的 MIME，
                   否则像 zip 这种「provider 报 application/zip、清单只写 text/plain」会被筛掉选不中 */
                java.util.LinkedHashSet<String> mimes = new java.util.LinkedHashSet<>();
                if (accept != null) {
                    for (String a : accept) {
                        if (a == null) continue;
                        for (String part : a.split(",")) {
                            part = part.trim().toLowerCase();
                            if (part.isEmpty()) continue;
                            if (part.startsWith(".")) {
                                switch (part) {
                                    case ".zip": mimes.add("application/zip");
                                        mimes.add("application/x-zip-compressed"); break;
                                    case ".txt": mimes.add("text/plain"); break;
                                    case ".md": case ".markdown":
                                        mimes.add("text/markdown"); mimes.add("text/plain"); break;
                                    case ".json": mimes.add("application/json"); break;
                                    case ".png": mimes.add("image/png"); break;
                                    case ".jpg": case ".jpeg": mimes.add("image/jpeg"); break;
                                    case ".webp": mimes.add("image/webp"); break;
                                    default: break;
                                }
                            } else if (part.contains("/")) {
                                mimes.add(part);
                            }
                        }
                    }
                }
                if (!mimes.isEmpty()) {
                    /* 再加 octet-stream：部分文件管理器把 zip / md 都报成二进制流 */
                    mimes.add("application/octet-stream");
                    intent.putExtra(Intent.EXTRA_MIME_TYPES, mimes.toArray(new String[0]));
                }
                intent.setType(type);
                if (params != null && params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE) {
                    intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
                }
                try {
                    startActivityForResult(Intent.createChooser(intent, "选择文件"), REQ_FILE);
                } catch (Exception e) {
                    fileCallback = null;
                    toast("没有可用的文件选择器");
                }
                return true;
            }

            @Override
            public boolean onConsoleMessage(ConsoleMessage msg) {
                Log.d(TAG, "console: " + msg.message() + " @" + msg.lineNumber());
                return true;
            }
        });

        web.setDownloadListener(new DownloadListener() {
            @Override
            public void onDownloadStart(String url, String userAgent, String contentDisposition,
                                        String mimeType, long contentLength) {
                if (url == null || !url.startsWith("http")) {
                    toast("该文件请用浏览器打开后再下载");
                    return;
                }
                downloadUrl(url, userAgent, contentDisposition, mimeType);
            }
        });
    }

    /* ---------------------------------------------------------------- 启动流程 */

    private void boot() {
        new Thread(new Runnable() {
            @Override
            public void run() {
                // 页面被系统重建时服务可能还活着：直接复用，避免重复绑端口
                if (ping()) {
                    loadApp();
                    return;
                }
                try {
                    prepareFiles();
                } catch (final Exception e) {
                    Log.e(TAG, "prepare failed", e);
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            showError("准备本地文件失败：" + e.getMessage());
                        }
                    });
                    return;     // 没有网页/字体就不启动引擎，避免进去后白屏
                }
                ensureEngine(false);
                // 第一次等 44s（首次启动要解压网页 / 字体）；失败再强制重启一轮，
                // 覆盖「上次进程残留 started 标记」「绑定端口失败」这类二次启动问题
                if (!waitServer(110)) {
                    Log.w(TAG, "first boot attempt failed: " + pythonLastError());
                    ensureEngine(true);
                    if (waitServer(75)) return;
                    showBootError();
                }
            }
        }, "mobit-boot").start();
    }

    /** 加载界面（只在主线程调用 loadUrl） */
    private void loadApp() {
        final WebView view = web;
        if (view == null) return;
        ui.post(new Runnable() {
            @Override
            public void run() {
                view.loadUrl(APP_URL + "/#/overview");
            }
        });
    }

    /** 启动 / 重启内嵌引擎；force=true 时清掉 python 侧遗留的启动标记 */
    private void ensureEngine(boolean force) {
        try {
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(MainActivity.this));
            }
            com.chaquo.python.PyObject mod =
                    Python.getInstance().getModule("android_entry");
            if (force) {
                mod.callAttr("force_restart", getFilesDir().getAbsolutePath(), PORT);
            } else {
                mod.callAttr("start_server", getFilesDir().getAbsolutePath(), PORT);
            }
            pythonError = "";
        } catch (Throwable e) {
            pythonError = "启动 Python 引擎失败：" + e;
            Log.e(TAG, "python start failed", e);
        }
    }

    /** python 侧最后一次启动错误（绑端口失败 / 启动异常），用于错误页展示 */
    private String pythonLastError() {
        try {
            if (!Python.isStarted()) return "";
            String e = Python.getInstance().getModule("android_entry")
                    .callAttr("last_error").toString();
            if (e == null) return "";
            e = e.trim();
            if (e.length() > 800) e = e.substring(e.length() - 800);
            return e;
        } catch (Throwable t) {
            return "";
        }
    }

    private void showBootError() {
        final String py = pythonLastError();
        String err;
        if (!pythonError.isEmpty()) {
            err = pythonError;
        } else if (!py.isEmpty()) {
            err = "本地引擎启动失败：\n" + py;
        } else {
            err = "本地引擎启动超时。请点「重新启动」再试。";
        }
        ui.post(new Runnable() {
            @Override
            public void run() {
                showError(err);
            }
        });
    }

    /** 把 APK 里的网页 / 默认配置 / 字体复制到 App 私有目录（升级后覆盖网页，配置只补缺失） */
    private void prepareFiles() throws IOException {
        File files = getFilesDir();
        int ver = getVersionCodeSafe();
        boolean firstOrUpgraded = prefs.getInt(KEY_ASSET_VERSION, 0) != ver;

        File webDir = new File(files, "web");
        if (firstOrUpgraded || !new File(webDir, "index.html").isFile()) {
            deleteRecursively(webDir);
            copyAssetDir("www", webDir, true);
        }
        copyAssetDir("seed/config", new File(files, "config"), false);

        File prompt = new File(files, "user_prompt_settings.txt");
        if (!prompt.isFile()) copyAssetFile("seed/user_prompt_settings.txt", prompt);

        File fonts = new File(files, "assets/fonts");
        // 字体 15MB：只在首次安装 / 版本升级时覆盖，避免每次启动都写一遍
        copyAssetDir("seed/fonts", fonts, firstOrUpgraded);

        // HTTPS 证书：Android 没有系统级 OpenSSL 证书路径，随包带一份
        copyAssetDir("seed/certs", new File(files, "certs"), firstOrUpgraded);

        prefs.edit().putInt(KEY_ASSET_VERSION, ver).apply();
    }

    private int getVersionCodeSafe() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionCode;
        } catch (Exception e) {
            return 1;
        }
    }

    private void copyAssetDir(String src, File dst, boolean overwrite) throws IOException {
        String[] items = getAssets().list(src);
        if (items == null || items.length == 0) {
            if (!overwrite && dst.exists() && dst.length() > 0) return;
            copyAssetFile(src, dst);
            return;
        }
        if (!dst.exists() && !dst.mkdirs()) throw new IOException("无法创建目录 " + dst);
        for (String it : items) {
            copyAssetDir(src + "/" + it, new File(dst, it), overwrite);
        }
    }

    private void copyAssetFile(String src, File dst) throws IOException {
        File parent = dst.getParentFile();
        if (parent != null && !parent.exists()) parent.mkdirs();
        InputStream in = getAssets().open(src);
        OutputStream out = new FileOutputStream(dst);
        try {
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        } finally {
            try { in.close(); } catch (Exception ignored) { }
            try { out.close(); } catch (Exception ignored) { }
        }
    }

    /** 轮询本机服务，就绪后加载界面；返回 false 表示这次没等到 */
    private boolean waitServer(int tries) {
        for (int i = 0; i < tries; i++) {
            if (ping()) {
                loadApp();
                return true;
            }
            // 引擎明确报错时不用死等满超时：交给上层重启一轮并显示原因
            if (!pythonError.isEmpty() && i > 6) return false;
            if (i > 6 && i % 5 == 0 && !pythonLastError().isEmpty()) return false;
            final int sec = i * 4 / 10;
            if (i % 10 == 0) {
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (splashTip != null && sec > 2) {
                            splashTip.setText("正在启动本地引擎…（首次启动需要解压文件，" + sec + "s）");
                        }
                    }
                });
            }
            try {
                Thread.sleep(400);
            } catch (InterruptedException ignored) {
                return false;
            }
        }
        return false;
    }

    private boolean ping() {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(APP_URL + "/api/stats").openConnection();
            conn.setConnectTimeout(600);
            conn.setReadTimeout(1500);
            // 服务重启后旧的 keep-alive 连接会失效：禁用缓存并主动断开，
            // 否则可能一直复用坏连接而误判「服务没起来」
            conn.setUseCaches(false);
            conn.setRequestProperty("Connection", "close");
            int code = conn.getResponseCode();
            if (code < 200 || code >= 300) return false;
            InputStream in = conn.getInputStream();
            byte[] buf = new byte[256];
            int n = in.read(buf);
            in.close();
            return n > 0;
        } catch (Exception e) {
            return false;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private void showError(String msg) {
        if (isFinishing() || isDestroyed()) return;
        if (splash != null) splash.setVisibility(View.GONE);
        if (web != null) web.setVisibility(View.GONE);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setPadding(dp(28), dp(28), dp(28), dp(28));
        box.setBackgroundColor(Color.parseColor("#F7F8FA"));

        TextView title = new TextView(this);
        title.setText("启动失败");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        title.setTypeface(title.getTypeface(), android.graphics.Typeface.BOLD);
        title.setTextColor(Color.parseColor("#1F2329"));
        box.addView(title);

        TextView detail = new TextView(this);
        detail.setText(msg);
        detail.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12.5f);
        detail.setTextColor(Color.parseColor("#5B6472"));
        detail.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(12);
        box.addView(detail, lp);

        Button retry = new Button(this);
        retry.setText("重新启动");
        retry.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                retryBoot();
            }
        });
        LinearLayout.LayoutParams lp2 = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp2.topMargin = dp(18);
        box.addView(retry, lp2);

        errorBox = box;
        root.addView(box, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
    }

    /** 原地重试：清掉错误页、强制重启内嵌引擎再等一轮，不必退出 App */
    private void retryBoot() {
        if (isFinishing() || isDestroyed()) return;
        if (web == null) {                  // WebView 已销毁：退回重建 Activity
            Intent i = getIntent();
            finish();
            startActivity(i);
            return;
        }
        if (errorBox != null) {
            root.removeView(errorBox);
            errorBox = null;
        }
        pageLoaded = false;
        pythonError = "";
        web.setVisibility(View.INVISIBLE);
        if (splash != null) {
            splash.setAlpha(1f);
            splash.setVisibility(View.VISIBLE);
        }
        if (splashTip != null) splashTip.setText("正在启动本地引擎…");
        new Thread(new Runnable() {
            @Override
            public void run() {
                ensureEngine(true);
                if (waitServer(110)) return;
                showBootError();
            }
        }, "mobit-retry").start();
    }

    /* ---------------------------------------------------------------- 链接 / 返回 */

    private boolean handleUrl(Uri uri) {
        if (uri == null) return false;
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();
        if ("file".equals(scheme) || "about".equals(scheme)) return false;
        if ("http".equals(scheme) || "https".equals(scheme)) {
            // 本机服务留在 WebView；外站交给系统浏览器
            if ("127.0.0.1".equals(uri.getHost()) || "localhost".equals(uri.getHost())) return false;
            openExternal(uri);
            return true;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception ignored) { }
        return true;
    }

    private void openExternal(Uri uri) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception e) {
            toast("无法打开外部链接");
        }
    }

    private void injectHelpers() {
        String js = "(function(){"
                + "document.documentElement.classList.add('in-app');"
                + "window.__MOBIT_APP__=true;"
                + "if(window.__mobitBlobHooked)return;window.__mobitBlobHooked=true;"
                + "document.addEventListener('click',function(e){"
                + "  var a=e.target&&e.target.closest?e.target.closest('a[download]'):null;"
                + "  if(!a||!a.href||a.href.indexOf('blob:')!==0)return;"
                + "  e.preventDefault();e.stopPropagation();"
                + "  fetch(a.href).then(function(r){return r.blob();}).then(function(b){"
                + "    var fr=new FileReader();"
                + "    fr.onload=function(){"
                + "      var s=String(fr.result);var i=s.indexOf(',');"
                + "      Native.downloadBase64(a.getAttribute('download')||'下载文件',b.type||'application/octet-stream',s.substring(i+1));"
                + "    };"
                + "    fr.readAsDataURL(b);"
                + "  }).catch(function(){Native.toast('下载失败');});"
                + "},true);"
                + "})();";
        web.evaluateJavascript(js, null);
    }

    /* ---------------------------------------------------------------- 下载 */

    private void downloadUrl(final String url, final String ua, final String disposition, final String mime) {
        toast("开始下载…");
        new Thread(new Runnable() {
            @Override
            public void run() {
                HttpURLConnection conn = null;
                try {
                    conn = (HttpURLConnection) new URL(url).openConnection();
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(60000);
                    if (ua != null) conn.setRequestProperty("User-Agent", ua);
                    String cookie = CookieManager.getInstance().getCookie(url);
                    if (cookie != null) conn.setRequestProperty("Cookie", cookie);
                    int code = conn.getResponseCode();
                    if (code < 200 || code >= 300) throw new Exception("HTTP " + code);
                    final String name = pickFileName(url, disposition, mime);
                    ByteArrayOutputStream bos = new ByteArrayOutputStream();
                    InputStream in = new BufferedInputStream(conn.getInputStream());
                    byte[] buf = new byte[16384];
                    int n;
                    while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
                    in.close();
                    final String path = saveBytes(name, mime, bos.toByteArray());
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            toast(path == null ? "保存失败" : "已保存：" + path);
                        }
                    });
                } catch (final Exception e) {
                    ui.post(new Runnable() {
                        @Override
                        public void run() {
                            toast("下载失败：" + e.getMessage());
                        }
                    });
                } finally {
                    if (conn != null) conn.disconnect();
                }
            }
        }).start();
    }

    private static String pickFileName(String url, String disposition, String mime) {
        String name = "";
        if (disposition != null) {
            String[] parts = disposition.split(";");
            for (String p : parts) {
                String t = p.trim();
                if (t.toLowerCase().startsWith("filename*=")) {
                    String v = t.substring(10).trim();
                    int idx = v.indexOf("''");
                    if (idx >= 0) v = v.substring(idx + 2);
                    try {
                        name = URLDecoder.decode(v, "UTF-8");
                    } catch (Exception ignored) {
                        name = v;
                    }
                } else if (t.toLowerCase().startsWith("filename=")) {
                    String v = t.substring(9).trim();
                    if (v.startsWith("\"") && v.endsWith("\"") && v.length() > 1) {
                        v = v.substring(1, v.length() - 1);
                    }
                    try {
                        name = URLDecoder.decode(v, "UTF-8");
                    } catch (Exception ignored) {
                        name = v;
                    }
                }
            }
        }
        if (name.isEmpty()) {
            try {
                String path = Uri.parse(url).getLastPathSegment();
                if (path != null) name = URLDecoder.decode(path, "UTF-8");
            } catch (Exception ignored) { }
        }
        if (name == null || name.trim().isEmpty() || name.contains("/") || name.contains("\\")) {
            name = "墨写下载-" + System.currentTimeMillis();
            if (mime != null && mime.contains("text")) name += ".txt";
        }
        return name.trim();
    }

    private String saveBytes(String name, String mime, byte[] data) {
        String type = (mime == null || mime.isEmpty()) ? "application/octet-stream" : mime;
        try {
            if (Build.VERSION.SDK_INT >= 29) {
                ContentValues v = new ContentValues();
                v.put(MediaStore.Downloads.DISPLAY_NAME, name);
                v.put(MediaStore.Downloads.MIME_TYPE, type);
                v.put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS + "/墨写");
                v.put(MediaStore.Downloads.IS_PENDING, 1);
                Uri item = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
                if (item == null) return null;
                OutputStream out = getContentResolver().openOutputStream(item);
                if (out == null) return null;
                out.write(data);
                out.close();
                v.clear();
                v.put(MediaStore.Downloads.IS_PENDING, 0);
                getContentResolver().update(item, v, null, null);
                return "下载/墨写/" + name;
            }
            File dir = new File(Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_DOWNLOADS), "墨写");
            if (!dir.exists() && !dir.mkdirs()) {
                dir = new File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), "墨写");
                if (!dir.exists()) dir.mkdirs();
            }
            File f = new File(dir, name);
            FileOutputStream fos = new FileOutputStream(f);
            fos.write(data);
            fos.close();
            return f.getAbsolutePath();
        } catch (Exception e) {
            Log.e(TAG, "save failed", e);
            return null;
        }
    }

    private static void deleteRecursively(File f) {
        if (f == null || !f.exists()) return;
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteRecursively(k);
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }

    /* ---------------------------------------------------------------- 文件选择 / 返回键 */

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_FILE) return;
        if (fileCallback == null) return;
        Uri[] results = null;
        if (resultCode == RESULT_OK && data != null) {
            if (data.getClipData() != null) {
                int count = data.getClipData().getItemCount();
                results = new Uri[count];
                for (int i = 0; i < count; i++) {
                    results[i] = data.getClipData().getItemAt(i).getUri();
                }
            } else if (data.getData() != null) {
                results = new Uri[]{data.getData()};
            }
        }
        fileCallback.onReceiveValue(results);
        fileCallback = null;
    }

    @Override
    public void onBackPressed() {
        if (web == null) {
            super.onBackPressed();
            return;
        }
        // 返回键优先关闭最上层浮层：抽屉 → 搜索面板 → 弹窗 → 页内候选/历史层；
        // 都没有时才走网页后退 / 退出，避免「弹窗还开着就退出页面」
        web.evaluateJavascript(
                "(function(){"
                        + "if(document.querySelector('.app.menu-open')){"
                        + "window.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));return '1';}"
                        + "var s=document.querySelector('.tb-search-sheet');"
                        + "if(s){var c=s.querySelector('.link-btn');if(c){c.click();}return '1';}"
                        // 取 z-index 最高的可见弹层：角色编辑抽屉上叠确认框时，返回键先关最上层
                        + "var ms=document.querySelectorAll('.modal-mask');"
                        + "if(ms.length){var best=null,bz=-999;"
                        + "for(var i=0;i<ms.length;i++){var el=ms[i];var st=getComputedStyle(el);"
                        + "if(st.display==='none'||st.visibility==='hidden')continue;"
                        + "var z=parseInt(st.zIndex||'0',10);if(isNaN(z))z=0;"
                        + "if(z>=bz){bz=z;best=el;}}"
                        + "if(best){var x=best.querySelector('.modal-x');if(x){x.click();}return '1';}}"
                        + "var cm=document.querySelector('.cand-mask');"
                        + "if(cm){cm.click();return '1';}"
                        + "return '0';})()",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if ("\"1\"".equals(value)) return;
                        backFallback();
                    }
                });
    }

    private void backFallback() {
        if (web == null) {
            finish();
            return;
        }
        if (web.canGoBack()) {
            web.goBack();
            return;
        }
        long now = System.currentTimeMillis();
        if (now - lastBackAt < 2000) {
            finish();
        } else {
            lastBackAt = now;
            toast("再按一次返回键退出");
        }
    }

    private void toast(final String msg) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                Toast.makeText(MainActivity.this, msg, Toast.LENGTH_SHORT).show();
            }
        });
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    /* ---------------------------------------------------------------- JS 桥 */

    public class Bridge {

        @JavascriptInterface
        public boolean isLocal() {
            return true;
        }

        @JavascriptInterface
        public String getVersion() {
            return "2.8.0";
        }

        @JavascriptInterface
        public String dataDir() {
            return getFilesDir().getAbsolutePath();
        }

        @JavascriptInterface
        public void reload() {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    web.reload();
                }
            });
        }

        @JavascriptInterface
        public void openExternal(final String url) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    if (url != null && (url.startsWith("http") || url.startsWith("mailto:")
                            || url.startsWith("tel:"))) {
                        MainActivity.this.openExternal(Uri.parse(url));
                    }
                }
            });
        }

        @JavascriptInterface
        public void toast(String msg) {
            MainActivity.this.toast(msg == null ? "" : msg);
        }

        @JavascriptInterface
        public void downloadBase64(final String name, final String mime, final String b64) {
            new Thread(new Runnable() {
                @Override
                public void run() {
                    try {
                        byte[] data = Base64.decode(b64, Base64.DEFAULT);
                        final String p = saveBytes(name == null || name.isEmpty() ? "墨写下载" : name, mime, data);
                        MainActivity.this.toast(p == null ? "保存失败" : "已保存：" + p);
                    } catch (Exception e) {
                        MainActivity.this.toast("保存失败：" + e.getMessage());
                    }
                }
            }).start();
        }

        @JavascriptInterface
        public void exitApp() {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    finish();
                }
            });
        }
    }
}

