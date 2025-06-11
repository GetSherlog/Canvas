"use client"

import { useState, useEffect, useRef } from "react"
import { useParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import dynamic from 'next/dynamic'
import CellCreationPills from "@/components/canvas/CellCreationPills"
import AIChatToggle from "@/components/AIChatToggle"
import { api } from "@/api/client"
import { useToast } from "@/hooks/use-toast"
import { useCanvasStore } from "@/store/canvasStore"
import { type Cell, type Notebook } from "@/store/types"
import CellFactory from "@/components/cells/CellFactory"
import { useNotebook } from "@/hooks/useNotebook"

const AIChatPanel = dynamic(() => import('@/components/AIChatPanelSimple'), {
  ssr: false,
  loading: () => <div className="fixed bottom-4 right-4 p-4 bg-gray-700 text-white rounded-lg shadow-lg">Loading Chat...</div>,
});

type DisplayCell = Cell & { isNew?: boolean }

export default function CanvasPage() {
  const params = useParams()
  const notebookId = params.id as string
  const { toast } = useToast()

  // Use the notebook hook for WebSocket-enabled real-time updates
  const { 
    notebook, 
    cells: hookCells, 
    loading, 
    error,
    wsStatus,
    executeCell: hookExecuteCell,
    updateCell: hookUpdateCell,
    deleteCell: hookDeleteCell,
    createCell: hookCreateCell,
    isExecuting
  } = useNotebook(notebookId)

  const [cells, setCells] = useState<DisplayCell[]>([])
  const [deletingCellId, setDeletingCellId] = useState<string | null>(null)
  const [isChatPanelOpen, setIsChatPanelOpen] = useState(false)
  const [isFilteredView, setIsFilteredView] = useState(false)

  const setStoreActiveNotebook = useCanvasStore((state) => state.setActiveNotebook)

  const initialized = useRef(false)

  useEffect(() => {
    if (notebookId) {
      console.log("🔑 Setting active notebook ID in store:", notebookId)
      setStoreActiveNotebook(notebookId)
    }
  }, [notebookId, setStoreActiveNotebook])

  // Sync cells from the hook (which handles WebSocket updates) with local state
  useEffect(() => {
    if (hookCells && hookCells.length > 0) {
      console.log("🔄 Syncing cells from useNotebook hook:", hookCells.length)
      setCells(hookCells.map(cell => ({ ...cell, isNew: false })))
    } else if (hookCells && hookCells.length === 0) {
      setCells([])
    }
  }, [hookCells])

  // Effect to scroll to new cells
  useEffect(() => {
    // Find the *last* cell in the array that is marked as new.
    const newCells = cells.filter(c => c.isNew);
    if (newCells.length > 0) {
      const cellToScrollTo = newCells[newCells.length - 1]; // Scroll to the latest new cell
      console.log(`[CanvasPage] Attempting to scroll to new cell: ${cellToScrollTo.id}`);
      setTimeout(() => { // Timeout to ensure DOM is updated
        const element = document.getElementById(`cell-${cellToScrollTo.id}`);
        if (element) {
          console.log(`[CanvasPage] Scrolling to element:`, element);
          element.scrollIntoView({ behavior: "smooth", block: "end" });
        } else {
          console.warn(`[CanvasPage] Could not find element for new cell ${cellToScrollTo.id} to scroll to.`);
        }
      }, 100); // A small delay for rendering.
    }
  }, [cells]); // Trigger when cells array changes


  // Mark as initialized when hook loads data
  useEffect(() => {
    if (!loading && notebook) {
      initialized.current = true
    }
  }, [loading, notebook])


  // Log WebSocket status changes
  useEffect(() => {
    console.log("🔌 WebSocket status:", wsStatus)
  }, [wsStatus])

  useEffect(() => {
    console.log("📊 Cells state changed, current count:", cells.length)
    console.log(
      "📊 Current cells:",
      cells.map((c) => ({ id: c.id, type: c.type })),
    )
  }, [cells])


  const handleAddCell = async (type: string, index: number, toolName?: string) => {
    if (!notebookId) return

    try {
      let defaultContent = ""
      let cellType: "markdown" | "tool" = "tool"
      let actualToolName = toolName
      
      // Handle both new format (type="tool", toolName="github") and legacy format (type="github")
      if (type === "markdown") {
        cellType = "markdown"
        defaultContent = "# New markdown cell"
      } else if (type === "tool" && toolName) {
        // New format
        cellType = "tool"
        actualToolName = toolName
        switch (toolName) {
          case "github":
            defaultContent = "{}"
            break
          case "filesystem":
            defaultContent = "list_dir ."
            break
          case "python":
            defaultContent = "# Enter Python code here"
            break
          default:
            defaultContent = ""
        }
      } else {
        // Legacy format - map old type to tool with tool_name
        cellType = "tool"
        actualToolName = type
        switch (type) {
          case "github":
            defaultContent = "{}"
            break
          case "filesystem":
            defaultContent = "list_dir ."
            break
          case "python":
            defaultContent = "# Enter Python code here"
            break
          default:
            defaultContent = ""
        }
      }

      const createData = {
        type: cellType,
        content: defaultContent,
        status: "idle" as const,
        tool_name: undefined as string | undefined,
        metadata: undefined as Record<string, unknown> | undefined,
      }
      
      // Add tool metadata for tool cells
      if (cellType === "tool" && actualToolName) {
        createData.tool_name = actualToolName
        createData.metadata = { original_type: actualToolName }
      }

      const newCell = await api.cells.create(notebookId, createData)

      const updatedCells = [...cells]
      updatedCells.splice(index, 0, { ...newCell, isNew: true })
      setCells(updatedCells)

      setTimeout(() => {
        setCells((cells) => cells.map((cell) => (cell.id === newCell.id ? { ...cell, isNew: false } : cell)))
      }, 500)

      toast({
        title: "Success",
        description: `New ${actualToolName || type} cell added.`,
      })
    } catch (err) {
      console.error("Failed to create cell:", err)
      toast({
        variant: "destructive",
        title: "Error",
        description: "Failed to create cell. Please try again.",
      })
    }
  }

  const handleDeleteCell = async (cellId: string) => {
    if (!notebookId) return

    try {
      setDeletingCellId(cellId)

      setTimeout(async () => {
        await api.cells.delete(notebookId, cellId)

        setCells(cells.filter((cell) => cell.id !== cellId))
        setDeletingCellId(null)

        toast({
          title: "Success",
          description: "Cell deleted successfully.",
        })
      }, 300)
    } catch (err) {
      console.error("Failed to delete cell:", err)
      setDeletingCellId(null)
      toast({
        variant: "destructive",
        title: "Error",
        description: "Failed to delete cell. Please try again.",
      })
    }
  }

  const handleCellContentChange = async (cellId: string, newContent: string, metadata?: Record<string, unknown>) => {
    if (!notebookId) return

    try {
      const cellIndex = cells.findIndex((cell) => cell.id === cellId)
      if (cellIndex === -1) return

      const updatedCells = [...cells]
      updatedCells[cellIndex] = {
        ...updatedCells[cellIndex],
        content: newContent,
        metadata: {
          ...updatedCells[cellIndex].metadata,
          ...metadata,
        },
      }
      setCells(updatedCells)

      // ⚠️ Removed immediate backend update on every keystroke.
      // The latest content/metadata will be persisted when the cell is executed
      // or blurred (future improvement).
    } catch (err) {
      console.error("Failed to update cell content:", err)
      toast({
        variant: "destructive",
        title: "Error",
        description: "Failed to update cell content. Please try again.",
      })
    }
  }

  const handleCellRun = async (cellId: string) => {
    if (!notebookId) return

    try {
      // Use the hook's executeCell function which handles WebSocket updates
      await hookExecuteCell(cellId)

      toast({
        title: "Cell Queued",
        description: "Cell has been queued for execution.",
      })
    } catch (err: unknown) {
      console.error("Failed to execute cell:", err)
      toast({
        variant: "destructive",
        title: "Error",
        description: "Failed to execute cell. Please try again.",
      })
    }
  }

  const toggleChatPanel = () => {
    setIsChatPanelOpen(!isChatPanelOpen)
  }

  return (
    <div className={`p-6 pb-32 ${isChatPanelOpen ? "pr-[440px]" : ""} transition-all duration-300`}>
      {loading ? (
        <div className="flex justify-center items-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
        </div>
      ) : error ? (
        <Alert variant="destructive">
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : notebook ? (
        <>
          <div className="mb-4 flex justify-between items-center">
            <div className="text-sm text-gray-500">
              WebSocket: {wsStatus === "connected" ? "🟢 Connected" : wsStatus === "connecting" ? "🟡 Connecting..." : "🔴 Disconnected"}
            </div>
            {cells.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setIsFilteredView(!isFilteredView)}
              >
                {isFilteredView ? "Show All Cells" : "Show Key Cells"}
              </Button>
            )}
          </div>

          <div className="space-y-6">
            {(isFilteredView
              ? cells.filter(
                  (cell) =>
                    cell.type === "markdown" ||
                    (cell.type === "tool" && cell.tool_name === "media_timeline") ||
                    (cell.type === "tool" && cell.tool_name === "investigation_report"),
                )
              : cells
            ).map((cell, index, displayedCellsArray) => (
              <div
                key={cell.id}
                id={`cell-${cell.id}`}
                className={`cell-container ${deletingCellId === cell.id ? "deleted" : ""} ${cell.isNew ? "cell-enter" : ""}`}
              >
                <CellFactory
                  cell={cell}
                  onExecute={() => handleCellRun(cell.id)}
                  onUpdate={handleCellContentChange}
                  onDelete={() => handleDeleteCell(cell.id)}
                  isExecuting={isExecuting(cell.id)}
                />
                {index === displayedCellsArray.length - 1 && !isFilteredView && (
                  <CellCreationPills
                    onAddCell={(type: string, toolName?: string) => {
                      // Calculate the actual index in the original 'cells' array
                      const originalIndex =
                        cells.length > 0
                          ? cells.findIndex((c) => c.id === cell.id) + 1
                          : 0
                      handleAddCell(type, originalIndex, toolName)
                    }}
                  />
                )}
              </div>
            ))}
            {(isFilteredView
              ? cells.filter(
                  (cell) =>
                    cell.type === "markdown" ||
                    (cell.type === "tool" && cell.tool_name === "media_timeline") ||
                    (cell.type === "tool" && cell.tool_name === "investigation_report"),
                )
              : cells
            ).length === 0 && (
              <div className="text-center py-12 bg-gray-50 rounded-lg">
                <h3 className="text-lg font-medium text-gray-900 mb-2">
                  {isFilteredView ? "No key cells to display" : "This canvas is empty"}
                </h3>
                <p className="text-gray-500 mb-4">
                  {isFilteredView
                    ? "Switch to 'Show All Cells' view or add a Markdown, Mediatimeline, or Investigation Report cell."
                    : "Add your first cell to get started"}
                </p>
                {!isFilteredView && (
                  <CellCreationPills
                    onAddCell={(type: string, toolName?: string) => {
                      handleAddCell(type, 0, toolName)
                    }}
                  />
                )}
              </div>
            )}
          </div>
        </>
      ) : null}

      <AIChatPanel isOpen={isChatPanelOpen} onToggle={toggleChatPanel} notebookId={notebookId} />

      <AIChatToggle isOpen={isChatPanelOpen} onToggle={toggleChatPanel} />
    </div>
  )
}
