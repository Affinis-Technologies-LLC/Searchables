import { useEffect } from "react";
import { Activity, useApp } from "../store";
import { Icon } from "../ui";

const ACTIVITIES: { id: Activity; icon: string; label: string; hint: string }[] = [
  { id: "search", icon: "search", label: "Search", hint: "Search the documents by words, meaning or identifier" },
  { id: "contents", icon: "contents", label: "Contents", hint: "The open document's clauses" },
  { id: "catalogue", icon: "catalogue", label: "Catalogue", hint: "Identifiers as entries: messages, their words and fields, data elements, and what uses them" },
  { id: "glossary", icon: "glossary", label: "Glossary", hint: "Defined terms and acronyms" },
  { id: "compare", icon: "compare", label: "Compare", hint: "Differences between two editions" },
  { id: "collections", icon: "collections", label: "Pins", hint: "Collections of pinned passages, tables and code" },
  { id: "code", icon: "code", label: "Code", hint: "Browse source code: symbols, usages, calls, dependencies, APIs" },
  { id: "library", icon: "library", label: "Library", hint: "Add and manage documents" },
  { id: "links", icon: "links", label: "Links", hint: "Check a PDF's internal links and bookmarks and download it fixed" },
  { id: "help", icon: "help", label: "Help", hint: "What each view does (F1)" },
];

export function ActivityBar() {
  const { activity, setActivity, openHelp } = useApp();
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "F1") { event.preventDefault(); openHelp(activity === "help" ? "help" : activity); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activity, openHelp]);
  return (
    <nav className="activity-bar" aria-label="Views">
      {ACTIVITIES.map((item) => (
        <button key={item.id} type="button" className={activity === item.id ? "on" : ""} title={item.hint}
                aria-current={activity === item.id} onClick={() => (item.id === "help" ? openHelp("help") : setActivity(item.id))}>
          <Icon name={item.icon} size={22} />
          <span>{item.label}</span>
        </button>
      ))}
    </nav>
  );
}
