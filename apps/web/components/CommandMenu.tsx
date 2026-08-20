"use client";

/**
 * The command menu (⌘K).
 *
 * DESIGN.md §4, Distinctive Components: "The single most important surface …
 * Fuzzy-filters every action: create issue, assign, change status, navigate to
 * team, switch workspace. Each row shows its keyboard shortcut on the trailing
 * edge in mono. Arrow keys move the purple focus wash; Enter executes; Esc
 * dismisses instantly." And §9: "The command menu (Cmd+K) is the soul of the
 * app — fast, fuzzy, keyboard-first."
 *
 * Geometry is from the spec and lives in globals.css: 560px centred sheet,
 * `--bg-surface` body, 1px `--border-default`, 12px radius, the large soft
 * shadow, a 44px search input with no border, 40px rows.
 *
 * Every command here is a real one. There are no disabled placeholders and no
 * entries for routes that do not exist, because a command menu that lists
 * things it cannot do is slower than no command menu — you learn to stop
 * trusting it. That is also CLAUDE.md's rule against placeholder controls.
 */
import { useEffect, useMemo, useRef, useState } from "react";

export interface Command {
  id: string;
  label: string;
  /** What this belongs under. Section captions are 11px uppercase per §4. */
  section: string;
  /** Rendered mono on the trailing edge. */
  shortcut?: string;
  /** Extra words that should match the query without being displayed. */
  keywords?: string;
  run: () => void;
}

/**
 * Subsequence match, which is what "fuzzy" means for a command menu: every
 * character of the query appears in order. "sv" finds "Se[v]erity" and
 * "gap" does not match "Group by" — a substring match would miss the first and
 * a word match would miss useful abbreviations.
 */
function matches(haystack: string, needle: string): boolean {
  if (!needle) return true;
  let index = 0;
  for (const character of needle) {
    index = haystack.indexOf(character, index);
    if (index === -1) return false;
    index += 1;
  }
  return true;
}

/**
 * Mounted only while open, so `query` and `cursor` start fresh every time it is
 * summoned. An earlier version kept it mounted and reset both in an effect on
 * the `open` prop, which meant one render with last time's query still in the
 * box before the reset landed — and a cascading render to fix it.
 */
export function CommandMenu({ commands, onClose }: { commands: Command[]; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return commands.filter((command) =>
      matches(
        `${command.label} ${command.section} ${command.keywords ?? ""}`.toLowerCase(),
        needle,
      ),
    );
  }, [commands, query]);

  // The cursor is clamped on render rather than stored pre-clamped, so a
  // shrinking result set can never point past the end.
  const index = filtered.length === 0 ? 0 : Math.min(cursor, filtered.length - 1);

  // Focus only. No state is set here, which is what keeps it a synchronisation
  // with the DOM rather than a render the component immediately corrects.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        // §4: "Esc dismisses instantly".
        event.preventDefault();
        onClose();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((current) => Math.min(filtered.length - 1, current + 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((current) => Math.max(0, current - 1));
      } else if (event.key === "Enter") {
        event.preventDefault();
        const command = filtered[index];
        if (command) {
          command.run();
          onClose();
        }
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [filtered, index, onClose]);

  // Keep the focused row in view when the arrow keys walk past the fold.
  //
  // These two lines used to read `if (!open) return` — a leftover from when
  // `open` was a prop. Removing the prop left the identifier resolving to
  // `window.open`, which is a function and therefore always truthy, so the
  // guard silently did nothing and TypeScript had no complaint to make. Worth
  // remembering that a name which still resolves is the worst kind of leftover.
  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>('[aria-selected="true"]')
      ?.scrollIntoView({ block: "nearest" });
  }, [index]);

  const sections = filtered.reduce<{ section: string; commands: Command[] }[]>(
    (groups, command) => {
      const last = groups[groups.length - 1];
      if (last && last.section === command.section) last.commands.push(command);
      else groups.push({ section: command.section, commands: [command] });
      return groups;
    },
    [],
  );

  let flat = -1;

  return (
    <>
      {/* §6: scrim behind floating surfaces. Clicking it dismisses, which is
          what every other dismissal affordance in the app also does. */}
      <div className="scrim" onClick={onClose} aria-hidden="true" />
      <div className="command" role="dialog" aria-modal="true" aria-label="Command menu">
        <div className="command-input-row">
          <span className="command-input-glyph" aria-hidden="true">
            ⌕
          </span>
          <input
            ref={inputRef}
            className="command-input"
            type="text"
            value={query}
            /* The spec's own placeholder copy. */
            placeholder="Type a command or search…"
            aria-label="Type a command or search"
            aria-controls="command-list"
            /* The listbox is separate from the input, so the input announces the
               active option rather than owning focus for it. */
            aria-activedescendant={filtered[index] ? `command-${filtered[index].id}` : undefined}
            onChange={(event) => {
              setQuery(event.target.value);
              setCursor(0);
            }}
          />
        </div>

        <div className="command-list" id="command-list" role="listbox" ref={listRef}>
          {filtered.length === 0 ? (
            <p className="command-empty">
              Nothing matches “{query}”. Every command here is one the build can actually run.
            </p>
          ) : (
            sections.map((group) => (
              <div key={group.section}>
                <p className="command-section">{group.section}</p>
                {group.commands.map((command) => {
                  flat += 1;
                  const focused = flat === index;
                  return (
                    <div
                      key={command.id}
                      id={`command-${command.id}`}
                      className="command-row"
                      role="option"
                      aria-selected={focused}
                      onMouseEnter={() => setCursor(filtered.indexOf(command))}
                      onClick={() => {
                        command.run();
                        onClose();
                      }}
                    >
                      <span className="command-label">{command.label}</span>
                      {command.shortcut ? (
                        <span className="command-shortcut mono">{command.shortcut}</span>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
}
