import type React from "react"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

interface SQLResultViewProps {
  result: {
    rows?: Array<Record<string, unknown>>
    rowCount?: number
    executionTime?: number
  } | null
}

const SQLResultView: React.FC<SQLResultViewProps> = ({ result }) => {
  // Handle different result formats
  if (!result || !result.rows || !Array.isArray(result.rows) || result.rows.length === 0) {
    return (
      <div className="text-gray-500 italic">
        {result?.rowCount === 0 ? "Query executed successfully. No rows returned." : "No results available."}
      </div>
    )
  }

  // Extract column names from the first row
  const columns = Object.keys(result.rows[0])

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column, index) => (
              <TableHead key={index}>{column}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {result.rows.map((row, rowIndex) => (
            <TableRow key={rowIndex}>
              {columns.map((column, colIndex) => (
                <TableCell key={colIndex}>{formatCellValue(row[column])}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="mt-2 text-sm text-gray-500">
        {result.rowCount === 1 ? "1 row" : `${result.rowCount} rows`} returned in {result.executionTime || "?"} ms
      </div>
    </div>
  )
}

// Helper function to format cell values
const formatCellValue = (value: unknown): React.ReactNode => {
  if (value === null || value === undefined) {
    return <span className="text-gray-400 italic">NULL</span>
  }

  if (typeof value === "object") {
    if (value instanceof Date) {
      return value.toISOString()
    }
    return JSON.stringify(value)
  }

  return String(value)
}

export default SQLResultView
