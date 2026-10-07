export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[]

export type Database = {
  public: {
    Tables: {
      notifications: {
        Row: {
          delivered: boolean
          error: string | null
          id: number
          price_cents: number
          reason: Database["public"]["Enums"]["alert_reason"]
          sent_at: string
          source_id: string | null
          variant_id: string | null
          watch_id: string
        }
        Insert: {
          delivered?: boolean
          error?: string | null
          id?: number
          price_cents: number
          reason: Database["public"]["Enums"]["alert_reason"]
          sent_at?: string
          source_id?: string | null
          variant_id?: string | null
          watch_id: string
        }
        Update: {
          delivered?: boolean
          error?: string | null
          id?: number
          price_cents?: number
          reason?: Database["public"]["Enums"]["alert_reason"]
          sent_at?: string
          source_id?: string | null
          variant_id?: string | null
          watch_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "notifications_source_id_fkey"
            columns: ["source_id"]
            referencedRelation: "my_watchlist"
            referencedColumns: ["source_id"]
          },
          {
            foreignKeyName: "notifications_source_id_fkey"
            columns: ["source_id"]
            referencedRelation: "product_sources"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "notifications_variant_id_fkey"
            columns: ["variant_id"]
            referencedRelation: "my_watchlist"
            referencedColumns: ["variant_id"]
          },
          {
            foreignKeyName: "notifications_variant_id_fkey"
            columns: ["variant_id"]
            referencedRelation: "variants"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "notifications_watch_id_fkey"
            columns: ["watch_id"]
            referencedRelation: "my_watchlist"
            referencedColumns: ["watch_id"]
          },
          {
            foreignKeyName: "notifications_watch_id_fkey"
            columns: ["watch_id"]
            referencedRelation: "watches"
            referencedColumns: ["id"]
          },
        ]
      }
      price_points: {
        Row: {
          currency: string
          id: number
          in_stock: boolean
          observed_at: string
          price_cents: number
          variant_id: string
        }
        Insert: {
          currency?: string
          id?: number
          in_stock?: boolean
          observed_at?: string
          price_cents: number
          variant_id: string
        }
        Update: {
          currency?: string
          id?: number
          in_stock?: boolean
          observed_at?: string
          price_cents?: number
          variant_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "price_points_variant_id_fkey"
            columns: ["variant_id"]
            referencedRelation: "my_watchlist"
            referencedColumns: ["variant_id"]
          },
          {
            foreignKeyName: "price_points_variant_id_fkey"
            columns: ["variant_id"]
            referencedRelation: "variants"
            referencedColumns: ["id"]
          },
        ]
      }
      product_sources: {
        Row: {
          canonical_url: string
          check_interval_mins: number
          consecutive_failures: number
          created_at: string
          created_by: string | null
          extractor: Database["public"]["Enums"]["extractor_kind"]
          extractor_config: Json
          id: string
          image_url: string | null
          last_checked_at: string | null
          last_error: string | null
          needs_browser: boolean
          next_check_at: string
          retailer: string
          status: Database["public"]["Enums"]["source_status"]
          title: string | null
          url_hash: string
        }
        Insert: {
          canonical_url: string
          check_interval_mins?: number
          consecutive_failures?: number
          created_at?: string
          created_by?: string | null
          extractor?: Database["public"]["Enums"]["extractor_kind"]
          extractor_config?: Json
          id?: string
          image_url?: string | null
          last_checked_at?: string | null
          last_error?: string | null
          needs_browser?: boolean
          next_check_at?: string
          retailer: string
          status?: Database["public"]["Enums"]["source_status"]
          title?: string | null
          url_hash: string
        }
        Update: {
          canonical_url?: string
          check_interval_mins?: number
          consecutive_failures?: number
          created_at?: string
          created_by?: string | null
          extractor?: Database["public"]["Enums"]["extractor_kind"]
          extractor_config?: Json
          id?: string
          image_url?: string | null
          last_checked_at?: string | null
          last_error?: string | null
          needs_browser?: boolean
          next_check_at?: string
          retailer?: string
          status?: Database["public"]["Enums"]["source_status"]
          title?: string | null
          url_hash?: string
        }
        Relationships: []
      }
      variants: {
        Row: {
          color: string | null
          created_at: string
          id: string
          size: string | null
          sku: string | null
          source_id: string
          variant_key: string
        }
        Insert: {
          color?: string | null
          created_at?: string
          id?: string
          size?: string | null
          sku?: string | null
          source_id: string
          variant_key?: string
        }
        Update: {
          color?: string | null
          created_at?: string
          id?: string
          size?: string | null
          sku?: string | null
          source_id?: string
          variant_key?: string
        }
        Relationships: [
          {
            foreignKeyName: "variants_source_id_fkey"
            columns: ["source_id"]
            referencedRelation: "my_watchlist"
            referencedColumns: ["source_id"]
          },
          {
            foreignKeyName: "variants_source_id_fkey"
            columns: ["source_id"]
            referencedRelation: "product_sources"
            referencedColumns: ["id"]
          },
        ]
      }
      watch_sources: {
        Row: {
          added_at: string
          source_id: string
          watch_id: string
        }
        Insert: {
          added_at?: string
          source_id: string
          watch_id: string
        }
        Update: {
          added_at?: string
          source_id?: string
          watch_id?: string
        }
        Relationships: [
          {
            foreignKeyName: "watch_sources_source_id_fkey"
            columns: ["source_id"]
            referencedRelation: "my_watchlist"
            referencedColumns: ["source_id"]
          },
          {
            foreignKeyName: "watch_sources_source_id_fkey"
            columns: ["source_id"]
            referencedRelation: "product_sources"
            referencedColumns: ["id"]
          },
          {
            foreignKeyName: "watch_sources_watch_id_fkey"
            columns: ["watch_id"]
            referencedRelation: "my_watchlist"
            referencedColumns: ["watch_id"]
          },
          {
            foreignKeyName: "watch_sources_watch_id_fkey"
            columns: ["watch_id"]
            referencedRelation: "watches"
            referencedColumns: ["id"]
          },
        ]
      }
      watches: {
        Row: {
          alert_below_cents: number | null
          alert_on_new_low: boolean
          alert_on_restock: boolean
          alert_pct_drop: number | null
          archived_at: string | null
          channel: Database["public"]["Enums"]["notify_channel"]
          created_at: string
          id: string
          min_alert_gap_hrs: number
          muted_until: string | null
          nickname: string | null
          user_id: string
          watched_variant_keys: string[] | null
        }
        Insert: {
          alert_below_cents?: number | null
          alert_on_new_low?: boolean
          alert_on_restock?: boolean
          alert_pct_drop?: number | null
          archived_at?: string | null
          channel?: Database["public"]["Enums"]["notify_channel"]
          created_at?: string
          id?: string
          min_alert_gap_hrs?: number
          muted_until?: string | null
          nickname?: string | null
          user_id: string
          watched_variant_keys?: string[] | null
        }
        Update: {
          alert_below_cents?: number | null
          alert_on_new_low?: boolean
          alert_on_restock?: boolean
          alert_pct_drop?: number | null
          archived_at?: string | null
          channel?: Database["public"]["Enums"]["notify_channel"]
          created_at?: string
          id?: string
          min_alert_gap_hrs?: number
          muted_until?: string | null
          nickname?: string | null
          user_id?: string
          watched_variant_keys?: string[] | null
        }
        Relationships: []
      }
    }
    Views: {
      my_watchlist: {
        Row: {
          alert_below_cents: number | null
          alert_on_new_low: boolean | null
          alert_on_restock: boolean | null
          alert_pct_drop: number | null
          canonical_url: string | null
          channel: Database["public"]["Enums"]["notify_channel"] | null
          consecutive_failures: number | null
          current_cents: number | null
          current_observed_at: string | null
          current_variant_key: string | null
          display_title: string | null
          has_failing_source: boolean | null
          high_90_cents: number | null
          image_url: string | null
          in_stock: boolean | null
          last_checked_at: string | null
          low_90_cents: number | null
          median_30_cents: number | null
          muted_until: string | null
          nickname: string | null
          pct_rank_90: number | null
          retailer: string | null
          source_count: number | null
          source_id: string | null
          status: Database["public"]["Enums"]["source_status"] | null
          variant_id: string | null
          watch_id: string | null
          watched_variant_keys: string[] | null
        }
        Relationships: []
      }
    }
    Functions: {
      armor: {
        Args: { "": string }
        Returns: string
      }
      dearmor: {
        Args: { "": string }
        Returns: string
      }
      gen_random_bytes: {
        Args: { "": number }
        Returns: string
      }
      gen_random_uuid: {
        Args: Record<PropertyKey, never>
        Returns: string
      }
      gen_salt: {
        Args: { "": string }
        Returns: string
      }
      pgp_armor_headers: {
        Args: { "": string }
        Returns: Record<string, unknown>[]
      }
      pgp_key_id: {
        Args: { "": string }
        Returns: string
      }
    }
    Enums: {
      alert_reason: "below_threshold" | "pct_drop" | "new_low" | "back_in_stock"
      extractor_kind: "jsonld" | "nextdata" | "microdata" | "css" | "manual"
      notify_channel: "email" | "ntfy" | "telegram" | "none"
      source_status: "active" | "failing" | "unsupported" | "paused"
    }
    CompositeTypes: {
      [_ in never]: never
    }
  }
}

