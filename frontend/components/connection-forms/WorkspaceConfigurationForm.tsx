import React from 'react'
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { AlertCircle, Plus, Trash2, Github, Folder, Info } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"

interface WorkspaceConfigurationFormProps {
  config: Record<string, string | string[] | boolean | undefined>
  onConfigChange: (field: string, value: string | boolean | string[]) => void
}

const WorkspaceConfigurationForm: React.FC<WorkspaceConfigurationFormProps> = ({
  config,
  onConfigChange
}) => {
  // Extract values from config with defaults
  const githubToken = (config.github_token as string) || ''
  const filesystemPaths = (config.filesystem_paths as string[]) || ['']

  const handleAddPath = () => {
    const newPaths = [...filesystemPaths, '']
    onConfigChange('filesystem_paths', newPaths)
  }

  const handleRemovePath = (index: number) => {
    const newPaths = filesystemPaths.filter((_, i) => i !== index)
    // Ensure at least one path
    if (newPaths.length === 0) {
      newPaths.push('')
    }
    onConfigChange('filesystem_paths', newPaths)
  }

  const handlePathChange = (index: number, value: string) => {
    const newPaths = [...filesystemPaths]
    newPaths[index] = value
    onConfigChange('filesystem_paths', newPaths)
  }

  return (
    <div className="space-y-6">
      <Alert>
        <Info className="h-4 w-4" />
        <AlertDescription>
          Configure your workspace to access GitHub repositories, analyze files and logs, execute Python code, and perform advanced data analysis.
          All features are provided through a unified server environment.
        </AlertDescription>
      </Alert>

      {/* GitHub Configuration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Github className="h-5 w-5" />
            GitHub Configuration
          </CardTitle>
          <CardDescription>
            Provide a GitHub Personal Access Token to enable GitHub repository analysis, issue tracking, and code search.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <Label htmlFor="github_token">Personal Access Token (Optional but Recommended)</Label>
            <Input
              id="github_token"
              type="password"
              value={githubToken}
              onChange={(e) => onConfigChange('github_token', e.target.value)}
              placeholder="ghp_xxxxxxxxxxxxxxxxxxxx"
            />
            <p className="text-sm text-muted-foreground">
              Create a token at{' '}
              <a 
                href="https://github.com/settings/tokens" 
                target="_blank" 
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                GitHub Settings → Developer settings → Personal access tokens
              </a>
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Filesystem Configuration */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Folder className="h-5 w-5" />
            Filesystem Paths
          </CardTitle>
          <CardDescription>
            Mount filesystem paths to analyze logs, code, and other files. At least one path is required.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {filesystemPaths.map((path, index) => (
              <div key={index} className="flex items-center gap-2">
                <Input
                  value={path}
                  onChange={(e) => handlePathChange(index, e.target.value)}
                  placeholder="/path/to/mount"
                  className="flex-1"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => handleRemovePath(index)}
                  disabled={filesystemPaths.length === 1}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleAddPath}
              className="w-full"
            >
              <Plus className="h-4 w-4 mr-2" />
              Add Path
            </Button>
          </div>
          {filesystemPaths.some(path => !path.trim()) && (
            <Alert className="mt-4" variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                At least one valid filesystem path is required.
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* Additional Settings */}
      <Card>
        <CardHeader>
          <CardTitle>Additional Settings</CardTitle>
          <CardDescription>
            Advanced configuration options for the workspace server.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="working_dir">Working Directory (Optional)</Label>
              <Input
                id="working_dir"
                value={(config.working_dir as string) || '/workspace'}
                onChange={(e) => onConfigChange('working_dir', e.target.value)}
                placeholder="/workspace"
              />
              <p className="text-sm text-muted-foreground">
                The working directory inside the analysis environment. Default is /workspace.
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="extra_args">Extra Docker Arguments (Optional)</Label>
              <Textarea
                id="extra_args"
                value={(config.extra_args as string) || ''}
                onChange={(e) => onConfigChange('extra_args', e.target.value)}
                placeholder="--memory=4g --cpus=2"
                rows={3}
              />
              <p className="text-sm text-muted-foreground">
                Additional Docker arguments for the analysis environment (one per line).
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default WorkspaceConfigurationForm