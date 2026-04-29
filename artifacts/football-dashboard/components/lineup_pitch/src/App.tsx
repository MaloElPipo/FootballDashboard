import React, { useEffect, useState } from "react";
import {
  Streamlit,
  withStreamlitConnection,
  ComponentProps,
} from "streamlit-component-lib";

type ChantierOneArgs = {
  home_team?: string;
  away_team?: string;
  kickoff?: string;
  league?: string;
};

function PitchAppInner({ args }: ComponentProps) {
  const a = args as ChantierOneArgs;
  const [pingCount, setPingCount] = useState(0);

  useEffect(() => {
    Streamlit.setFrameHeight();
  });

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
          {a.home_team ?? "?"} vs {a.away_team ?? "?"}
        </strong>{" "}
        — {a.kickoff ?? "?"}
        {a.league ? ` (${a.league})` : ""}
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

export const App = withStreamlitConnection(PitchAppInner);
