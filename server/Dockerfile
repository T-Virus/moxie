FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

# 封面排版需要中文字体；slim 镜像默认没有 CJK 字体
# 数据库备份/恢复依赖 pg_dump / pg_restore（PostgreSQL 客户端）
# 国内直连 deb.debian.org 很慢，先切到阿里云镜像源加速
RUN (sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null \
     || sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null \
     || true) \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 优先使用精确版本锁文件，保证构建可复现；锁文件缺失时回退到带版本上界的 requirements.txt。
COPY requirements*.txt ./
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
      -r $(test -f requirements.lock.txt && echo requirements.lock.txt || echo requirements.txt)

COPY . .
# 预建备份目录：命名卷首次挂载会继承镜像里目录的属主；
# 若镜像里不存在，Docker 会创建 root:root 目录导致 appuser 无法写入备份。
RUN mkdir -p /app/backups && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
