import { useState } from "react";
import { NavLink, Routes, Route, useLocation } from "react-router-dom";
import ConfigEditor from "./pages/ConfigEditor";
import Home from "./pages/Home";
import Logs from "./pages/Logs";
import About from "./pages/About";
import Prices from "./pages/Prices";

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const location = useLocation();
  const titles: Record<string, string> = {
    "/": "Accueil",
    "/prices": "Historique des prix",
    "/config": "Éditeur de configuration",
    "/logs": "Journaux",
    "/about": "À propos",
  };
  const currentTitle = titles[location.pathname] || "";

  return (
    <div className="flex h-screen flex-col bg-slate-50 text-slate-800">
      {/* ----- TOP BAR ----- */}
      <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b bg-white/80 backdrop-blur px-4">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="inline-flex md:hidden items-center justify-center rounded-md border border-slate-300 px-2.5 py-1.5 text-sm hover:bg-slate-100"
            aria-label="Ouvrir/fermer le menu"
          >
          ☰
        </button>
        <h1 className="text-lg font-semibold">ProTrader</h1>
        <span className="ml-2 text-xs rounded-full bg-emerald-50 px-2 py-0.5 text-emerald-700 border border-emerald-200">
          v1
        </span>

        <div className="ml-auto hidden sm:block text-sm text-slate-500">{currentTitle}</div>
      </header>

      {/* ----- LAYOUT WRAPPER ----- */}
      <div className="flex flex-1 overflow-hidden">
        {/* ----- SIDEBAR ----- */}
        <aside
          className={[
            "bg-white/80 backdrop-blur border-r border-slate-200 overflow-y-auto transition-all",
            sidebarOpen ? "w-60" : "hidden md:block md:w-16",
          ].join(" ")}
        >
          <div className="h-full flex flex-col">
            <div className="px-3 py-2 border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              Navigation
            </div>

            <nav className="flex-1 p-2 space-y-1">
              <NavLink
                to="/"
                end
                className={({ isActive }: { isActive: boolean }) =>
                  [
                    "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
                    isActive
                      ? "bg-sky-50 border-sky-200 text-sky-800"
                      : "bg-white border-slate-200 hover:bg-slate-50",
                  ].join(" ")
                }
              >
                <span className="shrink-0">🏠</span>
                <span className="truncate">Accueil</span>
              </NavLink>
              <NavLink
                to="/prices"
                className={({ isActive }: { isActive: boolean }) =>
                  [
                    "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
                    isActive
                      ? "bg-sky-50 border-sky-200 text-sky-800"
                      : "bg-white border-slate-200 hover:bg-slate-50",
                  ].join(" ")
                }
              >
                <span className="shrink-0">📈</span>
                <span className="truncate">Prix</span>
              </NavLink>
              <NavLink
                to="/config"
                className={({ isActive }: { isActive: boolean }) =>
                  [
                    "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
                    isActive
                      ? "bg-sky-50 border-sky-200 text-sky-800"
                      : "bg-white border-slate-200 hover:bg-slate-50",
                  ].join(" ")
                }
              >
                <span className="shrink-0">🛠️</span>
                <span className="truncate">Éditeur de configuration</span>
              </NavLink>
              <NavLink
                to="/logs"
                className={({ isActive }: { isActive: boolean }) =>
                  [
                    "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
                    isActive
                      ? "bg-sky-50 border-sky-200 text-sky-800"
                      : "bg-white border-slate-200 hover:bg-slate-50",
                  ].join(" ")
                }
              >
                <span className="shrink-0">📜</span>
                <span className="truncate">Journaux</span>
              </NavLink>
              <NavLink
                to="/about"
                className={({ isActive }: { isActive: boolean }) =>
                  [
                    "flex items-center gap-2 px-3 py-2 rounded-lg border text-sm",
                    isActive
                      ? "bg-sky-50 border-sky-200 text-sky-800"
                      : "bg-white border-slate-200 hover:bg-slate-50",
                  ].join(" ")
                }
              >
                <span className="shrink-0">ℹ️</span>
                <span className="truncate">À propos</span>
              </NavLink>
            </nav>
          </div>
        </aside>

        {/* ----- MAIN CONTENT ----- */}
        <main className="flex-1 overflow-y-auto p-4">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/prices" element={<Prices />} />
            <Route path="/config" element={<ConfigEditor />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/about" element={<About />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
