<template>
  <main class="page legal">
    <div class="legal__head">
      <h1 class="page-title">法律与合规</h1>
      <p class="page-sub">本页文本适用于墨写云端服务，当前版本 {{ LEGAL_VERSION }}。</p>
    </div>

    <SegmentedTabs v-model="tab" :tabs="tabs" class="legal__tabs" />

    <article class="card legal__body">
      <template v-if="tab === 'privacy'">
        <h2>隐私政策</h2>
        <p>墨写（下称“本服务”）由运营方提供，我们仅收集为提供创作与订阅服务所必需的最小范围个人信息。</p>
        <h3>我们收集的信息</h3>
        <ul>
          <li>账号信息：邮箱或手机号（用于登录与找回）、加密后的密码哈希。</li>
          <li>设备与日志：IP 地址、User-Agent、请求时间（用于安全与限流，不用于画像）。</li>
          <li>订阅与支付：订单号、金额、渠道状态；支付渠道返回的 openid 等标识会脱敏存储。</li>
          <li>创作数据：你主动上传的参考作品与生成的稿件，仅用于完成拆解/改编/体检任务。</li>
        </ul>
        <h3>我们如何使用信息</h3>
        <ul>
          <li>提供、维护与改进本服务；</li>
          <li>完成订阅开通、额度扣减与账单对账；</li>
          <li>履行法定义务与安全风控。</li>
        </ul>
        <p>我们不会出售你的个人信息，也不会在未经授权的情况下将你的稿件用于训练或对外披露。</p>
        <h3>数据保留与删除</h3>
        <p>你可以在账号设置中申请导出或删除个人数据；我们会在 30 日内处理。账号注销后，关联的稿件与订阅数据将按留存政策清理。</p>
      </template>

      <template v-else-if="tab === 'terms'">
        <h2>用户协议</h2>
        <p>使用本服务前，请确认你已阅读并同意以下条款。</p>
        <h3>账号与使用</h3>
        <ul>
          <li>你须保证注册信息真实有效，并对账号下的一切行为负责。</li>
          <li>你不得利用本服务生成或传播违法违规、侵犯他人合法权益的内容。</li>
        </ul>
        <h3>内容与版权</h3>
        <ul>
          <li>你上传的参考作品，须确保已获得合法的改编/使用权。</li>
          <li>本服务生成的内容不构成对任何真实作品名称、人物、情节的复制授权；你需要自行保证输出不侵权。</li>
        </ul>
        <h3>订阅与退款</h3>
        <ul>
          <li>订阅与额度按套餐约定扣减，具体以《退款政策》为准。</li>
          <li>服务可能因维护或不可抗力中断，我们不承担由此产生的间接损失。</li>
        </ul>
        <h3>终止</h3>
        <p>如你违反本协议或相关法律，我们有权暂停或终止服务并保留追究责任的权利。</p>
      </template>

      <template v-else-if="tab === 'refund'">
        <h2>退款政策</h2>
        <p>我们支持在合理范围内的退款请求，具体规则如下：</p>
        <ul>
          <li>自支付成功之日起 7 日内，如未实际使用对应额度，可申请全额退款。</li>
          <li>已消耗的额度按比例扣除后，剩余部分可退；已完成的拆解/改编/体检任务不支持按产出退款。</li>
          <li>退款将在审核通过后按原支付渠道原路退回，到账时间以支付渠道为准。</li>
          <li>通过欺诈、滥用免费额度或违反用户协议获得的权益不予退款。</li>
        </ul>
        <p>申请退款请通过客服渠道提交订单号与退款原因。</p>
      </template>

      <template v-else-if="tab === 'aigc'">
        <h2>AIGC 标识说明</h2>
        <p>本服务使用人工智能生成内容（AIGC），为满足合规与披露要求，我们作出以下说明：</p>
        <ul>
          <li>由本服务生成的稿件、大纲、设定与体检建议，均属 AIGC 产出。</li>
          <li>导出交付物时默认附加 AIGC 声明，标明“AI 生成合成内容”。</li>
          <li>本服务用于“合规拆解与再创作”辅助，不承诺也不提供规避平台 AI 检测的能力。</li>
          <li>请在对外发布时遵守各平台的 AI 内容标注规则与相关法律法规。</li>
        </ul>
        <p>我们默认对全部生成内容进行 AIGC 标注；如你用于商业发布，请自行完成平台侧的必要披露。</p>
      </template>

      <template v-else-if="tab === 'license'">
        <h2>授权链声明</h2>
        <p>使用拆解/改编类功能前，你必须声明素材来源合法，并在提交时勾选确认。可选基础如下：</p>
        <table class="legal__table">
          <thead>
            <tr><th>基础</th><th>含义</th><th>需保留的凭证</th></tr>
          </thead>
          <tbody>
            <tr><td>原创</td><td>素材由你本人创作</td><td>创作底稿、发布时间记录</td></tr>
            <tr><td>已获授权</td><td>已取得著作权人书面授权</td><td>授权书/合同扫描件</td></tr>
            <tr><td>公有领域</td><td>作品已进入公有领域</td><td>来源与作者卒年证明</td></tr>
            <tr><td>合法引用/评论</td><td>属于合理使用范围</td><td>引用范围说明</td></tr>
            <tr><td>平台授权内容</td><td>平台明确允许二次创作</td><td>平台条款截图</td></tr>
          </tbody>
        </table>
        <p>服务端会记录同意版本、基础类型、时间戳、IP 与来源标识并写入审计日志，供争议时举证。若声明不实，你独立承担全部责任。</p>
      </template>

      <template v-else-if="tab === 'subprocessors'">
        <h2>子处理者清单</h2>
        <p>为提供服务，我们会把必要数据委托给以下类型的第三方处理者，均位于中国境内，并按不低于本隐私政策的要求签署数据处理条款：</p>
        <table class="legal__table">
          <thead>
            <tr><th>处理者类型</th><th>处理的数据</th><th>目的</th></tr>
          </thead>
          <tbody>
            <tr><td>云主机与对象存储</td><td>账号、稿件、备份、日志</td><td>计算与存储</td></tr>
            <tr><td>数据库/缓存托管</td><td>账号、订单、任务状态</td><td>数据持久化</td></tr>
            <tr><td>大模型服务商</td><td>提示词与生成上下文</td><td>生成内容</td></tr>
            <tr><td>支付渠道</td><td>订单号、金额、支付状态</td><td>收款与退款</td></tr>
            <tr><td>邮件推送</td><td>邮箱地址、验证内容</td><td>验证与通知</td></tr>
            <tr><td>错误监控（可选）</td><td>脱敏错误堆栈</td><td>故障排查</td></tr>
          </tbody>
        </table>
        <p>新增或更换子处理者将提前 30 日在本页公告；公告期内你有权提出异议并终止服务。</p>
      </template>

      <template v-else>
        <h2>试点服务等级（SLA）</h2>
        <p>适用于签署试点协议的客户，期限默认 3 个月。指标按自然月统计：</p>
        <table class="legal__table">
          <thead>
            <tr><th>指标</th><th>目标</th></tr>
          </thead>
          <tbody>
            <tr><td>API 月度可用性</td><td>≥ 99.5%</td></tr>
            <tr><td>任务成功率</td><td>≥ 95%</td></tr>
            <tr><td>单章生成时延 P95</td><td>≤ 90 秒</td></tr>
            <tr><td>导出可用性</td><td>≥ 99.5%</td></tr>
          </tbody>
        </table>
        <h3>支持与响应</h3>
        <ul>
          <li>首响：试点客户 2 小时，标准客户 4 小时。</li>
          <li>阻断性问题（无法生成/支付/导出）：试点 4 小时、标准 8 小时内闭环。</li>
          <li>退款 3 个工作日，发票 5 个工作日。</li>
          <li>升级路径：一线支持 → 技术负责人 → 产品负责人。</li>
        </ul>
        <h3>服务信用</h3>
        <p>月度可用性低于 99.5% 将按档抵扣下期费用（5%–20%）；须在故障次月内申请。完整条款见交付包文档。</p>
      </template>
    </article>
  </main>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import SegmentedTabs, { type SegmentedTab } from '@/components/SegmentedTabs.vue'
