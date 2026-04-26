<!-- src/views/TodoView.vue -->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useTodoStore } from '@/stores/todo'
import { useAuthStore } from '@/stores/auth'
import {
  ElContainer,
  ElHeader,
  ElMain,
  ElButton,
  ElInput,
  ElCheckbox,
  ElPopconfirm,
  ElMessage,
  ElCard,
  ElRow,
  ElCol,
  ElSpace,
  ElEmpty,
} from 'element-plus'
import { Plus, Edit, Delete, Check, Close } from '@element-plus/icons-vue'

const todoStore = useTodoStore()
const authStore = useAuthStore()
const router = useRouter()

const newTitle = ref('')
const newDesc = ref('')
const adding = ref(false)

const editingId = ref<number | null>(null)
const editTitle = ref('')
const editDesc = ref('')
const editCompleted = ref(false)

onMounted(() => {
  todoStore.fetchTodos()
})

async function addTodo() {
  if (!newTitle.value.trim()) {
    ElMessage.warning('请输入标题')
    return
  }
  adding.value = true
  await todoStore.addTodo({
    title: newTitle.value,
    description: newDesc.value || null,
  })
  newTitle.value = ''
  newDesc.value = ''
  adding.value = false
  ElMessage.success('添加成功')
}

function startEdit(todo: any) {
  editingId.value = todo.id
  editTitle.value = todo.title
  editDesc.value = todo.description || ''
  editCompleted.value = todo.completed
}

async function saveEdit(id: number) {
  await todoStore.updateTodo(id, {
    title: editTitle.value,
    description: editDesc.value || null,
    completed: editCompleted.value,
  })
  editingId.value = null
  ElMessage.success('更新成功')
}

async function toggleComplete(todo: any) {
  await todoStore.updateTodo(todo.id, { completed: !todo.completed })
}

async function handleDelete(id: number) {
  await todoStore.deleteTodo(id)
  ElMessage.success('删除成功')
}

function logout() {
  authStore.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <el-header>
      <div class="header">
        <h2>✅ 待办清单</h2>
        <el-button type="danger" plain @click="logout">退出登录</el-button>
      </div>
    </el-header>
    <el-main>
      <div class="content-wrapper">
        <el-card class="add-card">
          <template #header>新建待办</template>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-input v-model="newTitle" placeholder="标题" clearable />
            </el-col>
            <el-col :span="10">
              <el-input v-model="newDesc" placeholder="描述（可选）" clearable />
            </el-col>
            <el-col :span="6">
              <el-button type="primary" :icon="Plus" :loading="adding" @click="addTodo">
                添加
              </el-button>
            </el-col>
          </el-row>
        </el-card>

        <el-card v-loading="todoStore.loading" class="list-card">
          <template #header>我的待办 ({{ todoStore.todos.length }})</template>
          <div v-if="todoStore.todos.length === 0">
            <el-empty description="暂无待办，添加一条吧" />
          </div>
          <div v-else class="todo-list">
            <div v-for="todo in todoStore.todos" :key="todo.id" class="todo-item">
              <template v-if="editingId !== todo.id">
                <div class="todo-content">
                  <el-checkbox :model-value="todo.completed" @change="() => toggleComplete(todo)" />
                  <div class="todo-text" :class="{ completed: todo.completed }">
                    <strong>{{ todo.title }}</strong>
                    <span v-if="todo.description" class="desc">{{ todo.description }}</span>
                  </div>
                </div>
                <div class="todo-actions">
                  <el-button text type="primary" :icon="Edit" @click="startEdit(todo)" />
                  <el-popconfirm title="确定删除此项？" @confirm="handleDelete(todo.id)">
                    <template #reference>
                      <el-button text type="danger" :icon="Delete" />
                    </template>
                  </el-popconfirm>
                </div>
              </template>
              <template v-else>
                <div class="edit-form">
                  <el-input v-model="editTitle" placeholder="标题" size="small" />
                  <el-input v-model="editDesc" placeholder="描述" size="small" />
                  <el-checkbox v-model="editCompleted">已完成</el-checkbox>
                  <el-space>
                    <el-button type="primary" :icon="Check" size="small" @click="saveEdit(todo.id)">
                      保存
                    </el-button>
                    <el-button :icon="Close" size="small" @click="editingId = null">
                      取消
                    </el-button>
                  </el-space>
                </div>
              </template>
            </div>
          </div>
        </el-card>
      </div>
    </el-main>
  </el-container>
</template>

<style scoped>
.layout {
  height: 100vh;
  background: #f0f2f5;
  display: flex;
  flex-direction: column;
  align-items: center;
}
.el-header {
  width: 100%;
  background: white;
  box-shadow: 0 1px 2px rgba(0,0,0,0.1);
  padding: 0 24px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 60px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
}
.el-main {
  width: 100%;
  display: flex;
  justify-content: center;
  padding: 20px;
}
.content-wrapper {
  width: 100%;
  max-width: 1000px;
}
.add-card {
  margin-bottom: 20px;
}
.list-card {
  min-height: 400px;
}
.todo-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.todo-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}
.todo-content {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}
.todo-text {
  display: flex;
  flex-direction: column;
}
.todo-text .desc {
  font-size: 12px;
  color: #909399;
}
.completed {
  text-decoration: line-through;
  color: #c0c4cc;
}
.todo-actions {
  display: flex;
  gap: 4px;
}
.edit-form {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  width: 100%;
}
</style>