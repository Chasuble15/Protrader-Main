import { useEffect, useState } from "react";
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from "chart.js";
import { Line } from "react-chartjs-2";
import {
  getKamasHistory,
  loadSelection,
  getHdvTimeseries,
  type Item,
  type KamasPoint,
} from "../api";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend);

const parseTimestamp = (t: string): number => {
  const n = Number(t);
  if (!Number.isNaN(n)) {
    return n < 1e12 ? n * 1000 : n;
  }
  return Date.parse(t.endsWith("Z") ? t : `${t}Z`);
};

const QTY_LIST = ["x1", "x10", "x100", "x1000"] as const;

const median = (values: number[]): number | null => {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? (sorted[mid - 1] + sorted[mid]) / 2
    : sorted[mid];
};

export default function Fortune() {
  const [points, setPoints] = useState<KamasPoint[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [medianMap, setMedianMap] = useState<Record<string, Record<string, number | null>>>({});

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
      const map: Record<string, Record<string, number | null>> = {};
      for (const it of items) {
        const qmap: Record<string, number | null> = {};
        await Promise.all(
          QTY_LIST.map(async (qty) => {
            try {
              const series = await getHdvTimeseries(
                [it.slug_fr],
                qty,
                "raw",
                null,
                start,
                end,
              );
              const prices = series[0]?.points.map((p) => p.price ?? p.value ?? 0) ?? [];
              qmap[qty] = median(prices);
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

  const imgSrc = (it: Item) => {
    if (!it.img_blob) return "";
    const maybePng = it.img_blob.startsWith("iVBOR");
    const mime = maybePng ? "image/png" : "image/jpeg";
    return `data:${mime};base64,${it.img_blob}`;
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
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">Fortune</h2>
      <Line data={data} options={options} />
      {items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b text-left">
                <th className="p-2">Ressource</th>
                <th className="p-2">Quantité</th>
                <th className="p-2">Prix médian (K)</th>
              </tr>
            </thead>
            <tbody>
              {items.flatMap((it) =>
                QTY_LIST.map((qty) => (
                  <tr key={`${it.id}-${qty}`} className="border-b last:border-0">
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
                      {(() => {
                        const v = medianMap[it.slug_fr]?.[qty];
                        return v != null ? `${Math.round(v / 1000)} K` : "—";
                      })()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
