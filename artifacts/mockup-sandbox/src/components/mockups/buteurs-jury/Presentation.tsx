import { useMemo, useState } from "react";
import data from "./data.json";

type Bucket = { n: number; min: number; xg: number; g: number; xa?: number; a?: number; xg90?: number };
type RawPlayer = {
  name: string;
  team: string;
  role: "XI" | "BENCH";
  pos: string;
  comment: string;
  mins_exp: number;
  cote_betclic: number;
  p_imp_brute: number;
  p_imp_norm: number;
  dom: Bucket;
  ucl: Bucket;
  other: Bucket;
  samples_all: number;
  mins_total_all: number;
  xg_total_all: number;
  goals_total_all: number;
  xg90_all: number;
  xg_match_v41: number;
  p_scorer_v41: number;
  ev_v41: number;
  verdict_v41: "VALUE" | "SURVEILLER" | "SKIP";
};

type Computed = RawPlayer & {
  xg90_w: number;
  fr_raw_w: number;
  fr_w: number;
  xg_match_v42: number;
  p_scorer_v42: number;
  delta_p_v42_vs_norm: number;
  ev_v42: number;
  verdict_v42: "VALUE" | "SURVEILLER" | "SKIP";
  coherence_ratio: number;
  coherence_flag: "ok" | "ucl_high" | "ucl_low" | "dom_only" | "ucl_only";
};

const fmtPct = (x: number, withSign = false) => {
  const v = (x * 100).toFixed(1);
  const sign = withSign && x > 0 ? "+" : "";
  return `${sign}${v}%`;
};

const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x));

const SEUIL_EV = 0.05;
const SEUIL_DP = 0.03;
const FR_LO = 0.7;
const FR_HI = 1.3;

function compute(p: RawPlayer, alpha: number): Computed {
  const dom = p.dom;
  const ucl = p.ucl;

  let xg90_w: number;
  let coherence_flag: Computed["coherence_flag"] = "ok";
  if (dom.min > 0 && ucl.min > 0) {
    xg90_w = alpha * (dom.xg90 ?? 0) + (1 - alpha) * (ucl.xg90 ?? 0);
  } else if (dom.min > 0) {
    xg90_w = dom.xg90 ?? 0;
    coherence_flag = "dom_only";
  } else if (ucl.min > 0) {
    xg90_w = ucl.xg90 ?? 0;
    coherence_flag = "ucl_only";
  } else {
    xg90_w = p.xg90_all;
  }

  const xg_w = alpha * dom.xg + (1 - alpha) * ucl.xg;
  const g_w = alpha * dom.g + (1 - alpha) * ucl.g;
  const fr_raw_w = xg_w > 0 ? g_w / xg_w : 1.0;
  const fr_w = clamp(fr_raw_w, FR_LO, FR_HI);

  const xg_match_v42 = xg90_w * (p.mins_exp / 90) * fr_w;
  const p_scorer_v42 = 1 - Math.exp(-xg_match_v42);
  const delta_p = p_scorer_v42 - p.p_imp_norm;
  const ev_v42 = p_scorer_v42 * p.cote_betclic - 1;

  let verdict_v42: Computed["verdict_v42"];
  if (ev_v42 >= SEUIL_EV && delta_p >= SEUIL_DP) verdict_v42 = "VALUE";
  else if (ev_v42 >= 0) verdict_v42 = "SURVEILLER";
  else verdict_v42 = "SKIP";

  const coherence_ratio = dom.xg90 && dom.xg90 > 0.05 ? (ucl.xg90 ?? 0) / dom.xg90 : 1;
  if (coherence_flag === "ok") {
    if (dom.xg90 && dom.xg90 > 0.05) {
      if (coherence_ratio > 1.5) coherence_flag = "ucl_high";
      else if (coherence_ratio < 0.5 && (ucl.xg90 ?? 0) > 0) coherence_flag = "ucl_low";
    }
  }

  return {
    ...p,
    xg90_w,
    fr_raw_w,
    fr_w,
    xg_match_v42,
    p_scorer_v42,
    delta_p_v42_vs_norm: delta_p,
    ev_v42,
    verdict_v42,
    coherence_ratio,
    coherence_flag,
  };
}

