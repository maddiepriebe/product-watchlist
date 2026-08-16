import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import type { Database } from "./database.types";
import { supabaseEnv } from "./env";

/** Paths reachable without a session. */
function isPublicPath(pathname: string): boolean {
  return pathname === "/login" || pathname.startsWith("/auth");
}

/**
 * Refreshes the Supabase session on every request and gates the app.
 * Unauthenticated users hitting a protected path are redirected to /login;
 * authenticated users hitting /login are sent on to /watchlist.
 *
 * Follows the @supabase/ssr contract: the returned response carries the
 * refreshed auth cookies, so it (or a copy of its cookies) must be returned.
 */
export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });
  const { url, anonKey } = supabaseEnv();

  const supabase = createServerClient<Database>(url, anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) =>
          request.cookies.set(name, value),
        );
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  // Do not run code between createServerClient and getUser — it keeps the
  // session fresh and avoids hard-to-debug logout bugs.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;

  if (!user && !isPublicPath(pathname)) {
    const redirect = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
    return redirect;
  }

  if (user && pathname === "/login") {
    const redirect = NextResponse.redirect(new URL("/watchlist", request.url));
    response.cookies.getAll().forEach((cookie) => redirect.cookies.set(cookie));
    return redirect;
  }

  return response;
}
