# Ponder Dashboard Redesign

## Overview

Redesign the agent-memory web dashboard from a raw developer tool into a showcase-ready interface called **Ponder**. The current UI (dark mode, monospace, raw JSON, dense tables) becomes a warm, readable, visually distinctive light-mode dashboard.

Reference mockup: `.superpowers/brainstorm/38079-1774855852/content/reference-approved.html`

## Branding

- **Name**: Ponder
- **Tagline**: "Shared memory for AI agents"
- **Repo**: TBD (`ponder-memory` or `ponder-ai`)
- **Logo**: Thought-bubble "P" mark. The mockup contains a placeholder SVG. Final logo to be designed separately in a design tool and swapped in.
- **Logo placement**: absolute positioned in hero area, right-aligned with page content max-width

## Visual Direction

### Theme: Light Paper
- Background: warm off-white `#f5f3ef`
- Surfaces (cards, chat): white `#fff` with subtle warm borders `#e0ddd6`
- Ink: near-black `#1a1a1a`, soft `#999`, muted `#ccc`
- Single accent color: terracotta `#c45a3c` (used sparingly: active links, high priority, active channel)
- No neon, no cyan, no gradient text, no glassmorphism
- Status pills use semantic colors only: green (`#e6f5ec`/`#1a6b3a`), amber (`#fef4e0`/`#8a6d2b`), muted gray for done

### Typography
- **Body/Headings**: Figtree (weights: 400, 500, 600, 700, 800, 900 via Google Fonts)
- **Code/IDs/Timestamps**: IBM Plex Mono (weights: 400, 500, 600 via Google Fonts)
- Hero headline: 52px, weight 900, letter-spacing -2px
- Section titles: 13px, weight 700, uppercase, letter-spacing 1px, color `#aaa`
- Body text: 13-14px
- Timestamps/meta: 10-11px in IBM Plex Mono

### Layout
- Single-column vertical flow, max-width 1100px, centered
- No sidebar navigation, no multi-column grids
- Sections stack vertically: Hero > Agents > Tabs > Content sections
- Each tab shows full-width content in the vertical flow
- Scrolling is acceptable but minimize it by keeping sections compact

## Page Structure

### Hero (top)
- Background: thought-bubble P logo mark (subtle, right-aligned within max-width)
- Headline: single line, dynamic text using `stats.agents` from `/api/status`. Singular/plural: "1 agent working" / "3 agents working". The mockup's second line ("across 2 projects") is intentionally removed (no project count in data model).
- Agent count number highlighted with terracotta underline effect (pseudo-element)
- No tagline text (removed to reduce noise)

### Agent Strip (below hero)
- Horizontal row of agent indicators
- Each agent: circular ring with initials (2 letters), name, current task, relative time
- Active agents: solid black `#1a1a1a` ring border, green `#2ecc71` status dot (positioned bottom-right of ring)
- Idle agents: gray `#d0ccc4` ring border, ring initials color `#bbb`, agent name color `#bbb`, no status dot. No opacity on wrapper (task text stays at full readability).
- Data source: `current_task` field from agent state (`/api/state`)
- Spacing: 24px gap between agents, margin-top separates from headline, agents sit close above tabs

### Tabs (segmented control style)
- 5 tabs: Overview, Chat, Agents, Knowledge, System
- Hash targets: `#overview`, `#chat`, `#agents`, `#knowledge`, `#system`
- Old hash targets (`#working`, `#episodes`, `#onboarding`) redirect to `#system` for backwards compatibility
- Style: pill-shaped background `#eae7e0`, active tab white with subtle shadow

### Overview Tab
Contains three sections:

#### Tasks
- Card-style rows (white background, rounded border)
- Each task: number, title, subtitle line, status pill
- Subtitle format: `{assigned_to} · [from {created_by} if different from assigned_to] · [{priority} in terracotta bold if set] · {relative time}`. Fields separated by ` · ` (middot). Optional fields omitted when null/empty.
- Done tasks: `opacity: 0.45`
- Hover: border darkens, subtle shadow
- "view all" link in terracotta: switches to a future dedicated Tasks tab (for now, no-op placeholder)

#### Recent Activity (Timeline)
- Grid layout: time | agent name | description
- Time in IBM Plex Mono, muted
- Agent name in IBM Plex Mono, bold
- Description in Figtree, references bold (channel names, task IDs, branch names)
- Separated by subtle bottom borders
- "all events" link: no-op placeholder

#### Chat (Preview)
- White card with rounded border
- Header: active channel name + channel tab list
- Active channel highlighted in terracotta
- Messages: sender (mono, bold), optional arrow + target, timestamp, body text
- "open full chat" link: switches to `#chat` tab