const verdictBadge = (v: string) => {
  const styles: Record<string, string> = {
    VALUE: "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/40",
    SURVEILLER: "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/40",
    SKIP: "bg-zinc-500/10 text-zinc-400 ring-1 ring-zinc-500/30",
  };
  return (
    <span className={`px-2 py-0.5 rounded text-[11px] font-semibold tracking-wide ${styles[v]}`}>
      {v}
    </span>
  );
};

const roleBadge = (r: string) => {
  if (r === "XI")
    return <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-blue-500/15 text-blue-300 ring-1 ring-blue-500/30">XI</span>;
  return <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-zinc-700/40 text-zinc-400 ring-1 ring-zinc-600/40">SUB</span>;
};

const coherenceBadge = (flag: Computed["coherence_flag"], ratio: number) => {
  if (flag === "ok")
    return <span className="text-zinc-600 text-[10px]">≈</span>;
  if (flag === "dom_only")
    return <span className="text-zinc-500 text-[10px]" title="Aucun match UCL — domestique seul">D</span>;
  if (flag === "ucl_only")
    return <span className="text-zinc-500 text-[10px]" title="Aucun match domestique — UCL seul">U</span>;
  if (flag === "ucl_high")
    return <span className="text-amber-400 text-[10px]" title={`UCL/DOM = ${ratio.toFixed(2)} — perf UCL surévaluée vs domestique`}>↑U</span>;
  if (flag === "ucl_low")
    return <span className="text-rose-400 text-[10px]" title={`UCL/DOM = ${ratio.toFixed(2)} — perf UCL sous-domestique`}>↓U</span>;
  return null;
};

