"use client";

import { inputClass, labelClass, primaryButtonClass } from "./ui";

export function PasteStep({
  url,
  onUrlChange,
  onSubmit,
  pending,
  error,
}: {
  url: string;
  onUrlChange: (url: string) => void;
  onSubmit: () => void;
  pending: boolean;
  error: string | null;
}) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
      className="flex flex-col gap-3"
    >
      <label htmlFor="product-url" className={labelClass}>
        Product link
      </label>
      <input
        id="product-url"
        type="url"
        required
        autoFocus
        inputMode="url"
        autoComplete="off"
        placeholder="https://store.example.com/products/…"
        value={url}
        onChange={(event) => onUrlChange(event.target.value)}
        aria-describedby={error ? "product-url-error" : undefined}
        aria-invalid={error ? true : undefined}
        className={`${inputClass} font-mono text-sm`}
      />
      {error && (
        <p id="product-url-error" role="alert" className="text-high">
          {error}
        </p>
      )}
      <div>
        <button type="submit" disabled={pending} className={primaryButtonClass}>
          {pending ? "Checking the price…" : "Check the price"}
        </button>
      </div>
    </form>
  );
}
