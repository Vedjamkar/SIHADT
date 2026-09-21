import { ThemeToggle } from "./ThemeToggle";

export type View = "home" | "verify" | "organizer" | "face" | "dashboard";

interface NavBarProps {
  view: View;
  onNavigate: (view: View) => void;
  locked?: boolean;
}

const LINKS: { view: View; label: string }[] = [
  { view: "home", label: "Home" },
  { view: "verify", label: "Verify" },
  { view: "organizer", label: "Documents" },
  { view: "face", label: "Face check" },
  { view: "dashboard", label: "Dashboard" },
];

export function NavBar({ view, onNavigate, locked = false }: NavBarProps) {
  return (
    <header className="app-header">
      <button type="button" className="app-header__brand" onClick={() => onNavigate("home")} disabled={locked}>
        <span className="app-header__brand-mark" aria-hidden="true">
          ⌗
        </span>
        <span>Document &amp; Identity Check</span>
      </button>
      <nav className="app-header__nav" aria-label="Primary">
        {LINKS.map((link) => (
          <button
            key={link.view}
            type="button"
            className={"app-header__nav-link" + (view === link.view ? " is-active" : "")}
            onClick={() => onNavigate(link.view)}
            disabled={locked && view !== link.view}
            aria-current={view === link.view ? "page" : undefined}
          >
            {link.label}
          </button>
        ))}
      </nav>
      <ThemeToggle />
    </header>
  );
}
