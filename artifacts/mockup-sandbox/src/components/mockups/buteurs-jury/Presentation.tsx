import data from "./data.json";

type Player = {
  name: string;
  team: string;
  pos: string;
  role: "XI" | "BENCH";
  samples: number;
  mins_total: number;
  goals_total: number;
  xg_total: number;
  xg90: number;
  fr_raw: number;
  fr_estim: number;
  mins_exp: number;
  cote_betclic: number;
  comment: string;
  xg_match_v41: number;
  xg_match_v42: number;
  p_scorer_v41: number;
  p_scorer_v42: number;
  p_imp_brute: number;
  p_imp_norm: number;
  ev_v41: number;
  ev_v42: number;
  delta_p_v42_vs_norm: number;
  verdict_v41: "VALUE" | "SURVEILLER" | "SKIP";
  verdict_v42: "VALUE" | "SURVEILLER" | "SKIP";
};

const fmtPct = (x: number, withSign = false) => {
  const v = (x * 100).toFixed(1);
  const sign = withSign && x > 0 ? "+" : "";
  return `${sign}${v}%`;
};

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

const shiftStyle = (v41: string, v42: string) => {
  if (v41 === v42) return "text-zinc-500";
  if (v42 === "VALUE") return "text-emerald-400 font-semibold";
  if (v42 === "SKIP" && v41 === "VALUE") return "text-rose-400 font-semibold";
  return "text-amber-400";
};

