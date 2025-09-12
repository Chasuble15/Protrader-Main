import { useEffect, useMemo, useRef, useState } from "react";
import { type Item, searchItems, getItemsByIds, loadSelection, saveSelection } from "../api";

type Props = {
  limit?: number;
  defaultSelectedIds?: number[];
  onChangeSelected?: (items: Item[]) => void;
  placeholder?: string;
  debounceMs?: number;
};

const cx = (...c: Array<string | false | null | undefined>) => c.filter(Boolean).join(" ");

export default function ResourcePicker({
  limit = 20,
  defaultSelectedIds = [],
  onChangeSelected,
  placeholder = "Rechercher une ressource…",
  debounceMs = 250,
}: Props) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState<Item[]>([]);
  const [selectedMap, setSelectedMap] = useState<Map<number, Item>>(() => new Map());
  const abortRef = useRef<{ aborted: boolean }>({ aborted: false });

  // Recharger depuis la base la sélection persistée
  const handleReload = async () => {
    try {
      const items = await loadSelection();
      const m = new Map<number, Item>();
      items.forEach((it) => m.set(it.id, it));
      setSelectedMap(m);
      onChangeSelected?.(Array.from(m.values()));
    } catch (e) {
      console.error("Reload selection failed:", e);
      // Optionnel: toast UI
    }
  };

  // Sauvegarder la sélection actuelle en base
  const handleSave = async () => {
    try {
      const ids = Array.from(selectedMap.values()).map((it) => it.id);
      await saveSelection(ids);
      // Optionnel: toast "Sauvegardé"
    } catch (e) {
      console.error("Save selection failed:", e);
      // Optionnel: toast erreur
    }
  };

  // Init sélection par défaut
  useEffect(() => {
    if (!defaultSelectedIds.length) return;
    (async () => {
      try {
        const items = await getItemsByIds(defaultSelectedIds);
        const m = new Map<number, Item>();
        items.forEach((it) => m.set(it.id, it));
        setSelectedMap(m);
        onChangeSelected?.(Array.from(m.values()));
      } catch {/* ignore */}
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Recherche (debounced)
  useEffect(() => {
    abortRef.current.aborted = false;
    if (!query.trim()) { setResults([]); setLoading(false); return; }

    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const items = await searchItems(query, limit);
        if (!abortRef.current.aborted) setResults(items);
      } catch {
        if (!abortRef.current.aborted) setResults([]);
      } finally {
        if (!abortRef.current.aborted) setLoading(false);
      }
    }, debounceMs);

    return () => { abortRef.current.aborted = true; clearTimeout(t); };
  }, [query, limit, debounceMs]);

    // 🔁 Auto-recharge au montage : charge d'abord la sélection persistée,
    // sinon retombe sur defaultSelectedIds si fournis.
    useEffect(() => {
    let cancelled = false;
    (async () => {
        try {
        const persisted = await loadSelection();
        if (!cancelled && persisted.length > 0) {
            const m = new Map<number, Item>();
            persisted.forEach((it) => m.set(it.id, it));
            setSelectedMap(m);
            onChangeSelected?.(Array.from(m.values()));
            return;
        }

        if (!cancelled && defaultSelectedIds.length > 0) {
            const items = await getItemsByIds(defaultSelectedIds);
            const m = new Map<number, Item>();
            items.forEach((it) => m.set(it.id, it));
            setSelectedMap(m);
            onChangeSelected?.(Array.from(m.values()));
        }
        } catch {
        // ignore (option: toast d'erreur)
        }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);


  const selected = useMemo(() => Array.from(selectedMap.values()), [selectedMap]);

  const toggleSelect = (item: Item) => {
    setSelectedMap((prev) => {
      const next = new Map(prev);
      if (next.has(item.id)) next.delete(item.id);
      else next.set(item.id, item);
      onChangeSelected?.(Array.from(next.values()));
      return next;
    });
  };

  const removeSelected = (id: number) => {
    setSelectedMap((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Map(prev);
      next.delete(id);
      onChangeSelected?.(Array.from(next.values()));
      return next;
    });
  };

  const imgSrc = (it: Item) => {
    if (!it.img_blob) return "";
    // Heuristique simple pour choisir le mime (PNG vs JPEG). Ajuste si tu connais le vrai format.
    const maybePng = it.img_blob.startsWith("iVBOR"); // base64 PNG commence souvent par iVBOR
    const mime = maybePng ? "image/png" : "image/jpeg";
    return `data:${mime};base64,${it.img_blob}`;
  };

  return (
    <div className="w-full max-w-5xl mx-auto">
        {/* Barre d’actions haut */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-base font-semibold">Ressources</div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleReload}
            className="btn btn-secondary"
            title="Recharger la sélection sauvegardée"
          >
            Recharger
          </button>
          <button
            onClick={handleSave}
            className="btn btn-primary"
            title="Sauvegarder la sélection actuelle"
          >
            Sauvegarder
          </button>
        </div>
      </div>
      {/* Search */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={placeholder}
            className={cx("input w-full")}
          />
          {loading && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-500">
              …
            </div>
          )}
        </div>
        {!!query && (
          <button
            onClick={() => setQuery("")}
            className="btn btn-secondary"
          >
            Effacer
          </button>
        )}
      </div>

      {/* Résultats */}
      <div className="mt-4">
        <h3 className="text-sm font-medium text-gray-700 mb-2">
          Résultats {query ? <>pour “{query}”</> : null}
        </h3>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {results.map((it) => {
            const isSelected = selectedMap.has(it.id);
            return (
              <button
                key={it.id}
                onClick={() => toggleSelect(it)}
                className={cx(
                  "group w-full text-left rounded-2xl border p-3 transition hover:shadow-sm",
                  isSelected
                    ? "border-cds-interactive ring-2 ring-cds-interactive ring-opacity-50"
                    : "border-cds-border"
                )}
              >
                <div className="flex items-center gap-3">
                  <div className="w-14 h-14 rounded-xl overflow-hidden bg-gray-100 flex items-center justify-center">
                    {it.img_blob ? (
                      // eslint-disable-next-line jsx-a11y/alt-text
                      <img src={imgSrc(it)} alt={it.name_fr} className="w-full h-full object-cover" loading="lazy" />
                    ) : (
                      <div className="text-xs text-gray-400">Aucune image</div>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="font-medium truncate">{it.name_fr}</div>
                    <div className="text-xs text-gray-500">Niveau {it.level}</div>
                  </div>
                  <input
                    type="checkbox"
                    readOnly
                    checked={isSelected}
                    className="ml-auto h-5 w-5 rounded border-gray-300"
                  />
                </div>
              </button>
            );
          })}
          {!loading && results.length === 0 && query && (
            <div className="text-sm text-gray-500 col-span-full">Aucun résultat.</div>
          )}
        </div>
      </div>

      {/* Sélection */}
      <div className="mt-6">
        <h3 className="text-sm font-medium text-gray-700 mb-2">Sélection ({selected.length})</h3>
        {selected.length === 0 ? (
          <div className="text-sm text-gray-500 border border-dashed rounded-2xl p-4">
            Rien de sélectionné pour l’instant.
          </div>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {selected.map((it) => (
              <li key={`sel-${it.id}`} className="rounded-2xl border border-cds-border p-3">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-xl overflow-hidden bg-gray-100 flex items-center justify-center">
                    {it.img_blob ? (
                      // eslint-disable-next-line jsx-a11y/alt-text
                      <img src={imgSrc(it)} alt={it.name_fr} className="w-full h-full object-cover" />
                    ) : (
                      <div className="text-[10px] text-gray-400">No img</div>
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="font-medium truncate">{it.name_fr}</div>
                    <div className="text-xs text-gray-500">Niveau {it.level}</div>
                  </div>
                  <button
                    onClick={() => removeSelected(it.id)}
                    className="ml-auto btn btn-secondary text-xs px-2 py-1"
                    title="Retirer"
                  >
                    Retirer
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
