import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { login as loginApi, getUserPermissions } from '@/api/auth'
import type { UserLoginResponse } from '@/api/generated/types.gen'

export interface PermissionItem {
    id: number
    name: string
    resource: string
    action: string
    description: string
}

export interface RoleItem {
    id: number
    name: string
    description: string
}

export const useAuthStore = defineStore('auth', () => {
    const token = ref<string>(localStorage.getItem('token') || '')
    const userInfo = ref<UserLoginResponse | null>(null)
    const permissions = ref<PermissionItem[]>([])
    const roles = ref<RoleItem[]>([])

    const isLoggedIn = computed(() => !!token.value)
    const username = computed(() => userInfo.value?.username || '')
    const userRoles = computed(() => roles.value.map((r) => r.name))

    function hasPermission(permName: string): boolean {
        return permissions.value.some((p) => p.name === permName)
    }

    function hasAnyPermission(permNames: string[]): boolean {
        return permNames.some((name) => hasPermission(name))
    }

    function hasRole(roleName: string): boolean {
        return roles.value.some((r) => r.name === roleName)
    }

    async function login(username: string, password: string) {
        const res = await loginApi(username, password)
        token.value = res.token
        userInfo.value = res
        localStorage.setItem('token', res.token)

        // 获取用户权限和角色
        try {
            const permRes = await getUserPermissions(res.user_id)
            permissions.value = (permRes.permissions || []) as PermissionItem[]
            roles.value = (permRes.roles || []) as RoleItem[]
        } catch {
            permissions.value = []
            roles.value = []
        }
    }

    function logout() {
        token.value = ''
        userInfo.value = null
        permissions.value = []
        roles.value = []
        localStorage.removeItem('token')
    }

    return {
        token,
        userInfo,
        permissions,
        roles,
        isLoggedIn,
        username,
        userRoles,
        hasPermission,
        hasAnyPermission,
        hasRole,
        login,
        logout,
    }
})