<script setup lang="ts">
defineProps<{ open: boolean; title: string; wide?: boolean; layer?: 'base' | 'confirm' }>()
const emit = defineEmits<{ (e: 'update:open', v: boolean): void }>()
function close() { emit('update:open', false) }
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-mask" :class="{ 'confirm-layer': layer === 'confirm' }" @mousedown.self="close">
      <div class="modal" :class="{ wide }">
        <div class="modal-head">
          <h3>{{ title }}</h3>
          <button class="modal-x" @click="close">×</button>
        </div>
        <div class="modal-body"><slot /></div>
        <div v-if="$slots.footer" class="modal-foot"><slot name="footer" /></div>
      </div>
    </div>
  </Teleport>
</template>
