/**
 * Main application entrypoint for typescript_sample.
 */
import { User, ApiResponse } from './types';

export function createUser(id: string, name: string, email: string): User {
  return {
    id,
    name,
    email,
    createdAt: new Date(),
  };
}

export function createSuccessResponse<T>(data: T): ApiResponse<T> {
  return {
    status: 'success',
    data,
  };
}

const user = createUser('1', 'Alice', 'alice@example.com');
console.log(createSuccessResponse(user));
