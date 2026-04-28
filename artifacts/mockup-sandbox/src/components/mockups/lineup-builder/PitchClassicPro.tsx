import { Wand2, RotateCcw, X, ArrowUpDown, TrendingUp, TrendingDown, Minus, ChevronRight } from "lucide-react";

type Player = {
  name: string;
  status?: "doubtful" | "injured" | "suspended";
  jersey?: number;
};

const formation = {
  GK: [{ name: "L. Chevalier", jersey: 30 }],
  DEF: [
    { name: "A. Hakimi", jersey: 2 },
    { name: "Marquinhos", jersey: 5 },
    { name: "W. Pacho", jersey: 51 },
    { name: "L. Beraldo", jersey: 35 },
  ],
  MID: [
    { name: "Vitinha", jersey: 17, status: "doubtful" as const },
    { name: "W. Zaïre-Emery", jersey: 33 },
    { name: "J. Neves", jersey: 87 },
  ],
  FWD: [
    { name: "D. Doué", jersey: 14, status: "doubtful" as const },
    { name: "O. Dembélé", jersey: 10 },
    { name: "K. Kvaratskhelia", jersey: 7 },
  ],
};

// Le joueur "sélectionné" (Vitinha) — état d'interaction du compact
const SELECTED = "Vitinha";

const statusBadge = (s?: Player["status"]) => {
  if (!s) return null;
  const map = {
    doubtful: { label: "?", color: "bg-amber-400 text-amber-950" },
    injured: { label: "+", color: "bg-red-500 text-white" },
    suspended: { label: "■", color: "bg-orange-500 text-white" },
  } as const;
  const c = map[s];
  return (
    <span className={`absolute -top-1 -right-1 w-4 h-4 rounded-full text-[9px] font-bold flex items-center justify-center ring-2 ring-emerald-700 ${c.color}`}>
      {c.label}
    </span>
  );
};

function PlayerDot({ p }: { p: Player }) {
  const isSelected = p.name === SELECTED;
  return (
    <div className="flex flex-col items-center gap-1 group cursor-pointer">
      <div className="relative">
        {isSelected && (
          <span className="absolute inset-0 -m-1.5 rounded-full bg-cyan-300/60 animate-pulse" />
        )}
        <div className={`relative w-11 h-11 rounded-full ring-2 shadow-lg flex items-center justify-center text-white text-[10px] font-bold ${
          isSelected
            ? "bg-gradient-to-br from-cyan-400 to-cyan-600 ring-cyan-200 scale-110"
            : "bg-gradient-to-br from-blue-600 to-blue-800 ring-white"
        }`}>
          {p.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
        </div>
        {statusBadge(p.status)}
      </div>
      <div className={`backdrop-blur-sm px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap ${
        isSelected ? "bg-cyan-500 text-white" : "bg-black/70 text-white"
      }`}>
        {p.name}
      </div>
    </div>
  );
}

// Stat row component
function StatRow({ label, value, sub, edge, hint }: {
  label: string;
  value: string;
  sub?: string;
  edge?: number;
  hint?: string;
}) {
  const edgeClasses = edge === undefined ? "" :
    edge > 3 ? "text-emerald-600 bg-emerald-50" :
    edge < -3 ? "text-red-600 bg-red-50" :
    "text-slate-500 bg-slate-100";
  const EdgeIcon = edge === undefined ? null :
    edge > 3 ? TrendingUp : edge < -3 ? TrendingDown : Minus;
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0">
      <div className="flex flex-col">
        <span className="text-[11px] text-slate-500 uppercase tracking-wide font-semibold">{label}</span>
        {hint && <span className="text-[10px] text-slate-400">{hint}</span>}
      </div>
      <div className="flex items-center gap-2">
        <div className="text-right">
          <div className="text-base font-bold font-mono text-slate-900">{value}</div>
          {sub && <div className="text-[10px] text-slate-500 font-mono">{sub}</div>}
        </div>
        {edge !== undefined && EdgeIcon && (
          <span className={`flex items-center gap-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${edgeClasses}`}>
            <EdgeIcon className="w-3 h-3" />
            {edge > 0 ? "+" : ""}{edge.toFixed(1)}%
          </span>
        )}
      </div>
    </div>
  );
}

