<script setup lang="ts">
import brandIcon from '../assets/brand-icon.png'

const highlights = [
  {
    icon: 'M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3Z',
    title: '角色隔离',
    desc: '仅管理员与客服可进入，普通用户账号无法登录后台',
  },
  {
    icon: 'M5 11V8a7 7 0 0 1 14 0v3M4 11h16v10H4z',
    title: '会话安全',
    desc: '令牌仅保存在当前浏览器会话，不写入地址栏与日志',
  },
  {
    icon: 'M4 4h16v16H4zM8 9h8M8 13h8M8 17h5',
    title: '操作留痕',
    desc: '关键配置与数据变更自动写入审计日志，可追溯',
  },
]
</script>

<template>
  <div class="auth-shell">
    <section class="auth-shell__hero">
      <div class="auth-shell__hero-top">
        <img class="auth-shell__logo" :src="brandIcon" alt="墨写" />
        <span>
          <span class="auth-shell__brand-name">墨写</span>
          <span class="auth-shell__brand-sub">MOXIE OPERATIONS</span>
        </span>
      </div>

      <div class="auth-shell__hero-main">
        <p class="auth-shell__eyebrow">OPERATION CONSOLE</p>
        <h1 class="auth-shell__hero-title">运营后台</h1>
        <p class="auth-shell__hero-desc">管理用户、订单、订阅与系统配置，一处掌控全线服务状态。</p>
        <div class="auth-shell__points">
          <div v-for="item in highlights" :key="item.title" class="auth-shell__point">
            <span class="auth-shell__point-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path :d="item.icon" />
              </svg>
            </span>
            <span class="auth-shell__point-text">
              <strong>{{ item.title }}</strong>
              <small>{{ item.desc }}</small>
            </span>
          </div>
        </div>
      </div>

      <div class="auth-shell__hero-foot">
        <span class="auth-shell__dot" /> 安全连接 · 受控访问
      </div>
    </section>

    <section class="auth-shell__panel">
      <div class="auth-shell__box">
        <slot />
      </div>
    </section>
  </div>
</template>

<style>
/* 公共认证页布局与表单样式，三页共用；class 统一 auth- 前缀避免全局污染 */
.auth-shell {
  display: flex;
  align-items: stretch;
  justify-content: flex-start;
  min-height: 100dvh;
  padding: 0;
  background: var(--bg);
}

