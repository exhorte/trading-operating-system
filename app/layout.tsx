import type { Metadata } from "next";
import "@fontsource-variable/inter";
import { RealtimeProvider } from "@/lib/realtime/provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

export const metadata: Metadata = {
  title: "Trading OS — Cockpit",
  description:
    "Operational cockpit of the Trading Operating System Algorithmique (mock realtime data).",
};

/**
 * Sets the theme before the first paint (node_modules/next/dist/docs/01-app/
 * 02-guides/preventing-flash-before-hydration.md): the saved choice if there
 * is one, else the system preference. The toggle (components/shell/
 * theme-toggle.tsx) flips the same `dark` class and the same `theme` key.
 */
const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("theme");if(t==="dark"||(t===null&&matchMedia("(prefers-color-scheme: dark)").matches))document.documentElement.classList.add("dark")}catch(e){}})()`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // suppressHydrationWarning: the inline script above changes the class of
    // <html> before React hydrates, and browser extensions inject attributes
    // there too. Scoped to this element only — it does not hide mismatches
    // inside the app tree.
    <html lang="fr" className="h-full antialiased" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      {/* suppressHydrationWarning: browser extensions (ColorZilla, Grammarly, …)
          inject attributes like cz-shortcut-listen onto <body> before React
          hydrates. Scoped to this element only; app markup is unaffected. */}
      <body className="min-h-full" suppressHydrationWarning>
        <RealtimeProvider>
          <TooltipProvider delayDuration={200}>{children}</TooltipProvider>
        </RealtimeProvider>
      </body>
    </html>
  );
}
