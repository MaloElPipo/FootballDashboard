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
  const [debug, setDebug] = useState<string[]>([
    "[boot] React monté",
  ]);
  const [pingCount, setPingCount] = useState(0);
  const readySent = useRef(false);

  useEffect(() => {
    const onRender = (event: Event) => {
      const data = (event as CustomEvent<RenderData>).detail;
      setDebug((d) => [
        ...d,
        `[render] reçu, args=${JSON.stringify(data?.args ?? {})}`,
      ]);
      setArgs(data?.args as ChantierOneArgs);
      Streamlit.setFrameHeight();
    };
    Streamlit.events.addEventListener(
      Streamlit.RENDER_EVENT,
      onRender as EventListener,
    );
    if (!readySent.current) {
      Streamlit.setComponentReady();
      setDebug((d) => [...d, "[boot] setComponentReady() envoyé"]);
      readySent.current = true;
    }
    Streamlit.setFrameHeight(260);
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
    setDebug((d) => [...d, `[ping] envoyé count=${next}`]);
  };

  return (
    <div
      style={{
        padding: "12px 16px",
        border: "2px solid #2563eb",
        borderRadius: 8,
        background: "linear-gradient(180deg, #f7faff 0%, #eef3fb 100%)",
        fontSize: 13,
        color: "#1a2433",
        minHeight: 220,
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 15 }}>
        Lineup Pitch — chantier 1 (debug visible)
      </div>
      <div style={{ marginBottom: 8 }}>
        Args reçus :{" "}
        {args === null ? (
          <span style={{ color: "#dc2626", fontWeight: 600 }}>
            ⏳ aucun render event reçu pour le moment
          </span>
        ) : (
          <span>
            <strong>
              {args.home_team ?? "?"} vs {args.away_team ?? "?"}
            </strong>{" "}
            — {args.kickoff ?? "?"}
            {args.league ? ` (${args.league})` : ""}
          </span>
        )}
      </div>
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
      <div
        style={{
          marginTop: 12,
          padding: 8,
          background: "#1a2433",
          color: "#9bd1ff",
          borderRadius: 6,
          fontFamily: "monospace",
          fontSize: 11,
          maxHeight: 120,
          overflowY: "auto",
        }}
      >
        {debug.map((line, i) => (
          <div key={i}>{line}</div>
        ))}
      </div>
    </div>
  );
}
