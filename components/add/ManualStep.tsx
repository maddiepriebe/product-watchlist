"use client";

import { useState } from "react";
import {
  inputClass,
  labelClass,
  linkButtonClass,
  primaryButtonClass,
} from "./ui";

/**
 * Manual fallback: the user types the price they see, and the worker looks
 * for that exact value on the page. Nothing is saved from this text alone.
 */
export function ManualStep({
  message,
  onSubmit,
  onCancel,
  pending,
  error,
}: {
  message: string;
  onSubmit: (priceText: string) => void;
  onCancel: () => void;
  pending: boolean;
  error: string | null;
}) {
  const [text, setText] = useState("");

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(text.trim());
      }}
      className="flex flex-col gap-3"
    >
      <p className="text-ink2">{message}</p>
      <label htmlFor="price-text" className={labelClass}>
        Paste the price exactly as you see it on the page
      </label>
      <input
        id="price-text"
        type="text"
        required
        autoFocus
        autoComplete="off"
        maxLength={64}
        placeholder="$298.00"
        value={text}
        onChange={(event) => setText(event.target.value)}
        aria-describedby={error ? "price-text-error" : undefined}
        aria-invalid={error ? true : undefined}
        className={`${inputClass} font-mono`}
      />
      {error && (
        <p id="price-text-error" role="alert" className="text-high">
          {error}
        </p>
      )}
      <div className="flex items-center gap-5">
        <button
          type="submit"
          disabled={pending || text.trim() === ""}
          className={primaryButtonClass}
        >
          {pending ? "Looking for it…" : "Find this price"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={pending}
          className={linkButtonClass}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
