import { useSyncExternalStore } from "react";
import { drafts } from "../code/drafts";
import { saveFile } from "../code/editing";
import { titleOf } from "../help/pages";
import { Tab, useApp } from "../store";
import { Icon } from "../ui";

export function TabBar() {
  const app = useApp();
  const dirty = useSyncExternalStore((listener) => drafts.subscribe(listener), () => drafts.dirtyIds().join(","));
  const unsaved = new Set(dirty.split(",").filter(Boolean).map(Number));
  const title = (tab: Tab) =>
    tab.kind === "doc" ? app.overview.documents.find((d) => d.id === tab.docId)?.title ?? "Document"
    : tab.kind === "help" ? `Help · ${titleOf(tab.page)}`
    : tab.kind === "links" ? `Links · ${tab.filename}`
    : tab.path.split("/").pop() ?? tab.path;
  const closing = app.closing;
  const settle = async (choice: "save" | "discard" | "cancel") => {
    if (!closing || closing.kind !== "code") return;
    if (choice === "save") {
      const saved = await saveFile(closing.fileId).catch((error) => { app.notify(error.message, "error"); return undefined; });
      if (!saved) { app.setClosing(null); return; }   // A conflict or an error: the tab stays open to show it
      app.filesChanged();
    } else if (choice === "discard") {
      drafts.discard(closing.fileId);
    }
    app.setClosing(null);
    if (choice !== "cancel") app.close(closing.id, true);
  };
  return (
    <div className="tab-bar">
      <button type="button" className="nav" disabled={!app.canGoBack} onClick={app.back} title="Back (Alt+Left)">
        <Icon name="back" />
      </button>
      <button type="button" className="nav" disabled={!app.canGoForward} onClick={app.forward} title="Forward (Alt+Right)">
        <Icon name="forward" />
      </button>
      <div className="tabs" role="tablist">
        {app.tabs.map((tab) => (
          <div key={tab.id} role="tab" aria-selected={tab.id === app.active?.id}
               className={`tab ${tab.id === app.active?.id ? "on" : ""}`}
               title={tab.kind === "code" ? tab.path : title(tab)}
               onClick={() => app.activate(tab.id)}
               onAuxClick={(e) => { if (e.button === 1) app.close(tab.id); }}>
            <Icon name={tab.kind === "doc" ? "file" : tab.kind === "help" ? "help" : tab.kind === "links" ? "links" : "code"} size={14} />
            <span className="tab-title">{title(tab)}{tab.kind === "code" && unsaved.has(tab.fileId) && <span className="unsaved" title="Unsaved changes"> ●</span>}</span>
            <button type="button" className="tab-close" title="Close"
                    onClick={(e) => { e.stopPropagation(); app.close(tab.id); }}>
              <Icon name="close" size={12} />
            </button>
          </div>
        ))}
      </div>
      {closing && (
        <div className="ask" role="dialog" aria-label="Unsaved changes">
          <span>Save the changes to <b>{title(closing)}</b>?</span>
          <button type="button" onClick={() => settle("save")}>Save</button>
          <button type="button" onClick={() => settle("discard")}>Don't save</button>
          <button type="button" onClick={() => settle("cancel")}>Cancel</button>
        </div>
      )}
    </div>
  );
}
