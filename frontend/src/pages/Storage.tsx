import { useEffect, useState } from "react";
import { api, type Storage } from "../api";
import type { Key } from "../i18n";
import { usePrefs } from "../prefs";
import { errorText } from "../errors";

export function bytes(n: number, lang: "en" | "es"): string {
  const units = ["B", "KB", "MB", "GB"];
  let v = n;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i += 1;
  }
  return `${v.toLocaleString(lang, { maximumFractionDigits: v < 10 && i > 0 ? 1 : 0 })} ${units[i]}`;
}

/** What the video takes on disk, and deleting what can be made again (src/opendub/storage.py). */
export function StorageCard({ id, busy, onChanged }: { id: string; busy: boolean; onChanged: () => void }) {
  const { t, prefs } = usePrefs();
  const [open, setOpen] = useState(false);
  const [usage, setUsage] = useState<Storage | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (open) api.storage(id).then(setUsage).catch((e) => setNote(errorText(e, t)));
  }, [id, open]);

  const deletable = usage ? usage.groups.reduce((sum, g) => sum + g.bytes, 0) : 0;

  async function remove(group: string) {
    const lost = t(`st_${group}_lost` as Key);
    if (!confirm(t("st_confirm", { what: t(`st_${group}` as Key), lost }))) return;
    try {
      const r = await api.deleteStorage(id, group);
      setUsage(r);
      setNote(t("st_freed", { n: bytes(r.freed, prefs.lang) }));
      onChanged();
    } catch (err) {
      setNote(errorText(err, t));
    }
  }

  return (
    <section className="card stack" aria-labelledby="storage" style={{ padding: 16, gap: 12 }}>
      <h2 id="storage" style={{ fontSize: 15 }}>
        <button type="button" className="link-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "▾" : "▸"} {t("storage")}
        </button>{" "}
        {usage && (
          <span className="small faint" style={{ fontWeight: 400 }}>
            · {t("st_summary", { free: bytes(deletable, prefs.lang), kept: bytes(usage.kept, prefs.lang) })}
          </span>
        )}
      </h2>
      {open && usage && (
        <>
          <div className="table-box">
            <table className="data" style={{ minWidth: 640 }}>
              <thead>
                <tr>
                  <th scope="col">{t("st_group")}</th>
                  <th scope="col" style={{ textAlign: "right" }}>{t("st_size")}</th>
                  <th scope="col">{t("st_if_deleted")}</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {usage.groups.map((g) => (
                  <tr key={g.id}>
                    <td>{t(`st_${g.id}` as Key)}</td>
                    <td className="num small" style={{ textAlign: "right" }}>{g.bytes ? bytes(g.bytes, prefs.lang) : "—"}</td>
                    <td className="small">
                      <span style={{ display: "block" }}>{t(`st_${g.id}_lost` as Key)}</span>
                      <span className="muted">{t(`st_${g.id}_redo` as Key)}</span>
                    </td>
                    <td>
                      <button type="button" className="btn danger" disabled={busy || !g.bytes} onClick={() => void remove(g.id)}>
                        {t("delete")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <span className="small muted" role="status">{note ?? t("st_hint")}</span>
        </>
      )}
    </section>
  );
}
