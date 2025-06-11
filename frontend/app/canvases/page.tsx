"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Plus, Search, MoreVertical, Trash2, FileText, LineChart, Github, Database, Loader2, AlertCircle, Settings, CheckCircle, Folder } from "lucide-react"
import { api, Notebook } from "@/api/client"
import { useToast } from "@/hooks/use-toast"
import { useConnectionStore } from "@/store/connectionStore"
import dynamic from 'next/dynamic'
// import DataConnectionsDialog from "@/components/DataConnectionsDialog" // Will be dynamically imported
import type { Connection } from "@/store/types"

const DataConnectionsDialog = dynamic(() => import('@/components/DataConnectionsDialog'), {
  ssr: false,
  loading: () => null, // Or a proper loading skeleton/spinner
});

// Define interfaces based on usage if not available from API client
interface Canvas {
  id: string;
  name: string;
  description?: string;
  updated_at?: string;
}

// Remove local Connection interface

// --- New WorkspaceConfigurationSection Component ---
interface WorkspaceConfigurationSectionProps {
  workspace: Connection | undefined;
  loading: boolean;
  error: string | null;
  onConfigure: () => void;
}

const WorkspaceConfigurationSection: React.FC<WorkspaceConfigurationSectionProps> = ({
  workspace,
  loading,
  error,
  onConfigure,
}) => {
  // Extract configuration details from workspace
  const hasGitHub = workspace?.config?.github_token ? true : false;
  const filesystemPaths = workspace?.config?.filesystem_paths || [];
  const hasFilesystem = filesystemPaths.length > 0;

  if (loading) {
    return (
      <div className="flex justify-center items-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <span className="ml-2 text-primary">Loading workspace configuration...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex justify-center items-center h-64">
        <Card className="w-full max-w-md border-destructive bg-destructive/10">
          <CardHeader>
            <CardTitle className="text-destructive flex items-center">
              <AlertCircle className="h-5 w-5 mr-2" /> Error Loading Configuration
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-destructive">{error}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">Workspace Configuration</h2>
          <p className="text-muted-foreground">
            Configure your workspace to enable data analysis features.
          </p>
        </div>
        <Button onClick={onConfigure} variant={workspace ? "outline" : "default"}>
          <Settings className="mr-2 h-4 w-4" />
          {workspace ? "Update Configuration" : "Configure Workspace"}
        </Button>
      </div>

      {!workspace ? (
        <Card>
          <CardContent className="p-8 text-center">
            <Database className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
            <h3 className="text-lg font-medium mb-2">Workspace Not Configured</h3>
            <p className="text-muted-foreground mb-4">
              Set up your workspace to enable GitHub integration, filesystem access, Python execution, and log analysis.
            </p>
            <Button onClick={onConfigure}>
              <Plus className="mr-2 h-4 w-4" />
              Configure Workspace
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* GitHub Integration */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Github className="h-5 w-5" />
                GitHub Integration
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                {hasGitHub ? (
                  <>
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm text-green-600">Configured</span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="h-4 w-4 text-yellow-500" />
                    <span className="text-sm text-yellow-600">Not configured</span>
                  </>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Filesystem Access */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <Folder className="h-5 w-5" />
                Filesystem Access
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                {hasFilesystem ? (
                  <>
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm text-green-600">{filesystemPaths.length} path(s)</span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="h-4 w-4 text-red-500" />
                    <span className="text-sm text-red-600">Required</span>
                  </>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Python Execution */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="h-5 w-5" />
                Python Execution
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-500" />
                <span className="text-sm text-green-600">Available</span>
              </div>
            </CardContent>
          </Card>

          {/* Log Analysis */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base flex items-center gap-2">
                <LineChart className="h-5 w-5" />
                Log Analysis
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-2">
                <CheckCircle className="h-4 w-4 text-green-500" />
                <span className="text-sm text-green-600">Available</span>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
};
// --- End of WorkspaceConfigurationSection Component ---

// --- Create Canvas Dialog Content Component ---
interface CreateCanvasDialogContentProps {
  newCanvasName: string;
  setNewCanvasName: (value: string) => void;
  newCanvasDescription: string;
  setNewCanvasDescription: (value: string) => void;
  handleCreateCanvas: () => void;
  setIsCreateDialogOpen: (isOpen: boolean) => void;
  isLoading: boolean;
}

const CreateCanvasDialogContent: React.FC<CreateCanvasDialogContentProps> = ({
  newCanvasName,
  setNewCanvasName,
  newCanvasDescription,
  setNewCanvasDescription,
  handleCreateCanvas,
  setIsCreateDialogOpen,
  isLoading,
}) => {
  return (
    <DialogContent className="bg-white">
      <DialogHeader>
        <DialogTitle>Create New Canvas</DialogTitle>
        <DialogDescription>Create a new canvas to start your analysis.</DialogDescription>
      </DialogHeader>
      <div className="space-y-4 py-4">
        <div className="space-y-2">
          <label htmlFor="name" className="text-sm font-medium">Name</label>
          <Input
            id="name"
            placeholder="Enter canvas name"
            value={newCanvasName}
            onChange={(e) => setNewCanvasName(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="description" className="text-sm font-medium">Description (optional)</label>
          <Input
            id="description"
            placeholder="Enter canvas description"
            value={newCanvasDescription}
            onChange={(e) => setNewCanvasDescription(e.target.value)}
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)}>Cancel</Button>
        <Button onClick={handleCreateCanvas} disabled={!newCanvasName.trim() || isLoading}>Create</Button>
      </DialogFooter>
    </DialogContent>
  );
};
// --- End Create Canvas Dialog Content Component ---

export default function CanvasesPage() {
  const { toast } = useToast()
  const [canvases, setCanvases] = useState<Canvas[]>([])
  const [filteredCanvases, setFilteredCanvases] = useState<Canvas[]>([])
  const [searchQuery, setSearchQuery] = useState("")
  const [loadingCanvases, setLoadingCanvases] = useState(true)
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [isConnectionsDialogOpen, setIsConnectionsDialogOpen] = useState(false)
  const [newCanvasName, setNewCanvasName] = useState("")
  const [newCanvasDescription, setNewCanvasDescription] = useState("")

  const {
    connections,
    loading: loadingConnections,
    error: connectionsError,
    loadConnections,
  } = useConnectionStore()

  const hasWorkspace = connections.some(c => c.type === 'logai_workspace');
  const existingWorkspace = connections.find(c => c.type === 'logai_workspace');

  // Fetch canvases
  useEffect(() => {
    const fetchCanvases = async () => {
      try {
        setLoadingCanvases(true)
        console.log("Fetching notebooks with api:", api.notebooks)
        const notebooks: Notebook[] = await api.notebooks.list()
        console.log("Fetched notebooks:", notebooks)
        const formattedCanvases: Canvas[] = notebooks.map(nb => ({
          id: nb.id,
          name: nb.metadata?.title || 'Untitled Canvas',
          description: nb.metadata?.description || '',
          updated_at: nb.metadata?.updated_at
        }));
        setCanvases(formattedCanvases)
        setFilteredCanvases(formattedCanvases)
      } catch (error) {
        console.error("Failed to fetch canvases:", error)
        const description = error instanceof Error ? error.message : "Failed to load canvases. Please try again.";
        toast({
          variant: "destructive",
          title: "Error Loading Canvases",
          description,
        })
      } finally {
        setLoadingCanvases(false)
      }
    }

    fetchCanvases()
  }, [toast])

  // Fetch connections using the store action
  useEffect(() => {
    console.log("CanvasesPage: Firing loadConnections effect")
    loadConnections();
  }, [loadConnections]);

  // Filter canvases based on search query
  useEffect(() => {
    if (!searchQuery.trim()) {
      setFilteredCanvases(canvases)
    } else {
      const filtered = canvases.filter((canvas) => canvas.name.toLowerCase().includes(searchQuery.toLowerCase()))
      setFilteredCanvases(filtered)
    }
  }, [searchQuery, canvases])

  // Create a new canvas
  const handleCreateCanvas = async () => {
    if (!newCanvasName.trim() || !hasWorkspace) return

    try {
      const newCanvas = await api.notebooks.create({
        title: newCanvasName,
        description: newCanvasDescription,
      })

      const formattedNewCanvas: Canvas = {
        id: newCanvas.id,
        name: newCanvas.metadata?.title || 'Untitled Canvas',
        description: newCanvas.metadata?.description || '',
        updated_at: newCanvas.metadata?.updated_at
      };

      setCanvases((prev) => [...prev, formattedNewCanvas])
      setNewCanvasName("")
      setNewCanvasDescription("")
      setIsCreateDialogOpen(false)

      toast({
        title: "Canvas Created",
        description: "Your new canvas has been created successfully.",
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
      setCanvases((prev) => prev.filter((canvas) => canvas.id !== id))

      toast({
        title: "Canvas Deleted",
        description: `"${name}" has been deleted successfully.`,
      })
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
  const formatDate = (dateString: string | undefined): string => {
    if (!dateString) return ""
    try {
      return new Date(dateString).toLocaleDateString()
    } catch {
      console.warn("Invalid date string for formatting:", dateString);
      return dateString;
    }
  }

  const isLoading = loadingCanvases || loadingConnections;

  const CreateCanvasButton = ({ isIconOnly = false }) => (
    <Button
      onClick={() => hasWorkspace && setIsCreateDialogOpen(true)}
      disabled={!hasWorkspace || isLoading || !!connectionsError}
      variant={isIconOnly ? "ghost" : "default"}
      size={isIconOnly ? "icon" : "default"}
    >
      <Plus className={`h-4 w-4 ${!isIconOnly ? 'mr-2' : ''}`} />
      {!isIconOnly && "New Canvas"}
    </Button>
  );

  return (
    <>
      <div className="w-full space-y-8">
        <section>
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-2xl font-semibold tracking-tight">Your Canvases</h2>
            <div className="flex items-center space-x-4">
              <div className="relative w-64">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search canvases..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8"
                />
              </div>
              <CreateCanvasButton />
            </div>
          </div>

          {loadingCanvases ? (
            <div className="flex justify-center items-center h-64">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
            </div>
          ) : filteredCanvases.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredCanvases.map((canvas: Canvas) => (
                <Card key={canvas.id} className="group hover:shadow-md transition-shadow">
                  <CardHeader className="pb-2">
                    <div className="flex justify-between items-start">
                      <CardTitle className="text-lg">
                        <Link href={`/canvas/${canvas.id}`} className="hover:text-primary transition-colors">
                          {canvas.name}
                        </Link>
                      </CardTitle>
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
                            onClick={() => handleDeleteCanvas(canvas.id, canvas.name)}
                          >
                            <Trash2 className="h-4 w-4 mr-2" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                    <CardDescription>{canvas.description || "No description"}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center text-xs text-muted-foreground">
                      <FileText className="h-3 w-3 mr-1" />
                      <span>Last updated: {formatDate(canvas.updated_at)}</span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : (
            <div className="text-center py-12 bg-gray-50 rounded-lg">
              <h3 className="text-lg font-medium text-gray-900 mb-2">
                  {searchQuery ? "No canvases match your search" : "No Canvases Yet"}
              </h3>
              <p className="text-gray-500 mb-4">
                {searchQuery
                   ? "Try a different search term."
                   : hasWorkspace && !connectionsError
                   ? "Create your first canvas to get started."
                   : connectionsError
                   ? "Could not load workspace configuration. Cannot create a canvas."
                   : "Configure your workspace before creating your first canvas."
                }
              </p>
              {!searchQuery && !connectionsError && (
                <CreateCanvasButton />
              )}
            </div>
          )}
        </section>

        <hr className="my-8" />

        <section>
          <WorkspaceConfigurationSection
            workspace={existingWorkspace}
            loading={loadingConnections}
            error={connectionsError}
            onConfigure={() => setIsConnectionsDialogOpen(true)}
          />
        </section>
      </div>

      <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
        <CreateCanvasDialogContent 
           newCanvasName={newCanvasName}
           setNewCanvasName={setNewCanvasName}
           newCanvasDescription={newCanvasDescription}
           setNewCanvasDescription={setNewCanvasDescription}
           handleCreateCanvas={handleCreateCanvas}
           setIsCreateDialogOpen={setIsCreateDialogOpen}
           isLoading={isLoading}
        />
      </Dialog>

      <DataConnectionsDialog
        isOpen={isConnectionsDialogOpen}
        onClose={() => setIsConnectionsDialogOpen(false)}
        initialPage="add"
      />
    </>
  )
}
