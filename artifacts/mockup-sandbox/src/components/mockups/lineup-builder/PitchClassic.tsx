import { Wand2, RotateCcw, AlertCircle } from "lucide-react";

type Player = { name: string; status?: "doubtful" | "injured" | "suspended" };

const formation = {
  GK: [{ name: "L. Chevalier" }],
  DEF: [
    { name: "A. Hakimi" },
    { name: "Marquinhos" },
    { name: "W. Pacho" },
    { name: "L. Beraldo" },
  ],
  MID: [
    { name: "Vitinha", status: "doubtful" as const },
    { name: "W. Zaïre-Emery" },
    { name: "J. Neves" },
  ],
  FWD: [
    { name: "D. Doué", status: "doubtful" as const },
    { name: "O. Dembélé" },
    { name: "K. Kvaratskhelia" },
  ],
};

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
  return (
    <div className="flex flex-col items-center gap-1 group cursor-pointer">
      <div className="relative">
        <div className="w-11 h-11 rounded-full bg-gradient-to-br from-blue-600 to-blue-800 ring-2 ring-white shadow-lg flex items-center justify-center text-white text-[10px] font-bold">
          {p.name.split(" ").map(w => w[0]).join("").slice(0, 2)}
        </div>
        {statusBadge(p.status)}
      </div>
      <div className="bg-black/70 backdrop-blur-sm px-1.5 py-0.5 rounded text-[10px] text-white font-medium whitespace-nowrap">
        {p.name}
      </div>
    </div>
  );
}

export function PitchClassic() {
  return (
    <div className="min-h-screen bg-slate-100 p-6 font-sans">
      <div className="max-w-md mx-auto space-y-4">
        {/* Header */}
        <div className="bg-white rounded-xl shadow-sm p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-blue-700 flex items-center justify-center text-white text-xs font-bold">PSG</div>
              <div>
                <div className="font-bold text-slate-900">Paris Saint-Germain</div>
                <div className="text-xs text-slate-500">Domicile · 4-3-3</div>
              </div>
            </div>
            <select className="text-xs border border-slate-200 rounded-md px-2 py-1.5 bg-slate-50 font-medium">
              <option>4-3-3</option>
              <option>4-2-3-1</option>
              <option>4-4-2</option>
              <option>3-5-2</option>
              <option>3-4-3</option>
              <option>5-3-2</option>
            </select>
          </div>
          <div className="flex gap-2">
            <button className="flex-1 flex items-center justify-center gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium py-2 rounded-md transition">
              <Wand2 className="w-3.5 h-3.5" /> Remplissage auto
            </button>
            <button className="flex items-center justify-center gap-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-medium px-3 py-2 rounded-md transition">
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Pitch */}
        <div className="relative rounded-xl overflow-hidden shadow-xl" style={{ aspectRatio: "3/4" }}>
          {/* Grass background with stripes */}
          <div className="absolute inset-0" style={{
            background: "repeating-linear-gradient(180deg, #2f9e44 0px, #2f9e44 40px, #37b04a 40px, #37b04a 80px)"
          }} />
          {/* Pitch markings */}
          <svg className="absolute inset-0 w-full h-full" viewBox="0 0 300 400" preserveAspectRatio="none">
            <rect x="10" y="10" width="280" height="380" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
            <line x1="10" y1="200" x2="290" y2="200" stroke="white" strokeWidth="2" opacity="0.7" />
            <circle cx="150" cy="200" r="40" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
            <rect x="80" y="10" width="140" height="50" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
            <rect x="80" y="340" width="140" height="50" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
            <rect x="115" y="10" width="70" height="20" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
            <rect x="115" y="370" width="70" height="20" stroke="white" strokeWidth="2" fill="none" opacity="0.7" />
          </svg>
          {/* Players grid */}
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

        {/* Legend / available players */}
        <div className="bg-white rounded-xl shadow-sm p-3">
          <div className="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-2 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" /> Cliquez sur un joueur pour le remplacer
          </div>
          <div className="flex flex-wrap gap-1.5 text-[10px]">
            <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">? doubtful</span>
            <span className="px-2 py-0.5 rounded-full bg-red-100 text-red-800">+ injured</span>
            <span className="px-2 py-0.5 rounded-full bg-orange-100 text-orange-800">■ suspended</span>
          </div>
        </div>
      </div>
    </div>
  );
}
