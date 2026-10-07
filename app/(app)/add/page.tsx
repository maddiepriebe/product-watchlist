import { AddWizard } from "@/components/add/AddWizard";
import { createClient } from "@/lib/supabase/server";

export default async function AddPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return <AddWizard link={null} email={user?.email ?? ""} />;
}
