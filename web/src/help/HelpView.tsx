// A help page in the main pane, rendered by the app's own Markdown reader.
import { Fragment, ReactNode } from "react";
import { Activity, HelpTab, useApp } from "../store";
import { Block, parse, Span } from "./markdown";
import { pages, titleOf } from "./pages";

export function HelpView({ tab }: { tab: HelpTab }) {
  const app = useApp();
  const text = pages[tab.page];
  const follow = (href: string) => {
    if (href.startsWith("app:")) {
      app.setActivity(href.slice(4) as Activity);
    } else if (href.endsWith(".md")) {
      app.openHelp(href.slice(0, -3));
    } else if (href.startsWith("#")) {
      document.getElementById(`help-${tab.page}-${href.slice(1)}`)?.scrollIntoView({ block: "start" });
    }
  };
  const inline = (span: Span, i: number): ReactNode => {
    switch (span.kind) {
      case "em": return <em key={i}>{span.text}</em>;
      case "strong": return <strong key={i}>{span.text}</strong>;
      case "code": return <code key={i}>{span.text}</code>;
      case "kbd": return <kbd key={i}>{span.text}</kbd>;
      case "link": return <a key={i} href={span.href} className="link" onClick={(e) => { e.preventDefault(); follow(span.href); }}>{span.text}</a>;
      default: return <Fragment key={i}>{span.text}</Fragment>;
    }
  };
  const block = (b: Block, i: number): ReactNode => {
    switch (b.type) {
      case "heading": {
        const id = `help-${tab.page}-${b.id}`;
        return b.level === 1 ? <h1 key={i} id={id}>{b.text}</h1> : b.level === 2 ? <h2 key={i} id={id}>{b.text}</h2> : <h3 key={i} id={id}>{b.text}</h3>;
      }
      case "paragraph": return <p key={i}>{b.spans.map(inline)}</p>;
      case "list": return b.ordered
        ? <ol key={i}>{b.items.map((item, j) => <li key={j}>{item.map(inline)}</li>)}</ol>
        : <ul key={i}>{b.items.map((item, j) => <li key={j}>{item.map(inline)}</li>)}</ul>;
      case "code": return <pre key={i} className="snippet">{b.text}</pre>;
    }
  };
  if (!text) return <div className="viewer"><div className="help-page"><h1>No such page</h1><p>There's no help page called “{tab.page}”.</p></div></div>;
  return (
    <div className="viewer">
      <div className="toolbar"><span className="grow">Help · {titleOf(tab.page)}</span><span className="muted">Searchables {__APP_VERSION__}</span></div>
      <article className="help-page">{parse(text).map(block)}</article>
    </div>
  );
}
