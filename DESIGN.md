# LLM Label interface

LLM Label is an operational workspace for importing datasets, configuring annotation schemas, reviewing AI predictions, and tracking review progress. Preserve the existing Traditional Chinese product language and functionality.

## Visual commitments

Gradient backgrounds and frosted glass are explicit product requirements. Keep the existing cool lavender / blue / cyan mesh, the dark blue mesh variant, and the existing app icon. Impeccable guidance is applied as refinement of this identity, not as a replacement aesthetic.

Use glass in layers: the background carries the color, translucent cards group projects, and denser popovers protect text readability. The login form uses the same material as the workspace. Keep the review screen's shared frame rather than nesting glass cards inside it.

## Shared system

- Geist Variable with system CJK fallback; 24px page headings, 17px project titles, 12–14px metadata and controls.
- Semantic color tokens in `frontend/src/index.css`; primary blue identifies actions, green approved, blue corrected, orange uncertain, and muted text pending. Every status also has a text label.
- Preserve light and dark mode. Light cards use 66% white and dark cards use 80% tinted neutral; popovers use near-opaque surfaces.
- 24px project-card spacing on desktop and 20px on mobile; 16px card radii and 20px login-panel radius.
- Shared Button, Input, and DarkToggle components; Lucide icons for changed controls.
- Borders, highlights, and soft shadows establish glass edges. Keep text and interaction targets clear against the gradient.

## Hierarchy and interaction

The project workspace separates page context, search, and project entries. Each project emphasizes its title, review action, labeled status counts, and completed percentage. Export is secondary; delete is an explicitly named icon button and retains the existing confirmation.

Search matches project name or filename locally. Distinguish loading, no projects, no search results, and request failure. Failures expose a retry action.

At narrow widths, stack project actions and wrap status counts. Keep touch controls at least 44px in the home and project workspaces. Login labels have explicit input associations and autocomplete hints. Preserve visible keyboard focus and honor reduced motion.

## Validation

Run `cd frontend && npm ci && npm run build`. Inspect light/dark screenshots at desktop and phone widths. Verify search, import opening, account menu, empty/error states, and login fields with fixture data; backend authentication and mutations require a live backend and separate validation.
