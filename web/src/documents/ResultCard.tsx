import { ReactNode } from "react";
import { useApp } from "../store";
import { Block, Term } from "../types";
import { Badge, Icon } from "../ui";

const PROVISION = { requirement: "shall", recommendation: "should", permission: "may", note: "note" };

/** A passage in a list: where it is, what it says, and the pin button. */
export function ResultCard({ block, docTitle, selected, onOpen, children, detail, extraBadges, terms, pinQuery }: {
  block: Block; docTitle: string; selected?: boolean; onOpen: () => void; children: ReactNode; detail?: ReactNode;
  extraBadges?: ReactNode; terms?: Term[]; pinQuery?: string;
}) {
  const app = useApp();
  const pinned = !!block.pin_key && app.pinned.has(block.pin_key);
  return (
    <article className={`card ${selected ? "selected" : ""}`} onClick={onOpen}>
      <header>
        <Badge kind="page">p. {block.display_page}</Badge>
        {(block.kind === "table" || block.kind === "figure") && <Badge kind="object">{block.label || `Untitled ${block.kind}`}</Badge>}
        {block.clause_num && <Badge>{block.clause_num}</Badge>}
        {block.provision && <Badge kind={block.provision}>{PROVISION[block.provision]}</Badge>}
        {extraBadges}
        <span className="card-title">{docTitle}</span>
      </header>
      <div className="card-path">{block.clause_path || "No clause detected"}</div>
      <div className="card-body">{children}</div>
      <footer onClick={(e) => e.stopPropagation()}>
        <span className="muted grow">{detail}</span>
        {terms && terms.length > 0 && (
          <details className="definitions">
            <summary>Definitions ({terms.length})</summary>
            {terms.map((term) => (
              <p key={term.clause_num + term.term}><strong>{term.term}</strong> · {term.clause_num}<br />{term.definition}</p>
            ))}
          </details>
        )}
        <button type="button" className={pinned ? "on" : ""} title={pinned ? "Remove from the collection" : "Save to the active collection"}
                onClick={() => app.togglePin(block, pinQuery)}>
          <Icon name="pin" size={13} /> {pinned ? "Pinned" : "Pin"}
        </button>
      </footer>
    </article>
  );
}
