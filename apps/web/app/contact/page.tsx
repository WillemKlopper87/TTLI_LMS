import { ContactForm } from "./contact-form";

export const metadata = {
  title: "Contact us",
  description: "We would really like to hear from you — send us a message.",
  alternates: { canonical: "/contact" },
};

export default function ContactPage() {
  return <ContactForm />;
}
