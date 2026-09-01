import { GuestAccessForm } from "./guest-access-form";

export const metadata = {
  title: "Try a free lesson",
  description: "A full sample lesson and assessment — no payment details required.",
  alternates: { canonical: "/guest-access" },
};

export default function GuestAccessPage() {
  return <GuestAccessForm />;
}
