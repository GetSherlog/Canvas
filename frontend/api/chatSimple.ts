import { BACKEND_URL } from "@/config/api-config"

export interface ChatMessage {
  role: "user" | "assistant" | "status" | "error"
  content: string
  timestamp: string
  id?: string
  agent?: string
  is_final?: boolean
}

export interface ChatSession {
  session_id: string
}

export const chatAPI = {
  // Create a new chat session for a notebook
  async createSession(notebookId: string): Promise<ChatSession> {
    const response = await fetch(`${BACKEND_URL}/api/v1/chat/sessions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ notebook_id: notebookId }),
    })

    if (!response.ok) {
      throw new Error(`Failed to create chat session: ${response.statusText}`)
    }

    return response.json()
  },

  // Get all messages for a session
  async getSessionMessages(sessionId: string): Promise<ChatMessage[]> {
    const response = await fetch(`${BACKEND_URL}/api/v1/chat/sessions/${sessionId}/messages`)

    if (!response.ok) {
      throw new Error(`Failed to get messages: ${response.statusText}`)
    }

    const text = await response.text()
    if (!text) return []

    // Parse newline-delimited JSON
    return text
      .split("\n")
      .filter((line) => line.trim())
      .map((line) => JSON.parse(line))
  },

  // Send a message and get streaming response
  async *sendMessage(
    sessionId: string,
    message: string
  ): AsyncGenerator<ChatMessage, void, unknown> {
    const formData = new FormData()
    formData.append("prompt", message)

    const response = await fetch(`${BACKEND_URL}/api/v1/chat/sessions/${sessionId}/messages`, {
      method: "POST",
      body: formData,
    })

    if (!response.ok || !response.body) {
      throw new Error(`Failed to send message: ${response.statusText}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        for (const line of lines) {
          if (line.trim()) {
            try {
              const message = JSON.parse(line) as ChatMessage
              yield message
            } catch (e) {
              console.error("Error parsing message:", e, "Line:", line)
            }
          }
        }
      }

      // Process any remaining buffer
      if (buffer.trim()) {
        try {
          const message = JSON.parse(buffer) as ChatMessage
          yield message
        } catch (e) {
          console.error("Error parsing final message:", e)
        }
      }
    } finally {
      reader.releaseLock()
    }
  },

  // Delete a chat session
  async deleteSession(sessionId: string): Promise<void> {
    const response = await fetch(`${BACKEND_URL}/api/v1/chat/sessions/${sessionId}`, {
      method: "DELETE",
    })

    if (!response.ok) {
      throw new Error(`Failed to delete session: ${response.statusText}`)
    }
  },
}