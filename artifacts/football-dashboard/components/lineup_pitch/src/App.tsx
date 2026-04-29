import React, { useEffect, useState } from "react";
import { Streamlit } from "./streamlit";

type ChantierOneArgs = {
  home_team?: string;
  away_team?: string;
  kickoff?: string;
  league?: string;
};

export function App() {
  const [args, setArgs] = useState<ChantierOneArgs>({});
  const [pingCount, setPingCount] = useState(0);

  useEffect(() => {
    Streamlit.events.addEventListener("render", (e) => {
      setArgs(e.args as ChantierOneArgs);
    });
    Streamlit.setComponentReady();
    Streamlit.setFrameHeight(180);
  }, []);

  useEffect(() => {
    Streamlit.setFrameHeight();
  }, [args, pingCount]);

  const handlePing = () => {
    const next = pingCount + 1;
    setPingCount(next);
    Streamlit.setComponentValue({
      action: "ping",
      ts: Date.now(),
      count: next,
    });
  };

  return (
    <div
      style={{
        padding: "12px 16px",
        border: "1px solid #c8d6e5",
        borderRadius: 8,
        background: "linear-gradient(180deg, #f7faff 0%, #eef3fb 100%)",
        fontSize: 14,
        color: "#1a2433",
      }}
    >
      <div style={{ fontWeight: 600, marginBottom: 6, fontSize: 15 }}>
        Lineup Pitch — chantier 1 : ping React {"<-->"} Python
      </div>
      <div style={{ marginBottom: 8 }}>
        Match reçu du Python :{" "}
        <strong>
          {args.home_team ?? "?"} vs {args.away_team ?? "?"}
        </strong>{" "}
        — {args.kickoff ?? "?"}
        {args.league ? ` (${args.league})` : ""}
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
    </div>
  );
}
