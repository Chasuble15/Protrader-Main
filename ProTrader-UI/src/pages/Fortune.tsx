import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from "chart.js";
import { Line } from "react-chartjs-2";
import {
  getKamasHistory,
  getPurchaseHistory,
  loadSelection,
  getHdvPriceStat,
  saveSelectionSettings,
  normalizeDateParam,
  type SelectedItem,
  type KamasPoint,
  type Qty,
  type PurchaseEvent,
} from "../api";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend);

const parseTimestamp = (input: string): number => {
  const raw = typeof input === "string" ? input.trim() : "";
  if (!raw) return Number.NaN;

  const numeric = Number(raw);
  if (!Number.isNaN(numeric)) {
    return numeric < 1e12 ? numeric * 1000 : numeric;
  }

  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const candidates: string[] = [];
  const pushCandidate = (value: string) => {
    if (!value || candidates.includes(value)) return;
    candidates.push(value);
  };

  if (/^\d{4}-\d{2}-\d{2}$/.test(normalized)) {
    pushCandidate(`${normalized}T00:00:00Z`);
  }

  if (hasTimezone) {
    pushCandidate(normalized);
  } else {
    if (!normalized.endsWith("Z")) {
      pushCandidate(`${normalized}Z`);
    }
    pushCandidate(normalized);
  }

  if (normalized !== raw) {
    pushCandidate(raw);
  }

  for (const candidate of candidates) {
    const parsed = Date.parse(candidate);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }

  return Number.NaN;
};

const QTY_LIST: Qty[] = ["x1", "x10", "x100", "x1000"];

type TimeRangeKey = "1d" | "3d" | "1w" | "1m" | "all";

type TimeRangeConfig = {
  label: string;
  durationMs?: number;
  bucket: "raw" | "minute" | "hour" | "day";
  purchaseLimit: number;
};

const DAY_MS = 24 * 3600 * 1000;
const TIME_RANGES: Record<TimeRangeKey, TimeRangeConfig> = {
  "1d": { label: "1 jour", durationMs: DAY_MS, bucket: "raw", purchaseLimit: 200 },
  "3d": { label: "3 jours", durationMs: 3 * DAY_MS, bucket: "hour", purchaseLimit: 400 },
  "1w": { label: "1 semaine", durationMs: 7 * DAY_MS, bucket: "hour", purchaseLimit: 600 },
  "1m": { label: "1 mois", durationMs: 30 * DAY_MS, bucket: "day", purchaseLimit: 1200 },
  all: { label: "All time", bucket: "day", purchaseLimit: 2000 },
};

type ChartPoint = { x: number; y: number; rawTimestamp: string };

type PurchaseTooltipGroup = {
  id: string;
  anchorX: number;
  anchorY: number;
  tooltipLeft: number;
  tooltipTop: number;
  purchases: PurchaseEvent[];
};

