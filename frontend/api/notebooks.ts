// API client for notebook operations
import axios from "axios"
import { BACKEND_URL } from "@/config/api-config"
// IMPORT Notebook and Cell types from store
import type { Notebook, Cell } from "@/store/types" // Use types from the store

export interface Dependency {
  source_cell_id: string
  target_cell_id: string
}

export interface ServerStatus {
  running: boolean
  port?: number
  sse_url?: string
  started_at?: number
  error?: string
}

const API_BASE_URL = `${BACKEND_URL}/api`

// Export the notebooks API with the correct structure
export const notebooks = {
  // Notebook operations
  list: async (): Promise<Notebook[]> => {
    const response = await axios.get(`${API_BASE_URL}/notebooks`)
    return response.data
  },

  get: async (notebookId: string): Promise<Notebook> => {
    const response = await axios.get(`${API_BASE_URL}/notebooks/${notebookId}`)
    return response.data
  },

  create: async (data: { title: string; description?: string }): Promise<Notebook> => {
    const response = await axios.post(`${API_BASE_URL}/notebooks`, data)
    return response.data
  },

  update: async (notebookId: string, data: Partial<Notebook>): Promise<Notebook> => {
    const response = await axios.put(`${API_BASE_URL}/notebooks/${notebookId}`, data)
    return response.data
  },

  delete: async (notebookId: string): Promise<void> => {
    await axios.delete(`${API_BASE_URL}/notebooks/${notebookId}`)
  },

  sendMessage: async (notebookId: string, cellId: string, message: string): Promise<Cell> => {
    const response = await axios.post(`${API_BASE_URL}/notebooks/${notebookId}/cells/${cellId}/message`, { message })
    return response.data
  },

  // Server management operations
  getServerStatus: async (notebookId: string): Promise<ServerStatus> => {
    const response = await axios.get(`${API_BASE_URL}/notebooks/${notebookId}/server-status`)
    return response.data
  },

  startServer: async (notebookId: string): Promise<{ success: boolean }> => {
    const response = await axios.post(`${API_BASE_URL}/notebooks/${notebookId}/server/start`)
    return response.data
  },

  stopServer: async (notebookId: string): Promise<{ success: boolean }> => {
    const response = await axios.post(`${API_BASE_URL}/notebooks/${notebookId}/server/stop`)
    return response.data
  },
}

// Keep the notebooksApi for backward compatibility
export const notebooksApi = notebooks

// Add default export for compatibility
export default { notebooks }
