import type React from "react"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

interface JiraConnectionFormProps {
  config: Record<string, string | boolean>
  onConfigChange: (field: string, value: string | boolean) => void
}

const JiraConnectionForm: React.FC<JiraConnectionFormProps> = ({
  config,
  onConfigChange,
}) => {
  return (
    <div className="space-y-4">
      <div className="grid gap-2">
        <Label htmlFor="jira_url">Jira URL</Label>
        <Input
          id="jira_url"
          value={config?.jira_url || ""}
          onChange={(e) => onConfigChange("jira_url", e.target.value)}
          placeholder="https://your-company.atlassian.net"
        />
      </div>
      <div className="grid gap-2">
        <Label>Authentication Type</Label>
        <div className="flex items-center space-x-4">
          <label className="flex items-center space-x-2 cursor-pointer">
            <input
              type="radio"
              name="jira_auth_type"
              value="cloud"
              checked={config?.jira_auth_type === "cloud"}
              onChange={(e) => onConfigChange("jira_auth_type", e.target.value)}
              className="form-radio h-4 w-4 text-primary border-gray-300 focus:ring-primary"
            />
            <span>Cloud</span>
          </label>
          <label className="flex items-center space-x-2 cursor-pointer">
            <input
              type="radio"
              name="jira_auth_type"
              value="server"
              checked={config?.jira_auth_type === "server"}
              onChange={(e) => onConfigChange("jira_auth_type", e.target.value)}
              className="form-radio h-4 w-4 text-primary border-gray-300 focus:ring-primary"
            />
            <span>Server/Data Center</span>
          </label>
        </div>
      </div>

      {config?.jira_auth_type === "cloud" && (
        <>
          <div className="grid gap-2">
            <Label htmlFor="jira_username">Username (Email)</Label>
            <Input
              id="jira_username"
              value={config?.jira_username || ""}
              onChange={(e) => onConfigChange("jira_username", e.target.value)}
              placeholder="your.email@company.com"
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="jira_api_token">API Token</Label>
            <Input
              id="jira_api_token"
              type="password"
              value={config?.jira_api_token || ""}
              onChange={(e) => onConfigChange("jira_api_token", e.target.value)}
              placeholder="Enter API Token"
            />
            <p className="text-xs text-muted-foreground mt-1">
              Create an API token at{" "}
              <a
                href="https://id.atlassian.com/manage-profile/security/api-tokens"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary hover:underline"
              >
                Atlassian Account Security
              </a>
            </p>
          </div>
        </>
      )}

      {config?.jira_auth_type === "server" && (
        <>
          <div className="grid gap-2">
            <Label htmlFor="jira_personal_token">Personal Access Token (PAT)</Label>
            <Input
              id="jira_personal_token"
              type="password"
              value={config?.jira_personal_token || ""}
              onChange={(e) => onConfigChange("jira_personal_token", e.target.value)}
              placeholder="Enter Personal Access Token"
            />
          </div>
          <div className="flex items-center space-x-2">
            <input
              type="checkbox"
              id="jira_ssl_verify"
              checked={config?.jira_ssl_verify !== false}
              onChange={(e) => onConfigChange("jira_ssl_verify", e.target.checked)}
              className="form-checkbox h-4 w-4 text-primary border-gray-300 rounded focus:ring-primary"
            />
            <Label htmlFor="jira_ssl_verify" className="cursor-pointer">Verify SSL Certificate</Label>
          </div>
          <p className="text-xs text-muted-foreground -mt-3 ml-6">Only uncheck if using self-signed certificates.</p>
        </>
      )}
    </div>
  )
}

export default JiraConnectionForm 