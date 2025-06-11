import axios from "axios"
import { BACKEND_URL } from "@/config/api-config"
import { chatAPI } from "./chatSimple"
import { notebooks } from "./notebooks"
import { models } from "./models"
import { connections } from "./connections"

// Update the baseURL to include the /api prefix
const apiClient = axios.create({
  baseURL: `${BACKEND_URL}/api`,
  headers: {
    "Content-Type": "application/json",
  },
})

// API error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error("API Error:", error)
    return Promise.reject(error)
  },
)

// Define the cells API
const cells = {
  list: async (notebookId: string) => {
    const response = await apiClient.get(`/notebooks/${notebookId}/cells`)
    return response.data
  },

  get: async (notebookId: string, cellId: string) => {
    const response = await apiClient.get(`/notebooks/${notebookId}/cells/${cellId}`)
    return response.data
  },

  create: async (notebookId: string, data: any) => {
    // Map the 'type' field to 'cell_type' for the API request
    const apiData = {
      ...data,
      cell_type: data.type,
    }
    // Remove the original 'type' field to avoid confusion
    delete apiData.type

    console.log("Creating cell with data:", apiData)
    const response = await apiClient.post(`/notebooks/${notebookId}/cells`, apiData)

    // Map the response back to our expected format
    const cellData = response.data
    if (cellData.cell_type && !cellData.type) {
      cellData.type = cellData.cell_type
    }

    return cellData
  },

  update: async (notebookId: string, cellId: string, data: any) => {
    // data is expected to be { content?: string, metadata?: { toolName?: string, toolArgs?: Record<string, any> } }
    const payload: Record<string, any> = {};

    if (data.content !== undefined) {
      payload.content = data.content;
    }
    if (data.metadata?.toolName !== undefined) {
      payload.tool_name = data.metadata.toolName;
    }
    if (data.metadata?.toolArgs !== undefined) {
      payload.tool_arguments = data.metadata.toolArgs;
    }
    // If there are other properties in data.metadata that should go into cell_metadata:
    // const { toolName, toolArgs, ...otherMetadata } = data.metadata || {};
    // if (Object.keys(otherMetadata).length > 0) {
    //   payload.cell_metadata = otherMetadata;
    // }


    const response = await apiClient.put(`/notebooks/${notebookId}/cells/${cellId}`, payload)
    return response.data
  },

  delete: async (notebookId: string, cellId: string) => {
    await apiClient.delete(`/notebooks/${notebookId}/cells/${cellId}`)
  },

  execute: async (notebookId: string, cellId: string, data?: any) => {
    const response = await apiClient.post(`/notebooks/${notebookId}/cells/${cellId}/execute`, data)
    return response.data
  },

  sendMessage: async (notebookId: string, cellId: string, message: string) => {
    const response = await apiClient.post(`/notebooks/${notebookId}/cells/${cellId}/message`, { message })
    return response.data
  },
}

// API endpoints
export const api = {
  // Use the imported notebooks directly
  notebooks,

  // Use the imported models directly
  models,

  // Use the imported connections directly
  connections,

  // Add cells API
  cells,

  // Chat operations
  chat: chatAPI,
}

export type Notebook = any
export type Cell = any
