import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Handles the magic-link redirect. Supabase sends the user here with a
 * one-time `code`; we exchange it for a session (sets the auth cookies via
 * the server client) and forward to the app. `next` is constrained to a
 * relative path to prevent open redirects.
 */
export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const nextParam = searchParams.get("next") ?? "/watchlist";
  const next = nextParam.startsWith("/") ? nextParam : "/watchlist";

  if (code) {
    const supabase = await createClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      return NextResponse.redirect(`${origin}${next}`);
    }
  }

  return NextResponse.redirect(`${origin}/login?error=link`);
}
