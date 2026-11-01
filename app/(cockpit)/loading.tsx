import { Skeleton } from "@/components/ui/skeleton";

/**
 * Same silhouette as a cockpit screen (ADR 0017): title, content 3/5, dark
 * panel 2/5, then the full-width list — so the page does not jump when the
 * real screen replaces it.
 */
export default function CockpitLoading() {
  return (
    <div className="flex flex-col gap-10" role="status" aria-busy="true">
      <span className="sr-only">Chargement de l&apos;écran…</span>
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-5">
        <div className="flex min-w-0 flex-col gap-4 lg:col-span-3">
          <Skeleton className="h-9 w-64 max-w-full" />
          <Skeleton className="h-4 w-80 max-w-full" />
          <Skeleton className="h-56 rounded-xl" />
        </div>
        <div className="flex min-w-0 flex-col gap-4 lg:col-span-2">
          <Skeleton className="h-[4.5rem] rounded-xl" />
          <Skeleton className="h-96 rounded-xl" />
        </div>
      </div>
      <Skeleton className="h-48 rounded-xl" />
    </div>
  );
}
