"use client";

import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

/**
 * A screen failed to render. The shell around it (sidebar, emergency stop,
 * lockout banners) is outside this boundary and stays usable.
 */
export default function CockpitError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div
      role="alert"
      className="mx-auto flex max-w-lg flex-col items-center gap-5 rounded-xl border border-destructive/30 bg-destructive/5 px-6 py-12 text-center"
    >
      <span className="flex size-12 items-center justify-center rounded-full border border-destructive/30 bg-background text-destructive shadow-xs">
        <TriangleAlert className="size-5" aria-hidden="true" />
      </span>
      <div>
        <h2 className="text-base font-semibold tracking-tight">Cet écran n&apos;a pas pu s&apos;afficher</h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          {error.message || "Une erreur inattendue est survenue pendant l'affichage."}
        </p>
        {error.digest && <p className="mt-2 text-xs text-muted-foreground">Référence : {error.digest}</p>}
      </div>
      <Button type="button" variant="outline" onClick={reset}>
        Réessayer
      </Button>
    </div>
  );
}
