"use client"

import { useState, useEffect } from "react"
import { useRouter, useParams } from "next/navigation"
import Link from "next/link"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Search, Plus, MoreVertical, Trash2, FileText, ChevronLeft, ChevronRight, Database } from "lucide-react"
import dynamic from 'next/dynamic'
import { api } from "@/api/client"
import { useToast } from "@/hooks/use-toast"
// import DataConnectionsDialog from "./DataConnectionsDialog" // Will be dynamically imported

const DataConnectionsDialog = dynamic(() => import('./DataConnectionsDialog'), {
  ssr: false,
  loading: () => null, // Or a proper loading skeleton/spinner
});

// Define a type for the raw notebook data structure from the API
interface RawNotebook {
  id: string
  metadata?: {
    title?: string
    description?: string
    created_at?: string
    updated_at?: string
    [key: string]: string | undefined // Allow other potential metadata fields
  }
  created_at?: string
  updated_at?: string
  // Include other top-level fields returned by the API
  [key: string]: unknown // Allow other potential top-level fields
}

// Keep the desired Canvas interface for the component's state
interface Canvas {
  id: string
  metadata: {
    title: string
    description?: string
    created_at: string
    updated_at: string
  }
  created_at: string // Keep top-level if needed elsewhere
  updated_at: string // Keep top-level if needed elsewhere
}

