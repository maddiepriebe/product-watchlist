import { redirect } from "next/navigation";

export default function Home() {
  // The middleware sends unauthenticated visitors to /login; authenticated
  // ones land on the watchlist.
  redirect("/watchlist");
}
