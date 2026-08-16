/**
 * ⚠️ PLACEHOLDER — NOT the real schema.
 *
 * Per project convention, DB types are GENERATED from Supabase, never
 * hand-written. This is an empty, valid shell so the typed client compiles
 * before credentials exist. Once `.env.local` has real Supabase values, run:
 *
 *     SUPABASE_PROJECT_ID=<ref> pnpm gen:types
 *
 * which OVERWRITES this file with the true schema types. Do not hand-edit
 * table shapes here.
 */
export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

export type Database = {
  public: {
    Tables: Record<string, never>;
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: Record<string, never>;
    CompositeTypes: Record<string, never>;
  };
};
