"use client"

import type React from "react"
import { useState, useEffect } from "react"
import { useConnectionStore } from "../store/connectionStore"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  AlertCircle,
  CheckCircle,
  Settings,
  Loader2,
  Server,
} from "lucide-react"
import { useToast } from "@/hooks/use-toast"
import WorkspaceConfigurationForm from "./connection-forms/WorkspaceConfigurationForm"
import { Alert, AlertDescription } from "@/components/ui/alert"

interface DataConnectionsDialogProps {
  isOpen: boolean
  onClose: () => void
  initialPage?: "list" | "add"
}

const DataConnectionsDialog: React.FC<DataConnectionsDialogProps> = ({ isOpen, onClose }) => {
  const [workspaceConfig, setWorkspaceConfig] = useState<{
    name: string
    type: string
    config: Record<string, string | string[] | boolean>
  }>({
    name: "My Workspace",
    type: "logai_workspace",
    config: {
      github_token: "",
      filesystem_paths: [""],
      working_dir: "/workspace",
      extra_args: ""
    },
  })
  const [testResult, setTestResult] = useState<{ valid: boolean; message: string } | null>(null)
  const [isTestingConnection, setIsTestingConnection] = useState(false)
  const [isCreatingConnection, setIsCreatingConnection] = useState(false)
  const [dialogError, setDialogError] = useState<string | null>(null)
  const { toast } = useToast()

  // Get state and actions from the store
  const {
    connections,
    loading,
    loadConnections,
    createConnection,
    deleteConnection,
    testConnection,
  } = useConnectionStore()

  // Check if workspace is already configured
  const existingWorkspace = connections.find(conn => conn.type === "workspace")

  // Effect to load connections when dialog opens
  useEffect(() => {
    if (isOpen) {
      loadConnections()
    }
  }, [isOpen, loadConnections])

  // Effect to populate form with existing workspace config
  useEffect(() => {
    if (existingWorkspace) {
      setWorkspaceConfig({
        name: existingWorkspace.name,
        type: existingWorkspace.type,
        config: existingWorkspace.config || {
          github_token: "",
          filesystem_paths: [""],
          working_dir: "/workspace",
          extra_args: ""
        }
      })
    }
  }, [existingWorkspace])

  // Reset state when dialog closes
  useEffect(() => {
    if (!isOpen) {
      setTestResult(null)
      setDialogError(null)
      setIsTestingConnection(false)
      setIsCreatingConnection(false)
    }
  }, [isOpen])

  const handleConfigChange = (field: string, value: string | boolean | string[]) => {
    setWorkspaceConfig((prev) => ({
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

    // Validate configuration
    const paths = workspaceConfig.config.filesystem_paths || []
    const validPaths = paths.filter((p: string) => p.trim())
    if (validPaths.length === 0) {
      setDialogError("At least one filesystem path is required")
      return
    }

    setIsTestingConnection(true)

    try {
      const result = await testConnection({
        ...workspaceConfig,
        config: {
          ...workspaceConfig.config,
          filesystem_paths: validPaths
        }
      })
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

  const handleSaveConfiguration = async () => {
    // Validate configuration
    const paths = workspaceConfig.config.filesystem_paths || []
    const validPaths = paths.filter((p: string) => p.trim())
    if (validPaths.length === 0) {
      setDialogError("At least one filesystem path is required")
      return
    }

    setDialogError(null)
    setIsCreatingConnection(true)

    try {
      const configToSave = {
        ...workspaceConfig,
        config: {
          ...workspaceConfig.config,
          filesystem_paths: validPaths
        }
      }

      let result
      if (existingWorkspace) {
        // Update existing workspace
        result = await deleteConnection(existingWorkspace.id)
        if (result) {
          result = await createConnection(configToSave)
        }
      } else {
        // Create new workspace
        result = await createConnection(configToSave)
      }

      if (result) {
        toast({
          title: "Workspace configured",
          description: "Your workspace has been successfully configured.",
        })
        onClose()
      }
    } catch (err) {
      console.error("Failed to save workspace configuration:", err)
      let errorMessage = "An unknown error occurred during configuration.";
      if (err instanceof Error) {
        errorMessage = err.message
      }
      setDialogError(errorMessage)
    } finally {
      setIsCreatingConnection(false)
    }
  }

  if (loading) {
    return (
      <Dialog open={isOpen} onOpenChange={onClose}>
        <DialogContent className="bg-white max-w-3xl">
          <div className="flex items-center justify-center h-40">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            <span className="ml-2 text-primary">Loading workspace configuration...</span>
          </div>
        </DialogContent>
      </Dialog>
    )
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="bg-white max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Server className="h-5 w-5" />
            Workspace Configuration
          </DialogTitle>
          <DialogDescription>
            Configure your workspace to enable all Sherlog Canvas features including GitHub integration, filesystem access, Python execution, and log analysis.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 mt-6">
          {existingWorkspace && (
            <Alert>
              <Settings className="h-4 w-4" />
              <AlertDescription>
                Your workspace is already configured. You can update the settings below.
              </AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="name">Configuration Name</Label>
            <Input
              id="name"
              value={workspaceConfig.name}
              onChange={(e) => setWorkspaceConfig(prev => ({ ...prev, name: e.target.value }))}
              placeholder="My Workspace"
              className="w-full"
            />
          </div>

          <WorkspaceConfigurationForm 
            config={workspaceConfig.config}
            onConfigChange={handleConfigChange}
          />

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

          <div className="flex justify-end space-x-2 pt-4">
            <Button
              variant="outline"
              onClick={handleTestConnection}
              disabled={isTestingConnection || isCreatingConnection}
            >
              {isTestingConnection ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Testing...
                </>
              ) : (
                "Test Connection"
              )}
            </Button>
            <Button
              onClick={handleSaveConfiguration}
              disabled={isTestingConnection || isCreatingConnection}
            >
              {isCreatingConnection ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Saving...
                </>
              ) : (
                existingWorkspace ? "Update Configuration" : "Save Configuration"
              )}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default DataConnectionsDialog