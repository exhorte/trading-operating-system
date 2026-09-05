import { EmptyState } from "@/components/ui/empty-state";

export default function SettingsPage() {
  return (
    <EmptyState
      title="Settings not built yet"
      description="Account, theme, and platform configuration arrive once there is real configuration to manage (auth, backend connection, strategy parameters)."
      hint="Planned: after backend bootstrap"
    />
  );
}
