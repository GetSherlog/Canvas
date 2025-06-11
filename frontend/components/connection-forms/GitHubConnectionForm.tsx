import type React from "react"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

interface GitHubConnectionFormProps {
  config: Record<string, string>
  onConfigChange: (field: string, value: string) => void
}

const GitHubConnectionForm: React.FC<GitHubConnectionFormProps> = ({
  config,
  onConfigChange,
}) => {
  return (
    <div className="space-y-4">
      <div className="grid gap-2">
        <Label htmlFor="github_personal_access_token">Personal Access Token</Label>
        <Input
          id="github_personal_access_token"
          type="password"
          value={config?.github_personal_access_token || ""}
          onChange={(e) => onConfigChange("github_personal_access_token", e.target.value)}
          placeholder="ghp_..."
        />
        <p className="text-xs text-muted-foreground mt-1">
          Create a token with repo and workflow permissions at{" "}
          <a
            href="https://github.com/settings/tokens"
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:underline"
          >
            github.com/settings/tokens
          </a>
        </p>
      </div>
    </div>
  )
}

export default GitHubConnectionForm 