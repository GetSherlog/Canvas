"use client"

import type React from "react"
import { useState, useEffect, useRef, useCallback } from "react"
import type { Cell } from "../../store/types"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardFooter } from "@/components/ui/card"
import { Textarea } from "@/components/ui/textarea"
import { Save, Trash, X } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm" // For GitHub Flavored Markdown support
import { cn } from "@/lib/utils" // For conditional class names

interface MarkdownCellProps {
  cell: Cell
  // onExecute: (cellId: string) => void // Assuming markdown doesn't execute?
  onUpdate: (cellId: string, content: string) => void
  onDelete: (cellId: string) => void
  // isExecuting: boolean
}

const MarkdownCell: React.FC<MarkdownCellProps> = ({ cell, onUpdate, onDelete }) => {
  const [isEditing, setIsEditing] = useState(false)
  const [content, setContent] = useState(cell.content)
  const containerRef = useRef<HTMLDivElement>(null); // Ref for click-outside detection

  const handleSave = useCallback(() => {
    if (content !== cell.content) {
      onUpdate(cell.id, content)
    }
    setIsEditing(false)
    // onExecute(cell.id) // Removed execution on save for markdown
  }, [content, cell.content, cell.id, onUpdate])

  const handleCancel = () => {
    setContent(cell.content)
    setIsEditing(false)
  }

  // Handle clicking outside to exit edit mode (optional, can be complex)
  // Basic example:
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (isEditing && containerRef.current && !containerRef.current.contains(event.target as Node)) {
        // Consider prompting user if changes are unsaved or auto-saving
         handleSave(); // Or handleCancel() if you want to discard changes
      }
    };

    if (isEditing) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isEditing, handleSave]); // Add dependencies


  return (
    <Card
      className={cn(
        "mb-4 relative group", // Add relative and group for hover controls
        isEditing ? "border-blue-500 border-2" : "border-transparent border-2 hover:border-gray-200" // Highlight when editing or hover
      )}
      ref={containerRef} // Attach ref
    >
      {/* Remove CardHeader */}
      <CardContent className={cn("p-4", isEditing ? "" : "cursor-pointer")} onClick={() => !isEditing && setIsEditing(true)}>
        {isEditing ? (
          <Textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="min-h-[150px] font-mono border rounded"
            placeholder="Enter markdown content..."
            autoFocus // Focus textarea when editing starts
          />
        ) : (
          <div className="prose prose-sm max-w-none">
            {/* Use remarkGfm for better markdown rendering */} 
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {cell.content || "*Empty markdown cell*"} 
            </ReactMarkdown>
          </div>
        )}
      </CardContent>
      {isEditing && (
        <CardFooter className="flex justify-end py-2 px-4 border-t bg-gray-50">
          <Button
            variant="ghost"
            size="sm"
            className="mr-2"
            onClick={handleCancel}
            title="Cancel edits"
          >
            <X className="h-4 w-4 mr-1" /> Cancel
          </Button>
          <Button size="sm" onClick={handleSave} title="Save changes">
            <Save className="h-4 w-4 mr-1" /> Save
          </Button>
        </CardFooter>
      )}
      {/* Hover controls - Delete Button */} 
      {!isEditing && (
         <div className="absolute top-1 right-1 hidden group-hover:flex space-x-1 bg-white p-1 rounded shadow">
           <Button
             variant="ghost"
             size="icon"
             className="h-6 w-6"
             onClick={(e) => {
               e.stopPropagation(); // Prevent triggering click-to-edit
               onDelete(cell.id)
             }}
             title="Delete Cell"
           >
             <Trash className="h-4 w-4 text-red-500" />
           </Button>
           {/* Add Edit button here if click-to-edit is not preferred */}
           {/* <Button variant="ghost" size="icon" className="h-6 w-6" onClick={(e) => { e.stopPropagation(); setIsEditing(true); }} title="Edit Cell">
             <Edit className="h-4 w-4" />
           </Button> */}
         </div>
       )}
    </Card>
  )
}

export default MarkdownCell
