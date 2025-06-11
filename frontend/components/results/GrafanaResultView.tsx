import type React from "react"
import Image from "next/image"
import { LineChart } from "@tremor/react"

interface GrafanaResultViewProps {
  result: {
    panels?: Array<{
      title: string
      imageUrl?: string
    }>
    series?: Array<{
      name?: string
      points: Array<[number, number]>
    }>
    logs?: Array<{
      timestamp: string | number
      level: string
      message: string
    }>
    executionTime?: number
  } | string | null
  queryType: string
}

const GrafanaResultView: React.FC<GrafanaResultViewProps> = ({ result, queryType }) => {
  if (!result) {
    return <div className="text-gray-500 italic">No results available.</div>
  }

  // Handle dashboard panels
  if (queryType === "dashboard" && typeof result === 'object' && result !== null) {
    return (
      <div>
        {result.panels && result.panels.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {result.panels.map((panel, index) => (
              <div key={index} className="border rounded-md p-4">
                <h3 className="text-sm font-semibold mb-2">{panel.title}</h3>
                {panel.imageUrl ? (
                  <Image 
                    src={panel.imageUrl || "/placeholder.svg"} 
                    alt={panel.title} 
                    width={600}
                    height={400}
                    style={{ width: '100%', height: 'auto' }}
                  />
                ) : (
                  <div className="text-gray-500 italic">Panel image not available</div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-gray-500 italic">No dashboard panels found</div>
        )}
      </div>
    )
  }

  // Handle metrics results
  if (queryType === "metrics" && typeof result === 'object' && result !== null) {
    if (!result.series || !Array.isArray(result.series) || result.series.length === 0) {
      return <div className="text-gray-500 italic">No metrics data available.</div>
    }

    // Transform the data for Tremor charts
    const chartData = transformMetricsData(result.series)
    const categories = result.series.map((s) => s.name || "Series")

    return (
      <div>
        <div className="h-80">
          <LineChart
            data={chartData}
            index="timestamp"
            categories={categories}
            colors={["blue", "green", "red", "purple", "orange", "yellow"]}
            yAxisWidth={60}
            showLegend={true}
            showGridLines={true}
            showAnimation={true}
          />
        </div>

        {result.executionTime && (
          <div className="mt-2 text-sm text-gray-500">Query executed in {result.executionTime} ms</div>
        )}
      </div>
    )
  }

  // Handle logs results
  if (queryType === "logs" && typeof result === 'object' && result !== null) {
    if (!result.logs || !Array.isArray(result.logs) || result.logs.length === 0) {
      return <div className="text-gray-500 italic">No logs data available.</div>
    }

    return (
      <div>
        <div className="bg-gray-900 text-gray-100 p-4 rounded-md font-mono text-sm overflow-x-auto">
          {result.logs.map((log, index) => (
            <div key={index} className="mb-1 border-b border-gray-700 pb-1">
              <span className="text-gray-400">{new Date(log.timestamp).toISOString()}</span>{" "}
              <span className={`px-1 rounded ${getLogLevelColor(log.level)}`}>{log.level}</span>{" "}
              <span>{log.message}</span>
            </div>
          ))}
        </div>

        {result.executionTime && (
          <div className="mt-2 text-sm text-gray-500">
            {result.logs.length} log entries returned in {result.executionTime} ms
          </div>
        )}
      </div>
    )
  }

  // Generic fallback for unknown result types
  return (
    <div>
      <pre className="bg-gray-100 p-3 rounded text-sm overflow-auto">
        {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
      </pre>
    </div>
  )
}

// Helper function to transform metrics data for charts
const transformMetricsData = (series: Array<{ name?: string; points: Array<[number, number]> }>) => {
  // Find all unique timestamps across all series
  const allTimestamps = new Set<string>()
  series.forEach((s) => {
    s.points.forEach((point) => {
      allTimestamps.add(new Date(point[0]).toISOString())
    })
  })

  // Create a map of timestamp -> values for each series
  const seriesMap = new Map<string, Map<string, number>>()
  series.forEach((s) => {
    const seriesName = s.name || "Series"
    const valueMap = new Map<string, number>()

    s.points.forEach((point) => {
      const timestamp = new Date(point[0]).toISOString()
      valueMap.set(timestamp, point[1])
    })

    seriesMap.set(seriesName, valueMap)
  })

  // Create the chart data array
  const chartData = Array.from(allTimestamps)
    .sort()
    .map((timestamp) => {
      const dataPoint: Record<string, string | number | null> = { timestamp }

      seriesMap.forEach((valueMap, seriesName) => {
        dataPoint[seriesName] = valueMap.get(timestamp) || null
      })

      return dataPoint
    })

  return chartData
}

// Helper function to get log level color
const getLogLevelColor = (level: string) => {
  const lowerLevel = (level || "").toLowerCase()

  switch (lowerLevel) {
    case "error":
    case "err":
    case "fatal":
      return "bg-red-600"
    case "warn":
    case "warning":
      return "bg-yellow-600"
    case "info":
      return "bg-blue-600"
    case "debug":
      return "bg-green-600"
    case "trace":
      return "bg-purple-600"
    default:
      return "bg-gray-600"
  }
}

export default GrafanaResultView
