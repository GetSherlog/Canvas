"use client"

import type React from "react"

import { useState, useEffect } from "react"
import { useConnectionStore } from "../store/connectionStore"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent } from "@/components/ui/dialog"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  AlertCircle,
  CheckCircle,
  Database,
  Plus,
  Trash,
  Loader2,
  ArrowLeft,
  Github,
  Folder,
  RefreshCw,
  Pencil, // Added Pencil icon
  Code, // Added Code icon
} from "lucide-react"
import type { Connection, ConnectionType } from "../store/types" // Added Connection
import { useToast } from "@/hooks/use-toast"
import GitHubConnectionForm from "./connection-forms/GitHubConnectionForm"
import JiraConnectionForm from "./connection-forms/JiraConnectionForm"
import FileSystemConnectionForm from "./connection-forms/FileSystemConnectionForm"
import { CodeIndexConnectionForm } from "./connection-forms/GitRepoConnectionForm"

interface DataConnectionsDialogProps {
  isOpen: boolean
  onClose: () => void
  initialPage?: "list" | "add" | "edit" // Added "edit"
}

const DataConnectionsDialog: React.FC<DataConnectionsDialogProps> = ({ isOpen, onClose, initialPage = "list" }) => {
  const [page, setPage] = useState<"list" | "add" | "edit">(initialPage) // Added "edit"
  const [currentConnection, setCurrentConnection] = useState<{ // Renamed from newConnection for clarity
    id?: string // Added id for editing
    name: string
    type: ConnectionType | ""
    config: Record<string, any>
  }>({
    name: "",
    type: "",
    config: {},
  })
  const [testResult, setTestResult] = useState<{ valid: boolean; message: string } | null>(null)
  const [isTestingConnection, setIsTestingConnection] = useState(false)
  const [isCreatingConnection, setIsCreatingConnection] = useState(false)
  const [isUpdatingConnection, setIsUpdatingConnection] = useState(false) // Added for update
  const [dialogError, setDialogError] = useState<string | null>(null)
  const [reindexingStates, setReindexingStates] = useState<Record<string, boolean>>({})
  const { toast } = useToast()

  // Get state and actions from the store
  const {
    connections,
    loading,
    error,
    availableTypes,
    loadConnections,
    createConnection,
    updateConnection, // Added updateConnection
    deleteConnection,
    testConnection,
    reindexConnection,
  } = useConnectionStore()

  // Effect to load connections (which now also loads types via the store action)
  useEffect(() => {
    if (isOpen) {
      console.log("DataConnectionsDialog: isOpen is true, calling loadConnections...")
      loadConnections()
    }
  }, [isOpen, loadConnections])

  // Effect to set default type for the form *after* types load from store
  useEffect(() => {
    if (isOpen && availableTypes.length > 0 && !currentConnection.type) {
        setCurrentConnection(prev => ({ ...prev, type: availableTypes[0] as ConnectionType }));
    }
    // Only run when types array changes or dialog opens
  }, [isOpen, availableTypes, currentConnection.type]) 

  // Update page state if initialPage prop changes while dialog is open
  useEffect(() => {
    if (isOpen) {
      setPage(initialPage);
    }
  }, [initialPage, isOpen]);

  // Reset state when dialog closes
  useEffect(() => {
    if (!isOpen) {
      setPage("list") // Default to list view when closing
      resetForm()
    }
  }, [isOpen])

  const resetForm = (isEditMode = false) => {
    // If not in edit mode, reset to default new connection state
    // If in edit mode, this function might be called to clear errors but preserve currentConnection data
    if (!isEditMode) {
      setCurrentConnection({
        id: undefined,
        name: "",
        type: availableTypes.length > 0 ? availableTypes[0] as ConnectionType : "",
        config: {},
      });
    }
    setTestResult(null)
    setDialogError(null)
    setIsTestingConnection(false)
    setIsCreatingConnection(false)
    setIsUpdatingConnection(false) // Reset update state
  }

  const handleInputChange = (field: string, value: string) => {
    setCurrentConnection((prev) => ({ ...prev, [field]: value }))
    setDialogError(null)
  }

  const handleConfigChange = (field: string, value: string | boolean | string[]) => {
    setCurrentConnection((prev) => ({
      ...prev,
      config: {
        ...prev.config,
        [field]: value,
      },
    }))
    setDialogError(null)
  }

  const handleTestConnection = async () => {
    setTestResult(null)
    setDialogError(null)

    // Check if a valid type is selected
    if (!currentConnection.type) {
      setDialogError("Please select a connection type.");
      return; 
    }

    setIsTestingConnection(true)

    try {
      // Type is guaranteed to be valid ConnectionType here
      const result = await testConnection(currentConnection as { type: ConnectionType; [key: string]: any })
      setTestResult(result)
    } catch (err) {
      console.error("Failed to test connection:", err)
      const errorMessage = err instanceof Error ? err.message : "An unknown error occurred during testing."
      setDialogError(errorMessage)
      setTestResult({
        valid: false,
        message: errorMessage,
      })
    } finally {
      setIsTestingConnection(false)
    }
  }

  const handleCreateConnection = async () => {
    if (!currentConnection.name.trim()) {
      setDialogError("Connection name is required")
      return
    }

    // Check if a valid type is selected
    if (!currentConnection.type) {
      setDialogError("Please select a connection type.");
      return; 
    }

    setDialogError(null)
    setIsCreatingConnection(true)

    try {
      // Type is guaranteed to be valid ConnectionType here
      const result = await createConnection(currentConnection as { name: string; type: ConnectionType; [key: string]: any })
      if (result) {
        resetForm() // Reset form for new connection
        setPage("list")
        toast({
          title: "Connection created",
          description: `${result.name} has been successfully created.`,
        })
      }
    } catch (err) {
      console.error("Failed to create connection:", err)
      let errorMessage = "An unknown error occurred during creation.";
      if (err instanceof Error) {
          // Check if the error message is JSON (like FastAPI validation error)
          try {
            // Attempt to parse the message as JSON
            const errorDetail = JSON.parse(err.message); 
            // If successful, format a user-friendly message
            if (Array.isArray(errorDetail.detail)) {
              errorMessage = errorDetail.detail.map((d: any) => 
                `Field '${d.loc.slice(1).join('.')}': ${d.msg}` // Join location path, skip 'body'
              ).join('; ');
            } else if (errorDetail.detail) {
              // Handle cases where detail might be a string
              errorMessage = String(errorDetail.detail);
            } else {
                errorMessage = err.message; // Use original message if parsing fails or format is unexpected
            }
          } catch (parseError) {
            // If parsing fails, it's likely a regular string error message
            errorMessage = err.message; 
          }
      }
      setDialogError(errorMessage)
    } finally {
        setIsCreatingConnection(false)
    }
  }

  const handleEditClick = (connection: Connection) => {
    // Fetch the full connection details if config is not already complete
    // For now, assume `connection.config` from the list is sufficient for pre-filling.
    // If not, an API call to `getConnection(id)` would be needed here.
    setCurrentConnection({
      id: connection.id,
      name: connection.name,
      type: connection.type as ConnectionType, // Cast as it's a known type from existing connection
      config: connection.config || {}, // Ensure config is an object
    });
    setPage("edit");
    setTestResult(null); // Clear previous test results
    setDialogError(null); // Clear previous errors
  };

  const handleUpdateConnection = async () => {
    if (!currentConnection.id || !currentConnection.type) {
      setDialogError("Connection ID and type are required for update.");
      return;
    }
    if (!currentConnection.name.trim()) {
      setDialogError("Connection name is required");
      return;
    }

    setDialogError(null);
    setIsUpdatingConnection(true);

    try {
      const result = await updateConnection(currentConnection.id, currentConnection as Connection);
      if (result) {
        resetForm(); // Reset form after successful update
        setPage("list");
        toast({
          title: "Connection updated",
          description: `${result.name} has been successfully updated.`,
        });
      }
    } catch (err) {
      console.error("Failed to update connection:", err);
      let errorMessage = "An unknown error occurred during update.";
      if (err instanceof Error) {
        try {
          const errorDetail = JSON.parse(err.message);
          if (Array.isArray(errorDetail.detail)) {
            errorMessage = errorDetail.detail.map((d: any) =>
              `Field '${d.loc.slice(1).join('.')}': ${d.msg}`
            ).join('; ');
          } else if (errorDetail.detail) {
            errorMessage = String(errorDetail.detail);
          } else {
            errorMessage = err.message;
          }
        } catch (parseError) {
          errorMessage = err.message;
        }
      }
      setDialogError(errorMessage);
    } finally {
      setIsUpdatingConnection(false);
    }
  };

  const handleDeleteConnection = async (id: string, name: string) => {
    try {
      const success = await deleteConnection(id)
      if (success) {
        toast({
          title: "Connection deleted",
          description: `${name} has been successfully deleted.`,
        })
      }
    } catch (err) {
      console.error("Failed to delete connection:", err)
      toast({
        variant: "destructive",
        title: "Delete failed",
        description: `Could not delete ${name}. Please try again.`,
      })
    }
  }

  // Function to handle re-indexing
  const handleReindexConnection = async (id: string, name: string) => {
    setReindexingStates(prev => ({ ...prev, [id]: true }));
    toast({ title: `Re-indexing ${name}...`, description: "Fetching latest data and updating index." });
    try {
      const result = await reindexConnection(id); // Call the actual store action
      // Use message from backend response in success toast
      toast({ title: "Re-index initiated", description: result.message || `${name} is being re-indexed.` });
    } catch (err) {
      console.error(`Failed to re-index connection ${name}:`, err);
      let displayError = "An unknown error occurred during re-indexing.";
      if (err instanceof Error) {
          // Assuming the placeholder or actual store action throws an error with a message
          displayError = err.message;
      }
      toast({ variant: "destructive", title: "Re-index failed", description: displayError });
    } finally {
      // Keep spinner potentially longer or remove immediately depending on UX preference
      // For now, remove immediately after the request is initiated/fails
      setReindexingStates(prev => ({ ...prev, [id]: false }));
    }
  };

  const getConnectionTypeIcon = (type: string) => {
    switch (type) {
      case "github":
        return <Github className="h-5 w-5 text-primary" />
      case "jira":
        return <Database className="h-5 w-5 text-primary" />
      case "filesystem":
        return <Folder className="h-5 w-5 text-primary" />
      case "code_index":
        return <Code className="h-5 w-5 text-primary" />
      default:
        return <Database className="h-5 w-5 text-muted-foreground" />
    }
  }

  const renderConnectionsList = () => {
    if (loading) {
      return (
        <div className="flex items-center justify-center h-40">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          <span className="ml-2 text-primary">Loading connections...</span>
        </div>
      )
    }

    if (error) {
      return (
        <div className="flex items-center justify-center h-40">
          <div className="p-4 bg-red-50 text-red-800 rounded-md max-w-md">
            <div className="flex items-center">
              <AlertCircle className="h-5 w-5 mr-2" />
              <p>{error}</p>
            </div>
            <Button variant="outline" className="mt-4" onClick={() => loadConnections()}>
              Retry
            </Button>
          </div>
        </div>
      )
    }

    return (
      <div className="space-y-4">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-semibold">Data Connections</h2>
          <div className="flex space-x-2">
            <Button size="sm" onClick={() => setPage("add")}>
              <Plus className="mr-2 h-4 w-4" />
              Add Connection
            </Button>
          </div>
        </div>

        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {connections.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center py-4 text-muted-foreground">
                      No connections available. Add a connection to get started.
                    </TableCell>
                  </TableRow>
                ) : (
                  Array.isArray(connections) && connections.map((connection) => (
                    <TableRow key={connection.id} className="transition-all duration-200 hover:bg-muted">
                      <TableCell className="font-medium">{connection.name}</TableCell>
                      <TableCell>
                        <div className="flex items-center">
                          {getConnectionTypeIcon(connection.type)}
                          <span className="ml-2">{connection.type}</span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex space-x-2">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleEditClick(connection)}
                            className="transition-all duration-200 hover:bg-blue-50"
                            title="Edit Connection"
                          >
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDeleteConnection(connection.id, connection.name)}
                            className="transition-all duration-200 hover:bg-red-50"
                            title="Delete Connection"
                          >
                            <Trash className="h-4 w-4" />
                          </Button>
                          {connection.type === "code_index" && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="ml-2 transition-all duration-200 hover:bg-blue-50"
                              onClick={() => handleReindexConnection(connection.id, connection.name)}
                              disabled={reindexingStates[connection.id] || loading}
                            >
                              {reindexingStates[connection.id] ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <RefreshCw className="h-4 w-4" /> 
                              )}
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    )
  }

  const renderConnectionForm = (isEditMode: boolean) => {
    const formTitle = isEditMode ? "Edit Connection" : "Add New Connection";
    const submitButtonText = isEditMode ? "Update Connection" : "Create Connection";
    const handleSubmit = isEditMode ? handleUpdateConnection : handleCreateConnection;
    const isLoading = isEditMode ? isUpdatingConnection : isCreatingConnection;

    return (
      <div className="space-y-4">
        <div className="flex items-center">
          {/* Show back button if not opened directly to add/edit page */}
          {(initialPage === "list" || page === "edit") && ( 
            <Button variant="ghost" size="sm" onClick={() => { setPage("list"); resetForm(); }} className="mr-2">
              <ArrowLeft className="h-4 w-4 mr-1" />
              Back
            </Button>
          )}
          <h2 className="text-xl font-semibold">{formTitle}</h2>
        </div>

        <div className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="type">Connection Type</Label>
            <select
              id="type"
              value={currentConnection.type}
              onChange={(e) => {
                setCurrentConnection((prev) => ({
                  ...prev,
                  type: e.target.value as ConnectionType,
                  config: {}, // Reset config when type changes
                }));
                setTestResult(null);
                setDialogError(null);
              }}
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 bg-white"
              disabled={isEditMode || availableTypes.length === 0} // Disable type change in edit mode
            >
              <option value="" disabled hidden>Select Type...</option>
              {availableTypes.map(type => (
                <option key={type} value={type}>
                  {type.charAt(0).toUpperCase() + type.slice(1)}
                </option>
              ))}
            </select>
             {isEditMode && <p className="text-xs text-muted-foreground">Connection type cannot be changed after creation.</p>}
          </div>
          <div className="grid gap-2">
            <Label htmlFor="name">Connection Name</Label>
            <Input
              id="name"
              value={currentConnection.name}
              onChange={(e) => handleInputChange("name", e.target.value)}
              placeholder="Enter connection name"
              className="w-full"
            />
          </div>

          {currentConnection.type === "github" && (
            <GitHubConnectionForm
              config={currentConnection.config}
              onConfigChange={handleConfigChange}
            />
          )}

          {currentConnection.type === "jira" && (
            <JiraConnectionForm
              config={currentConnection.config}
              onConfigChange={handleConfigChange}
            />
          )}

          {currentConnection.type === "filesystem" && (
            <FileSystemConnectionForm
              config={currentConnection.config}
              onConfigChange={handleConfigChange}
            />
          )}

          {currentConnection.type === "code_index" && (
            <CodeIndexConnectionForm
              config={currentConnection.config}
              updateConfig={(newConf: Record<string, any>) => setCurrentConnection(prev => ({ ...prev, config: newConf }))}
              isTesting={isTestingConnection}
            />
          )}

          {testResult && (
            <div
              className={`p-3 rounded-md ${
                testResult.valid ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"
              }`}
            >
              <div className="flex items-center">
                {testResult.valid ? (
                  <CheckCircle className="h-5 w-5 mr-2" />
                ) : (
                  <AlertCircle className="h-5 w-5 mr-2" />
                )}
                <p>{testResult.message || (testResult.valid ? "Connection successful!" : "Connection failed!")}</p>
              </div>
            </div>
          )}

          {dialogError && (
            <div className="p-3 rounded-md bg-red-50 text-red-800">
              <div className="flex items-center">
                <AlertCircle className="h-5 w-5 mr-2" />
                <p>{dialogError}</p>
              </div>
            </div>
          )}

          <div className="flex justify-end space-x-2 mt-4">
            {/* Test button can be added here if needed for edit mode too */}
            <Button
              onClick={handleSubmit}
              disabled={!currentConnection.name || !currentConnection.type || isTestingConnection || isLoading}
            >
              {isLoading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {isEditMode ? "Updating..." : "Creating..."}
                </>
              ) : (
                submitButtonText
              )}
            </Button>
          </div>
        </div>
      </div>
    );
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => {
      if (!open) {
        resetForm(); // Reset form when dialog is closed by any means
      }
      onClose();
    }}>
      <DialogContent className="bg-white max-w-3xl">
        {page === "list" && renderConnectionsList()}
        {page === "add" && renderConnectionForm(false)}
        {page === "edit" && renderConnectionForm(true)}
      </DialogContent>
    </Dialog>
  )
}

export default DataConnectionsDialog