import { LEGAL_VERSION } from '@/services/authApi'

type LegalTab = 'privacy' | 'terms' | 'refund' | 'aigc' | 'license' | 'subprocessors' | 'sla'

const tabs: SegmentedTab[] = [
  { id: 'privacy', label: '隐私政策' },
  { id: 'terms', label: '用户协议' },
  { id: 'refund', label: '退款政策' },
  { id: 'aigc', label: 'AIGC 标识说明' },
  { id: 'license', label: '授权链声明' },
  { id: 'subprocessors', label: '子处理者清单' },
  { id: 'sla', label: '试点 SLA' },
]

const LEGAL_TABS: LegalTab[] = ['privacy', 'terms', 'refund', 'aigc', 'license', 'subprocessors', 'sla']

const route = useRoute()
const tab = ref<LegalTab>('terms')

watch(
  () => route.query.doc,
  (doc) => {
    if (LEGAL_TABS.includes(doc as LegalTab)) tab.value = doc as LegalTab
  },
  { immediate: true },
)
</script>

<style scoped>
.legal {
  max-width: 860px;
  margin: 0 auto;
}

.legal__head {
  text-align: center;
  margin-bottom: var(--space-6);
}

.legal__tabs {
  justify-content: center;
  margin-bottom: var(--space-6);
}

.legal__body {
  padding: var(--space-6) var(--space-8);
  font-size: var(--text-sm);
  line-height: 1.8;
  color: var(--color-text-2);
}

.legal__body h2 {
  font-size: var(--text-xl);
  color: var(--color-text-1);
  margin: 0 0 var(--space-4);
}

.legal__body h3 {
  font-size: var(--text-base);
  color: var(--color-text-1);
  margin: var(--space-5) 0 var(--space-2);
}

.legal__body ul {
  margin: var(--space-2) 0 var(--space-4);
  padding-left: var(--space-6);
}

.legal__body li {
  margin-bottom: var(--space-1);
}

.legal__table {
  width: 100%;
  border-collapse: collapse;
  margin: var(--space-3) 0 var(--space-4);
  font-size: var(--text-sm);
}
.legal__table th,
.legal__table td {
  border: 1px solid var(--color-line);
  padding: var(--space-2) var(--space-3);
  text-align: left;
  vertical-align: top;
}
.legal__table th {
  background: var(--color-bg-soft);
  color: var(--color-text);
  font-weight: 600;
}
</style>
