<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { navigationConfig, type NavItem } from '@/config/navigation'
import {
    HomeFilled,
    User,
    Avatar,
    Key,
    Setting,
    ArrowLeftBold,
    ArrowRightBold,
    SwitchButton,
} from '@element-plus/icons-vue'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const isCollapsed = ref(false)

/**
 * 根据用户权限过滤可见的导航项
 */
const visibleNavItems = computed(() => {
    function filterByPermission(items: NavItem[]): NavItem[] {
        return items
            .map((item) => {
                const children = item.children ? filterByPermission(item.children) : undefined
                // 父级自身可见条件：无权限要求 或 用户拥有该权限
                const parentVisible =
                    item.permission === null || authStore.hasPermission(item.permission)
                // 如果父级可见或有子级可见，则保留
                if (parentVisible || (children && children.length > 0)) {
                    return { ...item, children }
                }
                return null
            })
            .filter((item): item is NavItem => item !== null)
    }
    return filterByPermission(navigationConfig)
})

/** 当前激活的导航项路径 */
const activeNavPath = computed(() => {
    const path = route.path
    // 高亮当前路径或父级路径
    for (const item of visibleNavItems.value) {
        if (item.path === path) return item.path
        if (item.children?.some((c) => c.path === path)) return item.path
    }
    return path
})

/** 当前展开的 sub-menu */
const openedMenus = computed(() => {
    return visibleNavItems.value
        .filter((item) => item.children && item.children.length > 0)
        .map((item) => item.path)
})

const iconMap: Record<string, any> = {
    HomeFilled,
    User,
    Avatar,
    Key,
    Setting,
}

function getIcon(iconName: string) {
    return iconMap[iconName]
}

function handleSelect(index: string) {
    router.push(index)
}

function handleLogout() {
    authStore.logout()
    router.push('/login')
}
</script>

<template>
    <el-container style="min-height: 100vh">
        <!-- 侧边栏 -->
        <el-aside :width="isCollapsed ? '64px' : '220px'" class="sidebar-container">
            <div class="sidebar-header" :class="{ collapsed: isCollapsed }">
                <span v-show="!isCollapsed" class="sidebar-title">崇明管理</span>
                <el-icon
                    class="collapse-btn"
                    :size="20"
                    @click="isCollapsed = !isCollapsed"
                >
                    <ArrowLeftBold v-if="!isCollapsed" />
                    <ArrowRightBold v-else />
                </el-icon>
            </div>

            <el-menu
                :default-active="activeNavPath"
                :default-openeds="openedMenus"
                :collapse="isCollapsed"
                :collapse-transition="false"
                router
                background-color="#304156"
                text-color="#bfcbd9"
                active-text-color="#409eff"
                @select="handleSelect"
            >
                <template v-for="item in visibleNavItems" :key="item.path">
                    <!-- 有子菜单 -->
                    <el-sub-menu
                        v-if="item.children && item.children.length > 0"
                        :index="item.path"
                    >
                        <template #title>
                            <el-icon v-if="getIcon(item.icon)">
                                <component :is="getIcon(item.icon)" />
                            </el-icon>
                            <span>{{ item.title }}</span>
                        </template>
                        <el-menu-item
                            v-for="child in item.children"
                            :key="child.path"
                            :index="child.path"
                        >
                            <el-icon v-if="getIcon(child.icon)">
                                <component :is="getIcon(child.icon)" />
                            </el-icon>
                            <span>{{ child.title }}</span>
                        </el-menu-item>
                    </el-sub-menu>

                    <!-- 无子菜单 -->
                    <el-menu-item v-else :index="item.path">
                        <el-icon v-if="getIcon(item.icon)">
                            <component :is="getIcon(item.icon)" />
                        </el-icon>
                        <span>{{ item.title }}</span>
                    </el-menu-item>
                </template>
            </el-menu>
        </el-aside>

        <!-- 右侧主区域 -->
        <el-container>
            <!-- 顶部栏 -->
            <el-header class="main-header">
                <div class="header-right">
                    <el-dropdown trigger="click">
                        <span class="user-info">
                            欢迎，<strong>{{ authStore.username }}</strong>
                            <el-icon class="el-icon--right"><ArrowLeftBold /></el-icon>
                        </span>
                        <template #dropdown>
                            <el-dropdown-menu>
                                <el-dropdown-item>
                                    <span>角色：{{ authStore.userRoles.join(', ') }}</span>
                                </el-dropdown-item>
                                <el-dropdown-item divided @click="handleLogout">
                                    <el-icon><SwitchButton /></el-icon>
                                    <span>退出登录</span>
                                </el-dropdown-item>
                            </el-dropdown-menu>
                        </template>
                    </el-dropdown>
                </div>
            </el-header>

            <!-- 内容区 -->
            <el-main class="main-content">
                <router-view />
            </el-main>
        </el-container>
    </el-container>
</template>

<style scoped>
.sidebar-container {
    background-color: #304156;
    transition: width 0.3s;
    overflow: hidden;
}

.sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 60px;
    padding: 0 16px;
    background-color: #2b3a4a;
    transition: padding 0.3s;
}

.sidebar-header.collapsed {
    justify-content: center;
    padding: 0;
}

.sidebar-title {
    color: #fff;
    font-size: 18px;
    font-weight: bold;
    white-space: nowrap;
}

.collapse-btn {
    color: #bfcbd9;
    cursor: pointer;
    flex-shrink: 0;
}

.collapse-btn:hover {
    color: #fff;
}

.el-menu {
    border-right: none;
}

.main-header {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    background-color: #fff;
    border-bottom: 1px solid #e6e6e6;
    padding: 0 20px;
}

.header-right {
    display: flex;
    align-items: center;
    gap: 16px;
}

.user-info {
    display: flex;
    align-items: center;
    cursor: pointer;
    color: #606266;
    gap: 6px;
}

.user-info strong {
    color: #303133;
}

.main-content {
    background-color: #f0f2f5;
    padding: 20px;
}
</style>