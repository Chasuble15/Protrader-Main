import { useEffect, useState } from "react";
import {
  listHdvResources,
  getHdvTimeseries,
  getHdvPriceStat,
  type HdvResource,
  type TimeseriesSeries,
} from "../api";
import {
  Chart as ChartJS,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
  type TooltipItem,
} from "chart.js";
import { Line } from "react-chartjs-2";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend);

const COLORS = ["#3b82f6", "#10b981", "#ef4444", "#f59e0b", "#8b5cf6"];

const parseTimestamp = (t: string): number => {
  const n = Number(t);
  if (!Number.isNaN(n)) {
    return n < 1e12 ? n * 1000 : n;
  }
  return Date.parse(t.endsWith("Z") ? t : `${t}Z`);
};

const imgSrc = (r: HdvResource) => {
  const blob = r.img_blob;
  if (!blob) return "";
  const maybePng = blob.startsWith("iVBOR");
  const mime = maybePng ? "image/png" : "image/jpeg";
  return `data:${mime};base64,${blob}`;
};

const formatPrice = (v: number) => Math.round(v).toLocaleString("fr-FR");

export default function Prices() {
  const [resources, setResources] = useState<HdvResource[]>([]);
  const [selected, setSelected] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem("prices.selected");
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [series, setSeries] = useState<TimeseriesSeries[]>([]);
  const [qty, setQty] = useState(() => localStorage.getItem("prices.qty") ?? "x1");
  const [start, setStart] = useState<string>("");
  const [end, setEnd] = useState<string>("");
  const [showAvg, setShowAvg] = useState(false);
  const [showMedian, setShowMedian] = useState(false);
  const [avgValues, setAvgValues] = useState<Record<string, number | null>>({});
  const [medianValues, setMedianValues] = useState<Record<string, number | null>>({});

  useEffect(() => {
    (async () => {
      try {
        const res = await listHdvResources(1000, qty);
        setResources(res);
      } catch (e) {
        console.error("Failed to load resources", e);
      }
    })();
  }, [qty]);

  useEffect(() => {
    if (selected.length === 0) {
      setSeries([]);
      return;
    }
    (async () => {
      try {
        const ts = await getHdvTimeseries(selected, qty, "day", "avg", start || undefined, end || undefined);
        setSeries(ts);
      } catch (e) {
        console.error("Failed to load timeseries", e);
        setSeries([]);
      }
    })();
  }, [selected, qty, start, end]);

  useEffect(() => {
    if (!showAvg || selected.length === 0) {
      setAvgValues({});
      return;
    }
    (async () => {
      try {
        const stats = await Promise.all(
          selected.map((slug) =>
            getHdvPriceStat(slug, qty, "avg", start || undefined, end || undefined)
          )
        );
        const map: Record<string, number | null> = {};
        for (const s of stats) map[s.slug] = s.value ?? null;
        setAvgValues(map);
      } catch (e) {
        console.error("Failed to load avg stats", e);
        setAvgValues({});
      }
    })();
  }, [showAvg, selected, qty, start, end]);

  useEffect(() => {
    if (!showMedian || selected.length === 0) {
      setMedianValues({});
      return;
    }
    (async () => {
      try {
        const stats = await Promise.all(
          selected.map((slug) =>
            getHdvPriceStat(slug, qty, "median", start || undefined, end || undefined)
          )
        );
        const map: Record<string, number | null> = {};
        for (const s of stats) map[s.slug] = s.value ?? null;
        setMedianValues(map);
      } catch (e) {
        console.error("Failed to load median stats", e);
        setMedianValues({});
      }
    })();
  }, [showMedian, selected, qty, start, end]);

  useEffect(() => {
    localStorage.setItem("prices.selected", JSON.stringify(selected));
  }, [selected]);

  useEffect(() => {
    localStorage.setItem("prices.qty", qty);
  }, [qty]);

  const startMs = start ? new Date(start).getTime() : undefined;
  const endMs = end ? new Date(end).getTime() : undefined;
  const allTimes = series.flatMap((s) => s.points.map((p) => parseTimestamp(p.t)));
  const minTime = startMs ?? (allTimes.length ? Math.min(...allTimes) : undefined);
  const maxTime = endMs ?? (allTimes.length ? Math.max(...allTimes) : undefined);

  const datasets = series.map((s, idx) => ({
    label: s.slug,
    data: s.points.map((p) => ({
      x: parseTimestamp(p.t),
      y: p.price ?? p.value ?? 0,
    })),
    borderColor: COLORS[idx % COLORS.length],
    backgroundColor: COLORS[idx % COLORS.length],
    tension: 0.1,
  }));

  if (showAvg) {
    Object.entries(avgValues).forEach(([slug, value]) => {
      if (value == null || minTime === undefined || maxTime === undefined) return;
      const idx = selected.indexOf(slug);
      const color = COLORS[(idx >= 0 ? idx : 0) % COLORS.length];
      datasets.push({
        label: `${slug} moyenne`,
        data: [
          { x: minTime, y: value },
          { x: maxTime, y: value },
        ],
        borderColor: color,
        backgroundColor: color,
        borderDash: [5, 5],
        pointRadius: 0,
        tension: 0,
      });
    });
  }

  if (showMedian) {
    Object.entries(medianValues).forEach(([slug, value]) => {
      if (value == null || minTime === undefined || maxTime === undefined) return;
      const idx = selected.indexOf(slug);
      const color = COLORS[(idx >= 0 ? idx : 0) % COLORS.length];
      datasets.push({
        label: `${slug} médiane`,
        data: [
          { x: minTime, y: value },
          { x: maxTime, y: value },
        ],
        borderColor: color,
        backgroundColor: color,
        borderDash: [2, 2],
        pointRadius: 0,
        tension: 0,
      });
    });
  }

  const chartData = { datasets };

  const chartOptions = {
    parsing: false,
    responsive: true,
    scales: {
      x: {
        type: "linear" as const,
        min: startMs,
        max: endMs,
        ticks: {
          callback: (value: number) => new Date(value).toLocaleString(),
        },
      },
      y: {
        type: "linear" as const,
        min: 0,
        beginAtZero: true,
      },
    },
    plugins: {
      legend: { position: "bottom" as const },
      tooltip: {
        callbacks: {
          title: (items: TooltipItem<"line">[]) =>
            new Date(items[0].parsed.x as number).toLocaleString(),
        },
      },
    },
  };

  const toggle = (slug: string, checked: boolean) => {
    setSelected((prev) => {
      if (checked) return prev.includes(slug) ? prev : [...prev, slug];
      return prev.filter((s) => s !== slug);
    });
  };

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold">Historique des prix</h2>
      <div className="flex flex-wrap gap-4">
        {resources.map((r) => {
          const isSel = selected.includes(r.slug);
          return (
            <button
              key={r.slug}
              onClick={() => toggle(r.slug, !isSel)}
              className={`w-32 p-2 rounded-lg border text-sm flex flex-col items-center gap-1 ${isSel ? "border-blue-500 ring-2 ring-blue-200" : "border-gray-200"}`}
            >
              <div className="w-10 h-10 rounded-md overflow-hidden bg-gray-100 flex items-center justify-center">
                {r.img_blob ? (
                  // eslint-disable-next-line jsx-a11y/alt-text
                  <img src={imgSrc(r)} alt={r.name_fr || r.slug} className="w-full h-full object-cover" />
                ) : (
                  <div className="text-xs text-gray-400">—</div>
                )}
              </div>
              <span className="truncate w-full text-center">{r.name_fr || r.slug}</span>
              {r.avg_unit_price != null && (
                <span className="text-xs text-gray-500">{formatPrice(r.avg_unit_price)} K</span>
              )}
            </button>
          );
        })}
      </div>
      <div className="flex items-center gap-4 text-sm">
        <label className="flex items-center gap-2">
          Quantité
          <select
            value={qty}
            onChange={(e) => setQty(e.target.value)}
            className="border rounded p-1"
          >
            <option value="x1">x1</option>
            <option value="x10">x10</option>
            <option value="x100">x100</option>
            <option value="x1000">x1000</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={showAvg}
            onChange={(e) => setShowAvg(e.target.checked)}
          />
          <span>Moyenne</span>
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={showMedian}
            onChange={(e) => setShowMedian(e.target.checked)}
          />
          <span>Médiane</span>
        </label>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label className="flex items-center gap-2">
          De
          <input
            type="datetime-local"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            className="border rounded p-1"
          />
        </label>
        <label className="flex items-center gap-2">
          À
          <input
            type="datetime-local"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            className="border rounded p-1"
          />
        </label>
      </div>
      <div className="border rounded-xl p-4 bg-white">
        {series.length === 0 ? (
          <div className="text-sm text-slate-500">Aucune donnée à afficher.</div>
        ) : (
          <Line data={chartData} options={chartOptions} />
        )}
      </div>
    </div>
  );
}

