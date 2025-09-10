import { useEffect, useRef, useState } from "react";
import {
  makeUIWebSocket,
  cmdGetConfig,
  cmdValidateConfig,
  cmdSetConfig,
  cmdPatchConfig,
  cmdScreenshot,
  sendCommand, // pour save_template (optionnel)
} from "../api";
import * as YAML from "js-yaml";

/** Types alignés sur ton YAML */
type ClickPoint = { x: number; y: number; jitter?: number };
type Rect = [number, number, number, number];

type ConfigShape = {
  base_dir?: string;
  click_points?: Record<string, ClickPoint>;
  ocr_zones?: Record<string, Rect>;
  templates?: Record<string, string>;
  settings?: {
    monitor_index?: number;
    default_threshold?: number;
    thresholds?: Record<string, number>;
  };
};

type WSMsg =
  | { type: "config"; ts: number; data: { content: string }; meta?: any }
  | { type: "config_saved"; ts: number; data: { ok: boolean; patched?: boolean }; meta?: any }
  | { type: "config_valid"; ts: number; data: { ok: boolean; error?: string }; meta?: any }
  | { type: "config_error"; ts: number; error: string; meta?: any }
  | { type: "screenshot"; ts: number; data: { data_url: string }; meta?: any }
  | { type: "agent_status"; connected: boolean }
  | Record<string, any>;

const TOKEN = "change-me"; // adapte si besoin