export default function CanvasSidebar() {
  const router = useRouter()
  const params = useParams()
  const currentCanvasId = params?.id as string
  const { toast } = useToast()

  const [canvases, setCanvases] = useState<Canvas[]>([])
  const [filteredCanvases, setFilteredCanvases] = useState<Canvas[]>([])
  const [searchQuery, setSearchQuery] = useState("")
  const [loading, setLoading] = useState(true)
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [newCanvasName, setNewCanvasName] = useState("")
  const [newCanvasDescription, setNewCanvasDescription] = useState("")
  // Add state for sidebar collapse
  const [isCollapsed, setIsCollapsed] = useState(false)
  // Add state for Data Connections Dialog
  const [isConnectionsDialogOpen, setIsConnectionsDialogOpen] = useState(false)

  // Helper to safely format RawNotebook to Canvas
  const formatNotebookToCanvas = (notebook: RawNotebook): Canvas => {
    const now = new Date().toISOString();
    const meta = notebook.metadata || {};
    return {
      id: notebook.id,
      metadata: {
        title: meta.title ?? 'Untitled Canvas',
        description: meta.description,
        created_at: meta.created_at ?? now,
        updated_at: meta.updated_at ?? now,
      },
      created_at: notebook.created_at ?? meta.created_at ?? now,
      updated_at: notebook.updated_at ?? meta.updated_at ?? now,
    };
  };

  // Fetch canvases
  useEffect(() => {
    const fetchCanvases = async () => {
      try {
        setLoading(true)
        console.log("Fetching notebooks with api:", api.notebooks)
        // Assuming api.notebooks.list() returns RawNotebook[] or similar
        const rawNotebooks: RawNotebook[] = await api.notebooks.list()
        console.log("Fetched raw notebooks:", rawNotebooks)
        const formattedCanvases: Canvas[] = rawNotebooks.map(formatNotebookToCanvas)
        setCanvases(formattedCanvases)
        setFilteredCanvases(formattedCanvases)
      } catch (error) {
        console.error("Failed to fetch canvases:", error)
        toast({
          variant: "destructive",
          title: "Error",
          description: "Failed to load canvases. Please try again.",
        })
      } finally {
        setLoading(false)
      }
    }

    fetchCanvases()
  }, [toast]) // Removed formatNotebookToCanvas from dependency array as it's stable

  // Filter canvases based on search query
  useEffect(() => {
    if (!searchQuery.trim()) {
      setFilteredCanvases(canvases)
    } else {
      const filtered = canvases.filter((canvas) =>
        canvas.metadata.title.toLowerCase().includes(searchQuery.toLowerCase())
      )
      setFilteredCanvases(filtered)
    }
  }, [searchQuery, canvases])

  // Create a new canvas
  const handleCreateCanvas = async () => {
    if (!newCanvasName.trim()) return

    try {
      // Assuming create response structure is similar to list item structure (RawNotebook)
      const newRawNotebook: RawNotebook = await api.notebooks.create({
        title: newCanvasName,
        description: newCanvasDescription,
      })

      // Format the response to match the Canvas interface
      const newCanvas = formatNotebookToCanvas(newRawNotebook)

      // Update state with the correctly formatted canvas
      setCanvases((prev) => [...prev, newCanvas])
      // Also update filteredCanvases if search is inactive or matches
      if (!searchQuery.trim() || newCanvas.metadata.title.toLowerCase().includes(searchQuery.toLowerCase())) {
        setFilteredCanvases((prev) => [...prev, newCanvas]);
      }

      setNewCanvasName("")
      setNewCanvasDescription("")
      setIsCreateDialogOpen(false)

      // Navigate to the new canvas
      router.push(`/canvas/${newCanvas.id}`)

      toast({
        title: "Canvas Created",
        description: `"${newCanvas.metadata.title}" has been created successfully.`,
      })
    } catch (error) {
      console.error("Failed to create canvas:", error)
      toast({
        variant: "destructive",
        title: "Error",
        description: "Failed to create canvas. Please try again.",
      })
    }
  }

  // Delete a canvas
  const handleDeleteCanvas = async (id: string, name: string) => {
    try {
      await api.notebooks.delete(id)
      // Update both state arrays
      setCanvases((prev) => prev.filter((canvas) => canvas.id !== id))
      setFilteredCanvases((prev) => prev.filter((canvas) => canvas.id !== id))

      toast({
        title: "Canvas Deleted",
        description: `"${name}" has been deleted successfully.`,
      })

      // If the current canvas was deleted, navigate to the home page
      if (id === currentCanvasId) {
        router.push("/")
      }
    } catch (error) {
      console.error("Failed to delete canvas:", error)
      toast({
        variant: "destructive",
        title: "Error",
        description: "Failed to delete canvas. Please try again.",
      })
    }
  }

  // Format date for display
  const formatDate = (dateString: string) => {
    if (!dateString) return ""
    try {
      return new Date(dateString).toLocaleDateString()
    } catch (error) {
      console.error("Error formatting date:", error)
      return "Invalid Date"
    }
  }

  // Toggle sidebar collapse
  const toggleSidebar = () => {
    setIsCollapsed(!isCollapsed)
  }

  return (
    <div
      className={`relative h-screen border-r bg-background flex flex-col transition-all duration-300 ${
        isCollapsed ? "w-16" : "w-64"
      }`}
    >
      {/* Collapse Toggle Button - Positioned relative to the parent */}
      <Button
        variant="outline"
        size="icon"
        className="absolute top-4 -right-3 z-10 h-6 w-6 rounded-full border-gray-200 bg-white shadow-md"
        onClick={toggleSidebar}
      >
        {isCollapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronLeft className="h-3 w-3" />}
      </Button>

      {/* Sidebar Header */}
      <div className={`p-4 border-b ${isCollapsed ? "flex justify-center" : ""}`}>
        {!isCollapsed && (
          <>
            <h2 className="text-lg font-semibold mb-4">Sherlog</h2>
            <div className="relative">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search canvases..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8"
              />
            </div>
          </>
        )}
        {isCollapsed && <span className="font-bold text-lg text-green-700">S</span>}
      </div>

      {/* Canvas List */}
      <ScrollArea className="flex-1">
        <div className="p-2">
          {loading ? (
            <div className="flex justify-center items-center h-20">
              <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary"></div>
            </div>
          ) : filteredCanvases.length > 0 ? (
            <div className="space-y-1">
              {filteredCanvases.map((canvas) => (
                <div
                  key={canvas.id}
                  className={`group flex items-center justify-between p-2 rounded-md transition-colors ${
                    canvas.id === currentCanvasId
                      ? "bg-accent text-accent-foreground"
                      : "hover:bg-accent/70"
                  } ${
                    canvas.id === currentCanvasId ? "border-l-4 border-primary" : ""
                  }`}
                >
                  <Link href={`/canvas/${canvas.id}`} className="flex items-center flex-1 min-w-0">
                    <FileText className="h-4 w-4 mr-2 text-muted-foreground" />
                    {!isCollapsed && (
                      <div className="truncate text-foreground">
                        <div className="font-medium truncate">{canvas.metadata.title}</div>
                        <div className="text-xs text-muted-foreground">{formatDate(canvas.metadata.updated_at)}</div>
                      </div>
                    )}
                  </Link>
                  {!isCollapsed && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100">
                          <MoreVertical className="h-4 w-4" />
                          <span className="sr-only">Open menu</span>
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          className="text-destructive focus:text-destructive"
                          onClick={() => handleDeleteCanvas(canvas.id, canvas.metadata.title)}
                        >
                          <Trash2 className="h-4 w-4 mr-2" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className={`text-center py-4 text-muted-foreground ${isCollapsed ? "px-0" : ""}`}>
              {searchQuery ? (isCollapsed ? "..." : "No canvases found") : isCollapsed ? "..." : "No canvases yet"}
            </div>
          )}
        </div>
      </ScrollArea>

      {/* Footer Buttons */}
      <div className={`p-4 border-t ${isCollapsed ? "flex flex-col items-center space-y-4" : ""}`}>
        {/* Data Connections Button - Changed from Link to Button triggering dialog */}
        <Button
          variant="outline"
          className={`${isCollapsed ? "w-10 h-10 p-0" : "w-full mb-2"}`}
          title="Data Connections"
          onClick={() => setIsConnectionsDialogOpen(true)}
        >
          <Database className={`h-4 w-4 ${isCollapsed ? "" : "mr-2"}`} />
          {!isCollapsed && "Data Connections"}
        </Button>

        {/* Create Canvas Button */}
        <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
          <DialogTrigger asChild>
            <Button className={`${isCollapsed ? "w-10 h-10 p-0" : "w-full"}`} title="New Canvas">
              <Plus className={`h-4 w-4 ${isCollapsed ? "" : "mr-2"}`} />
              {!isCollapsed && "New Canvas"}
            </Button>
          </DialogTrigger>
          <DialogContent 
            className="bg-white"
          >
            <DialogHeader>
              <DialogTitle>Create New Canvas</DialogTitle>
              <DialogDescription>Create a new canvas to start your analysis.</DialogDescription>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <label htmlFor="name" className="text-sm font-medium">
                  Name
                </label>
                <Input
                  id="name"
                  placeholder="Enter canvas name"
                  value={newCanvasName}
                  onChange={(e) => setNewCanvasName(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label htmlFor="description" className="text-sm font-medium">
                  Description (optional)
                </label>
                <Input
                  id="description"
                  placeholder="Enter canvas description"
                  value={newCanvasDescription}
                  onChange={(e) => setNewCanvasDescription(e.target.value)}
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)}>
                Cancel
              </Button>
              <Button onClick={handleCreateCanvas} disabled={!newCanvasName.trim()}>
                Create
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {/* Render the Data Connections Dialog */}
      <DataConnectionsDialog
        isOpen={isConnectionsDialogOpen}
        onClose={() => setIsConnectionsDialogOpen(false)}
        initialPage="list"
      />
    </div>
  )
}
