import Link from "next/link";
import { AddWizard, type LinkTarget } from "@/components/add/AddWizard";
import { isUuid } from "@/lib/add/save-input";
import { createClient } from "@/lib/supabase/server";

export default async function AddPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const { watch } = await searchParams;
  const watchId = typeof watch === "string" && isUuid(watch) ? watch : null;

  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  let link: LinkTarget | null = null;
  if (watch !== undefined) {
    // ?watch= was present: link mode, or a clear dead end. Never fall back to
    // "new watch" silently, or the user would add a duplicate by accident.
    // RLS scopes my_watchlist to the signed-in user's own watches.
    const { data } = watchId
      ? await supabase
          .from("my_watchlist")
          .select("display_title, watched_variant_keys")
          .eq("watch_id", watchId)
          .maybeSingle()
      : { data: null };
    if (!watchId || !data) {
      return (
        <div className="mx-auto w-full max-w-xl">
          <h1 className="text-xl font-medium text-ink">
            We couldn&apos;t find that watch
          </h1>
          <p className="mt-2 text-ink2">
            It may have been archived. Open your watchlist to pick another, or
            add a new product.
          </p>
          <p className="mt-4 flex gap-5 text-sm">
            <Link
              href="/watchlist"
              className="text-ink2 underline underline-offset-4 hover:text-ink"
            >
              Back to watchlist
            </Link>
            <Link
              href="/add"
              className="text-ink2 underline underline-offset-4 hover:text-ink"
            >
              Add a product
            </Link>
          </p>
        </div>
      );
    }
    link = {
      watchId,
      title: data.display_title ?? "this watch",
      watchedVariantKeys: data.watched_variant_keys,
    };
  }

  return <AddWizard link={link} email={user?.email ?? ""} />;
}
