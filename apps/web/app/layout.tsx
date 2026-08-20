import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Inter, JetBrains_Mono } from "next/font/google";
import "@fitos/ui/tokens.css";
import "./globals.css";

/**
 * Inter is the source spec's family, at 400/500/600 and nothing else: "no
 * light, no bold/black". `cv11` and `ss03` and tabular numerals are the feature
 * settings it names.
 *
 * The mono face carries identity, not content — gap references and keyboard
 * shortcuts. The spec asks for Berkeley Mono with an SF Mono fallback; Berkeley
 * is a paid licence, so JetBrains Mono stands in and SF Mono still wins on
 * Apple hardware through the fallback stack.
 */
const inter = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
  display: "swap",
});

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
    <html
      lang="en-GB"
      data-theme="dark"
      className={`${inter.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
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
