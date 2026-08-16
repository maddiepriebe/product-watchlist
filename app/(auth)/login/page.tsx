"use client";

import { useState } from "react";
import { createClient } from "@/lib/supabase/client";

type Status = "idle" | "sending" | "sent" | "error";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("sending");
    setError("");

    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/confirm?next=/watchlist`,
      },
    });

    if (error) {
      setError(error.message);
      setStatus("error");
    } else {
      setStatus("sent");
    }
  }

  if (status === "sent") {
    return (
      <Shell>
        <h1 className="text-xl font-medium text-ink">Check your email</h1>
        <p className="mt-2 text-ink2">
          We sent a sign-in link to <span className="font-mono">{email}</span>.
          Open it on this device to continue.
        </p>
        <button
          type="button"
          onClick={() => setStatus("idle")}
          className="mt-6 text-ink2 underline underline-offset-4 hover:text-ink"
        >
          Use a different email
        </button>
      </Shell>
    );
  }

  return (
    <Shell>
      <h1 className="text-xl font-medium text-ink">Sign in</h1>
      <p className="mt-2 text-ink2">
        We&apos;ll email you a link to sign in. No password.
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-3">
        <label htmlFor="email" className="text-sm text-ink3">
          Email
        </label>
        <input
          id="email"
          type="email"
          required
          autoComplete="email"
          autoFocus
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
          className="border border-rule bg-ground px-3 py-2 text-ink outline-none focus:border-ink"
          style={{ borderRadius: "var(--radius)" }}
        />
        <button
          type="submit"
          disabled={status === "sending"}
          className="mt-1 bg-ink px-3 py-2 text-surface disabled:opacity-60"
          style={{ borderRadius: "var(--radius)" }}
        >
          {status === "sending" ? "Sending…" : "Email me a link"}
        </button>
      </form>

      {status === "error" && (
        <p className="mt-4 text-high">
          That didn&apos;t work: {error}. Check the address and try again.
        </p>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div
        className="w-full max-w-sm border border-rule bg-surface p-8"
        style={{ borderRadius: "var(--radius)" }}
      >
        {children}
      </div>
    </main>
  );
}
