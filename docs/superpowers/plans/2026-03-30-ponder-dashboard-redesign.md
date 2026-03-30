# Ponder Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the agent-memory dashboard from dark/monospace to a warm light-mode UI called "Ponder", without changing backend or API.

**Architecture:** The entire UI lives in `daemon.py` as embedded HTML/CSS/JS strings (`DASHBOARD_HTML` and `LIVE_HTML`). The plan replaces `DASHBOARD_HTML` in 7 incremental tasks: CSS first, then hero, then tabs, then each content section. Each task produces a working page.

**Tech Stack:** Flask/Jinja2 templates, vanilla CSS/JS, Google Fonts (Figtree + IBM Plex Mono)

**Spec:** `docs/superpowers/specs/2026-03-30-ponder-dashboard-redesign.md`
**Mockup:** `.superpowers/brainstorm/38079-1774855852/content/reference-approved.html`

**Note on innerHTML:** The existing codebase uses innerHTML for dynamic rendering (chat messages, channel tabs). All user-generated content is escaped via the existing `escapeHtml()` function before insertion. This pattern is preserved in the restyled code. The escapeHtml function prevents XSS by converting `<`, `>`, `&`, `"`, `'` to HTML entities.

---

### Task 1: Replace CSS and page shell

**Files:**
- Modify: `daemon.py` (DASHBOARD_HTML, lines 78-192: CSS block + HTML shell)

Replace the entire `<style>` block and the HTML above the first `<div id="tab-` with the new Ponder theme. The full CSS is documented in the spec and mockup. Key changes:

- Google Fonts import: Figtree (400,500,600,700,800,900) + IBM Plex Mono (400,500,600)
- Background: `#f5f3ef`, text: `#1a1a1a`, accent: `#c45a3c`
- All existing CSS classes replaced with new ones from the spec
- Hero with thought-bubble SVG placeholder logo
- Agent strip with ring initials
- Segmented control tabs (5 tabs)
- Card-style tasks, timeline grid, chat preview, message styles
- Form elements restyled warm
- Responsive breakpoint at 760px

The page shell replaces: `<title>` to "Ponder", hero with dynamic headline using `{{ stats.agents }}`, agent strip iterating `{{ states }}`, tabs with 5 entries (overview, chat, agents, knowledge, system).

- [ ] Step 1: Replace the `<style>` block (lines 83-161) with the full new CSS
- [ ] Step 2: Replace the HTML shell (lines 162-192) with hero, agent strip, tabs
- [ ] Step 3: Verify page loads: `curl -s http://192.168.178.20:9077/ | head -5`
- [ ] Step 4: Commit: `git commit -m "feat: replace dashboard CSS and shell with Ponder Light Paper theme"`

---

### Task 2: Overview tab - Tasks section

**Files:**
- Modify: `daemon.py` (DASHBOARD_HTML, overview tab content - replace agent state table + tasks table)

Remove the old agent state table and tasks table. Replace with card-style task rows. Each task card shows: `#id`, title, subtitle (`assigned_to` + optional `from created_by` + optional priority in terracotta bold + relative time), status pill. Done tasks get `opacity: 0.45`.

Subtitle format: `{{ t.assigned_to }}{% if t.created_by != t.assigned_to %} · from {{ t.created_by }}{% endif %}{% if t.priority %} · <strong>{{ t.priority }}</strong>{% endif %} · <span class="relative-time" data-ts="{{ t.created_at }}">{{ t.created_at }}</span>`

- [ ] Step 1: Replace overview tab tasks HTML
- [ ] Step 2: Verify tasks render as white cards with pills
- [ ] Step 3: Commit: `git commit -m "feat: overview tasks as card rows with status pills"`

---

### Task 3: Overview tab - Activity Timeline and Chat Preview

**Files:**
- Modify: `daemon.py` (DASHBOARD_HTML, overview tab below tasks)

Replace "Recent Events" table with timeline grid (3 columns: `tl-time` | `tl-who` | `tl-text`). Each event shows relative time, source agent, event type (bold) + optional target + truncated data.

Add Chat Preview below: white card with channel header + last 3 messages. "open full chat" link calls `showTab('chat', findTabButton('chat'))`.

- [ ] Step 1: Replace events table with timeline grid
- [ ] Step 2: Add chat preview section below timeline
- [ ] Step 3: Verify both sections render
- [ ] Step 4: Commit: `git commit -m "feat: overview activity timeline and chat preview"`

---

### Task 4: Chat tab (full view) restyled

**Files:**
- Modify: `daemon.py` (DASHBOARD_HTML, chat tab HTML + JS render functions)

Keep all existing chat functionality (polling, compose, channels). Restyle HTML to use new CSS classes. Update two JS functions:

**`renderChatMessages()`**: Generate `<div class="msg">` with `.msg-head` (`.msg-from`, `.msg-arrow`, `.msg-to`, `.msg-time`) and `.msg-body`. Self detection via `watchAgent` input. Use `formatRelativeTime()` for timestamps. All content escaped via existing `escapeHtml()`.

**`renderChatChannelTabs()`**: Generate `<div class="chat-channel-tab">` with `.chat-channel-count`. Active channel gets `.active` class with dark background.

