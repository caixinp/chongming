// src/stores/todo.ts
import { defineStore } from 'pinia'
import {
    readTodosApiV1TodosGet,
    createTodoApiV1TodosPost,
    updateTodoApiV1TodosTodoIdPatch,
    deleteTodoApiV1TodosTodoIdDelete,
    type TodoRead,
    type TodoCreate,
    type TodoUpdate,
} from '@/api/generated'

interface TodoState {
    todos: TodoRead[]
    loading: boolean
}

export const useTodoStore = defineStore('todo', {
    state: (): TodoState => ({
        todos: [],
        loading: false,
    }),
    actions: {
        async fetchTodos() {
            this.loading = true
            try {
                const { data } = await readTodosApiV1TodosGet({
                    query: { offset: 0, limit: 100 },
                    throwOnError: true,
                })
                this.todos = data || []
            } catch (error) {
                console.error('获取 Todo 列表失败', error)
                throw error
            } finally {
                this.loading = false
            }
        },
        async addTodo(todo: TodoCreate) {
            const { data } = await createTodoApiV1TodosPost({
                body: todo,
                throwOnError: true,
            })
            if (data) {
                this.todos.unshift(data)
            }
            return data
        },
        async updateTodo(id: number, updates: TodoUpdate) {
            const { data } = await updateTodoApiV1TodosTodoIdPatch({
                path: { todo_id: id },
                body: updates,
                throwOnError: true,
            })
            if (data) {
                const index = this.todos.findIndex((t) => t.id === id)
                if (index !== -1) this.todos[index] = data
            }
            return data
        },
        async deleteTodo(id: number) {
            await deleteTodoApiV1TodosTodoIdDelete({
                path: { todo_id: id },
                throwOnError: true,
            })
            this.todos = this.todos.filter((t) => t.id !== id)
        },
    },
})