type DatabaseWithoutInternals = Omit<Database, "__InternalSupabase">

type DefaultSchema = DatabaseWithoutInternals[Extract<keyof Database, "public">]

export type Tables<
  DefaultSchemaTableNameOrOptions extends
    | keyof (DefaultSchema["Tables"] & DefaultSchema["Views"])
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
        DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? (DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"] &
      DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Views"])[TableName] extends {
      Row: infer R
    }
    ? R
    : never
  : DefaultSchemaTableNameOrOptions extends keyof (DefaultSchema["Tables"] &
        DefaultSchema["Views"])
    ? (DefaultSchema["Tables"] &
        DefaultSchema["Views"])[DefaultSchemaTableNameOrOptions] extends {
        Row: infer R
      }
      ? R
      : never
    : never

export type TablesInsert<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Insert: infer I
    }
    ? I
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Insert: infer I
      }
      ? I
      : never
    : never

export type TablesUpdate<
  DefaultSchemaTableNameOrOptions extends
    | keyof DefaultSchema["Tables"]
    | { schema: keyof DatabaseWithoutInternals },
  TableName extends DefaultSchemaTableNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"]
    : never = never,
> = DefaultSchemaTableNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaTableNameOrOptions["schema"]]["Tables"][TableName] extends {
      Update: infer U
    }
    ? U
    : never
  : DefaultSchemaTableNameOrOptions extends keyof DefaultSchema["Tables"]
    ? DefaultSchema["Tables"][DefaultSchemaTableNameOrOptions] extends {
        Update: infer U
      }
      ? U
      : never
    : never

