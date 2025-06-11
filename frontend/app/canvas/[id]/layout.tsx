"use client"

import type React from "react"
import { useState, useEffect } from "react"
import { useParams } from "next/navigation"
import dynamic from 'next/dynamic'
import { api } from "@/api/client"
import { useToast } from "@/hooks/use-toast"
import type { Notebook } from "@/store/types"

const CanvasHeader = dynamic(() => import('@/components/CanvasHeader'), {
  ssr: false,
  loading: () => null,
})

export default function CanvasIdLayout({ children }: { children: React.ReactNode }) {
  const params = useParams()
  const notebookId = params.id as string
  const { toast } = useToast()
  const [notebook, setNotebook] = useState<Notebook | null>(null)

  useEffect(() => {
    const fetchNotebook = async () => {
      if (!notebookId) return

      try {
        const notebookData = await api.notebooks.get(notebookId)
        setNotebook(notebookData)
      } catch (err: unknown) {
        console.error("Failed to fetch notebook data:", err)
      }
    }

    fetchNotebook()
  }, [notebookId])

  const handleNameChange = async (newName: string) => {
    if (!notebook || !newName.trim()) return

    try {
      const updatedNotebook = await api.notebooks.update(notebookId, {
        name: newName,
      })

      setNotebook(updatedNotebook)
      toast({
        title: "Success",
        description: "Canvas name updated successfully.",
      })
    } catch (err) {
      console.error("Failed to update canvas name:", err)
      toast({
        variant: "destructive",
        title: "Error",
        description: "Failed to update canvas name. Please try again.",
      })
    }
  }

  return (
    <div className="flex flex-col h-full">
      {notebook && (
        <CanvasHeader
          name={notebook?.name || notebook?.metadata?.title || "Untitled Notebook"}
          notebookId={notebookId}
          onNameChange={handleNameChange}
        />
      )}
      <div className="flex-1 overflow-auto">{children}</div>
    </div>
  )
}