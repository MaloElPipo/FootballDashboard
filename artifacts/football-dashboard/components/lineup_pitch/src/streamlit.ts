// Bridge minimal vers Streamlit Custom Components (sans dépendre de la lib
// `streamlit-component-lib` officielle qui n'est plus très maintenue côté JS).
// Implémente le protocole postMessage natif documenté ici :
// https://docs.streamlit.io/develop/concepts/custom-components/intro

export type StreamlitArgs = Record<string, unknown>;

export type RenderEvent = {
  args: StreamlitArgs;
  disabled: boolean;
  theme?: Record<string, string>;
};

type RenderListener = (e: RenderEvent) => void;

const listeners = new Set<RenderListener>();
let lastArgs: StreamlitArgs = {};
let lastDisabled = false;
let lastTheme: Record<string, string> | undefined;

window.addEventListener("message", (event: MessageEvent) => {
  const data = event.data;
  if (!data || typeof data !== "object") return;
  if (data.type !== "streamlit:render") return;
  lastArgs = (data.args || {}) as StreamlitArgs;
  lastDisabled = Boolean(data.disabled);
  lastTheme = data.theme as Record<string, string> | undefined;
  listeners.forEach((fn) =>
    fn({ args: lastArgs, disabled: lastDisabled, theme: lastTheme }),
  );
});

export const Streamlit = {
  /** À appeler une seule fois au mount du composant racine. */
  setComponentReady(): void {
    window.parent.postMessage(
      { type: "streamlit:componentReady", apiVersion: 1 },
      "*",
    );
  },

  /** Indique à Streamlit la hauteur de l'iframe (auto-resize). */
  setFrameHeight(height?: number): void {
    const h =
      height ?? Math.ceil(document.body.getBoundingClientRect().height) + 4;
    window.parent.postMessage(
      { type: "streamlit:setFrameHeight", height: h },
      "*",
    );
  },

  /** Renvoie une valeur à Python (récupérée via le `return value` du component). */
  setComponentValue(value: unknown): void {
    window.parent.postMessage(
      {
        type: "streamlit:setComponentValue",
        value: value,
        dataType: "json",
      },
      "*",
    );
  },

  /** S'abonner aux re-renders (Python a appelé render avec de nouveaux args). */
  events: {
    addEventListener(_type: "render", fn: RenderListener): void {
      listeners.add(fn);
      // Replay du dernier render reçu (utile si on s'abonne après le premier message).
      if (Object.keys(lastArgs).length > 0) {
        fn({ args: lastArgs, disabled: lastDisabled, theme: lastTheme });
      }
    },
    removeEventListener(_type: "render", fn: RenderListener): void {
      listeners.delete(fn);
    },
  },
};
