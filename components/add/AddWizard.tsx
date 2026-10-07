"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { detectAction } from "@/app/(app)/add/actions";
import type { Detected } from "@/lib/add/types";
import { ConfirmStep, type ConfirmChoice } from "./ConfirmStep";
import { PasteStep } from "./PasteStep";

/** Set when the page was opened with ?watch=<id>: add a source to that watch. */
export interface LinkTarget {
  watchId: string;
  title: string;
}

type Step =
  | { name: "paste" }
  | { name: "confirm"; detected: Detected }
  | { name: "alert"; detected: Detected; choice: ConfirmChoice };

export function AddWizard({ link }: { link: LinkTarget | null }) {
  const [step, setStep] = useState<Step>({ name: "paste" });
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function detect() {
    setError(null);
    startTransition(async () => {
      const result = await detectAction({ url });
      switch (result.kind) {
        case "detected":
          setStep({ name: "confirm", detected: result.detected });
          break;
        case "manual":
        case "unsupported":
        case "retry":
          setError(result.message);
          break;
      }
    });
  }

  return (
    <div className="mx-auto w-full max-w-xl">
      <h1 className="text-xl font-medium text-ink">
        {link ? (
          <>
            Link another retailer to{" "}
            <span className="text-ink2">{link.title}</span>
          </>
        ) : (
          "Add a product"
        )}
      </h1>
      <p className="mt-1 text-ink2">
        {link
          ? "Paste the same item from a different store. We'll track both."
          : "Paste a link to the product page. We'll find the price."}
      </p>

      <div className="mt-6 border border-rule bg-surface p-6 sm:p-8 rounded-[2px]">
        {step.name === "paste" && (
          <PasteStep
            url={url}
            onUrlChange={setUrl}
            onSubmit={detect}
            pending={pending}
            error={error}
          />
        )}
        {step.name === "confirm" && (
          <ConfirmStep
            detected={step.detected}
            pickVariants={!link}
            askNickname={!link}
            onConfirm={(choice) =>
              setStep({ name: "alert", detected: step.detected, choice })
            }
            onReject={() => {
              setError(null);
              setStep({ name: "paste" });
            }}
            pending={pending}
            error={error}
          />
        )}
        {step.name === "alert" && <p className="text-ink2">Set an alert.</p>}
      </div>

      <p className="mt-6 text-sm">
        <Link
          href="/watchlist"
          className="text-ink2 underline underline-offset-4 hover:text-ink"
        >
          Back to watchlist
        </Link>
      </p>
    </div>
  );
}
