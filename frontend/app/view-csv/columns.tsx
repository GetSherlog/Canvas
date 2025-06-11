"use client"

import { ColumnDef } from "@tanstack/react-table"

// Define a generic type for now, this will be replaced by the parsed CSV data type
export type CsvRow = Record<string, string | number | boolean | null>

// Placeholder columns, will be generated dynamically later
export const columns: ColumnDef<CsvRow>[] = [] 