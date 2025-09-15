import { useEffect, useState } from "react";
import { Chart as ChartJS, LinearScale, PointElement, LineElement, Tooltip, Legend } from "chart.js";
import { Line } from "react-chartjs-2";
import { getKamasHistory, type KamasPoint } from "../api";

ChartJS.register(LinearScale, PointElement, LineElement, Tooltip, Legend);

const parseTimestamp = (t: string): number => {
  const n = Number(t);
  if (!Number.isNaN(n)) {
    return n < 1e12 ? n * 1000 : n;
  }
  return Date.parse(t.endsWith("Z") ? t : `${t}Z`);
};

export default function Fortune() {
  const [points, setPoints] = useState<KamasPoint[]>([]);

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
    </div>
  );
}
