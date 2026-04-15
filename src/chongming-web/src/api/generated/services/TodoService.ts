/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { TodoCreate } from '../models/TodoCreate';
import type { TodoRead } from '../models/TodoRead';
import type { TodoUpdate } from '../models/TodoUpdate';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class TodoService {
    /**
     * Create Todo
     * @param requestBody
     * @returns TodoRead Successful Response
     * @throws ApiError
     */
    public static createTodoApiV1TodosPost(
        requestBody: TodoCreate,
    ): CancelablePromise<TodoRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/todos/',
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Read Todos
     * @param offset
     * @param limit
     * @returns TodoRead Successful Response
     * @throws ApiError
     */
    public static readTodosApiV1TodosGet(
        offset?: number,
        limit: number = 100,
    ): CancelablePromise<Array<TodoRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/todos/',
            query: {
                'offset': offset,
                'limit': limit,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Read Todo
     * @param todoId
     * @returns TodoRead Successful Response
     * @throws ApiError
     */
    public static readTodoApiV1TodosTodoIdGet(
        todoId: number,
    ): CancelablePromise<TodoRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/todos/{todo_id}',
            path: {
                'todo_id': todoId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Todo
     * @param todoId
     * @param requestBody
     * @returns TodoRead Successful Response
     * @throws ApiError
     */
    public static updateTodoApiV1TodosTodoIdPatch(
        todoId: number,
        requestBody: TodoUpdate,
    ): CancelablePromise<TodoRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/todos/{todo_id}',
            path: {
                'todo_id': todoId,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Delete Todo
     * @param todoId
     * @returns any Successful Response
     * @throws ApiError
     */
    public static deleteTodoApiV1TodosTodoIdDelete(
        todoId: number,
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'DELETE',
            url: '/api/v1/todos/{todo_id}',
            path: {
                'todo_id': todoId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
