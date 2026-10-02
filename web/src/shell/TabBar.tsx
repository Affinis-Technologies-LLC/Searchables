import { Tab, useApp } from "../store";
import { Icon } from "../ui";

export function TabBar() {
  const app = useApp();
  const title = (tab: Tab) =>
    tab.kind === "doc" ? app.overview.documents.find((d) => d.id === tab.docId)?.title ?? "Document"
                       : tab.path.split("/").pop() ?? tab.path;
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
            <Icon name={tab.kind === "doc" ? "file" : "code"} size={14} />
            <span className="tab-title">{title(tab)}</span>
            <button type="button" className="tab-close" title="Close"
                    onClick={(e) => { e.stopPropagation(); app.close(tab.id); }}>
              <Icon name="close" size={12} />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