export default function Fortune() {
  const [points, setPoints] = useState<KamasPoint[]>([]);
  const [items, setItems] = useState<SelectedItem[]>([]);
  const [medianMap, setMedianMap] = useState<Record<string, Record<Qty, number | null>>>({});
  const [settings, setSettings] = useState<
    Record<string, { marginType: "percent" | "absolute"; value: number; active: boolean }>
  >({});
  const [timeRange, setTimeRange] = useState<TimeRangeKey>("1w");
  const [purchases, setPurchases] = useState<PurchaseEvent[]>([]);
  const [tooltipGroups, setTooltipGroups] = useState<PurchaseTooltipGroup[]>([]);
  const [hoveredTooltipId, setHoveredTooltipId] = useState<string | null>(null);
  const chartRef = useRef<ChartJS<"line"> | null>(null);
  const hideTooltipTimeout = useRef<number | null>(null);

  const clearHideTooltip = useCallback(() => {
    if (hideTooltipTimeout.current !== null) {
      window.clearTimeout(hideTooltipTimeout.current);
      hideTooltipTimeout.current = null;
    }
  }, []);

  const showTooltip = useCallback(
    (id: string) => {
      clearHideTooltip();
      setHoveredTooltipId(id);
    },
    [clearHideTooltip],
  );

  const scheduleHideTooltip = useCallback(
    (id: string) => {
      clearHideTooltip();
      hideTooltipTimeout.current = window.setTimeout(() => {
        setHoveredTooltipId((prev) => (prev === id ? null : prev));
        hideTooltipTimeout.current = null;
      }, 120);
    },
    [clearHideTooltip],
  );

  useEffect(() => {
    return () => {
      if (hideTooltipTimeout.current !== null) {
        window.clearTimeout(hideTooltipTimeout.current);
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      const cfg = TIME_RANGES[timeRange];
      const now = new Date();
      const endIso = normalizeDateParam(now);
      const startIso = cfg.durationMs
        ? normalizeDateParam(new Date(now.getTime() - cfg.durationMs))
        : undefined;
      try {
        const [pts, purchaseList] = await Promise.all([
          getKamasHistory(cfg.bucket, startIso, endIso),
          getPurchaseHistory(startIso, endIso, cfg.purchaseLimit),
        ]);
        if (!cancelled) {
          setPoints(pts);
          setPurchases(purchaseList);
        }
      } catch (e) {
        if (!cancelled) {
          console.error("Failed to load fortune history", e);
        }
      }
    };
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [timeRange]);

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
      const start = normalizeDateParam(new Date(Date.now() - 7 * 24 * 3600 * 1000));
      const end = normalizeDateParam(new Date());
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

  const buildImgSrc = (blob?: string | null) => {
    if (!blob) return "";
    const maybePng = blob.startsWith("iVBOR");
    const mime = maybePng ? "image/png" : "image/jpeg";
    return `data:${mime};base64,${blob}`;
  };

const imgSrc = (it: SelectedItem) => buildImgSrc(it.img_blob);

const formatKamas = (v: number) => `${Math.round(v).toLocaleString("fr-FR")} K`;

const percentFormatter = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 0,
});

const formatKamasDelta = (value: number) => {
  const rounded = Math.round(value);
  const sign = rounded > 0 ? "+" : rounded < 0 ? "-" : "";
  return `${sign}${Math.abs(rounded).toLocaleString("fr-FR")} K`;
};

const formatPercentDelta = (value: number) => {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${percentFormatter.format(Math.abs(value))} %`;
};

const formatDateTime = useCallback((value: number | string) => {
  const timestamp = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(timestamp)) {
    return String(value);
  }
  return new Date(timestamp).toLocaleString("fr-FR", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "UTC",
  });
}, []);

  const computeSaleStats = useCallback(
    (purchase: PurchaseEvent): { saleTotal: number | null; profit: number | null } => {
      const purchaseTimestamp = purchase.datetime ? parseTimestamp(purchase.datetime) : Number.NaN;
      const saleTimestamp = purchase.saleDatetime ? parseTimestamp(purchase.saleDatetime) : null;
      const hasPurchaseTimestamp = Number.isFinite(purchaseTimestamp);
      const hasSaleTimestamp = typeof saleTimestamp === "number" && Number.isFinite(saleTimestamp);
      const saleIsChronologicalMatch = hasSaleTimestamp && hasPurchaseTimestamp
        ? saleTimestamp >= purchaseTimestamp
        : true;
      const rawSaleTotal = saleIsChronologicalMatch ? purchase.saleTotalPrice : null;
      const saleTotal =
        saleIsChronologicalMatch && typeof rawSaleTotal === "number" && Number.isFinite(rawSaleTotal)
          ? rawSaleTotal
          : null;
      let profit: number | null = null;
      if (saleTotal != null) {
        const delta = saleTotal - purchase.totalPrice;
        if (Number.isFinite(delta)) {
          profit = delta;
        }
      }
      return { saleTotal, profit };
    },
    [],
  );

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

  const kamasSeries = useMemo<ChartPoint[]>(() => {
    return points
      .map((p) => ({
        x: parseTimestamp(p.t),
        y: p.amount,
        rawTimestamp: p.t,
      }))
      .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y))
      .sort((a, b) => a.x - b.x);
  }, [points]);

  const currentFortune = useMemo(() => {
    if (kamasSeries.length === 0) return null;
    return kamasSeries[kamasSeries.length - 1].y;
  }, [kamasSeries]);

  const totalProfit = useMemo(() => {
    let sum = 0;
    for (const purchase of purchases) {
      const { profit } = computeSaleStats(purchase);
      if (profit != null) {
        sum += profit;
      }
    }
    return sum;
  }, [purchases, computeSaleStats]);

  const findClosestAmount = useCallback(
    (timestamp: number) => {
      if (kamasSeries.length === 0) return null;
      let low = 0;
      let high = kamasSeries.length;
      while (low < high) {
        const mid = Math.floor((low + high) / 2);
        if (kamasSeries[mid].x < timestamp) {
          low = mid + 1;
        } else {
          high = mid;
        }
      }
      const candidates: ChartPoint[] = [];
      if (low < kamasSeries.length) candidates.push(kamasSeries[low]);
      if (low > 0) candidates.push(kamasSeries[low - 1]);
      if (candidates.length === 0) {
        return kamasSeries[0].y;
      }
      let best = candidates[0];
      let minDelta = Math.abs(candidates[0].x - timestamp);
      for (let i = 1; i < candidates.length; i += 1) {
        const delta = Math.abs(candidates[i].x - timestamp);
        if (delta < minDelta) {
          minDelta = delta;
          best = candidates[i];
        }
      }
      return best.y;
    },
    [kamasSeries],
  );

  const recomputeTooltips = useCallback(() => {
    const chart = chartRef.current;
    if (!chart || !chart.scales?.x || !chart.scales?.y || !chart.chartArea) {
      setTooltipGroups([]);
      return;
    }
    if (purchases.length === 0 || kamasSeries.length === 0) {
      setTooltipGroups([]);
      return;
    }

    const xScale: any = chart.scales.x;
    const yScale: any = chart.scales.y;
    const area = chart.chartArea;
    const rawMin = xScale.min;
    const rawMax = xScale.max;
    const min = typeof rawMin === "number" ? rawMin : Number(rawMin ?? Number.NEGATIVE_INFINITY);
    const max = typeof rawMax === "number" ? rawMax : Number(rawMax ?? Number.POSITIVE_INFINITY);

    const positions: Array<{ purchase: PurchaseEvent; x: number; y: number }> = [];
    for (const purchase of purchases) {
      const ts = parseTimestamp(purchase.datetime);
      if (!Number.isFinite(ts)) continue;
      if (Number.isFinite(min) && ts < min) continue;
      if (Number.isFinite(max) && ts > max) continue;

      const x = xScale.getPixelForValue(ts);
      if (!Number.isFinite(x)) continue;

      const amount = findClosestAmount(ts);
      const fallbackAmount = kamasSeries[kamasSeries.length - 1]?.y ?? 0;
      const yValue = amount ?? fallbackAmount;
      const y = yScale.getPixelForValue(yValue);
      if (!Number.isFinite(y)) continue;

      positions.push({ purchase, x, y });
    }

    if (positions.length === 0) {
      setTooltipGroups([]);
      return;
    }

    positions.sort((a, b) => a.x - b.x);

    const thresholdPx = 56;
    type GroupAccumulator = {
      xSum: number;
      ySum: number;
      count: number;
      yMin: number;
      purchases: PurchaseEvent[];
    };
    const grouped: GroupAccumulator[] = [];

    for (const pos of positions) {
      const center = pos.x;
      const last = grouped[grouped.length - 1];
      if (!last) {
        grouped.push({ xSum: center, ySum: pos.y, count: 1, yMin: pos.y, purchases: [pos.purchase] });
        continue;
      }
      const lastCenter = last.xSum / last.count;
      if (Math.abs(center - lastCenter) > thresholdPx) {
        grouped.push({ xSum: center, ySum: pos.y, count: 1, yMin: pos.y, purchases: [pos.purchase] });
      } else {
        last.xSum += center;
        last.ySum += pos.y;
        last.count += 1;
        if (pos.y < last.yMin) {
          last.yMin = pos.y;
        }
        last.purchases.push(pos.purchase);
      }
    }

    const tooltipData: PurchaseTooltipGroup[] = grouped.map((group) => {
      const avgX = group.xSum / group.count;
      const avgY = group.ySum / group.count;
      const estimatedHeight = group.purchases.length * 22 + 18;
      const tooltipLeft = Math.min(Math.max(avgX, area.left + 16), area.right - 16);
      const topBase = group.yMin - estimatedHeight;
      const tooltipTop = Math.min(
        Math.max(topBase, area.top + 8),
        area.bottom - estimatedHeight - 8,
      );
      const id = group.purchases.map((p) => `${p.id}-${p.datetime}`).join("|") || String(avgX);
      return {
        id,
        anchorX: avgX,
        anchorY: avgY,
        tooltipLeft,
        tooltipTop,
        purchases: group.purchases,
      };
    });

    setTooltipGroups(tooltipData);
  }, [chartRef, findClosestAmount, kamasSeries, purchases]);

  useEffect(() => {
    const raf = requestAnimationFrame(() => {
      recomputeTooltips();
    });
    return () => cancelAnimationFrame(raf);
  }, [recomputeTooltips]);

  useEffect(() => {
    const handleResize = () => {
      recomputeTooltips();
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [recomputeTooltips]);

  const data = useMemo(
    () => ({
      datasets: [
        {
          label: "Kamas",
          data: kamasSeries,
          borderColor: "#f59e0b",
          backgroundColor: "#f59e0b",
          tension: 0.1,
        },
      ],
    }),
    [kamasSeries],
  );

  const options = useMemo(
    () => ({
      parsing: false,
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: "linear" as const,
          ticks: {
            callback: (value: number | string) => formatDateTime(value),
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
            title: (items: any[]) => {
              const raw = items[0]?.raw as { rawTimestamp?: string; x: number };
              if (raw?.rawTimestamp) {
                return raw.rawTimestamp.replace("T", " ").replace("Z", " UTC");
              }
              return formatDateTime(items[0].parsed.x as number);
            },
            label: (item: any) =>
              `${Math.round(item.parsed.y as number).toLocaleString("fr-FR")} K`,
          },
        },
      },
      animation: {
        duration: 0,
        onComplete: () => {
          recomputeTooltips();
        },
      },
    }),
    [formatDateTime, recomputeTooltips],
  );

  return (
    <div className="space-y-6 bg-white -m-4 p-4 min-h-full">
      <h2 className="text-lg font-semibold">Fortune</h2>
      <div className="flex flex-wrap items-center gap-2">
        {Object.entries(TIME_RANGES).map(([key, cfg]) => {
          const typedKey = key as TimeRangeKey;
          const isActive = timeRange === typedKey;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setTimeRange(typedKey)}
              className={`rounded-full border px-3 py-1 text-sm transition ${
                isActive
                  ? "border-amber-500 bg-amber-100 text-amber-700"
                  : "border-gray-200 text-gray-600 hover:border-amber-300 hover:text-amber-600"
              }`}
            >
              {cfg.label}
            </button>
          );
        })}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-3xl border border-amber-200 bg-gradient-to-br from-amber-50 via-amber-100 to-white p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-600">Fortune actuelle</p>
              <p className="mt-2 text-3xl font-bold text-amber-900">
                {currentFortune != null ? formatKamas(currentFortune) : "—"}
              </p>
            </div>
            <div className="hidden h-12 w-12 items-center justify-center rounded-full bg-white/70 text-2xl text-amber-500 sm:flex">
              💰
            </div>
          </div>
        </div>
        <div
          className={`rounded-3xl border bg-gradient-to-br p-5 shadow-sm ${
            totalProfit > 0
              ? "border-emerald-200 from-emerald-50 via-emerald-100 to-white"
              : totalProfit < 0
                ? "border-rose-200 from-rose-50 via-rose-100 to-white"
                : "border-slate-200 from-slate-50 via-slate-100 to-white"
          }`}
        >
          <div className="flex items-center justify-between">
            <div>
              <p
                className={`text-xs font-semibold uppercase tracking-wide ${
                  totalProfit > 0
                    ? "text-emerald-600"
                    : totalProfit < 0
                      ? "text-rose-600"
                      : "text-slate-600"
                }`}
              >
                Bénéfice total
              </p>
              <p
                className={`mt-2 text-3xl font-bold ${
                  totalProfit > 0
                    ? "text-emerald-700"
                    : totalProfit < 0
                      ? "text-rose-600"
                      : "text-slate-700"
                }`}
              >
                {formatKamasDelta(totalProfit)}
              </p>
            </div>
            <div
              className={`hidden h-12 w-12 items-center justify-center rounded-full bg-white/70 text-2xl sm:flex ${
                totalProfit > 0
                  ? "text-emerald-500"
                  : totalProfit < 0
                    ? "text-rose-500"
                    : "text-slate-500"
              }`}
            >
              📈
            </div>
          </div>
        </div>
      </div>
      <div className="relative h-[360px]">
        <Line ref={chartRef} data={data} options={options} style={{ height: "100%" }} />
        <div className="pointer-events-none absolute inset-0">
          {tooltipGroups.map((group) => {
            const isActive = hoveredTooltipId === group.id;
            const purchaseCount = group.purchases.length;
            return (
              <div key={group.id}>
                <button
                  type="button"
                  className="pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2 h-3 w-3 rounded-full border border-white bg-amber-500 shadow transition hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
                  style={{ left: `${group.anchorX}px`, top: `${group.anchorY}px` }}
                  onMouseEnter={() => showTooltip(group.id)}
                  onMouseLeave={() => scheduleHideTooltip(group.id)}
                  onFocus={() => showTooltip(group.id)}
                  onBlur={() => scheduleHideTooltip(group.id)}
                  aria-label={`Afficher ${purchaseCount} ${purchaseCount > 1 ? "achats" : "achat"}`}
                />
                {isActive && (
                  <div
                    className="pointer-events-auto absolute -translate-x-1/2"
                    style={{ left: `${group.tooltipLeft}px`, top: `${group.tooltipTop}px` }}
                    onMouseEnter={() => showTooltip(group.id)}
                    onMouseLeave={() => scheduleHideTooltip(group.id)}
                  >
                    <div className="flex flex-col gap-1 rounded-lg border border-amber-300 bg-white/95 px-2 py-1 text-xs shadow-md">
                      {group.purchases.map((purchase, idx) => {
                        const quantityLabel =
                          purchase.quantityLabel ??
                          (purchase.quantity > 0 ? `x${purchase.quantity}` : "?");
                        const key = `${purchase.id}-${purchase.datetime}-${idx}`;
                        const img = buildImgSrc(purchase.imgBlob);
                        const { saleTotal, profit: saleProfit } = computeSaleStats(purchase);
                        const saleDetails: string[] = [];
                        if (saleTotal != null && saleProfit != null) {
                          saleDetails.push(formatKamasDelta(saleProfit));
                          if (purchase.totalPrice > 0) {
                            const percent = (saleProfit / purchase.totalPrice) * 100;
                            if (Number.isFinite(percent)) {
                              saleDetails.push(formatPercentDelta(percent));
                            }
                          }
                        }
                        const deltaClass =
                          saleProfit != null
                            ? saleProfit > 0
                              ? "text-emerald-600"
                              : saleProfit < 0
                                ? "text-rose-600"
                                : "text-gray-600"
                            : "text-emerald-600";
                        return (
                          <div key={key} className="flex items-center gap-1 whitespace-nowrap">
                            {img ? (
                              <img src={img} alt="" className="h-4 w-4 rounded object-cover" />
                            ) : (
                              <div className="h-4 w-4 rounded bg-gray-200" />
                            )}
                            <span>{quantityLabel}</span>
                            <span className="font-semibold text-amber-600">
                              {formatKamas(purchase.totalPrice)}
                            </span>
                            {saleTotal != null && (
                              <>
                                <span className="text-gray-400">→</span>
                                <span className="font-semibold text-emerald-600">
                                  {formatKamas(saleTotal)}
                                </span>
                                {saleDetails.length > 0 && (
                                  <span className={deltaClass}>
                                    ({saleDetails.join(", ")})
                                  </span>
                                )}
                              </>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
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
