/**
 * Reads the public Supabase env vars. These are the ONLY Supabase secrets
 * the Next.js app is allowed to touch — the service-role key is worker-only
 * and must never appear here. Values are validated at call time (request
 * scope) so a missing .env.local surfaces as a clear runtime error, not a
 * silent misconfiguration.
 */
export function supabaseEnv(): { url: string; anonKey: string } {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    throw new Error(
      "Missing NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY. " +
        "Copy .env.local.example to .env.local and fill in your Supabase project values.",
    );
  }
  return { url, anonKey };
}
