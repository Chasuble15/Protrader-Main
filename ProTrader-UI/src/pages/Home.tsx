import { useEffect, useState } from "react";
import { makeUIWebSocket, sendCommand, loadAutoMode, saveAutoMode, loadTradeMode, saveTradeMode } from "../api";
import type { Item } from "../api";
import ResourcePicker from "../components/ResourcePicker";
import Card from "../components/Card";

const TOKEN = "change-me";

export default function Home() {
  const [agentConnected, setAgentConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [selected, setSelected] = useState<Item[]>([]);
  const [autoMode, setAutoMode] = useState(false);
  const [tradeMode, setTradeMode] = useState(false);

  // WebSocket pour suivre le statut de l’agent
  useEffect(() => {
    const ws = makeUIWebSocket("/ws/ui", {
      onMessage: (m: unknown) => {
        const data = m as { type?: string; connected?: boolean };
        if (data.type === "agent_status") {
          setAgentConnected(!!data.connected);
        }
        setLog((l) => [JSON.stringify(m), ...l].slice(0, 100));
      },
    });
    return () => ws.close();
  }, []);

  useEffect(() => {
    loadAutoMode().then((v) => setAutoMode(!!v)).catch(() => {});
    loadTradeMode().then((v) => setTradeMode(!!v)).catch(() => {});
  }, []);

  async function toggleAutoMode() {
    const v = !autoMode;
    setAutoMode(v);
    try { await saveAutoMode(v); } catch {}
  }

  async function toggleTradeMode() {
    const v = !tradeMode;
    setTradeMode(v);
    try { await saveTradeMode(v); } catch {}
  }

  function buildStartArgs(items: Item[]) {
    return {
      // Si l’ordre de la sélection est important, on l’encode explicitement
      item_ids: items.map((it) => it.id),
      items: items.map((it, idx) => ({
        id: it.id,
        name_fr: it.name_fr,
        slug_fr: it.slug_fr,
        level: it.level,
        order: idx, // pour préserver l’ordre côté agent
        img_blob: it.img_blob,
      })),
    };
  }

  async function onStartScript() {
    setBusy(true);
    try {
      const args = buildStartArgs(selected);
      await sendCommand("start_script", args, TOKEN);
      alert("🚀 Script démarré !");
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      alert("Erreur: " + message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* Carte statut agent */}
      <Card>
        <h2 className="text-base font-semibold mb-2">Statut de l'agent</h2>
        <p className="text-sm text-slate-600 flex items-center gap-2">
          Connexion :{" "}
          {agentConnected ? (
            <span className="text-emerald-700">✅ Connecté</span>
          ) : (
            <span className="text-red-600">❌ Déconnecté</span>
          )}
        </p>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoMode}
            onChange={toggleAutoMode}
            className="h-4 w-4"
          />
          <span>Mode auto</span>
        </label>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={tradeMode}
            onChange={toggleTradeMode}
            className="h-4 w-4"
          />
          <span>Mode achat/revente</span>
        </label>
      </Card>

      {/* Carte actions */}
      <Card className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold">Ressources</h2>
          <div className="text-sm text-slate-600">
            Sélection: <span className="font-medium">{selected.length}</span>
          </div>
        </div>

        <ResourcePicker
          limit={24}
          // Le composant appelle onChangeSelected:
          // - à chaque (dé)sélection
          // - à l’auto-reload au montage (depuis la DB)
          onChangeSelected={setSelected}
        />

        <div className="pt-2">
          <button
            onClick={onStartScript}
            disabled={busy || !agentConnected || selected.length === 0}
            className="px-4 py-2 rounded-md border border-blue-600 text-blue-700 hover:bg-blue-50 disabled:opacity-50"
            title={
              selected.length === 0
                ? "Sélection vide"
                : agentConnected
                ? "Prêt à démarrer"
                : "Agent déconnecté"
            }
          >
            ▶ Démarrer le script
          </button>
        </div>
      </Card>

      {/* Carte logs */}
      <Card>
        <h2 className="text-base font-semibold mb-2">Logs WebSocket</h2>
        <ul className="max-h-60 overflow-auto text-xs font-mono text-slate-700 space-y-1">
          {log.map((l, i) => (
            <li key={i} className="border-b border-slate-100 pb-1">
              {l}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

