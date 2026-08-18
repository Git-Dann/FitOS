import type { Metadata } from "next";
import type { ReactNode } from "react";
import "@fitos/ui/tokens.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "FitOS Gap Intelligence",
  description: "A governed ledger of gaps, evidence and actions.",
};

/**
 * Applied before first paint so a light-theme user never sees a dark flash.
 * It runs ahead of hydration, which is the only place this can be decided
 * without either flashing or shipping the whole app as a client component.
 */
const THEME_SCRIPT = `try{var t=localStorage.getItem("fitos-theme");
if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: light)").matches?"light":"dark"}
document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  // Dark is the default theme; light is a tested peer, reachable from the top
  // bar and remembered. See docs/design-system.md §2.
  return (
    <html lang="en-GB" data-theme="dark" suppressHydrationWarning>
      <head>
        {/* eslint-disable-next-line react/no-danger -- the theme has to be
            applied before first paint, and a <script> body is the only way to
            do that. The string is a module constant with no interpolation, so
            there is no injection surface. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