export default function ConfigEditor() {
  const [yamlText, setYamlText] = useState<string>("");
  const [conf, setConf] = useState<ConfigShape>({});
  const [agentConnected, setAgentConnected] = useState(false);
  const [pathInfo, setPathInfo] = useState<string>("");
  const [valid, setValid] = useState<null | boolean>(null);
  const [validError, setValidError] = useState<string>("");

  // UI
  const [tab, setTab] = useState<"yaml" | "forms">("forms");
  const [busy, setBusy] = useState(false);
  const [log, setLog] = useState<string[]>([]);

  // --- Screenshot picker state (points) ---
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerImg, setPickerImg] = useState<string>("");
  const [pickerForPoint, setPickerForPoint] = useState<string | null>(null);
  const [pendingPatchAfterPick, setPendingPatchAfterPick] = useState<boolean>(true);

  // --- Cropper state (templates) ---
  const [cropperOpen, setCropperOpen] = useState(false);
  const [cropImg, setCropImg] = useState<string>("");
  const [cropForTemplate, setCropForTemplate] = useState<string | null>(null);
  const [cropResult, setCropResult] = useState<string>(""); // dataURL PNG
  const [autoPatchTemplate, setAutoPatchTemplate] = useState<boolean>(true);
  const [suggestedFilename, setSuggestedFilename] = useState<string>("");

  // --- OCR zone picker state ---
  const [ocrPickerOpen, setOcrPickerOpen] = useState(false);
  const [ocrImg, setOcrImg] = useState<string>("");
  const [ocrForZone, setOcrForZone] = useState<string | null>(null);
  const [autoPatchOcr, setAutoPatchOcr] = useState<boolean>(true);

  // WebSocket UI
  useEffect(() => {
    const ws = makeUIWebSocket("/ws/ui", {
      onOpen: () => console.log("[ui] ws open"),
      onMessage: (m: WSMsg) => {
        setLog((l) => [JSON.stringify(m), ...l].slice(0, 200));

        if (m.type === "agent_status") {
          setAgentConnected(!!(m as any).connected);
        } else if (m.type === "config") {
          const content = (m as any).data?.content ?? "";
          setYamlText(content);
          setPathInfo((m as any).meta?.path ?? "");
          setValid(null);
          setValidError("");
          safeLoadToState(content);
        } else if (m.type === "config_saved") {
          alert("✅ Config enregistrée");
        } else if (m.type === "config_valid") {
          const ok = (m as any).data?.ok;
          setValid(ok);
          setValidError((m as any).data?.error ?? "");
        } else if (m.type === "config_error") {
          alert("❌ " + (m as any).error);
        } else if (m.type === "screenshot") {
          const dataUrl = (m as any).data?.data_url;
          if (typeof dataUrl === "string") {
            if (pickerForPoint) {
              setPickerImg(dataUrl);
              setPickerOpen(true);
            }
            if (cropForTemplate) {
              setCropImg(dataUrl);
              setCropperOpen(true);
              setCropResult("");
            }
            if (ocrForZone) {
              setOcrImg(dataUrl);
              setOcrPickerOpen(true);
            }
          }
        }
      },
    });
    return () => ws.close();
  }, [pickerForPoint, cropForTemplate, ocrForZone]);

  // Helpers YAML <-> state
  function safeLoadToState(text: string) {
    try {
      const obj = (YAML.load(text) as ConfigShape) || {};
      setConf(normalizeConfig(obj));
    } catch (e) {
      console.warn("YAML parse error (forms not updated):", e);
    }
  }

  function emitYamlFromState(next: ConfigShape) {
    try {
      const y = YAML.dump(next, { lineWidth: 120, noRefs: true, sortKeys: false });
      setYamlText(y);
    } catch (e) {
      console.warn("YAML dump error:", e);
    }
  }

  function normalizeConfig(c: ConfigShape): ConfigShape {
    return {
      base_dir: c.base_dir ?? "./assets",
      click_points: c.click_points ?? {},
      ocr_zones: c.ocr_zones ?? {},
      templates: c.templates ?? {},
      settings: {
        monitor_index: c.settings?.monitor_index ?? 1,
        default_threshold: c.settings?.default_threshold ?? 0.88,
        thresholds: c.settings?.thresholds ?? {},
      },
    };
  }

  async function onDefineOcrZone(name: string) {
    setOcrForZone(name);
    setOcrImg("");
    setOcrPickerOpen(false);
    try {
      setBusy(true);
      await cmdScreenshot(TOKEN, { monitor: conf.settings?.monitor_index || 1, format: "PNG" });
    } catch (e: any) {
      alert("Erreur screenshot: " + e.message);
      setOcrForZone(null);
    } finally {
      setBusy(false);
    }
  }

  function onOcrRectChosen(rect: Rect) {
    if (!ocrForZone) return;
    const next = {
      ...conf,
      ocr_zones: { ...(conf.ocr_zones || {}), [ocrForZone]: rect },
    };
    setConf(next);
    emitYamlFromState(next);
    if (autoPatchOcr) {
      patchOcrZone(ocrForZone, rect);
    }
    setOcrPickerOpen(false);
    setOcrForZone(null);
    setOcrImg("");
  }

  // Actions backend
  async function onLoad() {
    setBusy(true);
    try {
      await cmdGetConfig(TOKEN);
    } finally {
      setBusy(false);
    }
  }
  async function onValidate() {
    setBusy(true);
    try {
      await cmdValidateConfig(yamlText, TOKEN);
    } finally {
      setBusy(false);
    }
  }
  async function onSave() {
    setBusy(true);
    try {
      await cmdValidateConfig(yamlText, TOKEN);
      setTimeout(async () => {
        if (valid === false) {
          alert("❌ Config invalide. Corrige avant d'enregistrer.");
          setBusy(false);
          return;
        }
        await cmdSetConfig(yamlText, TOKEN);
        setBusy(false);
      }, 150);
    } catch {
      setBusy(false);
    }
  }

  // Patches ciblés (agent)
  async function patchClickPoint(name: string, point: ClickPoint) {
    setBusy(true);
    try {
      await cmdPatchConfig({ click_points: { [name]: point } }, TOKEN);
      const next = {
        ...conf,
        click_points: { ...(conf.click_points || {}), [name]: point },
      };
      setConf(next);
      emitYamlFromState(next);
    } finally {
      setBusy(false);
    }
  }
  async function patchOcrZone(name: string, rect: Rect) {
    setBusy(true);
    try {
      await cmdPatchConfig({ ocr_zones: { [name]: rect } }, TOKEN);
      const next = {
        ...conf,
        ocr_zones: { ...(conf.ocr_zones || {}), [name]: rect },
      };
      setConf(next);
      emitYamlFromState(next);
    } finally {
      setBusy(false);
    }
  }
  async function patchTemplate(name: string, path: string) {
    setBusy(true);
    try {
      await cmdPatchConfig({ templates: { [name]: path } }, TOKEN);
      const next = {
        ...conf,
        templates: { ...(conf.templates || {}), [name]: path },
      };
      setConf(next);
      emitYamlFromState(next);
    } finally {
      setBusy(false);
    }
  }

  // Form helpers
  function updateClickPoint(name: string, field: keyof ClickPoint, val: number) {
    const cp = { ...(conf.click_points?.[name] || { x: 0, y: 0, jitter: 5 }), [field]: val };
    const next = { ...conf, click_points: { ...(conf.click_points || {}), [name]: cp } };
    setConf(next);
    emitYamlFromState(next);
  }
  function removeClickPoint(name: string) {
    const { [name]: _, ...rest } = conf.click_points || {};
    const next = { ...conf, click_points: rest };
    setConf(next);
    emitYamlFromState(next);
  }
  function updateOcrZone(name: string, idx: number, val: number) {
    const oz = ([...(conf.ocr_zones?.[name] || [0, 0, 0, 0])] as Rect);
    oz[idx] = val as never;
    const next = { ...conf, ocr_zones: { ...(conf.ocr_zones || {}), [name]: oz } };
    setConf(next);
    emitYamlFromState(next);
  }
  function removeOcrZone(name: string) {
    const { [name]: _, ...rest } = conf.ocr_zones || {};
    const next = { ...conf, ocr_zones: rest };
    setConf(next);
    emitYamlFromState(next);
  }
  function updateTemplate(name: string, path: string) {
    const next = { ...conf, templates: { ...(conf.templates || {}), [name]: path } };
    setConf(next);
    emitYamlFromState(next);
  }
  function removeTemplate(name: string) {
    const { [name]: _, ...rest } = conf.templates || {};
    const next = { ...conf, templates: rest };
    setConf(next);
    emitYamlFromState(next);
  }

  // Ajout avec nom saisi
  function sanitizeKeyName(raw: string) {
    return raw.trim().replace(/\s+/g, "_").replace(/[^a-zA-Z0-9_\-]/g, "");
  }
  function ensureUniqueKey(base: string, exists: (k: string) => boolean) {
    let name = base || "unnamed";
    if (!exists(name)) return name;
    let i = 2;
    while (exists(`${name}_${i}`)) i++;
    return `${name}_${i}`;
  }
  function addClickPoint() {
    const raw = window.prompt("Nom du point de clic (clé YAML) :", "point");
    if (raw == null) return;
    const wanted = sanitizeKeyName(raw);
    if (!wanted) return alert("Nom invalide.");
    const exists = (k: string) => !!conf.click_points?.[k];
    const name = ensureUniqueKey(wanted, exists);
    const next = {
      ...conf,
      click_points: { ...(conf.click_points || {}), [name]: { x: 0, y: 0, jitter: 5 } },
    };
    setConf(next);
    emitYamlFromState(next);
  }
  function addOcrZone() {
    const raw = window.prompt("Nom de la zone OCR (clé YAML) :", "zone");
    if (raw == null) return;
    const wanted = sanitizeKeyName(raw);
    if (!wanted) return alert("Nom invalide.");
    const exists = (k: string) => !!conf.ocr_zones?.[k];
    const name = ensureUniqueKey(wanted, exists);
    const next = {
      ...conf,
      ocr_zones: { ...(conf.ocr_zones || {}), [name]: [0, 0, 0, 0] as Rect },
    };
    setConf(next);
    emitYamlFromState(next);
  }
  function addTemplate() {
    const raw = window.prompt("Nom du template (clé YAML) :", "tpl");
    if (raw == null) return;
    const wanted = sanitizeKeyName(raw);
    if (!wanted) return alert("Nom invalide.");
    const exists = (k: string) => !!conf.templates?.[k];
    const name = ensureUniqueKey(wanted, exists);
    const next = {
      ...conf,
      templates: { ...(conf.templates || {}), [name]: "" },
    };
    setConf(next);
    emitYamlFromState(next);
  }

  // ---- Screenshot picking (points) ----
  async function onPickCoordsForPoint(name: string) {
    setPickerForPoint(name);
    setPickerImg("");
    setPickerOpen(false);
    try {
      setBusy(true);
      await cmdScreenshot(TOKEN, { monitor: conf.settings?.monitor_index || 1, format: "PNG" });
    } catch (e: any) {
      alert("Erreur screenshot: " + e.message);
      setPickerForPoint(null);
    } finally {
      setBusy(false);
    }
  }
  function onCoordsPicked(x: number, y: number) {
    if (!pickerForPoint) return;
    const prev = conf.click_points?.[pickerForPoint] || { x: 0, y: 0, jitter: 5 };
    const next = {
      ...conf,
      click_points: {
        ...(conf.click_points || {}),
        [pickerForPoint]: { ...prev, x, y },
      },
    };
    setConf(next);
    emitYamlFromState(next);
    if (pendingPatchAfterPick) {
      patchClickPoint(pickerForPoint, { ...prev, x, y });
    }
    setPickerOpen(false);
    setPickerForPoint(null);
    setPickerImg("");
  }

  // ---- Screenshot & crop (templates) ----
  async function onCaptureTemplate(name: string) {
    setCropForTemplate(name);
    setCropImg("");
    setCropperOpen(false);
    setCropResult("");
    setSuggestedFilename(`${name}.png`);
    try {
      setBusy(true);
      await cmdScreenshot(TOKEN, { monitor: conf.settings?.monitor_index || 1, format: "PNG" });
    } catch (e: any) {
      alert("Erreur screenshot: " + e.message);
      setCropForTemplate(null);
    } finally {
      setBusy(false);
    }
  }
  function onTemplateCropped(dataUrl: string) {
    if (!cropForTemplate) return;
    setCropResult(dataUrl);
    const name = cropForTemplate;
    const path = conf.templates?.[name] || `${name}.png`;
    const next = { ...conf, templates: { ...(conf.templates || {}), [name]: path } };
    setConf(next);
    emitYamlFromState(next);

    if (autoPatchTemplate) {
      sendCommand(
        "save_template",
        {
          name,
          filename: path,
          data_url: dataUrl,
          base_dir: conf.base_dir || "./assets",
        },
        TOKEN
      ).catch(() => {});
    }
  }

  function downloadDataUrl(filename: string, dataUrl: string) {
    const a = document.createElement("a");
    a.href = dataUrl;
    a.download = filename || "crop.png";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  return (
    <section className="card p-4 mt-4">
      {/* Header */}
      <header className="flex items-center gap-3 mb-3">
        <h2 className="m-0 text-xl font-semibold">Éditeur de configuration</h2>

        <span className="text-sm">
          {agentConnected ? (
            <span className="chip chip-ok">✅ connecté</span>
          ) : (
            <span className="chip chip-fail">❌ déconnecté</span>
          )}
        </span>

        <span className="text-gray-500 truncate">{pathInfo}</span>

        <div className="ml-auto toolbar">
          <button onClick={onLoad} disabled={busy} className="btn btn-primary">
            ⬇ Charger
          </button>
          <button onClick={onValidate} disabled={busy} className="btn btn-secondary">
            ✅ Valider
          </button>
          <button onClick={onSave} disabled={busy} className="btn btn-accent">
            💾 Enregistrer
          </button>
        </div>
      </header>

      {/* Tabs */}
      <nav className="flex items-center gap-2 mb-3">
        <button
          onClick={() => setTab("forms")}
          disabled={tab === "forms"}
          className={`tab ${tab === "forms" ? "tab-active" : ""}`}
        >
          Formulaires
        </button>
        <button
          onClick={() => setTab("yaml")}
          disabled={tab === "yaml"}
          className={`tab ${tab === "yaml" ? "tab-active" : ""}`}
        >
          YAML brut
        </button>

        <span className="ml-auto text-sm">
          {valid === null ? "" : valid ? (
            <span className="chip chip-ok">✔ Valide</span>
          ) : (
            <span className="chip chip-fail">✖ Invalide</span>
          )}
          {valid === false && validError ? (
            <span className="ml-2 text-red-700">{validError}</span>
          ) : null}
        </span>
      </nav>

      {/* Body */}
      {tab === "yaml" ? (
        <textarea
          value={yamlText}
          onChange={(e) => {
            setYamlText(e.target.value);
            safeLoadToState(e.target.value);
          }}
          spellCheck={false}
          className="w-full h-[460px] font-mono text-[14px] leading-tight whitespace-pre border rounded-lg p-3 outline-none focus:ring-2 focus:ring-blue-500 bg-white shadow-sm"
          placeholder="# Colle/édite ton YAML ici…"
        />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          {/* CLICK POINTS */}
          <div className="card-section">
            <h3 className="mt-0 text-lg font-medium">Points de clic</h3>
            <button onClick={addClickPoint} className="mb-2 btn btn-outline">+ Ajouter un point</button>
            <div className="flex flex-col gap-2">
              {Object.entries(conf.click_points || {}).map(([name, cp]) => (
                <div key={name} className="border rounded-md p-2 bg-white shadow-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="min-w-[120px]">{name}</strong>
                    <label className="flex items-center gap-1">
                      x
                      <input
                        type="number"
                        value={cp.x ?? 0}
                        onChange={(e) => updateClickPoint(name, "x", Number(e.target.value))}
                        className="input w-20"
                      />
                    </label>
                    <label className="flex items-center gap-1">
                      y
                      <input
                        type="number"
                        value={cp.y ?? 0}
                        onChange={(e) => updateClickPoint(name, "y", Number(e.target.value))}
                        className="input w-20"
                      />
                    </label>
                    <label className="flex items-center gap-1">
                      jitter
                      <input
                        type="number"
                        value={cp.jitter ?? 5}
                        onChange={(e) => updateClickPoint(name, "jitter", Number(e.target.value))}
                        className="input w-20"
                      />
                    </label>
                    <button
                      onClick={() => patchClickPoint(name, { x: cp.x || 0, y: cp.y || 0, jitter: cp.jitter })}
                      title="Patch côté agent"
                      className="btn btn-secondary"
                    >
                      ↗ Patch
                    </button>
                    <button
                      onClick={() => onPickCoordsForPoint(name)}
                      title="Choisir les coordonnées depuis un screenshot"
                      className="btn btn-primary"
                    >
                      🎯 Choisir sur screenshot
                    </button>
                    <button
                      onClick={() => removeClickPoint(name)}
                      title="Supprimer localement"
                      className="btn btn-danger"
                    >
                      🗑
                    </button>
                  </div>
                </div>
              ))}
              {Object.keys(conf.click_points || {}).length === 0 && <em className="text-gray-500">Aucun point.</em>}
            </div>
          </div>

          {/* OCR ZONES */}
          <div className="card-section">
            <h3 className="mt-0 text-lg font-medium">Zones OCR</h3>
            <button onClick={addOcrZone} className="mb-2 btn btn-outline">+ Ajouter une zone</button>
            <div className="flex flex-col gap-2">
              {Object.entries(conf.ocr_zones || {}).map(([name, rect]) => (
                <div key={name} className="border rounded-md p-2 bg-white shadow-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="min-w-[140px]">{name}</strong>
                    <label className="flex items-center gap-1">
                      left
                      <input
                        type="number"
                        value={rect?.[0] ?? 0}
                        onChange={(e) => updateOcrZone(name, 0, Number(e.target.value))}
                        className="input w-20"
                      />
                    </label>
                    <label className="flex items-center gap-1">
                      top
                      <input
                        type="number"
                        value={rect?.[1] ?? 0}
                        onChange={(e) => updateOcrZone(name, 1, Number(e.target.value))}
                        className="input w-20"
                      />
                    </label>
                    <label className="flex items-center gap-1">
                      width
                      <input
                        type="number"
                        value={rect?.[2] ?? 0}
                        onChange={(e) => updateOcrZone(name, 2, Number(e.target.value))}
                        className="input w-20"
                      />
                    </label>
                    <label className="flex items-center gap-1">
                      height
                      <input
                        type="number"
                        value={rect?.[3] ?? 0}
                        onChange={(e) => updateOcrZone(name, 3, Number(e.target.value))}
                        className="input w-20"
                      />
                    </label>
                    <button
                      onClick={() =>
                        patchOcrZone(name, [
                          Number(conf.ocr_zones?.[name]?.[0] ?? 0),
                          Number(conf.ocr_zones?.[name]?.[1] ?? 0),
                          Number(conf.ocr_zones?.[name]?.[2] ?? 0),
                          Number(conf.ocr_zones?.[name]?.[3] ?? 0),
                        ])
                      }
                      title="Patch côté agent"
                      className="btn btn-secondary"
                    >
                      ↗ Patch
                    </button>
                    <button
                      onClick={() => onDefineOcrZone(name)}
                      title="Dessiner la zone sur un screenshot"
                      className="btn btn-primary"
                    >
                      📐 Définir via screenshot
                    </button>
                    <button
                      onClick={() => removeOcrZone(name)}
                      title="Supprimer localement"
                      className="btn btn-danger"
                    >
                      🗑
                    </button>
                  </div>
                </div>
              ))}
              {Object.keys(conf.ocr_zones || {}).length === 0 && <em className="text-gray-500">Aucune zone.</em>}
            </div>
          </div>

          {/* TEMPLATES */}
          <div className="card-section">
            <h3 className="mt-0 text-lg font-medium">Templates (détection images)</h3>
            <button onClick={addTemplate} className="mb-2 btn btn-outline">+ Ajouter un template</button>
            <div className="flex flex-col gap-2">
              {Object.entries(conf.templates || {}).map(([name, path]) => (
                <div key={name} className="border rounded-md p-2 bg-white shadow-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <strong className="min-w-[140px]">{name}</strong>
                    <input
                      type="text"
                      value={path ?? ""}
                      onChange={(e) => updateTemplate(name, e.target.value)}
                      placeholder="btn_login.png"
                      className="input flex-1 min-w-[160px]"
                    />
                    <button
                      onClick={() => onCaptureTemplate(name)}
                      title="Capturer une zone depuis screenshot"
                      className="btn btn-primary"
                    >
                      🖼️ Depuis screenshot
                    </button>
                    <button
                      onClick={() => patchTemplate(name, conf.templates?.[name] ?? "")}
                      title="Patch côté agent"
                      className="btn btn-secondary"
                    >
                      ↗ Patch
                    </button>
                    <button
                      onClick={() => removeTemplate(name)}
                      title="Supprimer localement"
                      className="btn btn-danger"
                    >
                      🗑
                    </button>
                  </div>
                </div>
              ))}
              {Object.keys(conf.templates || {}).length === 0 && <em className="text-gray-500">Aucun template.</em>}
            </div>

            <hr className="my-3" />
            <h4 className="font-medium">Paramètres</h4>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2">
                <span>monitor_index</span>
                <input
                  type="number"
                  value={conf.settings?.monitor_index ?? 1}
                  onChange={(e) => {
                    const next = {
                      ...conf,
                      settings: {
                        ...(conf.settings || {}),
                        monitor_index: Number(e.target.value),
                      },
                    };
                    setConf(next);
                    emitYamlFromState(next);
                  }}
                  className="input w-20"
                />
              </label>

              <label className="flex items-center gap-2">
                <span>default_threshold</span>
                <input
                  type="number"
                  step={0.01}
                  min={0}
                  max={1}
                  value={conf.settings?.default_threshold ?? 0.88}
                  onChange={(e) => {
                    const next = {
                      ...conf,
                      settings: {
                        ...(conf.settings || {}),
                        default_threshold: Number(e.target.value),
                      },
                    };
                    setConf(next);
                    emitYamlFromState(next);
                  }}
                  className="input w-24"
                />
              </label>
            </div>

            <div className="mt-2">
              <h5 className="text-sm font-medium">Seuils par template</h5>
              {Object.entries(conf.settings?.thresholds || {}).map(([k, v]) => (
                <div key={k} className="flex items-center gap-2 mb-1">
                  <code className="min-w-[140px]">{k}</code>
                  <input
                    type="number"
                    step={0.01}
                    min={0}
                    max={1}
                    value={v ?? 0}
                    onChange={(e) => {
                      const next = {
                        ...conf,
                        settings: {
                          ...(conf.settings || {}),
                          thresholds: { ...(conf.settings?.thresholds || {}), [k]: Number(e.target.value) },
                        },
                      };
                      setConf(next);
                      emitYamlFromState(next);
                    }}
                    className="input w-24"
                  />
                </div>
              ))}
              <AddThresholdForm
                onAdd={(name, thr) => {
                  const next = {
                    ...conf,
                    settings: {
                      ...(conf.settings || {}),
                      thresholds: { ...(conf.settings?.thresholds || {}), [name]: thr },
                    },
                  };
                  setConf(next);
                  emitYamlFromState(next);
                }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Logs */}
      <details className="mt-3">
        <summary className="cursor-pointer text-sm text-gray-700">Journal des messages WS</summary>
        <ul className="max-h-60 overflow-auto m-0 p-0 list-none">
          {log.map((l, i) => (
            <li key={i} className="border-b py-1">
              <code className="text-xs break-all">{l}</code>
            </li>
          ))}
        </ul>
      </details>

      {/* Modals */}
      {pickerOpen && pickerImg && pickerForPoint && (
        <ScreenshotPicker
          img={pickerImg}
          pointName={pickerForPoint}
          autoPatch={pendingPatchAfterPick}
          onToggleAutoPatch={() => setPendingPatchAfterPick((v) => !v)}
          onClose={() => {
            setPickerOpen(false);
            setPickerForPoint(null);
            setPickerImg("");
          }}
          onPicked={(x, y) => onCoordsPicked(x, y)}
        />
      )}

      {cropperOpen && cropImg && cropForTemplate && (
        <CropperModal
          img={cropImg}
          templateName={cropForTemplate}
          suggestedFilename={suggestedFilename}
          dataUrl={cropResult}
          autoPatch={autoPatchTemplate}
          onToggleAutoPatch={() => setAutoPatchTemplate((v) => !v)}
          onClose={() => {
            setCropperOpen(false);
            setCropForTemplate(null);
            setCropImg("");
            setCropResult("");
          }}
            onCropped={(dataUrl) => onTemplateCropped(dataUrl)}
          onDownload={() => {
            const fn = suggestedFilename || `${cropForTemplate}.png`;
            if (cropResult) downloadDataUrl(fn, cropResult);
          }}
        />
      )}

      {ocrPickerOpen && ocrImg && ocrForZone && (
        <OCRZonePickerModal
          img={ocrImg}
          zoneName={ocrForZone}
          autoPatch={autoPatchOcr}
          onToggleAutoPatch={() => setAutoPatchOcr((v) => !v)}
          onClose={() => {
            setOcrPickerOpen(false);
            setOcrForZone(null);
            setOcrImg("");
          }}
          onConfirm={(rect) => onOcrRectChosen(rect)}
        />
      )}
    </section>
  );
}

/* -----------------------
   Form: seuils
------------------------ */
function AddThresholdForm({ onAdd }: { onAdd: (name: string, thr: number) => void }) {
  const [name, setName] = useState("");
  const [thr, setThr] = useState(0.9);
  return (
    <div className="flex items-center gap-2 mt-2">
      <input
        type="text"
        placeholder="template_name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        className="input w-44"
      />
      <input
        type="number"
        step={0.01}
        min={0}
        max={1}
        value={thr}
        onChange={(e) => setThr(Number(e.target.value))}
        className="input w-24"
      />
      <button
        onClick={() => {
          if (!name.trim()) return;
          onAdd(name.trim(), thr);
          setName("");
          setThr(0.9);
        }}
        className="btn btn-outline"
      >
        + Ajouter seuil
      </button>
    </div>
  );
}

/* -----------------------
   Modal: pick coordonnées
------------------------ */
function ScreenshotPicker(props: {
  img: string;
  pointName: string;
  autoPatch: boolean;
  onToggleAutoPatch: () => void;
  onClose: () => void;
  onPicked: (x: number, y: number) => void;
}) {
  const { img, pointName, autoPatch, onToggleAutoPatch, onClose, onPicked } = props;
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [hoverXY, setHoverXY] = useState<{ x: number; y: number } | null>(null);

  function handleClick(e: React.MouseEvent<HTMLImageElement>) {
    const el = imgRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const dispX = e.clientX - rect.left;
    const dispY = e.clientY - rect.top;

    const natW = el.naturalWidth;
    const natH = el.naturalHeight;
    const scaleX = natW / rect.width;
    const scaleY = natH / rect.height;

    const x = Math.round(dispX * scaleX);
    const y = Math.round(dispY * scaleY);
    onPicked(x, y);
  }

  function handleMouseMove(e: React.MouseEvent<HTMLImageElement>) {
    const el = imgRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const dispX = e.clientX - rect.left;
    const dispY = e.clientY - rect.top;

    const natW = el.naturalWidth;
    const natH = el.naturalHeight;
    const scaleX = natW / rect.width;
    const scaleY = natH / rect.height;

    const x = Math.max(0, Math.min(natW, Math.round(dispX * scaleX)));
    const y = Math.max(0, Math.min(natH, Math.round(dispY * scaleY)));
    setHoverXY({ x, y });
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-[9999] flex flex-col">
      <div className="flex items-center gap-3 px-3 py-2 bg-neutral-900 text-white shadow">
        <strong>Choix des coordonnées — {pointName}</strong>
        <span className="text-neutral-300">
          {hoverXY ? `x=${hoverXY.x}, y=${hoverXY.y}` : "Clique sur l'image pour choisir"}
        </span>
        <label className="ml-auto flex items-center gap-2">
          <input type="checkbox" checked={autoPatch} onChange={onToggleAutoPatch} />
          Patch auto après choix
        </label>
        <button onClick={onClose} className="btn btn-danger">Fermer</button>
      </div>

      <div className="flex-1 overflow-auto p-4 flex justify-center items-start">
        <img
          ref={imgRef}
          src={img}
          alt="screenshot"
          onClick={handleClick}
          onMouseMove={handleMouseMove}
          className="max-w-[98%] max-h-[calc(100vh-120px)] cursor-crosshair block shadow-[0_0_0_1px_#333]"
        />
      </div>
    </div>
  );
}

/* -----------------------
   Modal: crop rectangle
------------------------ */
function CropperModal(props: {
  img: string;
  templateName: string;
  suggestedFilename: string;
  dataUrl: string; // résultat si déjà recadré
  autoPatch: boolean;
  onToggleAutoPatch: () => void;
  onClose: () => void;
  onCropped: (dataUrl: string, naturalRect: { x: number; y: number; w: number; h: number }) => void;
  onDownload: () => void;
}) {
  const { img, templateName, suggestedFilename, dataUrl, autoPatch, onToggleAutoPatch, onClose, onCropped, onDownload } = props;

  const imgRef = useRef<HTMLImageElement | null>(null);

  // Sélection DISPLAY (écran)
  const [dragging, setDragging] = useState(false);
  const [startD, setStartD] = useState<{ x: number; y: number } | null>(null);
  const [endD, setEndD] = useState<{ x: number; y: number } | null>(null);
  const [hoverD, setHoverD] = useState<{ x: number; y: number } | null>(null);

  function toDisplayCoords(clientX: number, clientY: number) {
    const el = imgRef.current;
    if (!el) return { x: 0, y: 0, inside: false };

    const rect = el.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const inside = x >= 0 && y >= 0 && x <= rect.width && y <= rect.height;

    const cx = Math.max(0, Math.min(rect.width, x));
    const cy = Math.max(0, Math.min(rect.height, y));
    return { x: cx, y: cy, inside };
  }

  function onMouseDown(e: React.MouseEvent) {
    const { x, y, inside } = toDisplayCoords(e.clientX, e.clientY);
    if (!inside) return;
    setDragging(true);
    setStartD({ x, y });
    setEndD({ x, y });
  }
  function onMouseMove(e: React.MouseEvent) {
    const d = toDisplayCoords(e.clientX, e.clientY);
    setHoverD({ x: d.x, y: d.y });
    if (dragging) setEndD({ x: d.x, y: d.y });
  }
  function onMouseUp() {
    setDragging(false);
  }

  function currentRectDisplay() {
    if (!startD || !endD) return null;
    const x1 = Math.min(startD.x, endD.x);
    const y1 = Math.min(startD.y, endD.y);
    const x2 = Math.max(startD.x, endD.x);
    const y2 = Math.max(startD.y, endD.y);
    const w = Math.max(1, Math.round(x2 - x1));
    const h = Math.max(1, Math.round(y2 - y1));
    return { x: Math.round(x1), y: Math.round(y1), w, h };
  }

  function displayToNativeRect(disp: { x: number; y: number; w: number; h: number }) {
    const el = imgRef.current!;
    const box = el.getBoundingClientRect();
    const natW = el.naturalWidth;
    const natH = el.naturalHeight;

    const scaleX = natW / box.width;
    const scaleY = natH / box.height;

    const nx = Math.max(0, Math.min(natW, Math.round(disp.x * scaleX)));
    const ny = Math.max(0, Math.min(natH, Math.round(disp.y * scaleY)));
    const nw = Math.max(1, Math.min(natW - nx, Math.round(disp.w * scaleX)));
    const nh = Math.max(1, Math.min(natH - ny, Math.round(disp.h * scaleY)));
    return { x: nx, y: ny, w: nw, h: nh };
  }

  async function doCrop() {
    const el = imgRef.current;
    const disp = currentRectDisplay();
    if (!el || !disp) return;

    const rect = displayToNativeRect(disp);

    const tmp = document.createElement("canvas");
    tmp.width = rect.w;
    tmp.height = rect.h;
    const ctx = tmp.getContext("2d");
    if (!ctx) return;

    await new Promise<void>((resolve) => {
      if (el.complete) return resolve();
      el.onload = () => resolve();
    });

    ctx.imageSmoothingEnabled = false;
    ctx.drawImage(el, rect.x, rect.y, rect.w, rect.h, 0, 0, rect.w, rect.h);
    const out = tmp.toDataURL("image/png");
    onCropped(out, rect);
  }

  function selectionStyle() {
    const el = imgRef.current;
    if (!el) return { display: "none" } as React.CSSProperties;
    const disp = currentRectDisplay();
    if (!disp) return { display: "none" } as React.CSSProperties;

    const box = el.getBoundingClientRect();
    const left = box.left + disp.x;
    const top = box.top + disp.y;
    const width = disp.w;
    const height = disp.h;

    return {
      position: "fixed" as const,
      left,
      top,
      width,
      height,
      border: "2px solid #60a5fa",
      boxShadow: "0 0 0 9999px rgba(0,0,0,0.35)",
      pointerEvents: "none" as const,
      zIndex: 10001,
    };
  }

  useEffect(() => {
    const el = imgRef.current;
    if (!el) return;
    const handler = (ev: Event) => ev.preventDefault();
    el.addEventListener("dragstart", handler);
    return () => el.removeEventListener("dragstart", handler);
  }, []);

  return (
    <div className="fixed inset-0 bg-black/70 z-[9999] flex flex-col select-none">
      <div className="flex items-center gap-3 px-3 py-2 bg-neutral-900 text-white shadow">
        <strong>Recadrer un template — {templateName}</strong>
        <span className="text-neutral-300">
          {hoverD ? `x=${Math.round(hoverD.x)}, y=${Math.round(hoverD.y)}` : "Glisse pour dessiner un rectangle"}
        </span>
        <label className="ml-auto flex items-center gap-2">
          <input type="checkbox" checked={autoPatch} onChange={onToggleAutoPatch} />
          Enregistrer côté PC après crop
        </label>
        <button onClick={onClose} className="btn btn-danger">Fermer</button>
      </div>

      <div
        className="flex-1 overflow-auto p-4 flex justify-center items-start relative cursor-crosshair"
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={() => setDragging(false)}
      >
        <img
          ref={imgRef}
          src={img}
          alt="screenshot"
          draggable={false}
          className="max-w-[98%] max-h-[calc(100vh-180px)] block shadow-[0_0_0_1px_#333] select-none"
        />
        <div style={selectionStyle()} />
      </div>

      <div className="px-3 py-2 bg-neutral-900 text-neutral-200 flex items-center gap-2">
        <span>Fichier suggéré :</span>
        <input
          type="text"
          value={suggestedFilename}
          readOnly
          className="input w-60"
          title="Le chemin final est géré dans 'templates' (clé → chemin)."
        />
        <button onClick={doCrop} className="btn btn-primary ml-2">✂ Recadrer</button>
        <button onClick={onDownload} disabled={!dataUrl} className="btn btn-secondary disabled:opacity-50">
          ⬇ Télécharger PNG
        </button>
        {dataUrl && (
          <span className="ml-2 text-emerald-300">
            Crop OK ({Math.round(dataUrl.length / 1024)} KB encodé)
          </span>
        )}
      </div>
    </div>
  );
}

/* -----------------------
   Modal: OCR zone
------------------------ */
function OCRZonePickerModal(props: {
  img: string;
  zoneName: string;
  autoPatch: boolean;
  onToggleAutoPatch: () => void;
  onClose: () => void;
  onConfirm: (rect: Rect) => void; // [l,t,w,h]
}) {
  const { img, zoneName, autoPatch, onToggleAutoPatch, onClose, onConfirm } = props;
  const imgRef = useRef<HTMLImageElement | null>(null);

  const [dragging, setDragging] = useState(false);
  const [startD, setStartD] = useState<{ x: number; y: number } | null>(null);
  const [endD, setEndD] = useState<{ x: number; y: number } | null>(null);
  const [hoverD, setHoverD] = useState<{ x: number; y: number } | null>(null);

  function toDisplayCoords(clientX: number, clientY: number) {
    const el = imgRef.current;
    if (!el) return { x: 0, y: 0, inside: false };
    const rect = el.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    const inside = x >= 0 && y >= 0 && x <= rect.width && y <= rect.height;
    const cx = Math.max(0, Math.min(rect.width, x));
    const cy = Math.max(0, Math.min(rect.height, y));
    return { x: cx, y: cy, inside };
  }
  function onMouseDown(e: React.MouseEvent) {
    const { x, y, inside } = toDisplayCoords(e.clientX, e.clientY);
    if (!inside) return;
    setDragging(true);
    setStartD({ x, y });
    setEndD({ x, y });
  }
  function onMouseMove(e: React.MouseEvent) {
    const d = toDisplayCoords(e.clientX, e.clientY);
    setHoverD({ x: d.x, y: d.y });
    if (dragging) setEndD({ x: d.x, y: d.y });
  }
  function onMouseUp() {
    setDragging(false);
  }

  function currentRectDisplay() {
    if (!startD || !endD) return null;
    const x1 = Math.min(startD.x, endD.x);
    const y1 = Math.min(startD.y, endD.y);
    const x2 = Math.max(startD.x, endD.x);
    const y2 = Math.max(startD.y, endD.y);
    const w = Math.max(1, Math.round(x2 - x1));
    const h = Math.max(1, Math.round(y2 - y1));
    return { x: Math.round(x1), y: Math.round(y1), w, h };
  }
  function displayToNativeRect(disp: { x: number; y: number; w: number; h: number }): Rect {
    const el = imgRef.current!;
    const box = el.getBoundingClientRect();
    const natW = el.naturalWidth;
    const natH = el.naturalHeight;

    const scaleX = natW / box.width;
    const scaleY = natH / box.height;

    const nx = Math.max(0, Math.min(natW, Math.round(disp.x * scaleX)));
    const ny = Math.max(0, Math.min(natH, Math.round(disp.y * scaleY)));
    const nw = Math.max(1, Math.min(natW - nx, Math.round(disp.w * scaleX)));
    const nh = Math.max(1, Math.min(natH - ny, Math.round(disp.h * scaleY)));
    return [nx, ny, nw, nh];
  }
  function selectionStyle(): React.CSSProperties {
    const el = imgRef.current;
    if (!el) return { display: "none" };
    const disp = currentRectDisplay();
    if (!disp) return { display: "none" };

    const box = el.getBoundingClientRect();
    const left = box.left + disp.x;
    const top = box.top + disp.y;
    const width = disp.w;
    const height = disp.h;

    return {
      position: "fixed",
      left,
      top,
      width,
      height,
      border: "2px solid #60a5fa",
      boxShadow: "0 0 0 9999px rgba(0,0,0,0.35)",
      pointerEvents: "none",
      zIndex: 10001,
    };
  }
  function confirmIfValid() {
    const disp = currentRectDisplay();
    if (!disp) return;
    const nat = displayToNativeRect(disp);
    onConfirm(nat);
  }

  useEffect(() => {
    const el = imgRef.current;
    if (!el) return;
    const prevent = (ev: Event) => ev.preventDefault();
    el.addEventListener("dragstart", prevent);
    return () => el.removeEventListener("dragstart", prevent);
  }, []);

  return (
    <div className="fixed inset-0 bg-black/70 z-[9999] flex flex-col select-none">
      <div className="flex items-center gap-3 px-3 py-2 bg-neutral-900 text-white shadow">
        <strong>Définir une zone OCR — {zoneName}</strong>
        <span className="text-neutral-300">
          {hoverD ? `x=${Math.round(hoverD.x)}, y=${Math.round(hoverD.y)}` : "Glisse pour dessiner un rectangle"}
        </span>
        <label className="ml-auto flex items-center gap-2">
          <input type="checkbox" checked={autoPatch} onChange={onToggleAutoPatch} />
          Patch côté PC après choix
        </label>
        <button onClick={onClose} className="btn btn-danger">Fermer</button>
      </div>

      <div
        className="flex-1 overflow-auto p-4 flex justify-center items-start relative cursor-crosshair"
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={() => setDragging(false)}
      >
        <img
          ref={imgRef}
          src={img}
          alt="screenshot"
          draggable={false}
          className="max-w-[98%] max-h-[calc(100vh-180px)] block shadow-[0_0_0_1px_#333] select-none"
        />
        <div style={selectionStyle()} />
      </div>

      <div className="px-3 py-2 bg-neutral-900 text-neutral-200 flex items-center gap-2">
        <button onClick={confirmIfValid} className="btn btn-primary ml-2">✅ Valider la zone</button>
        <span className="ml-2 text-sky-300">
          La zone sera enregistrée comme [left, top, width, height] en pixels natifs.
        </span>
      </div>
    </div>
  );
}
