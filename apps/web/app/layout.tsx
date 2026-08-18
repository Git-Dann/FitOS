import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fitos/ui/tokens.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "FitOS Gap Intelligence",
  description: "A governed ledger of gaps, evidence and actions.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  // Dark is the default theme. See docs/design-system.md §2.
  return (
    <html lang="en-GB" data-theme="dark">
      <body>{children}</body>
    </html>
  );
}
