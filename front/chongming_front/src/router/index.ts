import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { NavItem } from '@/config/navigation'
import { navigationConfig } from '@/config/navigation'

/**
 * 从导航配置中递归提取所有路由
 */
function flattenRoutes(items: NavItem[]): Array<{
  path: string
  name: string
  permission: string | null
}> {
  const result: Array<{ path: string; name: string; permission: string | null }> = []
  for (const item of items) {
    result.push({ path: item.path, name: item.routeName, permission: item.permission })
    if (item.children) {
      result.push(...flattenRoutes(item.children))
    }
  }
  return result
}

/** 所有需要权限的动态路由 */
const dynamicRoutes = flattenRoutes(navigationConfig)

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      redirect: '/dashboard',
    },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: () => import('@/views/DashboardView.vue'),
      meta: { requiresAuth: true, permission: null },
    },
    {
      path: '/users',
      name: 'users',
      component: () => import('@/views/UsersView.vue'),
      meta: { requiresAuth: true, permission: 'user.login' },
    },
    {
      path: '/roles',
      name: 'roles',
      component: () => import('@/views/RolesView.vue'),
      meta: { requiresAuth: true, permission: 'role.list' },
    },
    {
      path: '/permissions',
      name: 'permissions',
      component: () => import('@/views/PermissionsView.vue'),
      meta: { requiresAuth: true, permission: 'permission.list' },
    },
    {
      path: '/system',
      name: 'system',
      component: () => import('@/views/SystemView.vue'),
      meta: { requiresAuth: true, permission: 'role.create' },
    },
    // 403 无权限页面
    {
      path: '/403',
      name: 'forbidden',
      component: () => import('@/views/ForbiddenView.vue'),
      meta: { requiresAuth: false },
    },
    // 404
    {
      path: '/:pathMatch(.*)*',
      name: 'notFound',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { requiresAuth: false },
    },
  ],
})

// 全局路由守卫：鉴权 + 权限判断
router.beforeEach((to, _from, next) => {
  const authStore = useAuthStore()

  // 不需要登录的页面直接放行
  if (to.meta.requiresAuth === false) {
    next()
    return
  }

  // 需要登录但未登录 -> 跳转登录页
  if (!authStore.isLoggedIn) {
    next({ name: 'login', query: { redirect: to.fullPath } })
    return
  }

  // 已登录：检查权限
  const requiredPermission = to.meta.permission as string | null | undefined
  if (requiredPermission) {
    if (!authStore.hasPermission(requiredPermission)) {
      // 没有权限 -> 跳转 403
      next({ name: 'forbidden' })
      return
    }
  }

  next()
})

export { dynamicRoutes }
export default router