export type Enums<
  DefaultSchemaEnumNameOrOptions extends
    | keyof DefaultSchema["Enums"]
    | { schema: keyof DatabaseWithoutInternals },
  EnumName extends DefaultSchemaEnumNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"]
    : never = never,
> = DefaultSchemaEnumNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[DefaultSchemaEnumNameOrOptions["schema"]]["Enums"][EnumName]
  : DefaultSchemaEnumNameOrOptions extends keyof DefaultSchema["Enums"]
    ? DefaultSchema["Enums"][DefaultSchemaEnumNameOrOptions]
    : never

export type CompositeTypes<
  PublicCompositeTypeNameOrOptions extends
    | keyof DefaultSchema["CompositeTypes"]
    | { schema: keyof DatabaseWithoutInternals },
  CompositeTypeName extends PublicCompositeTypeNameOrOptions extends {
    schema: keyof DatabaseWithoutInternals
  }
    ? keyof DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"]
    : never = never,
> = PublicCompositeTypeNameOrOptions extends {
  schema: keyof DatabaseWithoutInternals
}
  ? DatabaseWithoutInternals[PublicCompositeTypeNameOrOptions["schema"]]["CompositeTypes"][CompositeTypeName]
  : PublicCompositeTypeNameOrOptions extends keyof DefaultSchema["CompositeTypes"]
    ? DefaultSchema["CompositeTypes"][PublicCompositeTypeNameOrOptions]
    : never

export const Constants = {
  public: {
    Enums: {
      alert_reason: ["below_threshold", "pct_drop", "new_low", "back_in_stock"],
      extractor_kind: ["jsonld", "nextdata", "microdata", "css", "manual"],
      notify_channel: ["email", "ntfy", "telegram", "none"],
      source_status: ["active", "failing", "unsupported", "paused"],
    },
  },
} as const

