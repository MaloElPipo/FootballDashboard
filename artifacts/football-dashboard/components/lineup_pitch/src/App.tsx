import React, { useEffect, useMemo, useRef, useState } from "react";
import { Streamlit, RenderData } from "streamlit-component-lib";
import fixture from "./fixtures/atletico_arsenal.json";
import { Pitch } from "./components/Pitch";
import { Bench } from "./components/Bench";
import { StatsPanel } from "./components/StatsPanel";
import { autoAssign, detectFormation, FORMATIONS } from "./formations";
import type { FormationKey, MatchData, Player, Side } from "./types";

const FORMATION_KEYS = Object.keys(FORMATIONS) as FormationKey[];
const FIXTURE = fixture as unknown as MatchData;

type ComponentArgs = {
  // Au chantier 3 : event_id réel + match data BSD live. Pour l'instant,
  // ces args ne servent qu'à l'affichage du header (titre, kickoff…).
  home_team?: string;
  away_team?: string;
  kickoff?: string;
  league?: string;
};

type SaveDelta = {
  side: Side;
  formation: FormationKey;
  starters_pids: (number | null)[]; // 11 pids dans l'ordre des slots
  minutes_overrides: Record<string, number>; // pid -> minutes
};

function teamHeader(args: ComponentArgs): {
  league: string;
  match: string;
  kickoff: string;
} {
  return {
    league: args.league ?? FIXTURE.league,
    match: `${args.home_team ?? FIXTURE.home_team} vs ${args.away_team ?? FIXTURE.away_team}`,
    kickoff: args.kickoff ?? "Kick-off à venir",
  };
}

// Breakpoint en dessous duquel le panneau passe en stack vertical sous le
// terrain (sinon le terrain est compressé et les pastilles se chevauchent).
const NARROW_BREAKPOINT = 720;

