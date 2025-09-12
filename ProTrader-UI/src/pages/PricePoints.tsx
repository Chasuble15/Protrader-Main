import { useEffect, useState } from "react";
import Card from "../components/Card";
import {
  listHdvPricePoints,
  deleteHdvPricePoint,
  type HdvPricePoint,
} from "../api";

export default function PricePoints() {
  const [slug, setSlug] = useState("");
  const [qty, setQty] = useState("");
  const [points, setPoints] = useState<HdvPricePoint[]>([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const pts = await listHdvPricePoints(slug || undefined, qty || undefined, 200);
      setPoints(pts);
    } catch (e) {
      console.error("Failed to load points", e);
      setPoints([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleDelete = async (id: number) => {
    if (!confirm("Supprimer ce point ?")) return;
    try {
      await deleteHdvPricePoint(id);
      setPoints((prev) => prev.filter((p) => p.id !== id));
    } catch (e) {
      console.error("Failed to delete point", e);
    }
  };

  return (
    <Card>
      <h2 className="text-base font-semibold mb-2">Gestion des prix</h2>
      <div className="flex flex-wrap items-center gap-2 mb-4 text-sm">
        <input
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          placeholder="slug..."
          className="border rounded p-1"
        />
        <select
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          className="border rounded p-1"
        >
          <option value="">Toutes qty</option>
          <option value="x1">x1</option>
          <option value="x10">x10</option>
          <option value="x100">x100</option>
          <option value="x1000">x1000</option>
        </select>
        <button
          onClick={load}
          className="border rounded px-2 py-1 hover:bg-slate-50"
        >
          Rafraîchir
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-left border-b">
              <th className="p-1">Slug</th>
              <th className="p-1">Qty</th>
              <th className="p-1">Prix</th>
              <th className="p-1">Date</th>
              <th className="p-1"></th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.id} className="border-b hover:bg-slate-50">
                <td className="p-1">{p.slug}</td>
                <td className="p-1">{p.qty}</td>
                <td className="p-1">{p.price}</td>
                <td className="p-1">{new Date(p.datetime).toLocaleString()}</td>
                <td className="p-1">
                  <button
                    onClick={() => handleDelete(p.id)}
                    className="text-red-600 hover:underline"
                  >
                    Suppr
                  </button>
                </td>
              </tr>
            ))}
            {points.length === 0 && !loading && (
              <tr>
                <td colSpan={5} className="text-center p-2 text-slate-500">
                  Aucun point
                </td>
              </tr>
            )}
            {loading && (
              <tr>
                <td colSpan={5} className="text-center p-2 text-slate-500">
                  Chargement...
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

