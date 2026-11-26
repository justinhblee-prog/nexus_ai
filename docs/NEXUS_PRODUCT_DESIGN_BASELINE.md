# NEXUS STUDIO PRO — Product Design Baseline

Status: carried-forward product decisions; implementation target for the active Draft PR.
Updated: 2026-11-27
Repository: `justinhblee-prog/nexus_ai`
Working branch: `fix/shorts-runtime-security-bootstrap`

This document preserves product decisions across repository migration. A repository change does not reset or reopen these decisions.

## 1. Theme system

Exactly one theme is the default:

- **Monochrome** — black-and-white. This is the initial/default theme.

The four additional comparison themes selected in the November 25 discussion are:

1. **Executive Blue**
2. **Emerald Luxe**
3. **Editorial Coral**
4. **Indigo Future**

All five themes must use the same component system, layout, data, and interactions. Theme switching changes visual tokens only; it must not rearrange content, change functionality, or create separate dashboard implementations. Do not add Neon Intelligence as a sixth theme: it appeared as an earlier exploration, not in the final four-theme comparison set.

## 2. Information architecture

Use one persistent application shell with a fixed left sidebar and these seven primary workspaces:

1. **Dashboard**
2. **AI Content Studio** — video creation and editing live inside this workspace; do not create a separate top-level Video Editor menu.
3. **Discovery**
4. **Review**
5. **Publishing**
6. **Analytics**
7. **Operations**

The same design system and navigation shell apply across all seven workspaces. Preserve the existing application workflows and connect the screens to the real API; do not replace working functionality with static mock data.

## 3. Dashboard

Implement the previously proposed NEXUS STUDIO PRO dashboard design, not a newly invented layout. Preserve the agreed visual hierarchy and dashboard composition from the existing design reference assets in this repository:

- `NEXUS STUDIO PRO 대시보드.png`
- `AI 숏폼 콘텐츠 운영 대시보드.png`

The dashboard must be a real application screen, not a screenshot. Its data and actions must be connected to the existing API and queue. Do not redesign the dashboard independently while adding the navigation shell or theme system.

## 4. Implementation constraints

- Desktop and mobile responsive layouts are required.
- Keep the content placement and functional structure identical across themes.
- Keep existing API, radar, durable queue, review, QA, and private-upload safeguards intact.
- Preserve human approval before upload; YouTube upload remains Private.
- No public publishing automation.
- Keep the pull request Draft and open. Do not merge, deploy, publish, force-push, or rewrite history.
- Do not ask the user to re-decide these recorded items. Only report a genuine conflict or missing source artifact that prevents faithful implementation.

## 5. Verification

A design task is complete only after:
- all seven workspaces are navigable and responsive;
- Monochrome is the initial theme;
- the four additional themes can be previewed without changing layout or behavior;
- theme preference persists across reloads;
- the Dashboard matches the existing design reference composition;
- all existing production, review, and operations actions still work against the API;
- browser interaction and mobile layout are checked, not just static markup.
