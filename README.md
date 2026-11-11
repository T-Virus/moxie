# 墨写 Moxie · 合规优先的 AI 小说创作工作流平台

> **把"AI 辅助写小说"从玩具变成能合规上线的生产工具。**
> 智能大纲/章节拆解 · 改编幅度检测 · 参考授权与 AIGC 标注闸门 · 多端一致（Web / 桌面 / 安卓）· 内置订阅与 License · 一键自托管部署。

[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Deploy](https://img.shields.io/badge/deploy-Docker%20Compose-success.svg)](INSTALL.md)
[![GitHub](https://img.shields.io/badge/GitHub-T--Virus/moxie-blue?logo=github)](https://github.com/T-Virus/moxie)
[![Afdian](https://img.shields.io/badge/爱发电-aimoxie-orange)](https://afdian.com/a/aimoxie)
[![Sponsor](https://img.shields.io/badge/❤-赞助%20Sponsor-orange.svg)](#赞助我)

---

## 为什么要做墨写？

AI 写小说已经很火，但真正能**合规、可控、能上线**的工具很少。创作者面临三条红线：

- **改编幅度 / 抄袭**：AI 容易"借鉴"过度，作者却难以量化自己的改写比例。
- **参考作品授权**：使用他人作品做参考/二创，必须确认使用权——这是法律要求，不是可选项。
- **AIGC 标注**：生成式 AI 内容需要明确标注（如国内《生成式人工智能服务管理暂行办法》）。

现有工具大多只做"对话机器人"，要么不管合规、要么闭源收费、要么不能自己部署。
**墨写把"合规"做进工作流本身**，而不是事后补救：在拆解和改编之前，就强制确认参考作品使用权并留下 AIGC 标注，再用本地相似度检测守住改编幅度。

---

## 核心特性

- 🧩 **智能拆解**：长篇小说的大纲 / 章节被拆解成可并发执行的任务，由 RQ 任务队列调度，支持断点续跑。
- 📐 **改编幅度 / 相似度检测**：本地 n-gram 相似度分析，量化"借鉴"比例，防止过度雷同。
- 🛡️ **合规闸门（Legal Gate）**：拆解 / 改编任务前，强制确认参考作品使用权与 AIGC 标注，未确认不执行。
- 🖥️ **多端一致**：
  - 云端前端 `client/`（站点根）
  - 管理后台 `admin/`（订阅、License、风控）
  - 桌面离线端（Windows / 安卓，基于 PyWebView）
  - 移动端（Android，Chaquopy + Gradle）
- 💳 **订阅与 License**：微信支付 / 支付宝 / Stripe，额度包，设备数限制，Ed25519 License 签名校验。
- 🔐 **数据自托管**：Docker Compose 一键部署，数据库、缓存、对象存储全在你自己的服务器，数据不出域。
- 🌐 **模型网关**：统一 LLM 网关，支持自定义 `base_url` / `api_key`（DeepSeek 等），并保留确定性假模型用于测试。

---

## 架构

```
                 ┌──────────── 多端 ────────────┐
   Web(client)   Admin       桌面离线端         Android
        │          │            │                │
        └──────────┴──────┬─────┴────────────────┘
                          ▼
                  nginx (Web 网关 / 同源 /v1)
                          │
                          ▼
                  FastAPI  api:8000
              ┌───────────┼────────────┐
           worker       scheduler    (RQ 队列 / 定时调度)
              └───────────┼────────────┘
      ┌─────────┬─────────┼──────────┬─────────┐
   Postgres   Redis     MinIO      artifacts   (数据卷持久化)
```

所有组件通过 Docker Compose 编排；前端由 nginx 托管并同源反代 `/v1`，免去跨域烦恼。

---

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python · FastAPI · SQLAlchemy · Alembic · RQ · Pydantic |
| 存储 | PostgreSQL · Redis · MinIO(S3 兼容) |
| 前端 | Vue 3 · Vite（`client` / `admin` / `web`） |
| 桌面端 | PyWebView · PyInstaller / Nuitka |
| 移动端 | Android · Chaquopy · Gradle |
| 部署 | Docker Compose · nginx |

---

## 快速开始

- **新手 / 服务器部署（含安全与 HTTPS）**：见 [INSTALL.md](INSTALL.md)
- **本地开发**：仓库根 `start.bat`（Windows 一键起全栈）
- **打包部署包**：`bash scripts/package.sh` → 产出 `build/moxie-deploy-*.tar.gz`
- **运维脚本**（部署包内）：`preflight.sh` / `start.sh` / `stop.sh` / `status.sh` / `logs.sh` / `backup.sh` / `restore.sh`

```bash
# 本地一键起全栈（Windows）
start.bat

# 生成可上服务器的部署包（需 Node + bash）
bash scripts/package.sh
```

---

## 路线图

- [ ] 协作写作 / 多人权限
- [ ] 更多模型与本地模型（Ollama）接入
- [ ] 插件 / 提示词市场
- [ ] 国际化（i18n）与多语言前端
- [ ] SaaS 多租户版本

---

## 赞助我 💛

墨写是一个**个人独立开源项目**。它不收集你的数据、不强加订阅，靠的是：

- 服务器与带宽成本
- 模型 API 调用费用（开发/演示用）
- 作者几乎全部的业余时间

如果你觉得这个项目有用，或者你相信"合规的 AI 创作工具"值得存在，**任何形式的赞助都是我继续做下去的理由**——哪怕只是一杯咖啡的钱。

### 赞助方式

| 渠道 | 链接 / 说明 |
|------|-------------|
| ⭐ GitHub 仓库 | https://github.com/T-Virus/moxie （Star / Watch / 提 Issue 都是对开源的支持） |
| 🥤 爱发电 (Afdian) | https://afdian.com/a/aimoxie |
| 💰 微信赞赏 | 扫码下方收款码（支付宝赞赏码欢迎 PR 补充） |
| ☕ 一次性捐赠 | 任意金额都欢迎，留言"墨写"即可 |

<p align="center">
  <img src="docs/wechat-pay.png" alt="微信收款码 · 赞赏墨写" width="240" />
  <br/>
  <sub>微信收款码 · 赞赏「墨写 Moxie」</sub>
</p>

### 赞助者能得到的

| 档位 | 回馈 |
|------|------|
| ☕ 一杯咖啡（¥20+） | 进入赞助者名单（如你愿意） |
| 🍱 一个月服务器（¥100+） | 优先响应你的需求 / Issue |
| 🚀 长期赞助（¥500+/月） | 联合署名、路线图投票权、定制功能咨询 |

> 赞助不影响软件的完全开源与免费使用。所有赞助将公开透明地用于项目本身。

---

## 许可证 License

本项目以 **AGPL-3.0**（Affero 通用公共许可证 v3.0）发布——这是一份强 copyleft 许可证，**即使你把它部署成网络服务（SaaS），衍生修改也必须开源**，非常适合保护这类自托管创作工具的开放性。完整文本见仓库 [LICENSE](LICENSE)。若你对许可证选择有建议，欢迎提 Issue 讨论。

---

<p align="center">
  用爱发电，也欢迎用电瓶车充电 ⚡<br/>
  <b>墨写 Moxie</b> — 让 AI 写小说，合规且安心。
</p>
