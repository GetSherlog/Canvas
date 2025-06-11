import React, { useState } from "react"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Plus, Trash2, Info } from "lucide-react"

interface WorkspaceConfigFormProps {
  config: {
    github_token?: string
    filesystem_paths?: string[]
    [key: string]: string | string[] | undefined
  }
  onConfigChange: (field: string, value: string | string[]) => void
}

export const WorkspaceConfigForm: React.FC<WorkspaceConfigFormProps> = ({ config, onConfigChange }) => {
  const [newPath, setNewPath] = useState("")

  const handleAddPath = () => {
    if (newPath.trim()) {
      const currentPaths = config.filesystem_paths || []
      onConfigChange("filesystem_paths", [...currentPaths, newPath.trim()])
      setNewPath("")
    }
  }

  const handleRemovePath = (index: number) => {
    const currentPaths = config.filesystem_paths || []
    const updatedPaths = currentPaths.filter((_, i) => i !== index)
    onConfigChange("filesystem_paths", updatedPaths)
  }

  return (
    <div className="space-y-6">
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          Configure your workspace to enable all Sherlog Canvas features. The workspace provides unified access to GitHub, filesystem, Python execution, and log analysis.
        </AlertDescription>
      </Alert>

      <Card>
        <CardHeader>
          <CardTitle>GitHub Integration</CardTitle>
          <CardDescription>
            Optional: Add a GitHub Personal Access Token to enable repository analysis and issue tracking
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-2">
            <Label htmlFor="github_token">GitHub Personal Access Token</Label>
            <Input
              id="github_token"
              type="password"
              value={config.github_token || ""}
              onChange={(e) => onConfigChange("github_token", e.target.value)}
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
            />
            <p className="text-sm text-muted-foreground">
              Create a token at{" "}
              <a
                href="https://github.com/settings/tokens"
                target="_blank"
                rel="noopener noreferrer"
                className="underline"
              >
                github.com/settings/tokens
              </a>
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Filesystem Access</CardTitle>
          <CardDescription>
            Required: Specify which directories the workspace can access for log analysis and file operations
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="grid gap-2">
              <Label htmlFor="new_path">Add Directory Path</Label>
              <div className="flex gap-2">
                <Input
                  id="new_path"
                  value={newPath}
                  onChange={(e) => setNewPath(e.target.value)}
                  placeholder="/path/to/your/logs"
                  onKeyPress={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      handleAddPath()
                    }
                  }}
                />
                <Button type="button" onClick={handleAddPath} size="icon">
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {config.filesystem_paths && config.filesystem_paths.length > 0 && (
              <div className="space-y-2">
                <Label>Configured Paths</Label>
                {config.filesystem_paths.map((path, index) => (
                  <div key={index} className="flex items-center gap-2 p-2 bg-muted rounded">
                    <span className="flex-1 font-mono text-sm">{path}</span>
                    <Button
                      type="button"
                      onClick={() => handleRemovePath(index)}
                      size="icon"
                      variant="ghost"
                      className="h-8 w-8"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}

            {(!config.filesystem_paths || config.filesystem_paths.length === 0) && (
              <Alert>
                <AlertDescription>
                  At least one filesystem path is required to create a workspace
                </AlertDescription>
              </Alert>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Additional Capabilities</CardTitle>
          <CardDescription>
            The workspace automatically includes:
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="list-disc list-inside space-y-1 text-sm text-muted-foreground">
            <li>Python execution environment with data science libraries</li>
            <li>Advanced log analysis and pattern detection</li>
            <li>Code search and semantic analysis</li>
            <li>Media analysis for screenshots and videos</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  )
}