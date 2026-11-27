# NEXUS STUDIO PRO — Product Design Baseline

Status: carried-forward product decisions; implementation target for the active Draft PR.
Updated: 2026-11-27
Repository: `justinhblee-prog/nexus_ai`
Working branch: `fix/shorts-runtime-security-bootstrap`

This document preserves product decisions across repository migration. A repository change does not reset or reopen these decisions.

## 1. Dashboard presentation modes and appearance system

The product has four selectable dashboard presentation modes, based on the four accepted NEXUS design concepts:

1. **Intelligence** — KPI and command-center oriented.
2. **Creator** — production workflow and content workspace oriented.
3. **Global Analytics** — regional and channel performance oriented.
4. **Executive Intelligence** — insights and operational decision oriented.

These are four ways to present the same NEXUS product, not separate products or feature sets. All four modes must expose the same underlying content, data, actions, and seven workspaces. The difference is layout, information hierarchy, and visual presentation only. Do not omit or fabricate data when switching modes.

Appearance is a separate setting from presentation mode. Users can independently customize:
- base palette / background and surface colors;
- accent color;
- card treatment;
- chart palette;
- typography scale;
- information density.

Changing appearance must not change the selected presentation mode, content, data, or behavior. Persist both selections independently. The initial appearance should be a restrained monochrome palette; do not replace the four accepted presentation modes with color-only theme presets.

## 2. Information architecture

Use one persistent application shell with a fixed left sidebar and these seven primary workspaces:

1. **Dashboard**
2. **AI Content Studio** — video creation and editing live inside this workspace; do not create a separate top-level Video Editor menu.
3. **Discovery**
4. **Review**
5. **Publishing**
6. **Analytics**
7. **Operations**

The same data and capabilities apply across all seven workspaces. Preserve the existing application workflows and connect the screens to the real API; do not replace working functionality with static mock data.

## 3. Dashboard

Implement the four accepted dashboard presentation modes described above. All four must use the same live data and common functional content, with different layout and visual hierarchy. Preserve the original accepted concept content; do not substitute generic dashboard mockups. Verify whether these reference assets are actually present before relying on them:

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
- Four dashboard presentation modes are selectable and share the same content and data;
- appearance customization is independent from presentation mode;
- the four additional themes can be previewed without changing layout or behavior;
- theme preference persists across reloads;
- the Dashboard matches the existing design reference composition;
- all existing production, review, and operations actions still work against the API;
- browser interaction and mobile layout are checked, not just static markup.
