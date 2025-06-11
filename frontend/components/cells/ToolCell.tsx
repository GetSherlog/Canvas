import type React from "react"
import { useState } from "react"
import { Trash2, Play, ChevronDown, ChevronRight, AlertCircle } from "lucide-react"
import type { Cell } from "../../store/types"
import { Button } from "../ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card"
import { Badge } from "../ui/badge"
import dynamic from 'next/dynamic'

const ReactMarkdown = dynamic(() => import('react-markdown'), { ssr: false })
const CodeBlock = dynamic(() => import('../ui/code-block').then(mod => mod.CodeBlock), { ssr: false })

interface ToolCellProps {
  cell: Cell
  onExecute: (cellId: string) => void
  onUpdate: (cellId: string, content: string, metadata?: Record<string, unknown>) => void
  onDelete: (cellId: string) => void
  isExecuting: boolean
}

const ToolCell: React.FC<ToolCellProps> = ({ cell, onExecute, onDelete, isExecuting }) => {
  const [isExpanded, setIsExpanded] = useState(true)
  
  // Get the original tool type from metadata or use tool_name
  const toolType = cell.metadata?.original_type || cell.tool_name || 'unknown'
  const displayName = getToolDisplayName(toolType)
  const toolColor = getToolColor(toolType)
  
  const hasResult = !!cell.result
  const hasError = !!cell.result?.error
  const resultContent = cell.result?.content || cell.result?.output

  // Tool-specific rendering functions
  const renderToolContent = () => {
    switch(toolType) {
      case 'github':
        return renderGitHubContent()
      case 'python':
        return renderPythonContent()
      case 'filesystem':
        return renderFileSystemContent()
      case 'log_ai':
        return renderLogAIContent()
      default:
        return renderGenericContent()
    }
  }

  const renderGitHubContent = () => {
    try {
      const query = JSON.parse(cell.content)
      return (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="font-medium">Repository:</span>
            <code className="px-2 py-1 bg-gray-100 rounded text-sm">{query.repo || 'N/A'}</code>
          </div>
          {query.query && (
            <div>
              <span className="font-medium">Query:</span>
              <pre className="mt-1 p-2 bg-gray-50 rounded text-sm whitespace-pre-wrap">{query.query}</pre>
            </div>
          )}
        </div>
      )
    } catch {
      return <pre className="text-sm">{cell.content}</pre>
    }
  }

  const renderPythonContent = () => (
    <CodeBlock
      code={cell.content}
      language="python"
      showLineNumbers={true}
    />
  )

  const renderFileSystemContent = () => {
    try {
      const query = JSON.parse(cell.content)
      return (
        <div className="space-y-2">
          {query.path && (
            <div className="flex items-center gap-2">
              <span className="font-medium">Path:</span>
              <code className="px-2 py-1 bg-gray-100 rounded text-sm">{query.path}</code>
            </div>
          )}
          {query.query && (
            <div>
              <span className="font-medium">Query:</span>
              <pre className="mt-1 p-2 bg-gray-50 rounded text-sm whitespace-pre-wrap">{query.query}</pre>
            </div>
          )}
        </div>
      )
    } catch {
      return <pre className="text-sm">{cell.content}</pre>
    }
  }

  const renderLogAIContent = () => {
    if (cell.tool_name && cell.tool_arguments) {
      return (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="font-medium">Tool:</span>
            <code className="px-2 py-1 bg-gray-100 rounded text-sm">{cell.tool_name}</code>
          </div>
          {Object.keys(cell.tool_arguments).length > 0 && (
            <div>
              <span className="font-medium">Arguments:</span>
              <pre className="mt-1 p-2 bg-gray-50 rounded text-sm whitespace-pre-wrap">
                {JSON.stringify(cell.tool_arguments, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )
    }
    return <pre className="text-sm">{cell.content}</pre>
  }

  const renderGenericContent = () => (
    <pre className="text-sm whitespace-pre-wrap">{cell.content}</pre>
  )

  const renderResult = () => {
    if (!hasResult) return null

    if (hasError) {
      return (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md">
          <div className="flex items-center gap-2 text-red-700">
            <AlertCircle className="w-4 h-4" />
            <span className="font-medium">Error</span>
          </div>
          <pre className="mt-2 text-sm text-red-600">{cell.result?.error}</pre>
        </div>
      )
    }

    // Tool-specific result rendering
    switch(toolType) {
      case 'python':
        return renderPythonResult()
      case 'github':
        return renderGitHubResult()
      default:
        return renderGenericResult()
    }
  }

  const renderPythonResult = () => {
    const result = cell.result?.content || {}
    return (
      <div className="mt-4 space-y-2">
        {result.stdout && (
          <div>
            <div className="text-sm font-medium text-gray-600 mb-1">Output:</div>
            <pre className="p-3 bg-gray-50 rounded-md text-sm overflow-x-auto">{result.stdout}</pre>
          </div>
        )}
        {result.stderr && (
          <div>
            <div className="text-sm font-medium text-red-600 mb-1">Error Output:</div>
            <pre className="p-3 bg-red-50 rounded-md text-sm text-red-600 overflow-x-auto">{result.stderr}</pre>
          </div>
        )}
      </div>
    )
  }

  const renderGitHubResult = () => {
    if (typeof resultContent === 'string') {
      return (
        <div className="mt-4">
          <div className="prose prose-sm max-w-none">
            <ReactMarkdown>{resultContent}</ReactMarkdown>
          </div>
        </div>
      )
    }
    return renderGenericResult()
  }

  const renderGenericResult = () => (
    <div className="mt-4">
      <div className="text-sm font-medium text-gray-600 mb-1">Result:</div>
      <pre className="p-3 bg-gray-50 rounded-md text-sm overflow-x-auto">
        {typeof resultContent === 'object' ? JSON.stringify(resultContent, null, 2) : resultContent}
      </pre>
    </div>
  )

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsExpanded(!isExpanded)}
              className="p-1"
            >
              {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </Button>
            <CardTitle className="text-base font-medium">
              {displayName}
            </CardTitle>
            <Badge variant="secondary" className={`${toolColor} text-white`}>
              {toolType}
            </Badge>
            {cell.status && (
              <Badge variant={cell.status === 'success' ? 'default' : 'destructive'}>
                {cell.status}
              </Badge>
            )}
          </div>
          <div className="flex gap-2">
            {!hasResult && (
              <Button
                size="sm"
                onClick={() => onExecute(cell.id)}
                disabled={isExecuting}
              >
                <Play className="w-4 h-4 mr-1" />
                Run
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onDelete(cell.id)}
            >
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      {isExpanded && (
        <CardContent>
          {renderToolContent()}
          {renderResult()}
        </CardContent>
      )}
    </Card>
  )
}

// Helper functions
function getToolDisplayName(toolType: string): string {
  const displayNames: Record<string, string> = {
    github: "GitHub Query",
    python: "Python Code",
    filesystem: "File System Query",
    log_ai: "Log-AI Analysis",
    summarization: "AI Summary",
    investigation_report: "Investigation Report",
    media_timeline: "Media Timeline",
    code_index_query: "Code Index Query",
    sql: "SQL Query",
    s3: "S3 Query",
    metric: "Metric Query",
    ai_query: "AI Query"
  }
  return displayNames[toolType] || "Tool Query"
}

function getToolColor(toolType: string): string {
  const colors: Record<string, string> = {
    github: "bg-purple-600",
    python: "bg-blue-600",
    filesystem: "bg-green-600",
    log_ai: "bg-indigo-600",
    summarization: "bg-yellow-600",
    investigation_report: "bg-red-600",
    media_timeline: "bg-pink-600",
    code_index_query: "bg-gray-600",
    sql: "bg-teal-600",
    s3: "bg-orange-600",
    metric: "bg-cyan-600",
    ai_query: "bg-violet-600"
  }
  return colors[toolType] || "bg-gray-600"
}

export default ToolCell