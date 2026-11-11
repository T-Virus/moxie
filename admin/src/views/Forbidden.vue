<script setup lang="ts">
import { computed } from 'vue'
import { denial } from '../guard'
import { hiddenNavLabels, ROLE_LABEL } from '../roles'
import { getRole } from '../session'
import StateBlock from '../components/StateBlock.vue'

const role = getRole()
const roleLabel = ROLE_LABEL[role || ''] || role || '未知'
const hidden = computed(() => hiddenNavLabels(role))
</script>

<template>
  <div class="card">
    <StateBlock
      kind="notready"
      title="权限不足"
      :message="denial.message || `当前账号（${roleLabel}）无权访问该模块。`"
      :endpoint="denial.required ? `缺少权限：${denial.required}` : ''"
    >
      <router-link class="btn ghost sm" to="/overview">返回概览</router-link>
    </StateBlock>
    <div v-if="hidden.length" class="notice warn" style="margin-bottom: 0">
      <div class="notice-body">
        <div class="notice-title">当前角色已隐藏以下菜单</div>
        <div>{{ hidden.join('、') }}。如确需访问，请使用管理员（admin）账号登录。</div>
      </div>
    </div>
  </div>
</template>
