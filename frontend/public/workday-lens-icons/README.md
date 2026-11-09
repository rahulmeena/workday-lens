# Workday Lens Icons

These are clean SVG assets recreated for the Workday Lens dashboard theme.

## Files

- `workday-lens-logo.svg`
- `focus-time-badge.svg`
- `meetings-time-badge.svg`
- `comms-time-badge.svg`
- `deep-work.svg`
- `meetings.svg`
- `comms.svg`
- `breaks.svg`
- `starburst.svg`
- `insight-bulb.svg`
- `folder-badge.svg`
- `music-badge.svg`
- `sunrise-badge.svg`
- `sidebar-today.svg`
- `sidebar-timeline.svg`
- `sidebar-projects.svg`
- `sidebar-insights.svg`
- `sidebar-learnings.svg`
- `WorkdayLensIcons.tsx`

## Next.js usage

Option 1: copy the SVGs into `public/icons/` and use:

```tsx
<img src="/icons/focus-time-badge.svg" alt="Focus time" className="h-14 w-14" />
```

Option 2: copy `WorkdayLensIcons.tsx` into `components/icons/` and use:

```tsx
import { WorkdayLensLogo, FocusTimeIcon, DeepWorkIcon } from "@/components/icons/WorkdayLensIcons";

export default function Example() {
  return (
    <div className="flex items-center gap-3">
      <WorkdayLensLogo size={36} />
      <FocusTimeIcon size={56} />
      <DeepWorkIcon size={22} />
    </div>
  );
}
```

## Transparency

All SVG files have transparent canvases. The badge icons intentionally include their own soft cream rounded/circular background because that is part of the design.
