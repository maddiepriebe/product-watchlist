import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import type { Database } from "./database.types";
import { supabaseEnv } from "./env";

/**
 * Server Supabase client for Server Components, Route Handlers, and Server
 * Actions. Reads/writes the session cookie so RLS runs as the signed-in
 * user. Uses the anon key only — never the service-role key.
 */
export async function createClient() {
  const cookieStore = await cookies();
  const { url, anonKey } = supabaseEnv();

  return createServerClient<Database>(url, anonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options),
          );
        } catch {
          // Called from a Server Component, where cookies are read-only.
          // The middleware refreshes the session cookie instead — safe to ignore.
        }
      },
    },
  });
}