export function Presentation() {
  const { match, config, players: rawPlayers } = data as unknown as {
    match: any;
    config: any;
    players: RawPlayer[];
  };

  const [alpha, setAlpha] = useState(0.7);

  const computedAll = useMemo(() => rawPlayers.map((p) => compute(p, alpha)), [alpha, rawPlayers]);

  const sortPlayers = (arr: Computed[]) =>
    [...arr].sort((a, b) => {
      if (a.role !== b.role) return a.role === "XI" ? -1 : 1;
      return b.xg_match_v42 - a.xg_match_v42;
    });
  const psgPlayers = sortPlayers(computedAll.filter((p) => p.team === "PSG"));
  const bayPlayers = sortPlayers(computedAll.filter((p) => p.team === "Bayern"));

  const sumPScorerV42 = (arr: Computed[]) => arr.reduce((s, p) => s + p.p_scorer_v42, 0);
  const sumImpBrute = (arr: Computed[]) => arr.reduce((s, p) => s + p.p_imp_brute, 0);

  // Live summary
  const summary = useMemo(() => {
    const all = computedAll;
    const cnt = (verdict: string, key: "verdict_v41" | "verdict_v42") => all.filter((p) => p[key] === verdict).length;
    const shifts: Record<string, number> = {};
    for (const p of all) {
      const k = `${p.verdict_v41}→${p.verdict_v42}`;
      shifts[k] = (shifts[k] || 0) + 1;
    }
    return {
      n_value_v41: cnt("VALUE", "verdict_v41"),
      n_value_v42: cnt("VALUE", "verdict_v42"),
      n_surv_v41: cnt("SURVEILLER", "verdict_v41"),
      n_surv_v42: cnt("SURVEILLER", "verdict_v42"),
      n_skip_v41: cnt("SKIP", "verdict_v41"),
      n_skip_v42: cnt("SKIP", "verdict_v42"),
      shifts,
      n_xi: all.filter((p) => p.role === "XI").length,
      n_bench: all.filter((p) => p.role === "BENCH").length,
      samples_avg: Math.round(all.reduce((s, p) => s + p.samples_all, 0) / all.length),
      samples_min: Math.min(...all.map((p) => p.samples_all)),
      samples_max: Math.max(...all.map((p) => p.samples_all)),
    };
  }, [computedAll]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 text-zinc-100 font-sans">
      <div className="max-w-[1280px] mx-auto px-10 py-10">
        {/* HEADER */}
        <div className="flex items-start justify-between border-b border-zinc-800 pb-6 mb-6">
          <div>
            <div className="text-[11px] uppercase tracking-[0.25em] text-amber-400 font-semibold mb-2">
              Présentation Jury — Test interne
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white">
              Modèle Buteurs Maison <span className="text-zinc-400">·</span>
              <span className="text-amber-300"> v4.1 vs v4.2</span>
            </h1>
            <div className="text-zinc-400 text-sm mt-2">
              Application sur <span className="text-white font-semibold">{match.home}</span>
              {" — "}
              <span className="text-white font-semibold">{match.away}</span>
              {" · "}
              {match.competition} · {match.venue}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[11px] uppercase tracking-wider text-zinc-500">Source stats joueur</div>
            <div className="text-emerald-400 text-xs mt-1 font-semibold">BSD · split DOM / UCL</div>
            <div className="text-zinc-500 text-xs mt-1">~{summary.samples_avg} matchs/joueur (min {summary.samples_min} · max {summary.samples_max})</div>
            <div className="text-zinc-600 text-[10px] mt-0.5">{summary.n_xi} titulaires · {summary.n_bench} subs</div>
          </div>
        </div>

        {/* CURSEUR ALPHA — pondération domestique vs UCL */}
        <div className="bg-amber-500/5 ring-1 ring-amber-500/30 rounded-lg p-5 mb-8">
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.2em] text-amber-300 font-bold">
                Curseur de pondération domestique vs UCL
              </div>
              <div className="text-zinc-400 text-xs mt-1">
                xG/90 pondéré = α × xG/90 (Bundesliga / Ligue 1) + (1−α) × xG/90 (UCL)
                {" · "}FR pondéré idem sur G/xG agrégés
              </div>
            </div>
            <div className="text-right">
              <div className="text-3xl font-bold text-amber-300 tabular-nums">α = {alpha.toFixed(2)}</div>
              <div className="text-[10px] text-zinc-500">
                {alpha === 1 ? "100% domestique" : alpha === 0 ? "100% UCL" : `${Math.round(alpha * 100)}% DOM · ${Math.round((1 - alpha) * 100)}% UCL`}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-[10px] text-zinc-500 w-20">100% UCL</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={alpha}
              onChange={(e) => setAlpha(parseFloat(e.target.value))}
              className="flex-1 accent-amber-400"
            />
            <span className="text-[10px] text-zinc-500 w-24 text-right">100% domestique</span>
          </div>
          <div className="flex items-center gap-2 mt-3">
            {[0, 0.3, 0.5, 0.7, 0.85, 1].map((v) => (
              <button
                key={v}
                onClick={() => setAlpha(v)}
                className={`px-2 py-0.5 text-[10px] rounded ring-1 transition ${
                  Math.abs(alpha - v) < 0.01
                    ? "bg-amber-500/30 ring-amber-400 text-amber-200 font-semibold"
                    : "bg-zinc-800/40 ring-zinc-700 text-zinc-400 hover:bg-zinc-700/40"
                }`}
              >
                {v.toFixed(2)}
              </button>
            ))}
            <span className="text-[10px] text-zinc-600 ml-auto">
              VALUE v4.2 : <span className="text-emerald-400 font-bold tabular-nums">{summary.n_value_v42}</span>
              {" · "}SURVEILLER : <span className="text-amber-400 font-bold tabular-nums">{summary.n_surv_v42}</span>
              {" · "}SKIP : <span className="text-zinc-400 font-bold tabular-nums">{summary.n_skip_v42}</span>
            </span>
          </div>
        </div>

        {/* LINEUPS */}
        <div className="grid grid-cols-2 gap-4 mb-8">
          <div className="bg-blue-950/30 ring-1 ring-blue-800/40 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] uppercase tracking-wider text-blue-300 font-bold">Paris Saint-Germain</span>
              <span className="text-[10px] text-blue-400/70">4-3-3 · L. Enrique</span>
            </div>
            <div className="text-zinc-300 text-[13px] leading-relaxed">{match.lineup_psg}</div>
          </div>
          <div className="bg-rose-950/30 ring-1 ring-rose-800/40 rounded-lg p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] uppercase tracking-wider text-rose-300 font-bold">FC Bayern München</span>
              <span className="text-[10px] text-rose-400/70">4-2-3-1 · V. Kompany</span>
            </div>
            <div className="text-zinc-300 text-[13px] leading-relaxed">{match.lineup_bay}</div>
          </div>
        </div>

        {/* SECTION 1 : CONTEXTE */}
        <section className="mb-10">
          <h2 className="text-[11px] uppercase tracking-[0.2em] text-amber-400 font-bold mb-3">
            ① Contexte du match
          </h2>
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-zinc-900/60 ring-1 ring-zinc-800 rounded-lg p-5">
              <div className="text-[11px] uppercase text-zinc-500 mb-1">λ équipe (intensité buts)</div>
              <div className="flex items-baseline gap-3 mt-2">
                <div>
                  <div className="text-[10px] text-zinc-500">PSG</div>
                  <div className="text-2xl font-bold text-blue-300">{match.lambda_psg.toFixed(3)}</div>
                </div>
                <div className="text-zinc-600">·</div>
                <div>
                  <div className="text-[10px] text-zinc-500">Bayern</div>
                  <div className="text-2xl font-bold text-rose-300">{match.lambda_bayern.toFixed(3)}</div>
                </div>
              </div>
              <div className="text-[11px] text-zinc-500 mt-2">
                Issu de g2_engine · bissection 1X2 + O/U 2.5
              </div>
            </div>
            <div className="bg-zinc-900/60 ring-1 ring-zinc-800 rounded-lg p-5">
              <div className="text-[11px] uppercase text-zinc-500 mb-1">P(équipe marque ≥ 1)</div>
              <div className="flex items-baseline gap-3 mt-2">
                <div>
                  <div className="text-[10px] text-zinc-500">PSG</div>
                  <div className="text-2xl font-bold text-blue-300">{fmtPct(match.p_team_marque_psg)}</div>
                </div>
                <div className="text-zinc-600">·</div>
                <div>
                  <div className="text-[10px] text-zinc-500">Bayern</div>
                  <div className="text-2xl font-bold text-rose-300">{fmtPct(match.p_team_marque_bayern)}</div>
                </div>
              </div>
              <div className="text-[11px] text-zinc-500 mt-2">1 − exp(−λ) Poisson</div>
            </div>
            <div className="bg-zinc-900/60 ring-1 ring-zinc-800 rounded-lg p-5">
              <div className="text-[11px] uppercase text-zinc-500 mb-1">Seuils décision v4.2</div>
              <div className="flex items-baseline gap-4 mt-2">
                <div>
                  <div className="text-[10px] text-zinc-500">EV mini</div>
                  <div className="text-2xl font-bold text-emerald-300">+{(SEUIL_EV * 100).toFixed(0)}%</div>
                </div>
                <div className="text-zinc-600">·</div>
                <div>
                  <div className="text-[10px] text-zinc-500">∆P mini</div>
                  <div className="text-2xl font-bold text-emerald-300">+{(SEUIL_DP * 100).toFixed(0)}%</div>
                </div>
              </div>
              <div className="text-[11px] text-zinc-500 mt-2">VALUE = double filtre PDF EV0</div>
            </div>
          </div>
        </section>

        {/* SECTION 2 : CE QUI CHANGE */}
        <section className="mb-10">
          <h2 className="text-[11px] uppercase tracking-[0.2em] text-amber-400 font-bold mb-3">
            ② Ce qui change entre v4.1 et v4.2
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-zinc-900/60 ring-1 ring-blue-500/30 rounded-lg p-5">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-[11px] font-bold text-blue-300 bg-blue-500/15 px-2 py-0.5 rounded">v4.1 actuel</span>
                <span className="text-zinc-500 text-xs">production · base toutes compétitions</span>
              </div>
              <div className="space-y-2 text-sm">
                <div className="text-zinc-300">
                  <span className="text-zinc-500">xG/90 =</span> total saison toutes compétitions
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">xG_match =</span> xG/90 × (mins attendues / 90)
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">P(buteur) =</span> 1 − exp(−xG_match)
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">Verdict =</span> EV &gt; +5%
                </div>
              </div>
            </div>
            <div className="bg-zinc-900/60 ring-1 ring-emerald-500/30 rounded-lg p-5">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-[11px] font-bold text-emerald-300 bg-emerald-500/15 px-2 py-0.5 rounded">v4.2 candidat</span>
                <span className="text-zinc-500 text-xs">PDF EV0 + pondération α</span>
              </div>
              <div className="space-y-2 text-sm">
                <div className="text-zinc-300">
                  <span className="text-zinc-500">xG/90 =</span> α × DOM + (1−α) × UCL
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">FR pondéré =</span> Σ Buts pondéré / Σ xG pondéré (clampé 0.7–1.3)
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">xG_match =</span> xG/90 pondéré × mins/90 × FR
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">Verdict =</span> EV &gt; +5% <span className="text-amber-300 font-semibold">ET</span> ∆P &gt; +3%
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* TABLE — PSG */}
        <section className="mb-8">
          <h2 className="text-[11px] uppercase tracking-[0.2em] text-amber-400 font-bold mb-3">
            ③ Comparatif joueur par joueur (XI puis bench probable)
          </h2>
          <div className="mb-2 flex items-center gap-2">
            <span className="text-blue-300 text-sm font-bold">Paris Saint-Germain</span>
            <span className="text-zinc-600 text-xs">
              · Σ p_scorer v4.2 = {sumPScorerV42(psgPlayers).toFixed(2)}
              · Σ 1/cote brute = {sumImpBrute(psgPlayers).toFixed(2)}
              · marge bookie ≈ {fmtPct(sumImpBrute(psgPlayers) / sumPScorerV42(psgPlayers) - 1)}
            </span>
          </div>
          <PlayerTable players={psgPlayers} />
        </section>

        <section className="mb-10">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-rose-300 text-sm font-bold">FC Bayern München</span>
            <span className="text-zinc-600 text-xs">
              · Σ p_scorer v4.2 = {sumPScorerV42(bayPlayers).toFixed(2)}
              · Σ 1/cote brute = {sumImpBrute(bayPlayers).toFixed(2)}
              · marge bookie ≈ {fmtPct(sumImpBrute(bayPlayers) / sumPScorerV42(bayPlayers) - 1)}
            </span>
          </div>
          <PlayerTable players={bayPlayers} />
        </section>

        {/* SECTION 4 : VERDICT GLOBAL */}
        <section className="mb-10">
          <h2 className="text-[11px] uppercase tracking-[0.2em] text-amber-400 font-bold mb-3">
            ④ Verdict global du test (live, suit le curseur α)
          </h2>
          <div className="grid grid-cols-4 gap-4 mb-4">
            <StatCard label="VALUE v4.1" value={summary.n_value_v41} accent="blue" />
            <StatCard label="VALUE v4.2" value={summary.n_value_v42} accent="emerald" />
            <StatCard label="SKIP v4.1" value={summary.n_skip_v41} accent="zinc" />
            <StatCard label="SKIP v4.2" value={summary.n_skip_v42} accent="zinc" />
          </div>
          <div className="bg-zinc-900/60 ring-1 ring-zinc-800 rounded-lg p-5">
            <div className="text-[11px] uppercase text-zinc-500 mb-3">Mouvements de verdict v4.1 → v4.2</div>
            <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm">
              {Object.entries(summary.shifts)
                .filter(([, v]) => v > 0)
                .sort((a, b) => (b[1] as number) - (a[1] as number))
                .map(([k, v]) => {
                  const [v41, v42] = k.split("→");
                  return (
                    <div key={k} className="flex items-center justify-between border-b border-zinc-800/60 py-1.5">
                      <div className="flex items-center gap-2">
                        {verdictBadge(v41)}
                        <span className="text-zinc-600">→</span>
                        {verdictBadge(v42)}
                      </div>
                      <span className="text-sm font-semibold text-zinc-300">{v as number} joueur{(v as number) > 1 ? "s" : ""}</span>
                    </div>
                  );
                })}
            </div>
          </div>
        </section>

        {/* SECTION 5 : INTERPRETATION */}
        <section className="mb-10">
          <h2 className="text-[11px] uppercase tracking-[0.2em] text-amber-400 font-bold mb-3">
            ⑤ Lecture du curseur — cas saillants
          </h2>
          <div className="bg-zinc-900/60 ring-1 ring-zinc-800 rounded-lg p-5 space-y-3 text-sm leading-relaxed">
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Pourquoi un curseur :</span>{" "}
              chaque joueur a un profil DOM ≠ profil UCL. Pondérer α ne biaise pas une seule métrique : ça permet d'ouvrir plusieurs lectures du même match.
              À α = 1 on lit la stat championnat pure (régulier, gros volume). À α = 0 on lit la stat UCL pure (qualité adverse + petits échantillons). Le défaut α = 0.7 reflète le fait que la stat domestique est plus stable.
            </p>
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Cas où la pondération bouge tout — Vitinha :</span>{" "}
              xG/90 Ligue 1 0.05 vs UCL 0.23 (ratio 4.6×). À α = 1 il sort SKIP indiscutable, à α = 0 il devient suspect VALUE. Le curseur force la transparence.
            </p>
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Cas où la pondération ne change rien — Kane :</span>{" "}
              DOM 1.05 / UCL 0.85, ratio cohérent 0.81. Que α soit 0 ou 1, il reste un VALUE massif. C'est le profil idéal "pari robuste".
            </p>
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Volet défense — Marquinhos, Tah, Pacho :</span>{" "}
              UCL/DOM &gt; 1.5 sur ces 3 défenseurs (ils marquent plus en UCL grâce aux corners et à la pression haute, mais l'échantillon est faible). À α élevé ils restent SKIP, à α faible ils deviennent SURVEILLER. Le flag ↑U signale qu'on ne se baserait pas dessus.
            </p>
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Échantillons fins — Musiala :</span>{" "}
              4 matchs UCL seulement. À α faible on prend un risque énorme sur ces 4 matchs. À α élevé on s'appuie sur 12 matchs Bundesliga. La position du curseur encode le risque qu'on accepte.
            </p>
            <p className="text-zinc-400 text-xs italic mt-2 pt-2 border-t border-zinc-800">
              Limite connue : les coupes nationales (DFB-Pokal, Coupe de France, Supercoupes, FIFA Club World Cup) totalisent 2-7 matchs/joueur mais BSD n'y track pas le xG → ces matchs ne sont pas comptés dans la pondération. Les buts marqués en coupes (5-7 chez Kane) sont visibles dans la colonne Smp mais ne pèsent pas sur le xG/90 pondéré.
            </p>
          </div>
        </section>

        {/* SECTION 6 : GARDE-FOUS */}
        <section className="mb-4">
          <h2 className="text-[11px] uppercase tracking-[0.2em] text-amber-400 font-bold mb-3">
            ⑥ Garde-fous & limites de ce test
          </h2>
          <div className="grid grid-cols-3 gap-4">
            <div className="bg-zinc-900/40 ring-1 ring-zinc-800 rounded-lg p-4 text-xs space-y-2">
              <div className="text-emerald-300 font-semibold">Stats joueurs</div>
              <div className="text-zinc-400">
                BSD getPlayerStats par joueur, classifiés DOM/UCL/OTHER en intersectant avec searchMatches par compétition (Bundesliga 309 matchs, Ligue 1 309, UCL 305 sur 25/26).
              </div>
            </div>
            <div className="bg-zinc-900/40 ring-1 ring-zinc-800 rounded-lg p-4 text-xs space-y-2">
              <div className="text-amber-300 font-semibold">Cotes Buteurs</div>
              <div className="text-zinc-400">
                Cotes plausibles UCL knockout (pas scrap réel Betclic). Marges bookie affichées en haut de chaque tableau pour contrôle.
              </div>
            </div>
            <div className="bg-zinc-900/40 ring-1 ring-zinc-800 rounded-lg p-4 text-xs space-y-2">
              <div className="text-amber-300 font-semibold">Code intouchable</div>
              <div className="text-zinc-400">
                Aucune modification de g2_engine.py, predict_today.py, betclic_scraper.py, modèle 4.1. Calculs en mémoire dans la présentation, hors pipeline.
              </div>
            </div>
          </div>
          <div className="text-[10px] text-zinc-600 mt-4 text-center">
            Présentation générée pour test 4.1 vs 4.2 — Pipeline V-Pin FR · Avril 2026 · Curseur α de pondération domestique vs UCL
          </div>
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value, accent }: { label: string; value: number; accent: "blue" | "emerald" | "zinc" }) {
  const colors = {
    blue: "text-blue-300 ring-blue-500/30",
    emerald: "text-emerald-300 ring-emerald-500/30",
    zinc: "text-zinc-400 ring-zinc-700",
  };
  return (
    <div className={`bg-zinc-900/60 ring-1 rounded-lg p-4 ${colors[accent]}`}>
      <div className="text-[11px] uppercase text-zinc-500">{label}</div>
      <div className={`text-3xl font-bold mt-1 ${colors[accent].split(" ")[0]} tabular-nums`}>{value}</div>
    </div>
  );
}

