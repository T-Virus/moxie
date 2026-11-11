<script setup lang="ts">
import Modal from './Modal.vue'
import { confirmState, resolveConfirm } from '../ui'
</script>

<template>
  <!-- 遮罩点击 / ESC 关闭也算「取消」：否则 confirmBox 的 Promise 永久悬挂，调用点后续逻辑中断 -->
  <Modal :open="confirmState.open" title="请确认" layer="confirm" @update:open="v => { if (!v) resolveConfirm(false) }">
    <div style="padding:6px 0 10px;line-height:1.8">{{ confirmState.msg }}</div>
    <template #footer>
      <button class="btn ghost" @click="resolveConfirm(false)">取消</button>
      <button class="btn" :class="{ danger: confirmState.danger }" @click="resolveConfirm(true)">
        {{ confirmState.ok }}
      </button>
    </template>
  </Modal>
</template>
