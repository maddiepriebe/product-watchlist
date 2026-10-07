"use client";

import Link from "next/link";
import { useState, useTransition } from "react";
import { detectAction } from "@/app/(app)/add/actions";
import type { Detected, DetectedVariant } from "@/lib/add/types";
import { AlertStep } from "./AlertStep";
import { ConfirmStep, type ConfirmChoice } from "./ConfirmStep";
import { ManualStep } from "./ManualStep";
import { PasteStep } from "./PasteStep";
import { UnsupportedStep } from "./UnsupportedStep";

/** Set when the page was opened with ?watch=<id>: add a source to that watch. */
export interface LinkTarget {
  watchId: string;
  title: string;
}

type Step =
  | { name: "paste" }
  | { name: "manual"; message: string }
  | { name: "confirm"; detected: Detected }
  | {
      name: "unsupported";
      message: string;
      retailer: string;
      title: string | null;
    }
  | { name: "alert"; detected: Detected | null; choice: ConfirmChoice | null };

/** The variants this watch will follow, for the alert step's price hint. */
function watchedVariants(
  step: Extract<Step, { name: "alert" }>,
): DetectedVariant[] | null {
  if (!step.detected) return null;
  const keys = step.choice?.watchedVariantKeys;
  return keys
    ? step.detected.variants.filter((v) => keys.includes(v.variant_key))
    : step.detected.variants;
}

function stepLabel(step: Step, total: number): string {
  switch (step.name) {
    case "paste":
      return `Step 1 of ${total} · Paste a link`;
    case "manual":
    case "confirm":
    case "unsupported":
      return `Step 2 of ${total} · Confirm the price`;
    case "alert":
      return `Step 3 of ${total} · Set an alert`;
  }
}

export function AddWizard({
  link,
  email,
}: {
  link: LinkTarget | null;
  email: string;
}) {
  const [step, setStepState] = useState<Step>({ name: "paste" });
  const [url, setUrl] = useState("");
  /** The price text that produced the current result; null for a plain detection. */
  const [priceText, setPriceText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function go(next: Step) {
    setError(null);
    setStepState(next);
  }

  /** Run detection, from the paste step or the manual fallback. */
  function detect(text: string | null) {
    setError(null);
    startTransition(async () => {
      const result = await detectAction({
        url,
        ...(text !== null && { priceText: text }),
      });
      switch (result.kind) {
        case "detected":
          setPriceText(text);
          go({ name: "confirm", detected: result.detected });
          break;
        case "manual":
          go({ name: "manual", message: result.message });
          break;
        case "unsupported":
          setPriceText(text);
          go({
            name: "unsupported",
            message: result.message,
            retailer: result.retailer,
            title: result.title,
          });
          break;
        case "retry":
          setError(result.message);
          break;
      }
    });
  }

  return (
    <div className="mx-auto w-full max-w-xl">
      <p className="mb-2 font-mono text-xs uppercase tracking-wide text-ink3">
        {stepLabel(step, link ? 2 : 3)}
      </p>
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
            onSubmit={() => detect(null)}
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
              go({ name: "alert", detected: step.detected, choice })
            }
            onReject={() =>
              go({
                name: "manual",
                message:
                  "Okay. Tell us the price you see and we'll look for it on the page.",
              })
            }
            pending={pending}
            error={error}
          />
        )}
        {step.name === "manual" && (
          <ManualStep
            message={step.message}
            onSubmit={(text) => detect(text)}
            onCancel={() => go({ name: "paste" })}
            pending={pending}
            error={error}
          />
        )}
        {step.name === "unsupported" && (
          <UnsupportedStep
            message={step.message}
            retailer={step.retailer}
            title={step.title}
            onKeep={() => go({ name: "alert", detected: null, choice: null })}
            onCancel={() => go({ name: "paste" })}
            pending={pending}
            error={error}
          />
        )}
        {step.name === "alert" && (
          <AlertStep
            email={email}
            watched={watchedVariants(step)}
            onSubmit={() => undefined}
            pending={pending}
            error={error}
          />
        )}
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
