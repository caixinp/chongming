<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
</script>

<template>
    <div class="dashboard">
        <h2>欢迎回来，{{ authStore.username }}</h2>
        <el-card class="info-card">
            <template #header>
                <span>个人信息</span>
            </template>
            <el-descriptions :column="2" border>
                <el-descriptions-item label="用户名">{{ authStore.userInfo?.username }}</el-descriptions-item>
                <el-descriptions-item label="邮箱">{{ authStore.userInfo?.email || '-' }}</el-descriptions-item>
                <el-descriptions-item label="用户ID">{{ authStore.userInfo?.user_id }}</el-descriptions-item>
                <el-descriptions-item label="角色">{{ authStore.userRoles.join(', ') }}</el-descriptions-item>
            </el-descriptions>
        </el-card>

        <el-card class="info-card" style="margin-top: 20px">
            <template #header>
                <span>拥有权限</span>
            </template>
            <div v-if="authStore.permissions.length > 0">
                <el-tag
                    v-for="perm in authStore.permissions"
                    :key="perm.id"
                    style="margin: 4px"
                    type="success"
                >
                    {{ perm }}
                </el-tag>
            </div>
            <el-empty v-else description="暂无权限数据" />
        </el-card>
    </div>
</template>

<style scoped>
.dashboard {
    padding: 0;
}
.dashboard h2 {
    margin-bottom: 20px;
}
.info-card {
    max-width: 800px;
}
</style>