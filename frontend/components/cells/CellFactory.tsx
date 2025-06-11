import type React from "react"
import dynamic from 'next/dynamic'
import type { Cell } from "../../store/types"

// Dynamically import cell components - simplified to just two types
const MarkdownCell = dynamic(() => import('./MarkdownCell'), { loading: () => <p>Loading Markdown Cell...</p> });
const ToolCell = dynamic(() => import('./ToolCell'), { loading: () => <p>Loading Tool Cell...</p> });

interface CellFactoryProps {
  cell: Cell
  onExecute: (cellId: string) => void
  onUpdate: (cellId: string, content: string, metadata?: Record<string, unknown>) => void
  onDelete: (cellId: string) => void
  isExecuting: boolean
}

const CellFactory: React.FC<CellFactoryProps> = ({ cell, onExecute, onUpdate, onDelete, isExecuting }) => {
  // Map legacy cell types to the simplified types
  const cellType = mapCellType(cell.type)
  
  switch (cellType) {
    case "markdown":
      return <MarkdownCell cell={cell} onUpdate={onUpdate} onDelete={onDelete} />
    case "tool":
      return (
        <ToolCell
          cell={cell}
          onExecute={onExecute}
          onUpdate={onUpdate}
          onDelete={onDelete}
          isExecuting={isExecuting}
        />
      )
    default:
      // This should never happen with our mapping, but keep as safety net
      return (
        <div className="p-4 border rounded-md bg-red-50">
          <p>Unknown cell type: {cell.type}</p>
          <pre className="mt-2 p-2 bg-gray-100 rounded text-sm">{JSON.stringify(cell, null, 2)}</pre>
        </div>
      )
  }
}

// Helper function to map legacy cell types to simplified types
function mapCellType(type: string): "markdown" | "tool" {
  if (type === "markdown") {
    return "markdown"
  }
  // All other types are tool-based
  return "tool"
}

export default CellFactory
