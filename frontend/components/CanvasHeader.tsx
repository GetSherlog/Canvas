"use client"

import type React from "react"
import { useState, useEffect } from "react"
import { ShareIcon, CopyIcon, PlayCircleIcon, Database, ChevronsUpDownIcon, Server, Loader2 } from "lucide-react"
import dynamic from 'next/dynamic'
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
// import DataConnectionsDialog from "./DataConnectionsDialog" // Will be dynamically imported
import { useConnectionStore } from "@/store/connectionStore"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { useInvestigationEventsSimple } from "@/hooks/useInvestigationEventsSimple"

const DataConnectionsDialog = dynamic(() => import('./DataConnectionsDialog'), {
  ssr: false,
  loading: () => null, // Or a proper loading skeleton/spinner
});

interface CanvasHeaderProps {
  name: string
  notebookId?: string
  onNameChange: (newName: string) => void
}

const CanvasHeader: React.FC<CanvasHeaderProps> = ({ name, notebookId, onNameChange }) => {
  const [isEditing, setIsEditing] = useState(false)
  const [editedName, setEditedName] = useState(name)
  
  // Update editedName when name prop changes
  useEffect(() => {
    setEditedName(name)
  }, [name])
  const [isConnectionsDialogOpen, setIsConnectionsDialogOpen] = useState(false)
  const [serverStatus, setServerStatus] = useState<{ running: boolean; loading?: boolean }>({ running: false })
  const { connections, mcpStatuses } = useConnectionStore()
  const areAllCellsExpanded = useConnectionStore((state) => state.areAllCellsExpanded)
  const toggleAllCellsExpanded = useConnectionStore((state) => state.toggleAllCellsExpanded)
  
  // Use the investigation events hook for WebSocket status
  const { wsStatus, isInvestigationRunning, currentStatus } = useInvestigationEventsSimple(notebookId || '')

  // Count active connections
  const activeConnections = connections.filter((conn) => mcpStatuses[conn.id]?.status === "running").length

  // Check server status periodically
  useEffect(() => {
    if (!notebookId) return

    const checkServerStatus = async () => {
      try {
        const { notebooks } = await import('@/api/notebooks')
        const status = await notebooks.getServerStatus(notebookId)
        setServerStatus({ running: status.running })
      } catch (error) {
        console.error('Failed to check server status:', error)
        setServerStatus({ running: false })
      }
    }

    // Check immediately
    checkServerStatus()

    // Check every 5 seconds
    const interval = setInterval(checkServerStatus, 5000)

    return () => clearInterval(interval)
  }, [notebookId])

  const handleServerToggle = async () => {
    if (!notebookId || serverStatus.loading) return

    setServerStatus(prev => ({ ...prev, loading: true }))

    try {
      const { notebooks } = await import('@/api/notebooks')
      
      if (serverStatus.running) {
        await notebooks.stopServer(notebookId)
        setServerStatus({ running: false, loading: false })
      } else {
        await notebooks.startServer(notebookId)
        setServerStatus({ running: true, loading: false })
      }
    } catch (error) {
      console.error('Failed to toggle server:', error)
      setServerStatus(prev => ({ ...prev, loading: false }))
    }
  }

  const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setEditedName(e.target.value)
  }

  const handleNameSubmit = () => {
    onNameChange(editedName)
    setIsEditing(false)
  }

  return (
    <div className="flex justify-between items-center p-4 border-b">
      {isEditing ? (
        <Input
          value={editedName}
          onChange={handleNameChange}
          onBlur={handleNameSubmit}
          onKeyPress={(e) => e.key === "Enter" && handleNameSubmit()}
          className="text-2xl font-bold w-1/2"
          autoFocus
        />
      ) : (
        <div className="flex items-center">
          <h1 className="text-2xl font-bold cursor-pointer" onClick={() => setIsEditing(true)}>
            {name}
          </h1>
          <div className="ml-4 flex items-center flex-shrink-0">
            <div
              className={`w-2 h-2 rounded-full mr-2 ${
                wsStatus === "connected" ? "bg-green-500" : wsStatus === "connecting" ? "bg-yellow-500" : "bg-red-500"
              }`}
            ></div>
            <span className="text-xs text-gray-500 mr-4">
              {wsStatus === "connected" ? "Connected" : wsStatus === "connecting" ? "Connecting..." : "Disconnected"}
            </span>

            {isInvestigationRunning && (
              <div className="flex items-center">
                <div className="animate-spin h-3 w-3 border-2 border-purple-500 rounded-full border-t-transparent mr-2"></div>
                <span className="text-xs text-purple-700">{currentStatus || "Investigation in progress..."}</span>
              </div>
            )}
          </div>
        </div>
      )}
      <div className="flex items-center space-x-4">
        {notebookId && (
          <Button
            variant={serverStatus.running ? "default" : "outline"}
            size="sm"
            onClick={handleServerToggle}
            disabled={serverStatus.loading}
            className="flex items-center gap-2"
          >
            {serverStatus.loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Server className="h-4 w-4" />
            )}
            <span>{serverStatus.running ? "Server Running" : "Server Stopped"}</span>
          </Button>
        )}
        <Button
          variant="outline"
          size="sm"
          onClick={() => setIsConnectionsDialogOpen(true)}
          className="flex items-center gap-2"
        >
          <Database className="h-4 w-4" />
          <span>Data Connections</span>
          {activeConnections > 0 && (
            <span className="inline-flex items-center justify-center w-5 h-5 text-xs font-medium bg-primary text-primary-foreground rounded-full">
              {activeConnections}
            </span>
          )}
        </Button>
        <div className="flex -space-x-2">
          <div className="w-6 h-6 bg-blue-500 rounded-full flex items-center justify-center text-white text-xs font-bold">
            NM
          </div>
          <div className="w-6 h-6 bg-green-500 rounded-full flex items-center justify-center text-white text-xs font-bold">
            SS
          </div>
        </div>
        <div className="flex space-x-2">
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button className="text-gray-600 hover:text-gray-800" onClick={toggleAllCellsExpanded}>
                  <ChevronsUpDownIcon className="w-5 h-5" />
                </button>
              </TooltipTrigger>
              <TooltipContent>
                <p>{areAllCellsExpanded ? "Collapse All Cells" : "Expand All Cells"}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button className="text-gray-600 hover:text-gray-800">
                  <ShareIcon className="w-5 h-5" />
                </button>
              </TooltipTrigger>
              <TooltipContent><p>Share Canvas (soon)</p></TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button className="text-gray-600 hover:text-gray-800">
                  <CopyIcon className="w-5 h-5" />
                </button>
              </TooltipTrigger>
              <TooltipContent><p>Copy Canvas Link (soon)</p></TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <TooltipProvider delayDuration={100}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button className="text-gray-600 hover:text-gray-800">
                  <PlayCircleIcon className="w-5 h-5" />
                </button>
              </TooltipTrigger>
              <TooltipContent><p>Run All Cells (soon)</p></TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>

      <DataConnectionsDialog isOpen={isConnectionsDialogOpen} onClose={() => setIsConnectionsDialogOpen(false)} />
    </div>
  )
}

export default CanvasHeader
