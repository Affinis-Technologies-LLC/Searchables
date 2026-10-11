// The Help activity (ADR-016): the pages on the left with a search box; a page opens in the main pane.
import { useMemo, useState } from "react";
import { useApp } from "../store";
import { Empty } from "../ui";
import { searchPages } from "./markdown";
import { ORDER, pages, titleOf } from "./pages";

export function HelpPanel() {
  const app = useApp();
  const [query, setQuery] = useState("");
  const hits = useMemo(() => searchPages(pages, query), [query]);
  const current = app.active?.kind === "help" ? app.active.page : null;
  return (
    <div className="panel">
      <div className="panel-head">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search the help" placeholder="A word from the help" />
      </div>
      <div className="panel-body">
        {query.trim() ? (
          hits.length ? hits.map((hit) => (
            <button key={hit.page} type="button" className={`tree-row ${hit.page === current ? "on" : ""}`} onClick={() => app.openHelp(hit.page)}>
              <span className="grow"><b>{hit.title}</b><br /><span className="muted">{hit.snippet}</span></span>
            </button>
          )) : <Empty>No page has every word of that.</Empty>
        ) : ORDER.filter((p) => pages[p]).map((page) => (
          <button key={page} type="button" className={`tree-row ${page === current ? "on" : ""}`} onClick={() => app.openHelp(page)}>
            <span className="grow">{titleOf(page)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
