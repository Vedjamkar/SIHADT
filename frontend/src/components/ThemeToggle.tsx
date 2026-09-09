import { useEffect, useState } from "react";

type ThemePref = "system" | "light" | "dark";

const STORAGE_KEY = "theme-preference";

function applyTheme(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", pref);
}

function readInitial(): ThemePref {
  if (typeof window === "undefined") return "system";
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") return stored;
  } catch {
    // Storage can throw in hardened/private browsing contexts.
  }
  return "system";
}

/**
 * A real theme toggle — now that App.css (which hardcoded light regardless
 * of system preference) is gone, both themes work, and this lets someone
 * override the OS setting explicitly rather than only ever inheriting it.
 * Cycles system -> light -> dark -> system.
 */
export function ThemeToggle() {
  const [pref, setPref] = useState<ThemePref>(readInitial);

  useEffect(() => {
    applyTheme(pref);
    try {
      window.localStorage.setItem(STORAGE_KEY, pref);
    } catch {
      // Private browsing / storage disabled — theme just won't persist.
    }
  }, [pref]);

  function cycle() {
    setPref((current) => (current === "system" ? "light" : current === "light" ? "dark" : "system"));
  }

  const label = pref === "system" ? "System theme" : pref === "light" ? "Light theme" : "Dark theme";
  const icon = pref === "system" ? "◐" : pref === "light" ? "☀" : "☾";

  return (
    <button type="button" className="theme-toggle" onClick={cycle} aria-label={`Theme: ${label}. Click to change.`}>
      <span aria-hidden="true">{icon}</span> {label}
    </button>
  );
}
