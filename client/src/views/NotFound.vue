<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="card notfound">
    <div class="notfound-code">404</div>
    <h2>页面不存在</h2>
    <p>你访问的地址不存在或已被移动。</p>
    <div class="notfound-actions">
      <button class="btn primary" type="button" @click="router.push('/')">返回首页</button>
      <button class="btn" type="button" @click="router.back()">返回上一页</button>
    </div>
  </div>
</template>

<style scoped>
.notfound {
  max-width: 520px;
  margin: 10vh auto;
  padding: 48px 32px;
  text-align: center;
}
.notfound-code {
  font-size: 72px;
  font-weight: 700;
  line-height: 1;
  color: var(--accent, #0d9488);
  opacity: 0.75;
}
.notfound h2 {
  margin: 16px 0 8px;
  font-size: 22px;
}
.notfound p {
  margin: 0 0 24px;
  color: var(--muted, #6b7280);
}
.notfound-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
}
</style>
