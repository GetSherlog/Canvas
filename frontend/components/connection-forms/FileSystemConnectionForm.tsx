import React from "react"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Plus, Trash } from "lucide-react"

interface FileSystemConnectionFormProps {
  config: {
    allowed_directories?: string[]
  }
  onConfigChange: (field: string, value: string | string[]) => void
}

const FileSystemConnectionForm: React.FC<FileSystemConnectionFormProps> = ({ config, onConfigChange }) => {
  const allowedDirectories = config.allowed_directories || [""]

  const handleDirectoryChange = (index: number, value: string) => {
    const newDirectories = [...allowedDirectories]
    newDirectories[index] = value
    onConfigChange("allowed_directories", newDirectories)
  }

  const addDirectory = () => {
    onConfigChange("allowed_directories", [...allowedDirectories, ""])
  }

  const removeDirectory = (index: number) => {
    const newDirectories = allowedDirectories.filter((_, i) => i !== index)
    // Ensure there's always at least one input field
    onConfigChange("allowed_directories", newDirectories.length > 0 ? newDirectories : [""])
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-2">
        <Label>Allowed Directories</Label>
        <p className="text-xs text-muted-foreground">
          Provide absolute local directory paths the connection can access.
        </p>
        {allowedDirectories.map((dir, index) => (
          <div key={index} className="flex items-center space-x-2">
            <Input
              type="text"
              value={dir}
              onChange={(e) => handleDirectoryChange(index, e.target.value)}
              placeholder="/path/to/allowed/directory"
              className="flex-grow"
              required
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => removeDirectory(index)}
              disabled={allowedDirectories.length === 1} // Disable remove for the last item
              className="flex-shrink-0"
            >
              <Trash className="h-4 w-4" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={addDirectory}
          className="mt-1 w-full sm:w-auto"
        >
          <Plus className="mr-2 h-4 w-4" /> Add Directory
        </Button>
      </div>
    </div>
  )
}

export default FileSystemConnectionForm 