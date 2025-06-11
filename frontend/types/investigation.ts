/**
 * Investigation Report Types
 * These types are used by the InvestigationReportCell component
 */

export interface CodeReference {
  file_path: string;
  line_number?: number | null;
  code_snippet?: string | null;
  url?: string | null;
  component_name?: string | null;
}

export interface Finding {
  summary: string;
  details?: string | null;
  code_reference?: CodeReference | null;
  supporting_quotes?: string[] | null;
}

export interface RelatedItem {
  type: "Pull Request" | "Issue" | "Commit" | "Discussion" | "Documentation" | "Other";
  identifier: string;
  url: string;
  relevance?: string | null;
  status?: string | null;
}

export interface InvestigationReportData {
  query: string;
  title: string;
  status?: string | null;
  status_reason?: string | null;
  estimated_severity?: "Critical" | "High" | "Medium" | "Low" | "Unknown" | null;
  issue_summary: Finding;
  root_cause: Finding;
  root_cause_confidence?: "Low" | "Medium" | "High" | null;
  key_components: CodeReference[];
  related_items: RelatedItem[];
  proposed_fix?: Finding | null;
  proposed_fix_confidence?: "Low" | "Medium" | "High" | null;
  affected_context?: Finding | null;
  suggested_next_steps: string[];
  tags: string[];
  error?: string | null;
}