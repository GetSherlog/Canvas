"use client"

import { useState, useEffect, useCallback } from "react"
import { useWebSocket, type WebSocketMessage } from "./useWebSocket"

/**
 * Simplified investigation events hook
 * 
 * This hook only handles status updates from the investigation.
 * Cell creation is handled directly by the backend, and the useNotebook
 * hook will automatically pick up new cells via WebSocket notifications.
 */
export function useInvestigationEventsSimple(notebookId: string) {
  const [isInvestigationRunning, setIsInvestigationRunning] = useState(false)
  const [currentStatus, setCurrentStatus] = useState<string | null>(null)
  const [latestMessage, setLatestMessage] = useState<WebSocketMessage | null>(null)

  // WebSocket connection
  const handleWebSocketMessage = useCallback((message: WebSocketMessage) => {
    setLatestMessage(message)
  }, [])

  const { status: wsStatus } = useWebSocket(notebookId, handleWebSocketMessage)

  // Process WebSocket messages
  useEffect(() => {
    if (!latestMessage) return

    const { type, data } = latestMessage

    switch (type) {
      case "investigation_started":
        setIsInvestigationRunning(true)
        setCurrentStatus("Investigation started...")
        break

      case "investigation_status":
        setCurrentStatus(data.message || "Processing...")
        break

      case "investigation_complete":
        setIsInvestigationRunning(false)
        setCurrentStatus("Investigation complete")
        // Clear status after a delay
        setTimeout(() => setCurrentStatus(null), 3000)
        break

      case "investigation_error":
        setIsInvestigationRunning(false)
        setCurrentStatus(`Error: ${data.message || "Unknown error"}`)
        break

      // Cell events - we don't need to handle these anymore
      // The useNotebook hook will handle cell updates
      case "cell_created":
      case "cell_updated":
        // Ignore - handled by useNotebook
        break
    }
  }, [latestMessage])

  return {
    wsStatus,
    isInvestigationRunning,
    currentStatus
  }
}