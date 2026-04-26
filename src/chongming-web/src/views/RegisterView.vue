<!-- src/views/RegisterView.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { ElCard, ElForm, ElFormItem, ElInput, ElButton, ElLink } from 'element-plus'

const router = useRouter()
const authStore = useAuthStore()
const form = ref({ email: '', username: '', password: '' })
const loading = ref(false)

async function handleRegister() {
  loading.value = true
  const success = await authStore.register(form.value.email, form.value.password, form.value.username)
  loading.value = false
  if (success) router.push('/todos')
}
</script>

<template>
  <div class="page-container">
    <el-card class="card">
      <template #header>
        <h2>注册</h2>
      </template>
      <el-form :model="form" @submit.prevent="handleRegister">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" type="email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="form.username" placeholder="可选" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">
            注册
          </el-button>
        </el-form-item>
        <el-form-item>
          <el-link type="info" @click="$router.push('/login')">已有账号？去登录</el-link>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.page-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: #f5f7fa;
}
.card {
  width: 400px;
}
</style>