### Chat Tab (full view)
Restyled version of the current chat implementation. Layout:

- **Two-column grid**: channel sidebar (220px) | message feed (1fr)
- **Channel sidebar**: vertical list of channels, each showing name + message count. Active channel: `background: #1a1a1a; color: #fff`. Hover: subtle background.
- **Message feed**: scrollable area (max-height 60vh), messages as cards with subtle borders
- **Message style**: white card, rounded border. Self messages: light terracotta tint background (`#faf5f3`) with border `#e8d8d2`
- **Self detection**: message sender matches the `default_onboarding_agent` Jinja variable (current behavior preserved)
- **Message layout**: sender (IBM Plex Mono, bold), optional arrow + target, timestamp right-aligned. Body below in Figtree.
- **Toolbar** (above compose): grid layout with: Highlight Agent input (drives client-side self-message styling via `watchAgent`), Post Channel input, Target input (optional), Sender input. All restyled with Figtree font, warm borders.
- **Compose area**: below the toolbar. Message textarea + terracotta Send button.
- **Note**: The Highlight Agent input is required for client-side self-message detection. When set, messages from that agent get the `.self` style. Falls back to `default_onboarding_agent` Jinja variable on page load.

### Agents Tab
- Agent profiles as card rows (same pattern as tasks)
- Each card: agent_id, display_name, status, integration_mode, native_feature
- Status shown as colored text (same classes as current, just restyled)

### Knowledge Tab
- Knowledge items as rows
- Category, subject (bold), predicate, object display
- Confidence as visual bar (green fill on gray background) + percentage text
- Source and validated_by shown in muted text

### System Tab
Consolidates three former tabs. Sub-sections separated by section headers:

#### Pinned Notes
- Existing pinned knowledge items (`category="pinned"`) shown at top of System tab
- White card with border, subject as heading, object in pre-formatted box, copy button
- Preserves current functionality from dashboard top area

#### Sessions
- Table listing active sessions: session ID, agent, start time, status (active/ended)
- Restyled with Figtree font, warm borders
- Empty state: "No sessions"

#### Working Memory
- Grouped by agent, key-value pairs in a simple table
- Agent name as section heading (IBM Plex Mono, bold)
- Empty state: "No active working memory."

#### Episodes
- List with title, agent, category, outcome, tags (as pills)
- Empty state: "No episodes yet."

#### Onboarding
- Agent selector dropdown, Load/Copy buttons
- Prompt display in pre-formatted box
- Preserves current functionality

## Timestamps

Hybrid approach implemented in JavaScript:
- Under 1 minute: "just now"
- Under 1 hour: "2m ago", "45m ago"
- Under 24 hours: "3h ago"
- Older: "Mar 28, 14:30"
- Every element with a relative time gets `title` attribute with full absolute timestamp for hover

## Implementation Constraints

- All UI lives in `daemon.py` as embedded HTML/CSS/JS (Jinja2 templates)
- No build step, no external CSS framework, no npm
- Google Fonts loaded via `@import` in `<style>`
- Existing API endpoints remain unchanged
- JavaScript handles: tab switching (hash-based routing), chat polling (3s interval), relative time formatting, chat channel switching

## What Changes

| Component | Current | New |
|-----------|---------|-----|
| Theme | Dark (#1a1a2e) | Light (#f5f3ef) |
| Font | Monospace only | Figtree + IBM Plex Mono |
| Agent display | Table row | Circular ring with initials |
| Tasks | Raw table | Card rows with pills |
| Events | JSON dump table | Timeline (time/agent/description grid) |
| Chat | Functional but raw | Restyled: warm cards, channel sidebar, compose form |
| Tabs | 7 horizontal underline | 5 segmented control pill |
| Tab routing | 7 hash targets | 5 hash targets + 3 redirects |
| Colors | 5+ accent colors | 1 accent (terracotta) + grays |
| Timestamps | Raw absolute | Hybrid relative with hover |
| Name/Title | Agent Memory | Ponder |
| Pinned notes | Above tabs on dashboard | Inside System tab |

## What Does NOT Change

- Flask backend and API routes
- Database schema and `memory.py`
- API response formats
- Chat polling mechanism (3s interval)
- All existing data and functionality (restyled, not removed)

## Empty States

Preserve existing empty-state messages, restyled to match new typography:
- No agents: "No agents registered yet"
- No tasks: "No tasks yet"
- No events: "No events yet"
- No episodes: "No episodes yet"
- No knowledge: "No knowledge yet"
- No working memory: "No active working memory."
- Empty chat: "No messages yet"

## Out of Scope

- Logo final design (separate task, design tool)
- Responsive/mobile layout (follow-up)
- Animations/transitions (follow-up)
- Keyboard navigation (follow-up)