export function App() {
  const [args, setArgs] = useState<ComponentArgs | null>(null);
  const [side, setSide] = useState<Side>("home");
  const [formation, setFormation] = useState<FormationKey>(() =>
    detectFormation(FIXTURE.home),
  );
  const [selectedPid, setSelectedPid] = useState<number | null>(null);
  // Mode swap actif : pid du joueur sélectionné comme source. Quand non null,
  // un click sur un autre joueur (terrain ou banc) exécute la permutation.
  const [swapSourcePid, setSwapSourcePid] = useState<number | null>(null);
  // Composition manuelle override : Map<slotIdx, pid>. null = on suit
  // autoAssign (composition de référence détectée par le moteur).
  const [customAssignment, setCustomAssignment] = useState<
    Map<number, number> | null
  >(null);
  const [minutesOverrides, setMinutesOverrides] = useState<
    Record<number, number>
  >({});
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [isNarrow, setIsNarrow] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const readySent = useRef(false);

  // Surveille la largeur réelle du conteneur (l'iframe Streamlit varie selon
  // que la sidebar est ouverte/fermée et selon la résolution écran) ET sa
  // hauteur, pour resizer dynamiquement l'iframe Streamlit. Sans ça, le
  // banc déplié (state interne au composant Bench) serait coupé.
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        setIsNarrow(w > 0 && w < NARROW_BREAKPOINT);
        // marge de 8 px pour absorber les bordures et éviter une scrollbar
        const h = Math.ceil(entry.contentRect.height) + 8;
        if (h > 0) Streamlit.setFrameHeight(h);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Bridge Streamlit ↔ React
  useEffect(() => {
    const onRender = (event: Event) => {
      const data = (event as CustomEvent<RenderData>).detail;
      setArgs(data?.args as ComponentArgs);
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
    Streamlit.setFrameHeight(620);
    return () => {
      Streamlit.events.removeEventListener(
        Streamlit.RENDER_EVENT,
        onRender as EventListener,
      );
    };
  }, []);

  const roster = side === "home" ? FIXTURE.home : FIXTURE.away;
  const teamName =
    side === "home"
      ? (args?.home_team ?? FIXTURE.home_team)
      : (args?.away_team ?? FIXTURE.away_team);
  const referenceFormation = useMemo(() => detectFormation(roster), [roster]);

  // Composition affichée : auto OU manuelle (customAssignment override).
  const { onPitch, bench } = useMemo(() => {
    if (customAssignment === null) {
      return autoAssign(roster, formation);
    }
    const onP = new Map<number, Player>();
    const usedPids = new Set<number>();
    for (const [idx, pid] of customAssignment.entries()) {
      const p = roster.find((r) => r.pid === pid);
      if (p) {
        onP.set(idx, p);
        usedPids.add(pid);
      }
    }
    // Si custom n'a pas couvert tous les slots (cas de roster réduit),
    // remplir avec autoAssign sur les slots restants.
    if (onP.size < FORMATIONS[formation].length) {
      const remaining = roster.filter(
        (p) => p.pid != null && !usedPids.has(p.pid),
      );
      const filler = autoAssign(remaining, formation);
      for (const [idx, p] of filler.onPitch.entries()) {
        if (!onP.has(idx)) {
          onP.set(idx, p);
          if (p.pid != null) usedPids.add(p.pid);
        }
      }
    }
    const benchPlayers = roster.filter(
      (p) => p.pid != null && !usedPids.has(p.pid),
    );
    return { onPitch: onP, bench: benchPlayers };
  }, [customAssignment, roster, formation]);

  useEffect(() => {
    Streamlit.setFrameHeight();
  });

  // Quand on change de side, re-detect le schéma + reset selection / overrides
  // / customAssignment (la compo manuelle ne s'applique pas à l'autre équipe)
  const handleSideChange = (newSide: Side) => {
    if (newSide === side) return;
    setSide(newSide);
    const newRoster = newSide === "home" ? FIXTURE.home : FIXTURE.away;
    setFormation(detectFormation(newRoster));
    setSelectedPid(null);
    setSwapSourcePid(null);
    setCustomAssignment(null);
    setMinutesOverrides({});
  };

  // Changement de schéma : on RESET la compo manuelle car les slots changent
  // (les positions ne mappent plus sur le même role bucket).
  const handleFormationChange = (f: FormationKey) => {
    setFormation(f);
    setCustomAssignment(null);
    setSelectedPid(null);
    setSwapSourcePid(null);
  };

  const handleReset = () => {
    setFormation(referenceFormation);
    setCustomAssignment(null);
    setSelectedPid(null);
    setSwapSourcePid(null);
    setMinutesOverrides({});
    setSavedAt(null);
  };

  const handleSave = () => {
    const slots = FORMATIONS[formation];
    const starters: (number | null)[] = slots.map(
      (_, idx) => onPitch.get(idx)?.pid ?? null,
    );
    const payload: SaveDelta = {
      side,
      formation,
      starters_pids: starters,
      minutes_overrides: Object.fromEntries(
        Object.entries(minutesOverrides).map(([k, v]) => [String(k), v]),
      ),
    };
    Streamlit.setComponentValue({
      action: "save",
      ts: Date.now(),
      payload,
    });
    setSavedAt(Date.now());
  };

  // Exécution d'une permutation entre 2 joueurs (par pid).
  // Cas gérés :
  //   - 2 titulaires : échange leurs slots
  //   - source titulaire, target banc : target prend la place de source
  //   - source banc, target titulaire : source prend la place de target
  // Le banc affiché est dérivé automatiquement de customAssignment.
  const executeSwap = (sourcePid: number, targetPid: number) => {
    if (sourcePid === targetPid) return;
    let sourceSlot: number | null = null;
    let targetSlot: number | null = null;
    for (const [idx, p] of onPitch.entries()) {
      if (p.pid === sourcePid) sourceSlot = idx;
      if (p.pid === targetPid) targetSlot = idx;
    }

    // Construire la map de départ (couvre tous les slots)
    const newMap = new Map<number, number>();
    for (const [idx, p] of onPitch.entries()) {
      if (p.pid != null) newMap.set(idx, p.pid);
    }

    if (sourceSlot != null && targetSlot != null) {
      newMap.set(sourceSlot, targetPid);
      newMap.set(targetSlot, sourcePid);
    } else if (sourceSlot != null && targetSlot == null) {
      newMap.set(sourceSlot, targetPid);
    } else if (sourceSlot == null && targetSlot != null) {
      newMap.set(targetSlot, sourcePid);
    } else {
      // les 2 sur le banc : aucune action (cas atteint uniquement si
      // l'utilisateur démarre un swap depuis un dépliage, peu probable)
      return;
    }

    setCustomAssignment(newMap);
    setSwapSourcePid(null);
    setSelectedPid(null);
  };

  // Click handler unifié : si swap actif → swap, sinon ouvre le panneau.
  const handleSelect = (pid: number) => {
    if (swapSourcePid != null) {
      if (pid === swapSourcePid) {
        // click sur la source = annulation
        setSwapSourcePid(null);
      } else {
        executeSwap(swapSourcePid, pid);
      }
      return;
    }
    setSelectedPid((cur) => (cur === pid ? null : pid));
  };

  const handleStartSwap = () => {
    if (selectedPid == null) return;
    setSwapSourcePid(selectedPid);
    setSelectedPid(null);
  };

  const selectedPlayer: Player | null = useMemo(() => {
    if (selectedPid == null) return null;
    return roster.find((p) => p.pid === selectedPid) ?? null;
  }, [selectedPid, roster]);

  const headerInfo = teamHeader(args ?? {});
  const isModified =
    customAssignment != null ||
    formation !== referenceFormation ||
    Object.keys(minutesOverrides).length > 0;

  return (
    <div
      ref={containerRef}
      style={{
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
        color: "#0f172a",
        background: "transparent",
        maxWidth: 880,
      }}
    >
      <style>{`@keyframes lineupPulse {
        0%, 100% { transform: scale(1); opacity: 0.55; }
        50% { transform: scale(1.18); opacity: 0.25; }
      }
      .lineup-pitch-btn:focus-visible {
        outline: 2px solid #22d3ee;
        outline-offset: 2px;
      }`}</style>

      {/* Header compact (1 ligne) : ligue · match · kickoff · actions */}
      <div
        style={{
          background: "white",
          borderRadius: 10,
          padding: "8px 12px",
          marginBottom: 8,
          boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 800, color: "#0f172a" }}>
            {headerInfo.match}
          </div>
          <div style={{ fontSize: 10, color: "#64748b", fontWeight: 600 }}>
            {headerInfo.league} · {headerInfo.kickoff}
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button
            onClick={handleReset}
            disabled={!isModified}
            className="lineup-pitch-btn"
            title="Restaurer la composition de référence (BSD/forward log)"
            style={{
              padding: "5px 9px",
              background: isModified ? "#f1f5f9" : "#e2e8f0",
              border: "1px solid #cbd5e1",
              borderRadius: 6,
              cursor: isModified ? "pointer" : "not-allowed",
              fontSize: 11,
              fontWeight: 600,
              color: isModified ? "#334155" : "#94a3b8",
            }}
          >
            ↺ Reset
          </button>
          <button
            onClick={handleSave}
            disabled={!isModified}
            className="lineup-pitch-btn"
            title={
              isModified
                ? "Sauvegarder la composition modifiée vers Python"
                : "Pas de modification à sauvegarder"
            }
            style={{
              padding: "5px 11px",
              background: isModified ? "#16a34a" : "#94a3b8",
              border: "none",
              borderRadius: 6,
              cursor: isModified ? "pointer" : "not-allowed",
              fontSize: 11,
              fontWeight: 700,
              color: "white",
            }}
          >
            {savedAt != null && Date.now() - savedAt < 3000
              ? "✓ Sauvegardé"
              : "Save"}
          </button>
        </div>
      </div>

      {/* Toggle home/away + dropdown schéma — bandeau compact */}
      <div
        style={{
          background: "white",
          borderRadius: 10,
          padding: "6px 10px",
          marginBottom: 8,
          boxShadow: "0 1px 3px rgba(0,0,0,0.06)",
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            background: "#f1f5f9",
            borderRadius: 7,
            padding: 2,
          }}
        >
          {(["home", "away"] as Side[]).map((s) => (
            <button
              key={s}
              onClick={() => handleSideChange(s)}
              className="lineup-pitch-btn"
              aria-pressed={side === s}
              style={{
                padding: "4px 12px",
                background: side === s ? "white" : "transparent",
                border: "none",
                borderRadius: 5,
                cursor: "pointer",
                fontSize: 11,
                fontWeight: 700,
                color: side === s ? "#0f172a" : "#64748b",
                boxShadow:
                  side === s ? "0 1px 2px rgba(0,0,0,0.08)" : "none",
              }}
            >
              {s === "home" ? FIXTURE.home_team : FIXTURE.away_team}
            </button>
          ))}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            marginLeft: "auto",
          }}
        >
          <label
            style={{
              fontSize: 10,
              color: "#64748b",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}
          >
            Schéma
          </label>
          <select
            value={formation}
            onChange={(e) =>
              handleFormationChange(e.target.value as FormationKey)
            }
            style={{
              padding: "4px 7px",
              border: "1px solid #cbd5e1",
              borderRadius: 5,
              fontSize: 11,
              fontWeight: 600,
              background: "white",
              cursor: "pointer",
            }}
          >
            {FORMATION_KEYS.map((k) => (
              <option key={k} value={k}>
                {k}
                {k === referenceFormation ? "  (réf BSD)" : ""}
              </option>
            ))}
          </select>
          {formation !== referenceFormation && (
            <span
              style={{
                fontSize: 9,
                padding: "2px 5px",
                background: "#fef3c7",
                color: "#78350f",
                borderRadius: 3,
                fontWeight: 700,
              }}
              title={`Référence détectée : ${referenceFormation}`}
            >
              OVERRIDE
            </span>
          )}
        </div>
      </div>

      {/* Bandeau mode swap actif */}
      {swapSourcePid != null && (
        <div
          style={{
            background: "linear-gradient(180deg, #fb923c 0%, #ea580c 100%)",
            color: "white",
            borderRadius: 8,
            padding: "6px 10px",
            marginBottom: 8,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            fontSize: 11,
            fontWeight: 700,
            boxShadow: "0 2px 6px rgba(234,88,12,0.35)",
          }}
        >
          <span>
            ⇄ Mode permutation actif · cliquez le joueur cible (terrain ou
            banc)
          </span>
          <button
            onClick={() => setSwapSourcePid(null)}
            className="lineup-pitch-btn"
            style={{
              background: "rgba(255,255,255,0.25)",
              border: "none",
              color: "white",
              padding: "2px 8px",
              borderRadius: 4,
              cursor: "pointer",
              fontSize: 10,
              fontWeight: 700,
            }}
          >
            Annuler
          </button>
        </div>
      )}

      {/* Layout : terrain + panneau (côte à côte si large, empilé si étroit) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: isNarrow
            ? "minmax(0, 1fr)"
            : "minmax(0, 1fr) " +
              (selectedPlayer ? "minmax(280px, 320px)" : "0px"),
          gridAutoFlow: "row",
          gap: selectedPlayer ? 10 : 0,
          alignItems: "start",
          transition: "grid-template-columns 200ms ease, gap 200ms ease",
        }}
      >
        <div>
          <Pitch
            formation={formation}
            onPitch={onPitch}
            selectedPid={selectedPid}
            swapSourcePid={swapSourcePid}
            teamName={teamName}
            onSelect={handleSelect}
          />
          <Bench
            players={bench}
            selectedPid={selectedPid}
            swapSourcePid={swapSourcePid}
            teamName={teamName}
            defaultExpanded={false}
            onSelect={handleSelect}
          />
        </div>

        {selectedPlayer && (
          <div style={{ overflow: "hidden" }}>
            <StatsPanel
              player={selectedPlayer}
              minutesOverride={
                selectedPid != null
                  ? (minutesOverrides[selectedPid] ?? null)
                  : null
              }
              onMinutesChange={(m) => {
                if (selectedPid == null) return;
                setMinutesOverrides((cur) => {
                  const next = { ...cur };
                  if (m == null) delete next[selectedPid];
                  else next[selectedPid] = m;
                  return next;
                });
              }}
              onStartSwap={handleStartSwap}
              onClose={() => setSelectedPid(null)}
            />
          </div>
        )}
      </div>

      {/* Footer indicateur état */}
      {isModified && (
        <div
          style={{
            marginTop: 8,
            padding: "5px 9px",
            background: "#fef3c7",
            color: "#78350f",
            borderRadius: 5,
            fontSize: 10,
            fontWeight: 600,
            display: "inline-block",
          }}
        >
          Modifications non sauvegardées
          {customAssignment != null
            ? ` · ${customAssignment.size} permutation(s)`
            : ""}
          {formation !== referenceFormation
            ? ` · schéma ${formation} (réf ${referenceFormation})`
            : ""}
          {Object.keys(minutesOverrides).length > 0
            ? ` · ${Object.keys(minutesOverrides).length} minute(s) overridées`
            : ""}
        </div>
      )}
    </div>
  );
}
