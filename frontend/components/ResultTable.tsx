import type React from "react"

interface ResultTableProps {
  data: Record<string, string | number | boolean | null>[]
}

const ResultTable: React.FC<ResultTableProps> = ({ data }) => (
  <div className="overflow-x-auto">
    <table className="min-w-full bg-white">
      <thead>
        <tr>
          {Object.keys(data[0]).map((key) => (
            <th key={key} className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              {key}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.map((row, i) => (
          <tr key={i} className={i % 2 === 0 ? "bg-gray-50" : "bg-white"}>
            {Object.values(row).map((value, j) => (
              <td key={j} className="px-4 py-2 whitespace-nowrap text-sm text-gray-900">
                {value}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
)

export default ResultTable
