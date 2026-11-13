# -*- coding: utf-8 -*-
"""服务端配置：全部来自环境变量 / server/.env。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = SERVER_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(SERVER_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def is_production(self) -> bool:
        """安全闸门的唯一判定口径：除显式开发/测试环境外一律按生产处理。

        原来各处散落 `env in ("prod","production")` / `env != "production"` /
        `env not in ("test","dev")`，写法不一致（例如 ENV=prod 时验证链接仍会
        回显、ENV=staging 时弱密钥校验被跳过）。统一为白名单后，任何非
        dev/test 的环境都会强制执行生产校验。
        """
        return self.env.strip().lower() not in {"dev", "test", "testing", "local"}

    app_name: str = "moxie-server"
    env: str = "dev"
    # 是否暴露 /docs /redoc /openapi.json；留空时仅非生产环境开启。
    docs_enabled: bool | None = None
    api_prefix: str = "/v1"
    # 是否信任反向代理注入的 X-Forwarded-For 作为客户端真实 IP。
    # 默认 False：直接取直连对端 IP，防止客户端伪造 XFF 绕过基于 IP 的限流/失败锁定。
    # 仅在确有可信反向代理（且代理会重写/丢弃客户端原始 XFF）时显式设为 True。
    trust_proxy: bool = False

    # 管理端跨域白名单（逗号分隔）；不允许 "*"，credentials 仅在明确来源时开启
    cors_allow_origins: str = "http://127.0.0.1:5180,http://localhost:5180"
    cors_allow_methods: str = "GET,POST,PATCH,DELETE,OPTIONS"
    cors_allow_headers: str = (
        "Authorization,Content-Type,Idempotency-Key,X-Request-Id,"
        "X-Rights-Confirmed,X-BYOK-Key,"
        "X-Payload-Key,X-Payload-Client,X-Payload-Nonce,X-Payload-Encrypted"
    )
    cors_max_age_seconds: int = 600

    # 数据库：开发默认 SQLite；生产用 postgresql+psycopg://...
    database_url: str = f"sqlite:///{(SERVER_DIR / 'novel_server.db').as_posix()}"
    auto_create_tables: bool = True

    # Redis：队列 / 限流 / 预占缓存
    redis_enabled: bool = True
    redis_url: str = "redis://127.0.0.1:6379/0"

    # JWT
    jwt_secret: str = "dev-only-change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30

    # 应用层载荷加密：ECDH(P-256) + AES-256-GCM
    payload_encryption_enabled: bool = True
    # 强制 JSON 接口必须使用密文；仅在测试/过渡期关闭
    payload_encryption_required: bool = True
    # 生产必须显式配置 EC P-256 私钥 PEM；开发环境留空则进程内临时生成
    payload_crypto_private_key_pem: str = ""

    # 设备与 License
    max_devices: int = 2
    license_refresh_days: int = 7
    license_grace_days: int = 14
    license_key_id: str = "moxie-license-1"
    license_private_key_pem: str | None = None

    # 支付
    # mock/fake 回调签名密钥；留空时 mock/fake 渠道拒绝注册（必须显式配置）
    mock_payment_secret: str = ""
    # mock/fake 渠道默认关闭；仅 test/dev 环境允许打开，生产环境启动即失败
    payments_mock_enabled: bool = False
    payments_fake_enabled: bool = False
    payment_timeout_seconds: float = 20.0
    webhook_tolerance_seconds: int = 300
    subscription_reminder_days: int = 7
    subscription_grace_days: int = 3
    # 可选：支付回调来源 IP 白名单（逗号分隔）；留空表示只依赖渠道签名校验
    payment_webhook_ip_allowlist: str = ""
    # 定时对账覆盖的渠道（逗号分隔）
    payment_reconcile_providers: str = "wechat,alipay,stripe"

    # 微信支付 v3
    wechat_mch_id: str = ""
    wechat_app_id: str = ""
    wechat_api_v3_key: str = ""
    # 商户 API 私钥 / 平台证书（PEM 内容或文件路径二选一）
    wechat_private_key_pem: str = ""
    wechat_private_key_path: str = ""
    wechat_cert_serial_no: str = ""
    wechat_platform_cert_pem: str = ""
    wechat_platform_cert_path: str = ""
    wechat_platform_serial_no: str = ""
    wechat_notify_url: str = ""
    wechat_api_base: str = "https://api.mch.weixin.qq.com"
    wechat_pay_scene: str = "native"  # native|jsapi|h5

    # 支付宝
    alipay_app_id: str = ""
    alipay_private_key_pem: str = ""
    alipay_private_key_path: str = ""
    alipay_public_key_pem: str = ""
    alipay_public_key_path: str = ""
    alipay_seller_id: str = ""
    alipay_gateway: str = "https://openapi.alipay.com/gateway.do"
    alipay_notify_url: str = ""
    alipay_return_url: str = ""
    alipay_scene: str = "page"  # page|precreate

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_success_url: str = "http://127.0.0.1:8000/v1/payments/stripe/success"
    stripe_cancel_url: str = "http://127.0.0.1:8000/v1/payments/stripe/cancel"
    stripe_portal_return_url: str = "http://127.0.0.1:8000/v1/payments/stripe/portal-return"
    stripe_api_base: str = "https://api.stripe.com"

    # 电子发票渠道：stub（本地模拟，默认）/ nuonuo（真实适配位）
    invoice_provider: str = "stub"
    # 回调验签密钥（stub 与真实渠道共用）；缺失时回调返回 501
    invoice_callback_secret: str = ""
    # stub 可指向本地 HTTP 模拟服务；留空则纯内存即时开票
    invoice_stub_url: str = ""
    # 真实渠道凭据（缺任意一项返回 501 invoice_provider_not_configured）
    invoice_api_base: str = "https://open.nuonuo.com"
    invoice_app_key: str = ""
    invoice_app_secret: str = ""
    invoice_seller_tax_no: str = ""

    # 调度与可观测
    scheduler_enabled: bool = False
    scheduler_interval_seconds: int = 60
    task_lease_seconds: int = 1800
    metrics_enabled: bool = True
    # /metrics 访问令牌：配置后需带 X-Metrics-Token 头（或 ?token=）；
    # 生产环境未配置时 /metrics 直接拒绝，避免队列/业务指标公开暴露。
    metrics_token: str = ""
    sentry_dsn: str = ""
    register_rate_limit_per_minute: int = 10
    login_rate_limit_per_minute: int = 20
    # 全局限流兜底：每 IP 每分钟请求数上限，防止刷接口耗尽资源（DoS）
    rate_limit_enabled: bool = True
    global_rate_limit_per_minute: int = 600
    # 认证类接口（注册/登录/刷新/验证等）单独用更严格的阈值
    auth_rate_limit_per_minute: int = 60
    # 登录失败锁定：窗口内连续失败达到上限后拒绝，防止密码暴力破解
    login_failure_limit: int = 5
    login_failure_window_seconds: int = 900
    usage_alert_multiplier: float = 3.0


    # 额度包：默认有效期 12 个月，不清零（到期后剩余作废，不结转）
    credit_pack_validity_days: int = 365
    # 退款按已用量折算：使用比例达到该值即视为已消耗完，可退 0
    refund_proration_enabled: bool = True

    # 通知
    notifications_enabled: bool = True
    notification_inapp_enabled: bool = True
    notification_email_enabled: bool = False
    notification_sms_enabled: bool = False
    notification_email_transport: str = "smtp"  # smtp|fake（fake 仅写发送记录，不连外网）
    notification_max_attempts: int = 3
    notification_retry_backoff_seconds: int = 300
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@moxie.local"
    smtp_use_tls: bool = True
    smtp_timeout_seconds: float = 10.0
    # 短信适配位：无凭据时 no-op（只记 skipped），接入后替换 provider
    sms_provider: str = "noop"  # noop|fake
    sms_api_url: str = ""
    sms_api_key: str = ""
    sms_sender: str = ""

    # 公开榜单抓取（热门写作调研）：只抓元数据，不抓正文；失败自动跳过
    ranking_enabled: bool = True
    ranking_sources: str = "qidian,fanqie,zongheng,jinjiang"
    ranking_female_sources: str = "xxsy,hongxiu,jinjiang"
    ranking_timeout_seconds: float = 6.0
    ranking_cache_seconds: int = 21600

    # 模型网关
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""  # 留空，运行时从环境变量 LLM_API_KEY 读取；请勿在此硬编码密钥
    # 后台自定义模型网关地址的 SSRF 防护：默认禁止指向内网 / 回环 / 云元数据地址。
    # 自托管 Ollama 等确实需要内网地址时，显式设为 true 并自行承担出站风险。
    model_gateway_allow_private_networks: bool = False
    llm_model: str = "deepseek-v4-flash"
    gateway_timeout_seconds: float = 120.0
    gateway_max_retries: int = 2
    gateway_rate_limit_per_minute: int = 60
    # 每 1000 token 成本（分），仅用于成本归集展示
    model_price_cents_per_1k_tokens: float = 0.8
    # 无真实 key / 测试时使用确定性假模型（不会访问外网）
    model_stub: bool = False
    # 工序模型配置里 api_key 的加密口令；留空则不加密（仅建议本地开发）。
    # 优先与环境变量 MODEL_KEY_SECRET 配合，回退到 artifact_signing_secret。
    model_key_secret: str = ""

    # 拆解链路
    src_path: str = str(ROOT_DIR / "src")
    # 每处理多少段主动让出 worker（0=不限）；用于分批执行与断点验证
    decompose_segment_batch: int = 0
    # 相似度检查（纯本地计算，不调用模型）：n-gram 长度、重合率阈值、单章最多输出段数
    similarity_ngram: int = 8
    similarity_threshold: float = 0.35
    similarity_max_paragraphs: int = 20
    # 允许读取的源文件根目录（逗号分隔，相对 ROOT_DIR 或绝对路径）
    task_source_dirs: str = "input,data"
    task_max_source_bytes: int = 5 * 1024 * 1024

    # 客户端上传源文件（POST /v1/uploads）
    upload_max_bytes: int = 30 * 1024 * 1024
    upload_allowed_extensions: str = ".txt,.md,.markdown,.csv,.json"
    upload_rate_limit_per_minute: int = 10
    # 上传源文件保留天数；0 = 不自动清理（只能显式 DELETE）
    upload_retention_days: int = 30

    # Agent 参考写作分段拆解：默认与 runners/decompose.py 的阈值对齐
    agent_segment_chars: int = 6000
    agent_segment_chapters: int = 2
    # 无章节结构且不超过该字数视为结构化大纲，按单段处理（不硬切碎）
    agent_outline_single_segment_chars: int = 20000
    # 单本源文件字符上限 / 段数上限；超出显式失败，禁止静默截断
    agent_max_source_chars: int = 600000
    agent_max_segments: int = 100

    # 产物存储：db（默认，全部落库）/ local（磁盘 fallback）/ s3（MinIO / OSS / S3）
    storage_backend: str = "db"
    storage_local_dir: str = str(SERVER_DIR / "artifacts")
    # 本地签名下载的对外地址前缀；留空则返回相对路径
    storage_public_base_url: str = ""
    artifact_presign_seconds: int = 900
    artifact_signing_secret: str = ""
    s3_endpoint_url: str = "http://minio:9000"
    s3_bucket: str = "moxie"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "change-me-minio-secret"
    s3_region: str = "us-east-1"
    s3_secure: bool = False
    # 容器内访问 S3 用 S3_ENDPOINT_URL；预签名链接需要浏览器可访问的地址
    # 例如 compose 里 S3_ENDPOINT_URL=http://minio:9000，公开地址为 http://127.0.0.1:9000
    s3_public_endpoint_url: str = ""

    # 离线安装包下载：接口按扩展名在各目录中取最新构建产物（后台未上传时的回退）
    offline_windows_dir: str = str(ROOT_DIR / "dist")
    offline_android_dir: str = str(ROOT_DIR / "mobile" / "dist")
    # 后台上传安装包的单文件大小上限（字节），默认 2GiB
    offline_package_max_bytes: int = 2 * 1024 * 1024 * 1024

    # AI 封面：优先 OpenAI 兼容的 /images/generations，失败回退 Pollinations，
    # 再失败用本地代码绘制底图；不配置 image_api_key 时直接走免费兜底。
    image_api_base: str = ""
    image_api_key: str = ""
    image_model: str = ""
    cover_pollinations_enabled: bool = True
    cover_width: int = 1400
    cover_height: int = 2100
    cover_timeout_seconds: int = 180
    cover_upload_max_bytes: int = 10 * 1024 * 1024

    # 版权确认闸门：拆解/改编任务必须显式确认（测试环境可关闭）
    legal_gate_enabled: bool = True
    # 法律文本当前版本号：注册勾选时校验并写入留痕；升级后旧客户端需重新同意
    legal_terms_version: str = "2026-11-01"

    # 邮箱验证：注册后必须验证邮箱才能登录（测试环境可关闭）
    email_verification_required: bool = True
    # 验证令牌有效期（分钟）
    email_verify_token_ttl_minutes: int = 1440
    # 前端基地址：用于拼接验证邮件里的链接；留空则使用请求 Origin 头
    app_client_base_url: str = ""
    # 同一账号两次验证邮件的最小发送间隔（秒）：防止接口被无限盗刷/对第三方邮箱轰炸
    email_resend_cooldown_seconds: int = 60

    # 多 worker 部署必须显式配置 License 私钥；禁止自动生成临时密钥
    license_allow_ephemeral_key: bool = False

    log_level: str = "INFO"

    @property
    def sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")
