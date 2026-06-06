<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElMessage } from 'element-plus'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const loginForm = ref({
    username: '',
    password: '',
})
const loading = ref(false)

async function handleLogin() {
    if (!loginForm.value.username || !loginForm.value.password) {
        ElMessage.warning('请输入用户名和密码')
        return
    }
    loading.value = true
    try {
        await authStore.login(loginForm.value.username, loginForm.value.password)
        ElMessage.success('登录成功')
        const redirect = (route.query.redirect as string) || '/dashboard'
        router.push(redirect)
    } catch (err: any) {
        ElMessage.error(err?.message || '登录失败，请检查用户名和密码')
    } finally {
        loading.value = false
    }
}
</script>

<template>
    <div class="login-container">
        <div class="login-card">
            <h1 class="login-title">崇明管理平台</h1>
            <el-form :model="loginForm" label-position="top" @submit.prevent="handleLogin">
                <el-form-item label="用户名">
                    <el-input
                        v-model="loginForm.username"
                        placeholder="请输入用户名"
                        size="large"
                        :prefix-icon="'User'"
                    />
                </el-form-item>
                <el-form-item label="密码">
                    <el-input
                        v-model="loginForm.password"
                        type="password"
                        placeholder="请输入密码"
                        size="large"
                        show-password
                        :prefix-icon="'Lock'"
                    />
                </el-form-item>
                <el-form-item>
                    <el-button
                        type="primary"
                        size="large"
                        :loading="loading"
                        style="width: 100%"
                        @click="handleLogin"
                    >
                        登 录
                    </el-button>
                </el-form-item>
            </el-form>
        </div>
    </div>
</template>

<style scoped>
.login-container {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.login-card {
    width: 400px;
    padding: 40px;
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
}

.login-title {
    text-align: center;
    margin-bottom: 30px;
    font-size: 24px;
    color: #303133;
}
</style>