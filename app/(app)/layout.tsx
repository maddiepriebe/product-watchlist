import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

async function signOut() {
  "use server";
  const supabase = await createClient();
  await supabase.auth.signOut();
  redirect("/login");
}

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  // Middleware already gates this group; this is defense in depth and gives
  // us the user for the header.
  if (!user) {
    redirect("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 border-b border-rule px-6 py-4">
        <nav className="flex items-center gap-5 text-sm">
          <Link
            href="/watchlist"
            className="font-medium tracking-tight text-ink hover:underline underline-offset-4"
          >
            Watchlist
          </Link>
          <Link
            href="/add"
            className="text-ink2 hover:text-ink hover:underline underline-offset-4"
          >
            Add a product
          </Link>
        </nav>
        <div className="flex items-center gap-4">
          <span className="font-mono text-sm text-ink3">{user.email}</span>
          <form action={signOut}>
            <button
              type="submit"
              className="text-sm text-ink2 underline underline-offset-4 hover:text-ink"
            >
              Sign out
            </button>
          </form>
        </div>
      </header>
      <main className="px-6 py-8">{children}</main>
    </div>
  );
}
