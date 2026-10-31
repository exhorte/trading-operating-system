"use client";

import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * Light / dark switch. Both icons are rendered and the `dark` class picks
 * which one shows: no React state, hence no hydration mismatch with the theme
 * the inline script of app/layout.tsx applied before the first paint.
 */
export function ThemeToggle() {
  const toggle = () => {
    const isDark = document.documentElement.classList.toggle("dark");
    try {
      localStorage.setItem("theme", isDark ? "dark" : "light");
    } catch {
      // Storage unavailable (private window): the theme still holds for the session.
    }
  };

  return (
    <Button variant="secondary" size="icon" onClick={toggle} aria-label="Basculer le thème clair / sombre">
      <Moon className="dark:hidden" />
      <Sun className="hidden dark:block" />
    </Button>
  );
}
