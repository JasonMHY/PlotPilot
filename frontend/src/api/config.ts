import axios, { type AxiosRequestConfig } from 'axios'

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api/v1'

// 创建原始 axios 实例
const axiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 增加到 120 秒，因为 LLM 生成可能需要较长时间
  headers: {
    'Content-Type': 'application/json',
  },
})

// Add response interceptor to extract data
axiosInstance.interceptors.response.use(response => response.data)

// 类型安全的 API 客户端接口
export interface ApiClient {
  get<T>(url: string, config?: AxiosRequestConfig): Promise<T>
  post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
  put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
  patch<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
  delete<T>(url: string, config?: AxiosRequestConfig): Promise<T>
}

// 导出类型安全的 apiClient
export const apiClient: ApiClient = axiosInstance as unknown as ApiClient
