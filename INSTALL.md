# 墨写 安装与部署指南（新手版）

> 这份文档写给**完全不懂服务器部署**的人。每一步都是复制粘贴即可，遇到术语我会先用大白话解释。
> 部署包内另有一份 `DEPLOY.md`（命令速查），本文件更偏"为什么这么做 + 安全"。

---

## 0. 先看懂几个词（人话版）

| 词 | 大白话 | 你需要做什么 |
|----|--------|--------------|
| 服务器 / ECS / 云主机 | 一台 24 小时开机的远程电脑，租来的 | 去云厂商买一台 |
| Docker | 把整个应用连同环境"打包成集装箱"，到哪都能一模一样地跑，**不用自己装 Python / 数据库** | 在服务器上装一次即可 |
| SSH | 远程连上服务器的"命令行窗口" | 用终端连进去敲命令 |
| 域名 | 给 IP 起的好记名字（如 `moxie.example.com`） | 可选，但**想安全就必须有**（见 HTTPS） |
| 安全组 / 防火墙 | 服务器的"门禁"，控制哪些端口能从外网进来 | 只放 80 / 443，别的别开 |

---

## 1. 准备一台服务器

- **系统**：选 **Ubuntu 22.04 LTS**（对新手最友好，命令通用）。
- **配置**：最低 **2 核 4G 内存**，系统盘 **40G+**（镜像构建 + 数据库要空间）。
- **厂商**：阿里云 ECS / 腾讯云 CVM / 华为云 / AWS EC2 / 海外 Vultr 都行。
- **门禁（安全组）**：只放行 `22`(SSH)、`80`、`443`。**千万不要**把 `8000`(API)、`9000`(MinIO)、`5432`(Postgres)、`6379`(Redis) 对公网开放——这些只该在服务器内部互相访问。
- 记下三样东西：**公网 IP**、**登录用户名**（Ubuntu 一般是 `ubuntu`，或 `root`）、**密码或 SSH 密钥**。

---

## 2. 连上服务器

- **Windows**：用 PowerShell / 终端，或下载 PuTTY。
- **Mac / Linux**：直接打开"终端"。

```bash
ssh 用户名@你的公网IP
# 例： ssh ubuntu@1.2.3.4
# 首次会问 yes/no，输入 yes，再输密码
```

---

## 3. 装 Docker（一条命令，约 1 分钟）

在服务器上执行：

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

> 第二条让你不用每次都加 `sudo`。**执行后退出重连一次** SSH 才生效。

验证装好了没：

```bash
docker --version
docker compose version      # 注意：不是 docker-compose（旧版），要 v2
```

两条都打印出版本号就 OK。

---

## 4. 在你自己的电脑上打包

> 这一步在**你本地电脑**做（需要 Node.js + Git Bash；Windows 装 Git for Windows 就带 bash）。

```bash
# 进入项目根目录后
bash scripts/package.sh
```

跑完会在 `build/` 下生成 `moxie-deploy-<时间戳>.tar.gz`——这就是"部署包"。

---

## 5. 上传并解压到服务器

```bash
# 本地电脑执行（把包传上去）
scp build/moxie-deploy-*.tar.gz 用户名@你的公网IP:/opt/

# 然后 SSH 进服务器，解压
ssh 用户名@你的公网IP
sudo mkdir -p /opt/moxie && cd /opt/moxie
sudo tar -xzf /opt/moxie-deploy-*.tar.gz --strip-components=1
sudo chown -R $USER:$USER /opt/moxie   # 让当前用户能改文件
```

解压后 `/opt/moxie` 里应有 `server/`、`client/dist/`、`admin/dist/`、`start.sh` 等。

---

## 6. 生成密钥 + 改配置（★ 安全最重要的一步）

```bash
cd /opt/moxie
./preflight.sh --gen-secrets     # 自动生成 JWT / License / 载荷加密 三套密钥
```

然后编辑 `server/.env`（用 `nano server/.env` 或 `vim`）：

| 项 | 怎么改 | 为什么 |
|----|--------|--------|
| `CORS_ALLOW_ORIGINS` | 改成你的前端地址，如 `https://moxie.example.com`。**没有域名先填 `http://服务器IP`**（上线必须换 https） | 防任意网站冒用你的 API |
| `DATABASE_URL` | 把里面的 `change-me-in-production` 换成**强密码**，如 `postgresql+psycopg://moxie:你的强密码@postgres:5432/moxie` | 数据库口令不能留默认 |
| `MINIO_ROOT_PASSWORD` | 换成强密码（和 `S3_SECRET_KEY` 保持一致） | 对象存储口令 |
| 其它 `change-me` | 搜一下 `.env` 里还有没有 `change-me`，全部换掉 | 应用启动会拒绝默认口令 |

**生成强密码的小命令**（复制输出贴进 `.env`）：
```bash
openssl rand -base64 24
```

改完再校验一次：
```bash
./preflight.sh
```
应显示一堆 `✓`，最后 `✓ 配置校验通过`。

---

## 7. 启动

```bash
./start.sh        # 首次会构建镜像，耗时几分钟，耐心等
./status.sh       # 看容器是否都起来了
```