function ReplacementRow({ name, minutes, status }: { name: string; minutes: number; status?: Player["status"] }) {
  return (
    <button className="w-full flex items-center justify-between gap-2 hover:bg-slate-100 rounded-md px-2 py-1.5 text-left transition group">
      <div className="flex items-center gap-2 min-w-0">
        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-slate-400 to-slate-500 flex-shrink-0 flex items-center justify-center text-white text-[9px] font-bold">
          {name.split(" ").map(w => w[0]).join("").slice(0, 2)}
        </div>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-slate-900 truncate">{name}</div>
          <div className="text-[10px] text-slate-500">{minutes}′ saison</div>
        </div>
      </div>
      <div className="flex items-center gap-1.5 flex-shrink-0">
        {status === "doubtful" && <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">?</span>}
        <ChevronRight className="w-3 h-3 text-slate-400 group-hover:text-slate-700" />
      </div>
    </button>
  );
}

export function PitchClassicPro() {
  return (
    <div className="min-h-screen bg-slate-100 p-6 font-sans">
      <div className="max-w-5xl mx-auto">
        {/* Match header */}
        <div className="bg-white rounded-xl shadow-sm p-3 mb-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-blue-700 flex items-center justify-center text-white text-[10px] font-bold">PSG</div>
            <div>
              <div className="text-xs text-slate-500 uppercase font-semibold tracking-wide">UCL · Demi-finale</div>
              <div className="font-bold text-slate-900">Paris SG vs Bayern Munich</div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-xs text-slate-500">Coup d'envoi</div>
            <div className="font-bold text-slate-900">Ce soir 21:00</div>
          </div>
        </div>

        {/* Two columns: pitch + stats panel */}
        <div className="grid grid-cols-[1fr_360px] gap-4">
          {/* Left: Pitch */}
          <div className="space-y-4">
            <div className="bg-white rounded-xl shadow-sm p-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs font-semibold text-slate-700 uppercase tracking-wide">Composition · Domicile</span>
                <select className="text-xs border border-slate-200 rounded-md px-2 py-1 bg-slate-50 font-medium">
                  <option>4-3-3</option>
                  <option>4-2-3-1</option>
                  <option>4-4-2</option>
                  <option>3-5-2</option>
                  <option>3-4-3</option>
                  <option>5-3-2</option>
                </select>
              </div>
              <div className="flex gap-2">
                <button className="flex-1 flex items-center justify-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium py-1.5 rounded-md transition">
                  <Wand2 className="w-3.5 h-3.5" /> Remplissage auto
                </button>
                <button className="flex items-center justify-center gap-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-medium px-3 py-1.5 rounded-md transition">
                  <RotateCcw className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            <div className="relative rounded-xl overflow-hidden shadow-xl" style={{ aspectRatio: "3/4" }}>
              <div className="absolute inset-0" style={{
                background: "repeating-linear-gradient(180deg, #2f9e44 0px, #2f9e44 40px, #37b04a 40px, #37b04a 80px)"
              }} />
              <svg className="absolute inset-0 w-full h-full" viewBox="0 0 300 400" preserveAspectRatio="none">
                <rect x="10" y="10" width="280" height="380" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
                <line x1="10" y1="200" x2="290" y2="200" stroke="white" strokeWidth="2" opacity="0.7" />
                <circle cx="150" cy="200" r="40" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
                <rect x="80" y="10" width="140" height="50" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
                <rect x="80" y="340" width="140" height="50" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
                <rect x="115" y="10" width="70" height="20" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
                <rect x="115" y="370" width="70" height="20" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
              </svg>
              <div className="absolute inset-0 flex flex-col justify-around py-6">
                <div className="flex justify-around px-6">
                  {formation.FWD.map(p => <PlayerDot key={p.name} p={p} />)}
                </div>
                <div className="flex justify-around px-8">
                  {formation.MID.map(p => <PlayerDot key={p.name} p={p} />)}
                </div>
                <div className="flex justify-around px-3">
                  {formation.DEF.map(p => <PlayerDot key={p.name} p={p} />)}
                </div>
                <div className="flex justify-center">
                  {formation.GK.map(p => <PlayerDot key={p.name} p={p} />)}
                </div>
              </div>
            </div>
          </div>

          {/* Right: Stats panel for selected player */}
          <div className="space-y-3">
            <div className="bg-white rounded-xl shadow-md overflow-hidden">
              {/* Header */}
              <div className="bg-gradient-to-br from-cyan-500 to-cyan-700 p-4 text-white relative">
                <button className="absolute top-2 right-2 text-white/80 hover:text-white">
                  <X className="w-4 h-4" />
                </button>
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-full bg-white/20 ring-2 ring-white flex items-center justify-center text-white text-sm font-bold">
                    17
                  </div>
                  <div>
                    <div className="text-[11px] uppercase tracking-wider opacity-80">Milieu · Joueur sélectionné</div>
                    <div className="text-lg font-black leading-tight">Vitinha</div>
                    <div className="flex items-center gap-1.5 mt-1">
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-amber-400 text-amber-950">DOUBTFUL</span>
                      <span className="text-[10px] opacity-90">Heel Injury</span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Stats */}
              <div className="p-4 space-y-1">
                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Marchés bookmakers</div>
                <StatRow
                  label="Cote Buteur"
                  hint="Fair 4.20 · Betclic 4.50"
                  value="4.50"
                  edge={6.7}
                />
                <StatRow
                  label="Cote Passeur"
                  hint="Fair 3.80 · BSD 4.00"
                  value="4.00"
                  edge={5.0}
                />

                <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mt-4 mb-2">Stats attendues match</div>
                <StatRow label="xG" hint="Buts attendus" value="0.32" sub="0.42 / 90′" />
                <StatRow label="xA" hint="Passes déc. attendues" value="0.18" sub="0.24 / 90′" />
                <StatRow label="xT" hint="Tirs attendus" value="1.85" sub="2.45 / 90′" />
                <StatRow label="xTC" hint="Tirs cadrés attendus" value="0.72" sub="0.95 / 90′" />
              </div>
            </div>

            {/* Replacement panel */}
            <div className="bg-white rounded-xl shadow-md overflow-hidden">
              <div className="px-4 py-2.5 bg-slate-50 border-b border-slate-200 flex items-center gap-2">
                <ArrowUpDown className="w-3.5 h-3.5 text-slate-500" />
                <span className="text-xs font-bold text-slate-700 uppercase tracking-wide">Remplacer par...</span>
                <span className="ml-auto text-[10px] text-slate-500">trié par minutes saison</span>
              </div>
              <div className="p-2 space-y-1">
                <ReplacementRow name="Fabián Ruiz" minutes={1980} status="doubtful" />
                <ReplacementRow name="Senny Mayulu" minutes={780} />
                <ReplacementRow name="Kang-in Lee" minutes={195} />
                <ReplacementRow name="Dro Fernández" minutes={0} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