function PlayerTable({ players }: { players: Computed[] }) {
  return (
    <div className="bg-zinc-900/40 ring-1 ring-zinc-800 rounded-lg overflow-hidden">
      <table className="w-full text-[11.5px]">
        <thead>
          <tr className="text-[9.5px] uppercase text-zinc-500 bg-zinc-950/40">
            <th className="text-left px-3 py-2 font-semibold">Joueur</th>
            <th className="text-center px-1 py-2 font-semibold">R</th>
            <th className="text-right px-1 py-2 font-semibold" title="Échantillon DOM (Bundesliga / Ligue 1)">D</th>
            <th className="text-right px-1 py-2 font-semibold" title="Échantillon UCL">U</th>
            <th className="text-right px-1 py-2 font-semibold text-zinc-400" title="xG/90 domestique">xG/90<br/>DOM</th>
            <th className="text-right px-1 py-2 font-semibold text-zinc-400" title="xG/90 UCL">xG/90<br/>UCL</th>
            <th className="text-right px-1 py-2 font-semibold text-amber-300" title="xG/90 pondéré α (recalculé live)">xG/90<br/>pond.</th>
            <th className="text-center px-1 py-2 font-semibold" title="Cohérence DOM vs UCL">≈</th>
            <th className="text-right px-1 py-2 font-semibold text-amber-300" title="FR pondéré (Σ G pondéré / Σ xG pondéré, clampé 0.7-1.3)">FR<br/>pond.</th>
            <th className="text-right px-1 py-2 font-semibold">Min</th>
            <th className="text-right px-1 py-2 font-semibold">Cote</th>
            <th className="text-right px-1 py-2 font-semibold border-l border-zinc-800">P_imp<br/>norm</th>
            <th className="text-right px-1 py-2 font-semibold border-l border-zinc-800 text-blue-300">P v4.1</th>
            <th className="text-right px-1 py-2 font-semibold text-blue-300">EV v4.1</th>
            <th className="text-center px-1 py-2 font-semibold text-blue-300">V v4.1</th>
            <th className="text-right px-1 py-2 font-semibold border-l border-zinc-800 text-emerald-300">P v4.2</th>
            <th className="text-right px-1 py-2 font-semibold text-emerald-300">∆P</th>
            <th className="text-right px-1 py-2 font-semibold text-emerald-300">EV v4.2</th>
            <th className="text-center px-1 py-2 font-semibold text-emerald-300 pr-3">V v4.2</th>
          </tr>
        </thead>
        <tbody>
          {players.map((p, idx) => {
            const isFirstBench = p.role === "BENCH" && (idx === 0 || players[idx - 1].role !== "BENCH");
            return (
              <tr key={p.name} className={`border-t ${isFirstBench ? "border-zinc-700 border-t-2" : "border-zinc-800/60"} hover:bg-zinc-800/20 ${p.role === "BENCH" ? "opacity-75" : ""}`}>
                <td className="px-3 py-2">
                  <div className="font-semibold text-white">{p.name}</div>
                  <div className="text-[10px] text-zinc-500">{p.pos} · {p.comment}</div>
                </td>
                <td className="text-center px-1 py-2">{roleBadge(p.role)}</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-400" title={`${p.dom.min} min · ${p.dom.g} buts · ${p.dom.xg.toFixed(2)} xG`}>{p.dom.n}</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-400" title={`${p.ucl.min} min · ${p.ucl.g} buts · ${p.ucl.xg.toFixed(2)} xG`}>{p.ucl.n}</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-300">{p.dom.xg90?.toFixed(2) ?? "—"}</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-300">{p.ucl.xg90?.toFixed(2) ?? "—"}</td>
                <td className="text-right px-1 py-2 tabular-nums text-amber-300 font-semibold">{p.xg90_w.toFixed(2)}</td>
                <td className="text-center px-1 py-2">{coherenceBadge(p.coherence_flag, p.coherence_ratio)}</td>
                <td className="text-right px-1 py-2 tabular-nums text-amber-300" title={`FR brut pondéré = ${p.fr_raw_w.toFixed(2)}`}>{p.fr_w.toFixed(2)}</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-300">{p.mins_exp}'</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-200 font-semibold">{p.cote_betclic.toFixed(2)}</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-400 border-l border-zinc-800">{fmtPct(p.p_imp_norm)}</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-200 border-l border-zinc-800">{fmtPct(p.p_scorer_v41)}</td>
                <td className={`text-right px-1 py-2 tabular-nums font-semibold ${p.ev_v41 >= 0.05 ? "text-emerald-400" : p.ev_v41 > 0 ? "text-amber-400" : "text-rose-400"}`}>{fmtPct(p.ev_v41, true)}</td>
                <td className="text-center px-1 py-2">{verdictBadge(p.verdict_v41)}</td>
                <td className="text-right px-1 py-2 tabular-nums text-zinc-200 border-l border-zinc-800">{fmtPct(p.p_scorer_v42)}</td>
                <td className={`text-right px-1 py-2 tabular-nums ${p.delta_p_v42_vs_norm >= 0.03 ? "text-emerald-400 font-semibold" : p.delta_p_v42_vs_norm > 0 ? "text-amber-400" : "text-rose-400"}`}>{fmtPct(p.delta_p_v42_vs_norm, true)}</td>
                <td className={`text-right px-1 py-2 tabular-nums font-semibold ${p.ev_v42 >= 0.05 ? "text-emerald-400" : p.ev_v42 > 0 ? "text-amber-400" : "text-rose-400"}`}>{fmtPct(p.ev_v42, true)}</td>
                <td className="text-center px-1 py-2 pr-3">{verdictBadge(p.verdict_v42)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