export function Presentation() {
  const { match, config, players, summary } = data as unknown as {
    match: any;
    config: any;
    players: Player[];
    summary: any;
  };
  // Sort: XI first then BENCH, within each by xg_match_v42 desc
  const sortPlayers = (arr: Player[]) =>
    [...arr].sort((a, b) => {
      if (a.role !== b.role) return a.role === "XI" ? -1 : 1;
      return b.xg_match_v42 - a.xg_match_v42;
    });
  const psgPlayers = sortPlayers(players.filter((p) => p.team === "PSG"));
  const bayPlayers = sortPlayers(players.filter((p) => p.team === "Bayern"));

  const sumPScorerV42 = (arr: Player[]) => arr.reduce((s, p) => s + p.p_scorer_v42, 0);
  const sumImpBrute = (arr: Player[]) => arr.reduce((s, p) => s + p.p_imp_brute, 0);

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
            <div className="text-emerald-400 text-xs mt-1 font-semibold">Toutes compétitions saison</div>
            <div className="text-zinc-500 text-xs mt-1">~{summary.samples_avg} matchs/joueur (min {summary.samples_min} · max {summary.samples_max})</div>
            <div className="text-zinc-600 text-[10px] mt-0.5">{summary.n_xi} titulaires · {summary.n_bench} subs</div>
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
                  <div className="text-2xl font-bold text-emerald-300">+{(config.seuil_ev * 100).toFixed(0)}%</div>
                </div>
                <div className="text-zinc-600">·</div>
                <div>
                  <div className="text-[10px] text-zinc-500">∆P mini</div>
                  <div className="text-2xl font-bold text-emerald-300">+{(config.seuil_dp * 100).toFixed(0)}%</div>
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
                <span className="text-zinc-500 text-xs">production</span>
              </div>
              <div className="space-y-2 text-sm">
                <div className="text-zinc-300">
                  <span className="text-zinc-500">xG_match =</span> xG/90 saison × (minutes attendues / 90)
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">P(buteur) =</span> 1 − exp(−xG_match)
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">Verdict =</span> EV &gt; +5%
                </div>
                <div className="text-rose-400 text-xs mt-3 italic">
                  Faiblesse : suppose que tous les joueurs convertissent leurs xG au taux théorique 1:1.
                </div>
              </div>
            </div>
            <div className="bg-zinc-900/60 ring-1 ring-emerald-500/30 rounded-lg p-5">
              <div className="flex items-center gap-2 mb-3">
                <span className="text-[11px] font-bold text-emerald-300 bg-emerald-500/15 px-2 py-0.5 rounded">v4.2 candidat</span>
                <span className="text-zinc-500 text-xs">PDF EV0 — 6 étapes</span>
              </div>
              <div className="space-y-2 text-sm">
                <div className="text-zinc-300">
                  <span className="text-zinc-500">xG_match =</span> v4.1 × <span className="text-amber-300 font-semibold">FinishRate</span>
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">FinishRate =</span> Buts / xG (clampé 0.7–1.3)
                </div>
                <div className="text-zinc-300">
                  <span className="text-zinc-500">Verdict =</span> EV &gt; +5% <span className="text-amber-300 font-semibold">ET</span> ∆P &gt; +3%
                </div>
                <div className="text-emerald-400 text-xs mt-3 italic">
                  Apport : différencie sur-finisseurs (Kane, Kvara) des sous-finisseurs (Barcola, Jackson).
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
            ④ Verdict global du test
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
              {Object.entries(summary.shifts as Record<string, number>)
                .filter(([, v]) => v > 0)
                .sort((a, b) => b[1] - a[1])
                .map(([k, v]) => {
                  const [v41, v42] = k.split("→");
                  return (
                    <div key={k} className="flex items-center justify-between border-b border-zinc-800/60 py-1.5">
                      <div className="flex items-center gap-2">
                        {verdictBadge(v41)}
                        <span className="text-zinc-600">→</span>
                        {verdictBadge(v42)}
                      </div>
                      <span className={`text-sm font-semibold ${shiftStyle(v41, v42)}`}>{v} joueur{v > 1 ? "s" : ""}</span>
                    </div>
                  );
                })}
            </div>
          </div>
        </section>

        {/* SECTION 5 : INTERPRETATION */}
        <section className="mb-10">
          <h2 className="text-[11px] uppercase tracking-[0.2em] text-amber-400 font-bold mb-3">
            ⑤ Interprétation des cas saillants
          </h2>
          <div className="bg-zinc-900/60 ring-1 ring-zinc-800 rounded-lg p-5 space-y-3 text-sm leading-relaxed">
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Le pic absolu — Kane :</span>{" "}
              cote 1.90 vs P_v4.2 67.4%, EV <span className="text-emerald-300 font-semibold">+28%</span>. 44 matchs cette saison, 52 buts pour 33.18 xG (FR brut 1.57, clampé 1.30). Sur-finisseur historique, l'écart bookie-modèle est massif et stable.
            </p>
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Pari contrarian PSG — Nuno Mendes :</span>{" "}
              cote 9.50 vs P_v4.2 19.5%, EV <span className="text-emerald-300 font-semibold">+85%</span>. xG/90 = 0.20 toutes compétitions (vs 0.11 si on regardait UCL seule), soit 6 buts/2481 min cette saison. Le marché Buteurs PSG sous-cote complètement le latéral gauche projeté.
            </p>
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Profil milieu sous-coté — João Neves :</span>{" "}
              cote 9.00 vs P_v4.2 18.3%, EV <span className="text-emerald-300 font-semibold">+65%</span>. 6 buts/3.84 xG sur 30 matchs (FR clampé 1.30), profil box-to-box que le bookie ne valorise pas.
            </p>
            <p className="text-zinc-300">
              <span className="text-emerald-300 font-semibold">Côté Bayern :</span>{" "}
              <span className="text-white">Musiala</span> (cote 2.95, EV +21.6%) reste VALUE même avec xG/90 corrigé à 0.66 (vs 0.92 UCL only). <span className="text-white">Díaz</span> (2.70, EV +12.9%) passe SKIP → VALUE en v4.2 grâce à FR 1.30 (24 buts/18 xG sur 46 matchs).
            </p>
            <p className="text-zinc-300">
              <span className="text-amber-300 font-semibold">Cas qui basculent v4.1→v4.2 :</span>{" "}
              <span className="text-white">Marquinhos</span> et <span className="text-white">Pacho</span> sortent du VALUE (xG/90 plus bas une fois la base élargie). <span className="text-white">Stanišić</span> et <span className="text-white">Upamecano</span> idem côté Bayern. <span className="text-white">Dembélé</span> apparaît en VALUE grâce à FR 1.30.
            </p>
            <p className="text-zinc-300">
              <span className="text-rose-300 font-semibold">Top attaquants restés SKIP :</span>{" "}
              <span className="text-white">Olise</span> (2.60), <span className="text-white">Kvara</span> (2.40), <span className="text-white">Vitinha</span> (4.80). Marché efficient sur les stars cotées court : la cote intègre déjà volume + conversion.
            </p>
            <p className="text-zinc-300">
              <span className="text-rose-300 font-semibold">Sous-finisseurs identifiés :</span>{" "}
              <span className="text-white">Barcola</span> (12 buts pour 13.74 xG, FR 0.87) reste SKIP renforcé. <span className="text-white">Upamecano</span> (1 but pour 2.27 xG, FR 0.70) idem.
            </p>
            <p className="text-zinc-400 text-xs italic mt-2 pt-2 border-t border-zinc-800">
              Bénéfice du passage UCL only → toutes compétitions : <span className="text-emerald-400">+30 matchs/joueur en moyenne</span>, FinishRate stabilisé sur 8-50 buts au lieu de 0-12, <span className="text-white">Musiala</span> ramené de surévaluation 0.92 à valeur réaliste 0.66, et 4 nouveaux profils de bench enfin exploitables (Doué, Karl, Jackson, Gnabry tous &gt; 30 matchs).
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
                BSD getPlayerStats par joueur, <span className="text-emerald-300">toutes compétitions saison 2025/26</span> (championnat + UCL + coupes nationales). Échantillons 18-47 matchs/joueur (moyenne ~38). Inclut donc la UCL elle-même — légère contamination acceptée pour gagner en volume.
              </div>
            </div>
            <div className="bg-zinc-900/40 ring-1 ring-zinc-800 rounded-lg p-4 text-xs space-y-2">
              <div className="text-amber-300 font-semibold">Cotes Buteurs</div>
              <div className="text-zinc-400">
                Cotes plausibles UCL knockout (pas scrap réel Betclic). Marge PSG +31.4% (réaliste), Bayern +10.6% (toujours un peu basse, à recalibrer avec scrap réel).
              </div>
            </div>
            <div className="bg-zinc-900/40 ring-1 ring-zinc-800 rounded-lg p-4 text-xs space-y-2">
              <div className="text-amber-300 font-semibold">Code intouchable</div>
              <div className="text-zinc-400">
                Aucune modification de g2_engine.py, predict_today.py, betclic_scraper.py, modèle 4.1. Calculs en mémoire, hors pipeline.
              </div>
            </div>
          </div>
          <div className="text-[10px] text-zinc-600 mt-4 text-center">
            Présentation générée pour test 4.1 vs 4.2 — Pipeline V-Pin FR · Avril 2026 · Compositions probables intégrées
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
      <div className={`text-3xl font-bold mt-1 ${colors[accent].split(" ")[0]}`}>{value}</div>
    </div>
  );
}