浏览器打开 `http://服务器IP/`（**临时用 http 看看效果**，正式必须走 https，见下）。

- 前端：`http://服务器IP/`
- 管理端：`http://服务器IP/admin/`
- 接口文档：`http://服务器IP/v1/docs`

---

## 8. 强烈建议：开启 HTTPS（加密传输）

> **为什么必须做**：现在默认是 `http`，你的**登录令牌（JWT）和密钥是明文传输**的，在公共网络被截获就等于账号被盗。上线请务必上 HTTPS。

**有域名时（推荐）：**
1. 在域名控制台把 `A 记录` 指向服务器公网 IP。
2. 在服务器装 certbot 申请**免费**证书：
   ```bash
   sudo apt update && sudo apt install -y certbot
   sudo certbot certonly --standalone -d 你的域名
   # 证书默认在 /etc/letsencrypt/live/你的域名/
   ```
3. 把证书拷到部署包的 certs 目录：
   ```bash
   mkdir -p /opt/moxie/server/nginx/certs
   sudo cp /etc/letsencrypt/live/你的域名/fullchain.pem /opt/moxie/server/nginx/certs/
   sudo cp /etc/letsencrypt/live/你的域名/privkey.pem  /opt/moxie/server/nginx/certs/
   sudo chown -R $USER:$USER /opt/moxie/server/nginx/certs
   ```
4. 启用 HTTPS 版配置并重载：
   ```bash
   cd /opt/moxie
   mv server/nginx/default.https.conf server/nginx/default.conf
   docker compose -f server/docker-compose.yml -f server/docker-compose.web.yml up -d nginx
   ```
5. 把 `server/.env` 里的 `CORS_ALLOW_ORIGINS` 改为 `https://你的域名`，再 `./start.sh`。
6. **放通安全组的 443 端口**（80 也保留，会自动跳 https）。

**没有域名时（临时方案）：**
- 用 Cloudflare 的"橙云代理"把流量包一层 TLS；或暂时只用内网/局域网访问，不要在有公网明文暴露的情况下长期使用。

---

## 9. 安全清单（上线前逐条核对）

| 优先级 | 项目 | 怎么做 |
|--------|------|--------|
| 🔴 最高 | 改掉所有默认口令 | `JWT_SECRET`、`DATABASE_URL` 密码、`MINIO_ROOT_PASSWORD`/`S3_SECRET_KEY` 全部换掉；默认 `change-me` 会被启动拒绝 |
| 🔴 最高 | 开启 HTTPS | 见第 8 节，否则令牌明文 |
| 🟠 高 | `.env` 文件权限 | 脚本已自动 `chmod 600 server/.env`（仅属主可读）；**备份出来的 `env.env` 同样含全部密钥，存到加密盘或异地** |
| 🟠 高 | 端口不暴露内网服务 | 安全组/防火墙**只开 80/443**；`5432/6379/9000/8000` 绝不对外 |
| 🟠 高 | CORS 不用 `*` | `CORS_ALLOW_ORIGINS` 填具体域名，否则任意网站可借用户浏览器调你的 API |
| 🟡 中 | SSH 加固 | 设强密码或改用**密钥登录**、关闭密码登录、可改默认 22 端口、装 `fail2ban` 防爆破 |
| 🟡 中 | 系统更新 | `sudo apt update && sudo apt upgrade -y` |
| 🟡 中 | 备份异地保存 | `./backup.sh` 生成的 `backups/` 要**下载到本地或对象存储**，只在服务器本地不算安全 |
| 🟢 低 | 不填用不到的密钥 | 支付/微信/支付宝密钥留空即可，不启用就不影响；别图省事填示例值 |
| 🟢 低 | 慎用 `down -v` | `docker compose ... down -v` 会**删除数据库卷**，只在确认要清空时执行 |

---

## 10. 日常运维

```bash
./status.sh                 # 看容器状态 + 健康检查
./logs.sh -f api            # 实时看后端日志（Ctrl+C 退出）
./backup.sh                 # 备份数据库+产物+配置 到 backups/
./restore.sh                # 从最新备份恢复（会删库重建，先确认）
./stop.sh                   # 停止（数据卷保留）
```

**升级版本：**
1. 本地重新 `bash scripts/package.sh` 出包。
2. 上传覆盖 `/opt/moxie`，然后 `./stop.sh` → `./start.sh`（镜像按新代码重建）。

---

## 11. 常见问题

- **`./start.sh` 启动失败**：多半是 `.env` 里还有 `change-me` 占位口令没改，看 `./logs.sh api`。
- **80 端口被占用**：在 `server/.env` 设 `WEB_PORT=8080`（或别的），重启。
- **前端白屏 / 404**：本地打包时没构建前端，重跑 `bash scripts/package.sh`。
- **HTTPS 后 443 连不上**：确认安全组开了 443，且 `server/nginx/certs/` 里有 `fullchain.pem` + `privkey.pem`。
- **忘了 `.env` 改了什么**：`./preflight.sh` 会逐项告诉你哪不合格。

---

> 提示：部署包里自带的 `DEPLOY.md` 是命令速查版；本文件是新手+安全版。两份配合看即可。