/* 左侧品牌区 */
.auth-shell__hero {
  position: relative;
  width: 46%;
  max-width: 620px;
  flex: none;
  padding: 40px 52px;
  display: flex;
  flex-direction: column;
  color: #e8eef7;
  background:
    radial-gradient(520px 380px at 18% 8%, rgba(25, 183, 165, .22), transparent 62%),
    radial-gradient(560px 420px at 92% 96%, rgba(115, 87, 214, .24), transparent 60%),
    linear-gradient(155deg, #111d30 0%, #0d1423 100%);
  overflow: hidden;
}
.auth-shell__hero::after {
  content: '';
  position: absolute;
  right: -120px;
  bottom: -140px;
  width: 360px;
  height: 360px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, .06);
  box-shadow: 0 0 0 60px rgba(255, 255, 255, .025), 0 0 0 120px rgba(255, 255, 255, .015);
  pointer-events: none;
}
.auth-shell__hero-top { display: flex; align-items: center; gap: 12px; position: relative; z-index: 1; }
.auth-shell__logo {
  width: 44px; height: 44px; flex: none; border-radius: 12px; display: block;
  object-fit: contain; padding: 3px;
  background: #f4f7f9; box-shadow: 0 8px 22px rgba(25, 183, 165, .3);
}
.auth-shell__hero-top > span:last-child { display: flex; flex-direction: column; }
.auth-shell__brand-name { font-size: 18px; font-weight: 700; color: #fff; letter-spacing: .5px; }
.auth-shell__brand-sub { font-size: 10.5px; color: #7f90a8; letter-spacing: 1.2px; margin-top: 2px; }

.auth-shell__hero-main { margin: auto 0; position: relative; z-index: 1; padding: 32px 0; }
.auth-shell__eyebrow { font-size: 11px; color: #4fd7c7; letter-spacing: 2.4px; font-weight: 600; }
.auth-shell__hero-title { font-size: 44px; font-weight: 800; color: #fff; letter-spacing: -1px; margin-top: 12px; line-height: 1.1; }
.auth-shell__hero-desc { font-size: 14px; color: #9fb0c6; line-height: 1.8; margin-top: 16px; max-width: 380px; }
.auth-shell__points { display: flex; flex-direction: column; gap: 18px; margin-top: 38px; }
.auth-shell__point { display: flex; align-items: flex-start; gap: 12px; }
.auth-shell__point-icon {
  width: 34px; height: 34px; flex: none; border-radius: 10px; display: flex;
  align-items: center; justify-content: center; color: #5ee0d0;
  background: rgba(25, 183, 165, .12); border: 1px solid rgba(25, 183, 165, .2);
}
.auth-shell__point-icon svg { width: 18px; height: 18px; }
.auth-shell__point-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.auth-shell__point-text strong { font-size: 13.5px; color: #eef4fb; font-weight: 600; }
.auth-shell__point-text small { font-size: 11.5px; color: #8496ad; line-height: 1.6; }
.auth-shell__hero-foot { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #71829a; position: relative; z-index: 1; }
.auth-shell__dot { width: 7px; height: 7px; border-radius: 50%; background: #2fbf8f; box-shadow: 0 0 0 4px rgba(47, 191, 143, .14); }

/* 右侧表单区 */
.auth-shell__panel {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 24px;
  background:
    radial-gradient(600px 400px at 88% 6%, rgba(15, 155, 142, .06), transparent 60%),
    var(--bg);
}
.auth-shell__box { width: min(400px, 100%); }

/* 通用表单元素 */
.auth-head { margin-bottom: 24px; }
.auth-kicker { font-size: 11px; color: var(--primary); font-weight: 700; letter-spacing: 2px; }
.auth-title { font-size: 26px; font-weight: 800; color: var(--text); letter-spacing: -.4px; margin-top: 8px; }
.auth-desc { font-size: 13px; color: var(--text-3); margin-top: 7px; line-height: 1.65; }
.auth-form { display: flex; flex-direction: column; gap: 16px; margin-top: 20px; }
.auth-form .field > label { font-size: 12.5px; }
.auth-input-wrap { position: relative; }
.auth-input-icon {
  position: absolute; left: 12px; top: 50%; transform: translateY(-50%);
  width: 17px; height: 17px; color: var(--text-3); pointer-events: none;
}
.input.auth-input--icon { padding-left: 38px; height: 42px; }
.input.auth-input--toggle { padding-right: 42px; }
.auth-pwd-toggle {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  width: 32px; height: 32px; border: none; border-radius: 8px; background: none;
  color: var(--text-3); display: inline-flex; align-items: center; justify-content: center;
}
.auth-pwd-toggle:hover { background: var(--primary-soft); color: var(--primary); }
.auth-pwd-toggle:disabled { cursor: not-allowed; opacity: .5; }
.auth-pwd-toggle svg { width: 17px; height: 17px; }
.auth-field-error { font-size: 11.5px; color: var(--red); margin: 5px 0 0; }
.auth-submit { height: 44px; width: 100%; margin-top: 4px; font-size: 13.5px; font-weight: 600; }
.auth-arrow { width: 16px; height: 16px; margin-left: 2px; }
.auth-links { display: flex; justify-content: flex-end; margin-top: 14px; gap: 12px; flex-wrap: wrap; }
.auth-links a { font-size: 12.5px; color: var(--primary); font-weight: 500; }
.auth-links a:hover { color: var(--primary-hover); }
.auth-action {
  display: flex; align-items: center; justify-content: center; height: 42px;
  border-radius: var(--radius-sm); background: var(--primary); color: #fff;
  font-size: 13px; font-weight: 600; margin-top: 18px;
}
.auth-action:hover { background: var(--primary-hover); color: #fff; }
.auth-foot { margin-top: 26px; padding-top: 16px; border-top: 1px solid var(--border); }
.auth-foot-row { display: flex; align-items: center; gap: 10px; font-size: 11.5px; color: var(--text-3); }
.auth-foot-row code { font-size: 11px; color: var(--text-2); background: #f2f6f5; padding: 2px 7px; border-radius: 5px; word-break: break-all; }
.auth-foot-hint { font-size: 11px; color: var(--text-3); line-height: 1.6; margin-top: 8px; }
.auth-dev-link { word-break: break-all; }
.auth-dev-link a { color: var(--primary); font-weight: 600; }

@media (max-width: 900px) {
  .auth-shell__hero { display: none; }
  .auth-shell__panel { padding: 24px 20px; }
}
@media (max-height: 560px) and (min-width: 901px) {
  .auth-shell__points { display: none; }
  .auth-shell__hero-title { font-size: 34px; }
}
</style>
