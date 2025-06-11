"use client";

import React, { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Papa, { ParseResult } from 'papaparse';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { CsvRow } from './columns'; // Import columns definition
import { DataTable } from './data-table'; // Import DataTable component
import { ColumnDef, Row } from '@tanstack/react-table'; // Import Row type
import { DataTableColumnHeader } from '@/components/ui/data-table-column-header'; // Import column header

const CsvViewerContent: React.FC = () => {
  const searchParams = useSearchParams();
  const [csvData, setCsvData] = useState<CsvRow[]>([]); // Use CsvRow type
  const [csvColumns, setCsvColumns] = useState<ColumnDef<CsvRow>[]>([]); // State for dynamic columns
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const filePath = searchParams.get('filePath');


  useEffect(() => {
    // 1. If we have a filePath, fetch from backend as before
    if (filePath) {
      setIsLoading(true);
      setError(null);

      const apiUrl = `/api/read-file?filePath=${encodeURIComponent(filePath)}`;

      fetch(apiUrl)
        .then(response => {
          if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
          }
          return response.text();
        })
        .then(csvText => {
          // parse via Papa (same logic moved to helper function)
          handleCsvText(csvText);
        })
        .catch(err => {
          console.error("Failed to fetch CSV:", err);
          setError(`Failed to load file: ${err.message}`);
          setIsLoading(false);
        });

      return; // Exit early because we used filePath
    }

    // 2. Fallback: Try to read CSV content directly from sessionStorage
    const storedCsv = typeof window !== 'undefined' ? sessionStorage.getItem('fullCsvData') : null;

    if (!storedCsv) {
      setError('File path is missing and no CSV data found.');
      setIsLoading(false);
      return;
    }

    // We have stored CSV text; parse it client-side
    handleCsvText(storedCsv);
  }, [filePath]);

  // Helper to parse CSV text and populate state via Papa
  const handleCsvText = (csvText: string) => {
    Papa.parse<CsvRow>(csvText, { // Use CsvRow type directly here
      header: true,
      skipEmptyLines: true,
      complete: (results: ParseResult<CsvRow>) => { // Add type for results
        if (results.errors.length > 0) {
          console.error("CSV parsing errors:", results.errors);
          setError(`Error parsing CSV: ${results.errors[0].message}`);
          setIsLoading(false);
          return;
        }
        const headers = results.meta.fields;
        if (!headers) {
          setError("Could not extract headers from CSV.");
          setIsLoading(false);
          return;
        }
        setCsvData(results.data); // No need to cast now

        // --- Dynamically generate columns for DataTable ---
        const generatedColumns: ColumnDef<CsvRow>[] = headers.map((header: string): ColumnDef<CsvRow> => ({ // Add return type
          accessorKey: header,
          // Use DataTableColumnHeader for the header
          header: ({ column }) => (
            <DataTableColumnHeader column={column} title={header} />
          ),
          // Optional: Add basic cell rendering
          cell: ({ row }: { row: Row<CsvRow> }) => <div>{row.getValue(header)}</div>, // Add type for row
          // Enable filtering for all columns by default (can be overridden)
          enableColumnFilter: true,
          // Enable sorting for all columns by default (can be overridden)
          enableSorting: true,
        }));
        setCsvColumns(generatedColumns);
        // --- End dynamic column generation ---

        setIsLoading(false);
      },
      error: (err: Error) => { // Use standard Error type
        console.error("CSV parsing error:", err);
        setError(`Failed to parse CSV: ${err.message}`);
        setIsLoading(false);
      }
    });
  };


  if (isLoading) {
    return <div>Loading CSV data...</div>;
  }

  if (error) {
    return <div>Error: {error}</div>;
  }

  if (!csvData.length || !csvColumns.length) { // Check csvColumns as well
    return <div>No data found in the CSV file or no columns defined.</div>;
  }

  return (
    <div className="container mx-auto p-4">
      <Card>
        <CardHeader>
          <CardTitle>CSV Data Viewer</CardTitle>
          <CardDescription>Displaying content of: {filePath}</CardDescription>
        </CardHeader>
        <CardContent>
          {/* --- Replace Tremor Table with shadcn/ui DataTable --- */}
          <DataTable columns={csvColumns} data={csvData} />
          {/* --- End replacement --- */}
        </CardContent>
      </Card>
    </div>
  );
};

// Wrap the component in Suspense in the default export
const FullCsvViewerPage: React.FC = () => {
  return (
    <Suspense fallback={<div>Loading file path...</div>}> {/* Add Suspense wrapper */}
      <CsvViewerContent />
    </Suspense>
  );
};

export default FullCsvViewerPage; 