/* Translates presentation only. Download URLs and CSV contents never change. */
(() => {
  const languages = ["fr", "es", "de", "it", "en"];
  // French source -> Spanish, German, Italian, English.
  const phrases = [
    ["Portail CSV", "Portal CSV", "CSV-Portal", "Portale CSV", "CSV portal"],
    ["Langue", "Idioma", "Sprache", "Lingua", "Language"],
    ["Données de carrière des joueurs actifs des championnats trackés par", "Datos de carrera de los jugadores activos de las ligas seguidas por", "Karrieredaten aktiver Spieler aus den erfassten Ligen von", "Dati di carriera dei giocatori attivi nei campionati seguiti da", "Career data for active players in leagues tracked by"],
    ["Source : Transfermarkt (endpoint ceapi). Mise à jour hebdomadaire programmée le", "Fuente: Transfermarkt (endpoint ceapi). Actualización semanal programada para el", "Quelle: Transfermarkt (ceapi-Endpunkt). Wöchentliche Aktualisierung geplant für", "Fonte: Transfermarkt (endpoint ceapi). Aggiornamento settimanale programmato per", "Source: Transfermarkt (ceapi endpoint). Weekly update scheduled for"],
    ["lundi à 5h15 (Paris)", "lunes a las 5:15 (París)", "Montag um 05:15 Uhr (Paris)", "lunedì alle 5:15 (Parigi)", "Monday at 05:15 (Paris)"],
    ["Le démarrage peut être retardé par GitHub.", "GitHub puede retrasar el inicio.", "GitHub kann den Start verzögern.", "GitHub potrebbe ritardare l’avvio.", "GitHub may delay the start."],
    ["Datasets disponibles", "Conjuntos disponibles", "Verfügbare Datensätze", "Dataset disponibili", "Available datasets"],
    ["Joueurs trackés", "Jugadores registrados", "Erfasste Spieler", "Giocatori monitorati", "Tracked players"],
    ["Lignes career totales", "Filas de carrera totales", "Karrierezeilen insgesamt", "Righe carriera totali", "Total career rows"],
    ["Volume total", "Tamaño total", "Gesamtgröße", "Dimensione totale", "Total size"],
    ["Comment ça marche ?", "¿Cómo funciona?", "Wie funktioniert es?", "Come funziona?", "How does it work?"],
    ["Pour chaque championnat, deux téléchargements sont proposés :", "Hay dos descargas disponibles para cada liga:", "Für jede Liga stehen zwei Downloads zur Verfügung:", "Per ogni campionato sono disponibili due download:", "Two downloads are available for each league:"],
    ["Tout télécharger", "Descargar todo", "Alles herunterladen", "Scarica tutto", "Download all"],
    ["Mise à jour saison", "Actualización de temporada", "Saisonaktualisierung", "Aggiornamento stagione", "Season update"],
    ["ZIP des 4 CSV complets :", "ZIP con los 4 CSV completos:", "ZIP mit den 4 vollständigen CSV-Dateien:", "ZIP con i 4 CSV completi:", "ZIP containing all 4 complete CSV files:"],
    ["(1 ligne/joueur, totaux carrière)", "(1 fila/jugador, totales de carrera)", "(1 Zeile/Spieler, Karrieregesamtwerte)", "(1 riga/giocatore, totali carriera)", "(1 row/player, career totals)"],
    ["(1 ligne par saison × compétition × club)", "(1 fila por temporada × competición × club)", "(1 Zeile pro Saison × Wettbewerb × Verein)", "(1 riga per stagione × competizione × club)", "(1 row per season × competition × club)"],
    ["(10 derniers matchs ou 3 derniers mois)", "(últimos 10 partidos o últimos 3 meses)", "(letzte 10 Spiele oder letzte 3 Monate)", "(ultime 10 partite o ultimi 3 mesi)", "(last 10 matches or last 3 months)"],
    ["(référentiel des codes compétitions rencontrés). Idéal pour une analyse complète.", "(lista de códigos de las competiciones encontradas). Ideal para un análisis completo.", "(Verzeichnis der gefundenen Wettbewerbscodes). Ideal für eine vollständige Analyse.", "(elenco dei codici delle competizioni incontrate). Ideale per un’analisi completa.", "(reference list of competition codes encountered). Ideal for a complete analysis."],
    ["ZIP léger contenant uniquement les lignes de la", "ZIP ligero que contiene solo las filas de la", "Kompaktes ZIP nur mit den Zeilen der", "ZIP leggero contenente solo le righe della", "Compact ZIP containing only rows from the"],
    ["saison en cours", "temporada actual", "aktuellen Saison", "stagione in corso", "current season"],
    ["À télécharger chaque semaine pour suivre l'actualité sans tout retéléverser.", "Descárgalo cada semana para seguir las novedades sin volver a cargarlo todo.", "Wöchentlich herunterladen, um aktuell zu bleiben, ohne alles erneut hochzuladen.", "Scaricalo ogni settimana per seguire gli aggiornamenti senza ricaricare tutto.", "Download weekly to stay up to date without uploading everything again."],
    ["Championnat", "Liga", "Liga", "Campionato", "League"],
    ["Contenu", "Contenido", "Inhalt", "Contenuto", "Contents"],
    ["Dernière mise à jour", "Última actualización", "Letzte Aktualisierung", "Ultimo aggiornamento", "Last updated"],
    ["Téléchargement", "Descarga", "Download", "Download", "Download"],
    ["Pas encore scrapé", "Aún sin recopilar", "Noch nicht erfasst", "Non ancora raccolto", "Not collected yet"],
    ["À venir", "Próximamente", "Demnächst", "In arrivo", "Coming soon"],
    ["Jamais", "Nunca", "Nie", "Mai", "Never"],
    ["Sélections nationales — Mondial 2026", "Selecciones nacionales — Mundial 2026", "Nationalmannschaften — WM 2026", "Nazionali — Mondiali 2026", "National teams — World Cup 2026"],
    ["Sélection", "Selección", "Nationalmannschaft", "Nazionale", "National team"],
    ["Amériques", "Américas", "Amerika", "Americhe", "Americas"],
    ["Asie/Océanie", "Asia/Oceanía", "Asien/Ozeanien", "Asia/Oceania", "Asia/Oceania"],
    ["Afrique", "África", "Afrika", "Africa", "Africa"],
    ["Europe", "Europa", "Europa", "Europa", "Europe"],
    ["championnats", "ligas", "Ligen", "campionati", "leagues"],
    ["joueurs", "jugadores", "Spieler", "giocatori", "players"],
    ["lignes career", "filas de carrera", "Karrierezeilen", "righe carriera", "career rows"],
    ["matchs", "partidos", "Spiele", "partite", "matches"],
    ["Page générée le", "Página generada el", "Seite erstellt am", "Pagina generata il", "Page generated on"],
    ["Code source", "Código fuente", "Quellcode", "Codice sorgente", "Source code"],
    ["Angleterre", "Inglaterra", "England", "Inghilterra", "England"],
    ["Écosse", "Escocia", "Schottland", "Scozia", "Scotland"],
    ["Irlande du Nord", "Irlanda del Norte", "Nordirland", "Irlanda del Nord", "Northern Ireland"],
    ["Pays de Galles", "Gales", "Wales", "Galles", "Wales"]
  ];
  const countryCodes = {
    "Canada": "CA", "Uruguay": "UY", "Égypte": "EG", "Émirats arabes unis": "AE",
    "Panama": "PA", "Costa Rica": "CR", "Jamaïque": "JM", "Tunisie": "TN",
    "Sénégal": "SN", "Côte d'Ivoire": "CI", "Nigeria": "NG", "Ghana": "GH",
    "Iran": "IR", "Qatar": "QA", "Ouzbékistan": "UZ", "Jordanie": "JO",
    "Nouvelle-Zélande": "NZ", "Bolivie": "BO", "Irak": "IQ"
  };
  const flags = JSON.parse(document.getElementById("country-flags").textContent);
  for (const [name, flag] of Object.entries(flags)) {
    const letters = Array.from(flag);
    if (letters.length === 2 && letters.every(c => c.codePointAt(0) >= 0x1F1E6 && c.codePointAt(0) <= 0x1F1FF)) {
      countryCodes[name] = letters.map(c => String.fromCharCode(c.codePointAt(0) - 0x1F1E6 + 65)).join("");
    }
  }
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const originals = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (node.textContent.trim() && !node.parentElement.closest("script,style,select,code")) {
      originals.push([node, node.textContent]);
    }
  }
  const originalTitle = document.title;
  const selector = document.getElementById("language");
  function setLanguage(lang) {
    if (!languages.includes(lang)) lang = "fr";
    const index = languages.indexOf(lang);
    const table = new Map(phrases.map(row => [row[0], row[index]]));
    const regions = new Intl.DisplayNames([lang], {type: "region"});
    for (const [name, code] of Object.entries(countryCodes)) table.set(name, lang === "fr" ? name : regions.of(code));
    const keys = [...table.keys()].sort((a, b) => b.length - a.length);
    const escape = text => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const pattern = new RegExp(keys.map(escape).join("|"), "g");
    function translate(text) {
      let result = text.replace(pattern, match => table.get(match));
      if (lang !== "fr") {
        result = result.replace(/(\d+) j\b/g, (_, n) => `${n} ${["j", "d", "T", "g", "d"][index]}`)
          .replace(/\bKo\b/g, "KB").replace(/\bMo\b/g, "MB").replace(/(\d+) o\b/g, "$1 B");
      }
      return result.replace(/\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC/g, stamp => {
        const date = new Date(stamp.replace(" ", "T").replace(" UTC", ":00Z"));
        return new Intl.DateTimeFormat(lang, {dateStyle: "short", timeStyle: "short", timeZone: "UTC"}).format(date) + " UTC";
      });
    }
    for (const [node, text] of originals) {
      // Keep official league names and the requested English bundle labels.
      if (node.parentElement.closest(".league-name") && !table.has(text.trim())) continue;
      node.textContent = translate(text);
    }
    document.title = translate(originalTitle);
    document.documentElement.lang = lang;
    selector.value = lang;
    try { localStorage.setItem("football-portal-language", lang); } catch (_) { /* storage may be disabled */ }
  }
  selector.addEventListener("change", () => setLanguage(selector.value));
  let saved = "fr";
  try { saved = localStorage.getItem("football-portal-language") || "fr"; } catch (_) {}
  setLanguage(saved);
})();
