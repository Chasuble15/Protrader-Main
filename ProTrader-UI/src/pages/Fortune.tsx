import { useEffect, useState } from "react";
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from "chart.js";
import { Line } from "react-chartjs-2";
import {
  getKamasHistory,
  loadSelection,
  getHdvPriceStat,
  saveSelectionSettings,
  type SelectedItem,
  type KamasPoint,
  type Qty,
} from "../api";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend);

const parseTimestamp = (t: string): number => {
  const n = Number(t);
  if (!Number.isNaN(n)) {
    return n < 1e12 ? n * 1000 : n;
  }
  return Date.parse(t.endsWith("Z") ? t : `${t}Z`);
};

const QTY_LIST: Qty[] = ["x1", "x10", "x100", "x1000"];

export default function Fortune() {
  const [points, setPoints] = useState<KamasPoint[]>([]);
  const [items, setItems] = useState<SelectedItem[]>([]);
  const [medianMap, setMedianMap] = useState<Record<string, Record<Qty, number | null>>>({});
  const [settings, setSettings] = useState<
    Record<string, { marginType: "percent" | "absolute"; value: number; active: boolean }>
  >({});

  useEffect(() => {
    (async () => {
      try {
        const pts = await getKamasHistory("day");
        setPoints(pts);
      } catch (e) {
        console.error("Failed to load kamas history", e);
      }
    })();
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const sel = await loadSelection();
        setItems(sel);
        const map: Record<string, { marginType: "percent" | "absolute"; value: number; active: boolean }> = {};
        sel.forEach((it) => {
          QTY_LIST.forEach((qty) => {
            const s = it.settings?.[qty];
            map[`${it.id}-${qty}`] = {
              marginType: s?.margin_type === "absolute" ? "absolute" : "percent",
              value: s?.margin_value ?? 0,
              active: s?.active ?? true,
            };
          });
        });
        setSettings(map);
      } catch (e) {
        console.error("Failed to load selection", e);
      }
    })();
  }, []);

  useEffect(() => {
    if (items.length === 0) {
      setMedianMap({});
      return;
    }
    (async () => {
      const start = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();
      const end = new Date().toISOString();
      const map: Record<string, Record<Qty, number | null>> = {};
      for (const it of items) {
        const qmap: Record<Qty, number | null> = {} as Record<Qty, number | null>;
        await Promise.all(
          QTY_LIST.map(async (qty) => {
            try {
              const stat = await getHdvPriceStat(it.slug_fr, qty, "median", start, end);
              qmap[qty] = stat.value;
            } catch {
              qmap[qty] = null;
            }
          }),
        );
        map[it.slug_fr] = qmap;
      }
      setMedianMap(map);
    })();
  }, [items]);

  const imgSrc = (it: SelectedItem) => {
    if (!it.img_blob) return "";
    const maybePng = it.img_blob.startsWith("iVBOR");
    const mime = maybePng ? "image/png" : "image/jpeg";
    return `data:${mime};base64,${it.img_blob}`;
  };

  const formatKamas = (v: number) => `${Math.round(v).toLocaleString("fr-FR")} K`;

  const updateSetting = (
    key: string,
    patch: Partial<{ marginType: "percent" | "absolute"; value: number; active: boolean }>,
  ) => {
    setSettings((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));
  };

  const handleSave = async () => {
    try {
      const payload = Object.entries(settings).map(([k, v]) => {
        const [idStr, qty] = k.split("-");
        return {
          item_id: Number(idStr),
          qty: qty as Qty,
          margin_type: v.marginType,
          margin_value: v.value,
          active: v.active,
        };
      });
      await saveSelectionSettings(payload);
    } catch (e) {
      console.error("Failed to save settings", e);
    }
  };

  const data = {
    datasets: [
      {
        label: "Kamas",
        data: points.map((p) => ({ x: parseTimestamp(p.t), y: p.amount })),
        borderColor: "#f59e0b",
        backgroundColor: "#f59e0b",
        tension: 0.1,
      },
    ],
  };

  const options = {
    parsing: false,
    responsive: true,
    scales: {
      x: {
        type: "linear" as const,
        ticks: {
          callback: (value: number) =>
            new Date(value).toLocaleString("fr-FR", { timeZone: "UTC" }),
        },
      },
      y: {
        type: "linear" as const,
        beginAtZero: true,
      },
    },
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          title: (items: any[]) =>
            new Date(items[0].parsed.x as number).toLocaleString("fr-FR", { timeZone: "UTC" }),
          label: (item: any) => `${item.parsed.y as number} K`,
        },
      },
    },
  };

  return (
    <div className="space-y-6 bg-white -m-4 p-4 min-h-full">
      <h2 className="text-lg font-semibold">Fortune</h2>
      <Line data={data} options={options} />
      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b text-left">
                <th className="p-2">Ressource</th>
                <th className="p-2">Quantité</th>
                <th className="p-2">Prix médian du lot (K)</th>
                <th className="p-2">Marge</th>
                <th className="p-2">Valeur</th>
                <th className="p-2">Valeur achat (K)</th>
                <th className="p-2">Bénéfice estimé (K)</th>
                <th className="p-2">Actif</th>
              </tr>
            </thead>
            <tbody>
              {items.flatMap((it) =>
                QTY_LIST.map((qty) => {
                  const key = `${it.id}-${qty}`;
                  const cfg = settings[key] || { marginType: "percent", value: 0, active: true };
                  const median = medianMap[it.slug_fr]?.[qty] ?? null;
                  let purchase: number | null = null;
                  if (cfg.marginType === "percent") {
                    purchase = median != null ? median * (1 - cfg.value / 100) : null;
                  } else {
                    purchase = cfg.value;
                  }
                  const profit =
                    median != null && purchase != null ? median - purchase : null;
                    return (
                      <tr
                        key={key}
                        className={`border-b last:border-0 ${
                          cfg.active
                            ? "bg-sky-50 font-medium"
                            : "bg-gray-50 text-gray-500"
                        }`}
                      >
                      <td className="p-2">
                        <div className="flex items-center gap-2">
                          {it.img_blob ? (
                            // eslint-disable-next-line jsx-a11y/alt-text
                            <img
                              src={imgSrc(it)}
                              alt={it.name_fr}
                              className="w-6 h-6 rounded object-cover"
                            />
                          ) : (
                            <div className="w-6 h-6 bg-gray-200 rounded" />
                          )}
                          <span className="truncate">{it.name_fr}</span>
                        </div>
                      </td>
                      <td className="p-2">{qty}</td>
                      <td className="p-2">
                        {median != null ? formatKamas(median) : "—"}
                      </td>
                      <td className="p-2">
                        <select
                          className="border rounded px-1 py-0.5 text-sm"
                          value={cfg.marginType}
                          onChange={(e) =>
                            updateSetting(key, {
                              marginType: e.target.value as "percent" | "absolute",
                            })
                          }
                          disabled={!cfg.active}
                        >
                          <option value="percent">Pourcent</option>
                          <option value="absolute">Absolu</option>
                        </select>
                      </td>
                      <td className="p-2">
                        <input
                          type="number"
                          className="border rounded px-1 py-0.5 w-24 text-sm"
                          value={cfg.value}
                          onChange={(e) =>
                            updateSetting(key, { value: Number(e.target.value) })
                          }
                          disabled={!cfg.active}
                        />
                      </td>
                      <td className="p-2">
                        {purchase != null ? formatKamas(purchase) : "—"}
                      </td>
                      <td className="p-2">
                        {profit != null ? formatKamas(profit) : "—"}
                      </td>
                      <td className="p-2 text-center">
                        <input
                          type="checkbox"
                          checked={cfg.active}
                          onChange={(e) =>
                            updateSetting(key, { active: e.target.checked })
                          }
                        />
                      </td>
                    </tr>
                  );
                }),
              )}
            </tbody>
          </table>
          <div className="mt-4">
            <button
              onClick={handleSave}
              className="px-3 py-2 rounded-xl border border-gray-300 hover:bg-gray-50"
            >
              Sauvegarder
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
