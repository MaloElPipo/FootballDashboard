import { Wand2, RotateCcw, ChevronDown } from "lucide-react";

type Player = { name: string; status?: "doubtful" | "injured" | "suspended"; minutes?: number };

const lineup: Record<string, Player[]> = {
  GK: [{ name: "Lucas Chevalier", minutes: 1620 }],
  DEF: [
    { name: "Achraf Hakimi", minutes: 2410 },
    { name: "Marquinhos", minutes: 2235 },
    { name: "Willian Pacho", minutes: 2598 },
    { name: "Lucas Beraldo", minutes: 1180 },
  ],
  MID: [
    { name: "Vitinha", minutes: 2680, status: "doubtful" },
    { name: "W. Zaïre-Emery", minutes: 2415 },
    { name: "João Neves", minutes: 1890 },
  ],
  FWD: [
    { name: "Désiré Doué", minutes: 1450, status: "doubtful" },
    { name: "Ousmane Dembélé", minutes: 1620 },
    { name: "Khvicha Kvara.", minutes: 2110 },
  ],
};

const lineColor = {
  GK: "bg-yellow-500",
  DEF: "bg-blue-600",
  MID: "bg-emerald-600",
  FWD: "bg-red-600",
};

function StatusBadge({ s }: { s?: Player["status"] }) {
  if (!s) return null;
  const map = {
    doubtful: "bg-amber-100 text-amber-800 border-amber-300",
    injured: "bg-red-100 text-red-800 border-red-300",
    suspended: "bg-orange-100 text-orange-800 border-orange-300",
  };
  return <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border ${map[s]} uppercase`}>{s}</span>;
}

function PlayerSlot({ p, line }: { p: Player; line: string }) {
  return (
    <button className="w-full flex items-center justify-between gap-2 bg-white border border-slate-200 hover:border-slate-400 rounded-md px-2 py-1.5 text-left transition group">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <span className={`w-1.5 h-6 rounded-full flex-shrink-0 ${lineColor[line as keyof typeof lineColor]}`} />
        <div className="min-w-0 flex-1">
          <div className="text-xs font-semibold text-slate-900 truncate">{p.name}</div>
          {p.minutes !== undefined && (
            <div className="text-[10px] text-slate-500">{p.minutes}′ saison</div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        <StatusBadge s={p.status} />
        <ChevronDown className="w-3 h-3 text-slate-400 group-hover:text-slate-700" />
      </div>
    </button>
  );
}

function MiniPitch() {
  // Tiny visual reminder of formation
  return (
    <div className="relative rounded-md overflow-hidden bg-emerald-700" style={{ height: "90px" }}>
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 100 60" preserveAspectRatio="none">
        <rect x="2" y="2" width="96" height="56" stroke="white" strokeWidth="0.4" fill="none" opacity="0.5" />
        <line x1="50" y1="2" x2="50" y2="58" stroke="white" strokeWidth="0.4" opacity="0.5" />
        <circle cx="50" cy="30" r="8" stroke="white" strokeWidth="0.4" fill="none" opacity="0.5" />
      </svg>
      {/* dots positioned for 4-3-3 horizontal */}
      <div className="absolute inset-0 flex items-center justify-around">
        {[1,4,3,3].map((cnt, idx) => (
          <div key={idx} className="flex flex-col gap-1.5">
            {Array.from({length:cnt}).map((_,i)=>(
              <div key={i} className="w-2.5 h-2.5 rounded-full bg-white shadow-md" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export function PitchCompact() {
  return (
    <div className="min-h-screen bg-slate-50 p-4 font-sans">
      <div className="max-w-md mx-auto space-y-3">
        {/* Header */}
        <div className="bg-white rounded-lg border border-slate-200 p-3">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded bg-blue-700 flex items-center justify-center text-white text-[10px] font-bold">PSG</div>
              <div className="font-bold text-sm text-slate-900">Paris Saint-Germain</div>
            </div>
            <span className="text-[10px] text-slate-500 uppercase font-semibold">Domicile</span>
          </div>
          <div className="flex items-center gap-2">
            <select className="flex-1 text-xs border border-slate-300 rounded px-2 py-1.5 bg-white font-medium">
              <option>4-3-3</option>
              <option>4-2-3-1</option>
              <option>4-4-2</option>
              <option>3-5-2</option>
              <option>3-4-3</option>
              <option>5-3-2</option>
            </select>
            <button className="flex items-center gap-1 bg-emerald-600 hover:bg-emerald-700 text-white text-[11px] font-medium px-2.5 py-1.5 rounded transition">
              <Wand2 className="w-3 h-3" /> Auto
            </button>
            <button className="flex items-center bg-slate-100 hover:bg-slate-200 text-slate-600 px-2 py-1.5 rounded transition">
              <RotateCcw className="w-3 h-3" />
            </button>
          </div>
        </div>

        {/* Mini schema reminder */}
        <MiniPitch />

        {/* Player list grouped by line */}
        <div className="space-y-2">
          {(["FWD","MID","DEF","GK"] as const).map(line => (
            <div key={line} className="bg-white rounded-lg border border-slate-200 p-2">
              <div className="flex items-center gap-2 mb-1.5 px-1">
                <span className={`w-1 h-3 rounded ${lineColor[line]}`} />
                <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider">
                  {line === "GK" ? "Gardien" : line === "DEF" ? "Défense" : line === "MID" ? "Milieu" : "Attaque"}
                  <span className="ml-1 text-slate-400 font-normal">({lineup[line].length})</span>
                </span>
              </div>
              <div className="space-y-1">
                {lineup[line].map(p => <PlayerSlot key={p.name} p={p} line={line} />)}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
