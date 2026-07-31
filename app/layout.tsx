import type { Metadata } from "next";
import { Geist } from "next/font/google";
import "./globals.css";
import { ScenarioProvider } from "./ui/scenario-context";
import { OperationsProvider } from "./ui/operations-context";
import { Polish } from "./ui/Polish";

const geist = Geist({ variable: "--font-geist", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "FitOS — Fitting room operations",
  description: "A retail operations prototype for responsive fitting rooms.",
  openGraph: {
    title: "FitOS — Fitting rooms, connected",
    description: "A retail operations prototype for responsive fitting rooms.",
    images: ["/og.png"],
  },
  twitter: {
    card: "summary_large_image",
    title: "FitOS — Fitting rooms, connected",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-GB">
      <body className={geist.variable}>
        <ScenarioProvider><OperationsProvider><Polish />{children}</OperationsProvider></ScenarioProvider>
      </body>
    </html>
  );
}
