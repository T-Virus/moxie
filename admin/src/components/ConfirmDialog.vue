<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { confirmState, resolveConfirm } from '../dialog'
import Icon from './Icon.vue'

function onKey(event: KeyboardEvent) {
  if (!confirmState.open) return
  if (event.key === 'Escape') resolveConfirm(false)
}

onMounted(() => window.addEventListener('keydown', onKey))
onUnmounted(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div v-if="confirmState.open" class="modal-overlay" @mousedown.self="resolveConfirm(false)">
      <div class="modal narrow confirm-dialog" role="alertdialog" aria-modal="true">
        <div class="modal-head">
          <div class="confirm-icon" :class="confirmState.options.danger ? 'danger' : 'info'">
            <Icon :name="confirmState.options.danger ? 'warning' : 'info'" :size="20" />
          </div>
          <div class="confirm-heading">
            <h3>{{ confirmState.options.title }}</h3>
          </div>
          <button class="close" type="button" title="关闭" @click="resolveConfirm(false)">
            <Icon name="close" :size="18" />
          </button>
        </div>
        <div class="modal-body">
          <p class="confirm-message">{{ confirmState.options.message }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn ghost" type="button" @click="resolveConfirm(false)">
            {{ confirmState.options.cancelText }}
          </button>
          <button
            class="btn"
            :class="confirmState.options.danger ? 'danger' : ''"
            type="button"
            @click="resolveConfirm(true)"
          >
            {{ confirmState.options.confirmText }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
