import { useCallback, useEffect, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { api, onSignedOut } from "./api";
import { CodeInspector } from "./code/CodeInspector";
import { CodePanel } from "./code/CodePanel";
import { CodeView } from "./code/CodeView";
import { CollectionsPanel } from "./documents/CollectionsPanel";
import { ComparePanel } from "./documents/ComparePanel";
import { ContentsPanel } from "./documents/ContentsPanel";
import { DocInspector } from "./documents/DocInspector";
import { GlossaryPanel } from "./documents/GlossaryPanel";
import { LibraryPanel } from "./documents/LibraryPanel";
import { PdfView } from "./documents/PdfView";
import { SearchPanel } from "./documents/SearchPanel";
import { ActivityBar } from "./shell/ActivityBar";
import { Login, SessionInfo } from "./shell/Login";
import { StatusBar } from "./shell/StatusBar";
import { TabBar } from "./shell/TabBar";
import { AppProvider, useApp } from "./store";
import { Overview } from "./types";
import { Empty } from "./ui";

export function App() {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [failed, setFailed] = useState("");

  const check = useCallback(async () => {
    try {
      const info = await api.get<SessionInfo>("/session");
      setSession(info);
      setOverview(info.authenticated ? await api.get<Overview>("/state") : null);
      setFailed("");
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => { check(); }, [check]);
  useEffect(() => onSignedOut(() => { setOverview(null); check(); }), [check]);

  if (failed) return <div className="center"><div className="notice error">The app's server can't be reached: {failed}</div></div>;
  if (!session) return <div className="center"><div className="loading">Loading…</div></div>;
  if (!session.authenticated || !overview) return <Login session={session} onSignedIn={check} />;
  return (
    <AppProvider initial={overview}>
      <Workbench onSignedOut={check} />
    </AppProvider>
  );
}

function Workbench({ onSignedOut }: { onSignedOut: () => void }) {
  const app = useApp();
  const { activity, active, tabs } = app;

  // Alt+Left / Alt+Right step through where you've been, as in a browser or an IDE
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!event.altKey || event.shiftKey || event.ctrlKey || event.metaKey) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); app.back(); }
      if (event.key === "ArrowRight") { event.preventDefault(); app.forward(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [app]);

  // Every side panel stays mounted (hidden), so a search or a codebase's view is still there when you come back
  const panels = {
    search: <SearchPanel />, contents: <ContentsPanel />, glossary: <GlossaryPanel />, compare: <ComparePanel />,
    collections: <CollectionsPanel />, library: <LibraryPanel />, code: <CodePanel />,
  };
  const side = Object.entries(panels).map(([name, panel]) => (
    <div key={name} className="side-pane" hidden={name !== activity}>{panel}</div>
  ));

  return (
    <div className="workbench">
      <div className="workbench-body">
        <ActivityBar />
        <PanelGroup direction="horizontal" autoSaveId="searchables-layout">
          <Panel defaultSize={26} minSize={14} className="side">{side}</Panel>
          <PanelResizeHandle className="handle" />
          <Panel defaultSize={48} minSize={20} className="main">
            <TabBar />
            <div className="editor-area">
              {tabs.length === 0 && (
                <Empty>
                  Search the library or the code on the left; what you open appears here, with what's related to it
                  on the right. <kbd>Alt</kbd>+<kbd>←</kbd> and <kbd>Alt</kbd>+<kbd>→</kbd> step back and forward
                  through where you've been.
                </Empty>
              )}
              {/* Every open tab stays mounted, so switching back is instant and keeps its place */}
              {tabs.map((tab) => (
                <div key={tab.id} className="editor-pane" hidden={tab.id !== active?.id}>
                  {tab.kind === "doc" ? <PdfView tab={tab} visible={tab.id === active?.id} />
                                      : <CodeView tab={tab} visible={tab.id === active?.id} />}
                </div>
              ))}
            </div>
          </Panel>
          <PanelResizeHandle className="handle" />
          <Panel defaultSize={26} minSize={14} className="inspector">
            {active?.kind === "doc" && <DocInspector tab={active} />}
            {active?.kind === "code" && <CodeInspector tab={active} />}
            {!active && <Empty>What's related to the passage or symbol you're looking at appears here.</Empty>}
          </Panel>
        </PanelGroup>
      </div>
      <StatusBar onSignedOut={onSignedOut} />
      <div className="toasts">
        {app.toasts.map((toast) => <div key={toast.id} className={`toast ${toast.kind}`}>{toast.text}</div>)}
      </div>
    </div>
  );
}
