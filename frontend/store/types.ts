import { z } from "zod"

// Define schemas with Zod for type safety
export const CellStatusSchema = z.enum([
  "idle",
  "queued",
  "running",
  "success",
  "error",
  "stale",
])
export type CellStatus = z.infer<typeof CellStatusSchema>

// Simplified cell types - only markdown and tool
export const CellTypeSchema = z.enum([
  "markdown",
  "tool",
])
export type CellType = z.infer<typeof CellTypeSchema>

// Legacy cell types - for reference only, these should be mapped to "tool" type
export const LegacyCellTypes = [
  "github",
  "summarization",
  "investigation_report",
  "filesystem",
  "python",
  "media_timeline",
  "code_index_query",
  "log_ai",
  "sql",
  "s3",
  "metric",
  "ai_query",
] as const

// New schema for CellResult matching backend
export const CellResultSchema = z.object({
  content: z.any().optional(),
  error: z.string().optional(),
  execution_time: z.number().optional(),
  timestamp: z.string().datetime().optional(),
})
export type CellResult = z.infer<typeof CellResultSchema>

export const CellSchema = z.object({
  id: z.string(),
  notebook_id: z.string(),
  type: CellTypeSchema,
  content: z.string(),
  result: CellResultSchema.optional(),
  status: CellStatusSchema,
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
  metadata: z.record(z.any()).optional(),
  connection_id: z.number().int().optional(),
  error: z.string().optional(),
  dependencies: z.array(z.string()).optional(),
  dependents: z.array(z.string()).optional(),
  tool_name: z.string().optional(),
  tool_arguments: z.record(z.any()).optional(),
  tool_call_id: z.string().uuid().optional(),
  settings: z.record(z.any()).optional(),
  isNew: z.boolean().optional(),
})
export type Cell = z.infer<typeof CellSchema>

export const NotebookSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string().optional(),
  created_at: z.string().datetime(),
  updated_at: z.string().datetime(),
  metadata: z.record(z.any()).optional(),
  cells: z.record(CellSchema).optional(),
})
export type Notebook = z.infer<typeof NotebookSchema>

// --- Update: Remove 'grafana' and 'python' from ConnectionTypeSchema ---
export const ConnectionTypeSchema = z.enum(["github", "jira", "filesystem", "git_repo", "logai_workspace"]) // Added "git_repo" and "logai_workspace"
export type ConnectionType = z.infer<typeof ConnectionTypeSchema>

export const ConnectionSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: ConnectionTypeSchema,
  config: z.record(z.any()),
  is_default: z.boolean(),
})

export const WebSocketStatusSchema = z.enum(["connecting", "connected", "disconnected", "error"])
export type WebSocketStatus = z.infer<typeof WebSocketStatusSchema>

export const WebSocketMessageSchema = z.object({
  type: z.string(),
  data: z.any(),
})
export type WebSocketMessage = z.infer<typeof WebSocketMessageSchema>

// --- Tool Definitions ---
// Removed ToolParameter and ToolDefinition

// --- Simplified Tool Info Structure (matches backend) ---
export interface MCPToolInfo {
  name: string;
  description?: string | null; // Match Optional[str] from Pydantic
  inputSchema: Record<string, any>; // Raw JSON Schema (Record<string, any> is equivalent to Dict[str, Any])
}
// --- End Simplified Tool Info Structure ---

// Interface for the base connection structure returned by the list endpoint
// Configuration is redacted here
export interface ConnectionListItem {
  id: string;
  name: string;
  type: ConnectionType;
  is_default: boolean;
  config: Record<string, any>; // Redacted config is just a generic object
}
export interface GithubConnectionConfig {
  // github_pat is redacted
  [key: string]: any; // Allow other potential fields
}

// New interface for Jira redacted config
export interface JiraConnectionConfig {
  jira_url?: string;
  jira_auth_type?: 'cloud' | 'server';
  jira_ssl_verify?: boolean;
  jira_username?: string; // May or may not be redacted by backend policy
  enabled_tools?: string;
  read_only_mode?: boolean;
  jira_projects_filter?: string;
  // api_token and personal_token are redacted
  [key: string]: any; // Allow other potential fields
}

// New interface for Filesystem redacted config (Placeholder)
export interface FileSystemConnectionConfig {
  base_path?: string; // Example field, assuming backend redacts sensitive details
  allowed_paths?: string[]; // Example field
  [key: string]: any; // Allow other potential fields
}

// New interface for GitRepo redacted config
export interface GitRepoConnectionConfig {
  repo_url?: string; // This is the main config
  collection_name?: string; // This might be added by the backend
  [key: string]: any;
}

// Represents a fully loaded connection object (potentially used in UI state after fetching details)
// The config here uses the specific interfaces defined above.
export interface Connection {
  id: string;
  name: string;
  type: ConnectionType;
  is_default: boolean;
  config: GithubConnectionConfig | JiraConnectionConfig | FileSystemConnectionConfig | GitRepoConnectionConfig | Record<string, any>; // Use specific types + fallback
}
export interface GithubConnectionCreateFormData {
  name: string;
  github_personal_access_token: string;
}

// New interface for Jira form data
export interface JiraConnectionCreateFormData {
  name: string;
  jira_url: string;
  jira_auth_type: 'cloud' | 'server';
  jira_ssl_verify: boolean;
  jira_username?: string; // Optional in form, required for cloud submission
  jira_api_token?: string; // Optional in form, required for cloud submission
  jira_personal_token?: string; // Optional in form, required for server submission
  enabled_tools?: string;
  read_only_mode?: boolean | null; // Allow null if using a tri-state or default
  jira_projects_filter?: string;
}

// New interface for Filesystem form data (Placeholder)
export interface FileSystemConnectionCreateFormData {
  name: string;
  base_path: string;
  allowed_paths?: string[]; // Optional example
}

// New interface for GitRepo form data
export interface GitRepoConnectionCreateFormData {
  name: string;
  repo_url: string;
}
