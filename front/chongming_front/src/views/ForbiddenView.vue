<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
    <div class="forbidden-container">
        <el-result icon="warning" title="403" sub-title="抱歉，您没有权限访问该页面">
            <template #extra>
                <el-button type="primary" @click="router.push('/dashboard')">返回首页</el-button>
            </template>
        </el-result>
    </div>
</template>

<style scoped>
.forbidden-container {
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
}
</style>