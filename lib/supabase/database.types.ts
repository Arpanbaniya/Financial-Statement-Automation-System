// Selected Supabase rows used by the authenticated workspace.
type ReadOnlyTable<Row> = {
  Row: Row;
  Insert: never;
  Update: never;
  Relationships: [];
};

export type Database = {
  public: {
    Tables: {
      profiles: {
        Row: {
          id: string;
          display_name: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id: string;
          display_name?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          id?: string;
          display_name?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Relationships: [];
      };
      companies: ReadOnlyTable<{
        id: string;
        user_id: string;
        name: string;
        ticker: string | null;
        country: string | null;
        industry: string | null;
        created_at: string;
      }>;
      documents: ReadOnlyTable<{
        id: string;
        user_id: string;
        company_id: string | null;
        original_filename: string;
        file_size: number;
        mime_type: string;
        status: string;
        created_at: string;
        updated_at: string;
        storage_path: string;
        sha256: string | null;
      }>;
      processing_jobs: ReadOnlyTable<{
        id: string;
        user_id: string;
        document_id: string;
        status: string;
        stage: string;
        progress: number;
        error_code: string | null;
        error_message: string | null;
        created_at: string;
        updated_at: string;
      }>;
      financial_statements: ReadOnlyTable<{
        id: string;
        user_id: string;
        company_id: string;
        document_id: string;
        statement_type: string;
        period_type: string;
        period_start: string | null;
        period_end: string;
        currency: string | null;
        unit_scale: string | null;
        status: string;
        detection_confidence: number | null;
      }>;
      financial_line_items: ReadOnlyTable<{
        id: string;
        user_id: string;
        statement_id: string;
        canonical_name: string | null;
        original_label: string;
        original_value: string | null;
        normalized_value: number | null;
        source_page: number | null;
        source_sheet: string | null;
        source_cell: string | null;
        review_status: string;
      }>;
      financial_metrics: ReadOnlyTable<{
        id: string;
        user_id: string;
        company_id: string;
        statement_id: string | null;
        period_end: string;
        metric_name: string;
        metric_value: number | null;
        formula_version: string;
        metadata: unknown;
        is_stale: boolean;
      }>;
      validation_results: ReadOnlyTable<{
        id: string;
        user_id: string;
        document_id: string;
        statement_id: string | null;
        check_name: string;
        status: string;
        severity: string;
        expected_value: number | null;
        actual_value: number | null;
        difference: number | null;
        message: string | null;
        is_stale: boolean;
      }>;
      manual_reviews: ReadOnlyTable<{
        id: string;
        user_id: string;
        line_item_id: string;
        status: string;
        suggested_mapping: string | null;
        selected_mapping: string | null;
        review_note: string | null;
        created_at: string;
      }>;
      reports: ReadOnlyTable<{
        id: string;
        user_id: string;
        company_id: string;
        document_id: string | null;
        report_type: string;
        status: string;
        storage_path: string | null;
        is_stale: boolean;
        created_at: string;
      }>;
      audit_events: ReadOnlyTable<{
        id: string;
        user_id: string;
        document_id: string | null;
        entity_type: string;
        entity_id: string;
        action: string;
        old_value: unknown;
        new_value: unknown;
        metadata: unknown;
        created_at: string;
      }>;
      canonical_fields: ReadOnlyTable<{
        statement_type: string;
        machine_name: string;
        is_core_field: boolean;
      }>;
    };
    Views: Record<string, never>;
    Functions: {
      resolve_manual_review: {
        Args: {
          p_review_id: string;
          p_action: string;
          p_selected_mapping?: string | null;
          p_reason?: string | null;
        };
        Returns: undefined;
      };
    };
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
};
