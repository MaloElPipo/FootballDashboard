import React, { useEffect, useRef, useState } from "react";
import { Streamlit, RenderData } from "streamlit-component-lib";

type ChantierOneArgs = {
  home_team?: string;
  away_team?: string;
  kickoff?: string;
  league?: string;
};

export function App() {
  const [args, setArgs] = useState<ChantierOneArgs | null>(null);
  const [pingCount, setPingCount] = useState(0);
  const readySent = useRef(false);

  useEffect(() => {
    const onRender = (event: Event) => {
      const data = (event as CustomEvent<RenderData>).detail;
      setArgs(data?.args as ChantierOneArgs);
      Streamlit.setFrameHeight();
    };
    Streamlit.events.addEventListener(
      Streamlit.RENDER_EVENT,
      onRender as EventListener,
    );
    if (!readySent.current) {
      Streamlit.setComponentReady();
      readySent.current = true;
    }
    Streamlit.setFrameHeight(140);
    return () => {
      Streamlit.events.removeEventListener(
        Streamlit.RENDER_EVENT,
        onRender as EventListener,
      );
    };
  }, []);

  const handlePing = () => {
    const next = pingCount + 1;
    setPingCount(next);
    Streamlit.setComponentValue({
      action: "ping",
      ts: Date.now(),
      count: next,
    });
  };

  const matchLine = args
    ? `${args.home_team ?? "?"} vs ${args.away_team ?? "?"} — ${args.kickoff ?? "?"}${args.league ? ` (${args.league})` : ""}`
    : "(en attente du premier render Streamlit…)";

  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid #c8d6e5",
        borderRadius: 8,
        background: "linear-gradient(180deg, #f7faff 0%, #eef3fb 100%)",
        fontSize: 14,
        color: "#1a2433",
        minHeight: 100,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 15 }}>
        Lineup Pitch — chantier 1 : pipe React ↔ Python validé
      </div>
      <div style={{ marginBottom: 10 }}>Match : {matchLine}</div>
      <button
        onClick={handlePing}
        style={{
          padding: "6px 14px",
          background: "#2563eb",
          color: "white",
          border: "none",
          borderRadius: 6,
          cursor: "pointer",
          fontWeight: 600,
        }}
      >
        Ping vers Python
      </button>
      <span style={{ marginLeft: 12, color: "#5f7184" }}>
        Pings envoyés : {pingCount}
      </span>
    </div>
  );
}
