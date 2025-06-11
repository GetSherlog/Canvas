import type React from "react"
import Image from "next/image"

interface CodeResultViewProps {
  result: {
    stdout?: string
    stderr?: string
    output?: string
    error?: string
    plots?: string[]
    dataframes?: Array<{
      columns: string[]
      data: Array<Array<string | number | boolean | null>>
    }>
    executionTime?: number
    exitCode?: number
  } | string | null
  language: string
}

const CodeResultView: React.FC<CodeResultViewProps> = ({ result, language }) => {
  // Handle different result formats based on language
  if (!result) {
    return <div className="text-gray-500 italic">No results available.</div>
  }

  // For Python results that include stdout, stderr, and possibly plots
  if (language === "python" && typeof result === 'object' && result !== null) {
    return (
      <div>
        {result.stdout && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-1">Output:</h3>
            <pre className="bg-gray-100 p-3 rounded text-sm overflow-auto">{result.stdout}</pre>
          </div>
        )}

        {result.stderr && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-1 text-red-600">Errors:</h3>
            <pre className="bg-red-50 p-3 rounded text-sm overflow-auto text-red-800">{result.stderr}</pre>
          </div>
        )}

        {result.plots && result.plots.length > 0 && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-1">Plots:</h3>
            <div className="flex flex-wrap gap-4">
              {result.plots.map((plot: string, index: number) => (
                <div key={index} className="relative border rounded overflow-hidden">
                  <Image
                    src={`data:image/png;base64,${plot}`}
                    alt={`Plot ${index + 1}`}
                    width={600}
                    height={400}
                    style={{ width: '100%', height: 'auto' }}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {result.dataframes && result.dataframes.length > 0 && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-1">Data Frames:</h3>
            {result.dataframes.map((df, index) => (
              <div key={index} className="overflow-x-auto mb-4">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      {df.columns.map((col: string, colIndex: number) => (
                        <th
                          key={colIndex}
                          className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {df.data.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {row.map((cell, cellIndex) => (
                          <td key={cellIndex} className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {cell === null ? <span className="italic">null</span> : String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}

        {result.executionTime && <div className="text-sm text-gray-500">Executed in {result.executionTime} ms</div>}
      </div>
    )
  }

  // For JavaScript results
  if (language === "javascript" && typeof result === 'object' && result !== null) {
    return (
      <div>
        {result.output && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-1">Output:</h3>
            <pre className="bg-gray-100 p-3 rounded text-sm overflow-auto">{result.output}</pre>
          </div>
        )}

        {result.error && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-1 text-red-600">Error:</h3>
            <pre className="bg-red-50 p-3 rounded text-sm overflow-auto text-red-800">{result.error}</pre>
          </div>
        )}

        {result.executionTime && <div className="text-sm text-gray-500">Executed in {result.executionTime} ms</div>}
      </div>
    )
  }

  // For Bash results
  if (language === "bash" && typeof result === 'object' && result !== null) {
    return (
      <div>
        {result.stdout && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-1">Standard Output:</h3>
            <pre className="bg-gray-100 p-3 rounded text-sm overflow-auto">{result.stdout}</pre>
          </div>
        )}

        {result.stderr && (
          <div className="mb-4">
            <h3 className="text-sm font-semibold mb-1 text-red-600">Standard Error:</h3>
            <pre className="bg-red-50 p-3 rounded text-sm overflow-auto text-red-800">{result.stderr}</pre>
          </div>
        )}

        {result.exitCode !== undefined && (
          <div className="text-sm text-gray-500">
            Exit code: {result.exitCode} {result.executionTime && `(executed in ${result.executionTime} ms)`}
          </div>
        )}
      </div>
    )
  }

  // Generic fallback for other languages or unknown formats
  return (
    <div>
      <pre className="bg-gray-100 p-3 rounded text-sm overflow-auto">
        {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
      </pre>
    </div>
  )
}

export default CodeResultView
