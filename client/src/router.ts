import { createRouter, createWebHistory } from 'vue-router'
import Home from '@/views/Home.vue'
import Auth from '@/views/Auth.vue'
import Plans from '@/views/Plans.vue'
import Runs from '@/views/Runs.vue'
import Tools from '@/views/Tools.vue'
import Workspace from '@/views/Workspace.vue'
import Legal from '@/views/Legal.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: Home },
    { path: '/login', name: 'login', component: Auth },
    { path: '/plans', name: 'plans', component: Plans },
    { path: '/runs', name: 'runs', component: Runs },
    { path: '/runs/:id', name: 'workspace', component: Workspace, props: true },
    { path: '/tools', name: 'tools', component: Tools },
    { path: '/legal', name: 'legal', component: Legal },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

export default router