function PlayerTable({ players }: { players: Player[] }) {
  return (
    <div className="bg-zinc-900/40 ring-1 ring-zinc-800 rounded-lg overflow-hidden">
      <table className="w-full text-[12px]">
        <thead>
          <tr className="text-[10px] uppercase text-zinc-500 bg-zinc-950/40">
            <th className="text-left px-3 py-2 font-semibold">Joueur</th>
            <th className="text-center px-1 py-2 font-semibold">R</th>
            <th className="text-right px-2 py-2 font-semibold" title="Échantillon = nombre de matchs joués cette saison toutes compétitions">Smp</th>
            <th className="text-right px-2 py-2 font-semibold">Min</th>
            <th className="text-right px-2 py-2 font-semibold">xG/90</th>
            <th className="text-right px-2 py-2 font-semibold" title="Buts/xG brut, clampé 0.7-1.3">FR</th>
            <th className="text-right px-2 py-2 font-semibold">Cote</th>
            <th className="text-right px-2 py-2 font-semibold border-l border-zinc-800">P_imp<br/>norm</th>
            <th className="text-right px-2 py-2 font-semibold border-l border-zinc-800 text-blue-300">P v4.1</th>
            <th className="text-right px-2 py-2 font-semibold text-blue-300">EV v4.1</th>
            <th className="text-center px-2 py-2 font-semibold text-blue-300">V v4.1</th>
            <th className="text-right px-2 py-2 font-semibold border-l border-zinc-800 text-emerald-300">P v4.2</th>
            <th className="text-right px-2 py-2 font-semibold text-emerald-300">∆P v4.2</th>
            <th className="text-right px-2 py-2 font-semibold text-emerald-300">EV v4.2</th>
            <th className="text-center px-2 py-2 font-semibold text-emerald-300 pr-3">V v4.2</th>
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
                <td className="text-right px-2 py-2 tabular-nums text-zinc-400" title={`${p.mins_total} min totales · ${p.goals_total} buts · ${p.xg_total.toFixed(2)} xG`}>{p.samples}</td>
                <td className="text-right px-2 py-2 tabular-nums text-zinc-300">{p.mins_exp}'</td>
                <td className="text-right px-2 py-2 tabular-nums text-zinc-300">{p.xg90.toFixed(2)}</td>
                <td className="text-right px-2 py-2 tabular-nums text-amber-300" title={`FR brut = ${p.fr_raw.toFixed(2)}`}>{p.fr_estim.toFixed(2)}</td>
                <td className="text-right px-2 py-2 tabular-nums text-zinc-200 font-semibold">{p.cote_betclic.toFixed(2)}</td>
                <td className="text-right px-2 py-2 tabular-nums text-zinc-400 border-l border-zinc-800">{fmtPct(p.p_imp_norm)}</td>
                <td className="text-right px-2 py-2 tabular-nums text-zinc-200 border-l border-zinc-800">{fmtPct(p.p_scorer_v41)}</td>
                <td className={`text-right px-2 py-2 tabular-nums font-semibold ${p.ev_v41 >= 0.05 ? "text-emerald-400" : p.ev_v41 > 0 ? "text-amber-400" : "text-rose-400"}`}>{fmtPct(p.ev_v41, true)}</td>
                <td className="text-center px-2 py-2">{verdictBadge(p.verdict_v41)}</td>
                <td className="text-right px-2 py-2 tabular-nums text-zinc-200 border-l border-zinc-800">{fmtPct(p.p_scorer_v42)}</td>
                <td className={`text-right px-2 py-2 tabular-nums font-semibold ${p.delta_p_v42_vs_norm >= 0.03 ? "text-emerald-400" : p.delta_p_v42_vs_norm > 0 ? "text-amber-400" : "text-rose-400"}`}>{fmtPct(p.delta_p_v42_vs_norm, true)}</td>
                <td className={`text-right px-2 py-2 tabular-nums font-semibold ${p.ev_v42 >= 0.05 ? "text-emerald-400" : p.ev_v42 > 0 ? "text-amber-400" : "text-rose-400"}`}>{fmtPct(p.ev_v42, true)}</td>
                <td className="text-center px-2 py-2 pr-3">{verdictBadge(p.verdict_v42)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
