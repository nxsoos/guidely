# Guidely design system

User direction: dark black/charcoal and gray with green accents.

Use the semantic variables in `frontend/src/style.css` for every page. Background
`#101213`, sidebar `#151819`, cards `#1a1e20`, elevated surfaces `#22282a`,
primary text `#eef2f0`, secondary text `#aebbb6`, accent `#65dfa6`, accent text
`#102219`. Red and amber are reserved for errors and pending/warning states.

Keep the existing DM Sans / Manrope typography, content-first layout, visible
keyboard focus, readable source passages, responsive forms and reduced-motion
support. Use green for primary actions and active navigation, with neutral gray
for supporting surfaces. Never communicate indexing status by color alone.

UI/UX Pro Max was installed globally for Codex in
`~/.agents/skills/ui-ux-pro-max`. Its verified `dark-mode-oled` style guidance and
contrast recommendations informed this theme. The automatic design-system search
suggested unrelated marketing patterns, so those were not adopted. React styling
searches returned no match; CSS variables use standard implementation judgment.

Before delivery: check desktop and 375–390px mobile layouts, normal-text contrast
of at least 4.5:1, keyboard focus, native dark form controls, and browser workflows.

## Typography and layout

Use DM Sans for body and controls; Manrope for headings. Body text is 15px,
answers 16px with 1.9 line height, supporting text 12–14px, and uppercase section
labels 9–10px. Main headings scale from 26px to 32px; use 38px only for the
empty-state headline on larger screens. Avoid tiny text for actionable controls.

Use a consistent 4/8px spacing rhythm, a 264px desktop sidebar, 44px desktop
page gutters, 20px mobile gutters, and an 820–900px reading column. Cards use
14px corners with 20–28px internal spacing. SVG outline icons share a consistent
stroke and carry no redundant accessible labels beside visible text.

The question composer follows the conversation in normal document flow so it
cannot cover answers or keyboard-focused source controls. On shorter desktop
screens the empty state uses compact spacing. Mobile navigation uses four equal
columns, forms stack vertically, and document metadata/actions wrap below titles.
