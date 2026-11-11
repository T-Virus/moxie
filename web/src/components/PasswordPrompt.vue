<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import Modal from './Modal.vue'
import { passwordState, resolvePassword } from '../ui'

/* 导出包口令输入：确认返回口令，取消 / 关闭返回 null（调用点据此中止流程） */
const input = ref<HTMLInputElement | null>(null)
watch(() => passwordState.open, v => { if (v) nextTick(() => input.value?.focus()) })

function ok() {
  const v = passwordState.value.trim()
  if (v) resolvePassword(v)
}
</script>

<template>
  <Modal :open="passwordState.open" :title="passwordState.title" layer="confirm"
         @update:open="v => { if (!v) resolvePassword(null) }">
    <div class="pwd-msg">{{ passwordState.msg }}</div>
    <input ref="input" class="input" type="password" v-model="passwordState.value"
           :placeholder="passwordState.placeholder" autocomplete="new-password"
           @keydown.enter.prevent="ok" />
    <template #footer>
      <button class="btn ghost" @click="resolvePassword(null)">取消</button>
      <button class="btn" :disabled="!passwordState.value.trim()" @click="ok">确定</button>
    </template>
  </Modal>
</template>

<style scoped>
.pwd-msg { padding: 6px 0 12px; line-height: 1.8; white-space: pre-line; }
</style>