- [ ] Step 1: Replace chat tab HTML with new markup (keep all form fields: highlight agent, channel, target, sender, textarea)
- [ ] Step 2: Update `renderChatMessages` to use new CSS classes
- [ ] Step 3: Update `renderChatChannelTabs` to use new CSS classes
- [ ] Step 4: Verify chat works: channels list, messages render, send works, polling works
- [ ] Step 5: Commit: `git commit -m "feat: restyle chat tab with Ponder theme"`

---

### Task 5: Agents, Knowledge, System tabs

**Files:**
- Modify: `daemon.py` (DASHBOARD_HTML, remaining tab content)

**Agents tab**: Card rows instead of table. Each card: agent_id + display_name, status color, integration info, onboarding note.

**Knowledge tab**: Table restyled with new `th`/`td` styles. Confidence bar preserved. Column: #, Category, Subject (bold), Predicate, Object, Confidence, Source.

**System tab** (new, consolidates 3 former tabs):
1. Pinned Notes (moved from above tabs): white card, heading, pre box, copy button
2. Sessions: table with session ID, agent, start time, status
3. Working Memory: grouped by agent in panels, key-value tables
4. Episodes: table with tags as pill spans
5. Onboarding: agent selector, load/copy buttons, prompt pre box

Remove old `tab-working`, `tab-episodes`, `tab-onboarding` div IDs. New single `tab-system` div.

- [ ] Step 1: Replace agents tab HTML with card layout
- [ ] Step 2: Restyle knowledge tab table
- [ ] Step 3: Create system tab combining pinned notes, sessions, working memory, episodes, onboarding
- [ ] Step 4: Remove old `tab-working`, `tab-episodes`, `tab-onboarding` divs
- [ ] Step 5: Verify all tabs render
- [ ] Step 6: Commit: `git commit -m "feat: agents, knowledge, system tabs with Ponder styling"`

---

### Task 6: JavaScript - tab routing, relative timestamps, hash redirects

**Files:**
- Modify: `daemon.py` (DASHBOARD_HTML, `<script>` section)

**TAB_NAMES**: Change from `['overview', 'chat', 'agents', 'working', 'episodes', 'knowledge', 'onboarding']` to `['overview', 'chat', 'agents', 'knowledge', 'system']`.

**TAB_REDIRECTS**: Add `const TAB_REDIRECTS = { 'working': 'system', 'episodes': 'system', 'onboarding': 'system' };`

**getHashState()**: Add redirect lookup: `if (TAB_REDIRECTS[tab]) tab = TAB_REDIRECTS[tab];`

**formatRelativeTime(ts)**: New function. Returns "just now" (<60s), "Nm ago" (<1h), "Nh ago" (<24h), "Mon DD, HH:MM" (older). Parses timestamps with space-to-T conversion and UTC assumption.

**updateRelativeTimes()**: New function. Queries all `.relative-time[data-ts]` elements, sets `textContent` to formatted time and `title` to raw timestamp. Called on load and every 30 seconds via `setInterval`.

- [ ] Step 1: Update `TAB_NAMES` array and add `TAB_REDIRECTS`
- [ ] Step 2: Update `getHashState()` with redirect logic
- [ ] Step 3: Add `formatRelativeTime()` function
- [ ] Step 4: Add `updateRelativeTimes()` and wire up on load + interval
- [ ] Step 5: Verify: navigate to `#working` redirects to system tab, timestamps show relative
- [ ] Step 6: Commit: `git commit -m "feat: tab routing with redirects and relative timestamps"`

---

### Task 7: Update LIVE_HTML and daemon metadata

**Files:**
- Modify: `daemon.py` (LIVE_HTML string, module docstring)

- [ ] Step 1: Change LIVE_HTML `<title>` from "Agent Memory - Live" to "Ponder - Live"
- [ ] Step 2: Change LIVE_HTML `<h1>` text from "Agent Memory Live" to "Ponder Live"
- [ ] Step 3: Update module docstring: "Agent Memory Daemon" to "Ponder Daemon"
- [ ] Step 4: Verify live page: `http://192.168.178.20:9077/live` shows "Ponder - Live"
- [ ] Step 5: Commit: `git commit -m "feat: rename to Ponder in live dashboard and docstring"`

---

## Self-Review

**Spec coverage:**
- Branding/name: Task 1 (shell) + Task 7 (live) ✓
- Light Paper CSS: Task 1 ✓
- Hero + Agent strip: Task 1 ✓
- Tabs (5, segmented): Task 1 + Task 6 (routing) ✓
- Overview Tasks: Task 2 ✓
- Overview Timeline: Task 3 ✓
- Overview Chat Preview: Task 3 ✓
- Chat Tab Full: Task 4 ✓
- Agents Tab: Task 5 ✓
- Knowledge Tab: Task 5 ✓
- System Tab (pinned, sessions, WM, episodes, onboarding): Task 5 ✓
- Timestamps hybrid: Task 6 ✓
- Hash redirects: Task 6 ✓
- Empty states: preserved in all tab templates ✓

**No placeholders found.**
**Type/name consistency verified across tasks.**
