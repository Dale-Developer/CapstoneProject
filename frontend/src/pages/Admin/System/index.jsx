import { useCallback, useEffect, useState } from "react";
import { PageHeader, PageShell, StatCard } from "../../../components/prof/PageShell";
import { getAdminOverview, getSystemHealth } from "../../../api/adminApi";

function Dot({ ok }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${ok ? "bg-emerald-500" : "bg-rose-500"}`}
      aria-label={ok ? "available" : "unavailable"}
    />
  );
}

function Service({ name, ok, detail, error, children }) {
  return (
    <div className="rounded-xl border border-slate-200 p-4">
      <div className="mb-2 flex items-center gap-2">
        <Dot ok={ok} />
        <h3 className="font-bold text-[#0B1739]">{name}</h3>
        <span className={`ml-auto text-[11px] font-bold ${ok ? "text-emerald-600" : "text-rose-600"}`}>
          {ok ? "Available" : "Unavailable"}
        </span>
      </div>
      {detail && <p className="text-xs text-slate-500">{detail}</p>}
      {error && (
        <p className="mt-2 break-words rounded-lg bg-rose-50 px-3 py-2 text-[11px] leading-4 text-rose-700">
          {error}
        </p>
      )}
      {children}
    </div>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-slate-50 py-1.5 last:border-0">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="font-mono text-xs font-semibold text-slate-700">{String(value)}</span>
    </div>
  );
}

function AdminSystem() {
  const [health, setHealth] = useState(null);
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [h, o] = await Promise.all([getSystemHealth(), getAdminOverview()]);
      setHealth(h);
      setOverview(o);
      setError("");
    } catch (err) {
      setError(err.message || "Unable to read system status.");
    } finally {
      setLoading(false);
    }
  }, []);

  // Poll while the page is open: warmup finishes asynchronously after a
  // restart, so a single fetch can show "unavailable" for a service that is
  // seconds away from being ready.
  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  if (loading) {
    return (
      <PageShell>
        <p className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center text-sm text-slate-500">
          Reading system status…
        </p>
      </PageShell>
    );
  }

  const ollama = health?.ollama || {};
  const easyocr = health?.easyocr || {};
  const nlp = health?.nlp || {};
  const settings = health?.ocrSettings || {};
  const lastOllamaError = ollama.lastError?.error;

  return (
    <PageShell>
      <PageHeader
        eyebrow="Administration"
        title="System status"
        description="Live readiness of every AI component, refreshed every 15 seconds."
        action={
          <button
            onClick={load}
            className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-bold text-slate-600 hover:bg-slate-50"
          >
            <i className="bx bx-refresh text-lg" />
            Refresh
          </button>
        }
      />

      {error && (
        <div className="mb-5 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      )}

      {overview && (
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <StatCard label="Classes" value={overview.content.classes} icon="bx-book" />
          <StatCard label="Exams" value={overview.content.exams} icon="bx-file" />
          <StatCard label="Submissions" value={overview.content.submissions} icon="bx-scan"
            description={`${overview.content.submissionsThisWeek} this week`} />
          <StatCard label="Users" value={overview.users.total} icon="bx-group" />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h2 className="mb-4 font-bold text-[#0B1739]">Recognition</h2>
          <div className="space-y-3">
            <Service
              name="EasyOCR"
              ok={easyocr.available}
              detail={`Network ${easyocr.network} · ${easyocr.gpu ? "GPU" : "CPU"}`}
              error={easyocr.error}
            />
            <Service
              name="Ollama vision verifier"
              ok={ollama.available && ollama.verifyEnabled}
              detail={`${ollama.model} at ${ollama.baseUrl}`}
              error={ollama.error}
            >
              {!ollama.verifyEnabled && (
                <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-4 text-amber-800">
                  Verification is switched off (OLLAMA_OCR_VERIFY=false), so EasyOCR is
                  the only engine transcribing answers.
                </p>
              )}
              {lastOllamaError && (
                <p className="mt-2 break-words rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-4 text-amber-800">
                  Last call failed after {ollama.lastError.seconds}s: {lastOllamaError}
                </p>
              )}
            </Service>
            <Service name="OMR bubble detection" ok={health?.omr?.available} />
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5">
          <h2 className="mb-4 font-bold text-[#0B1739]">Grading</h2>
          <div className="space-y-3">
            <Service
              name="spaCy"
              ok={Boolean(nlp.spacy?.loaded ?? nlp.loaded)}
              detail={nlp.spacy?.model || nlp.model}
              error={nlp.spacy?.error || nlp.error}
            />
            <Service
              name="Sentence-BERT"
              ok={Boolean(nlp.sbert?.loaded)}
              detail={nlp.sbert?.model}
              error={nlp.sbert?.error}
            >
              {nlp.sbert && !nlp.sbert.loaded && (
                <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] leading-4 text-amber-800">
                  Answer Relevance is falling back to a lexical measure, which is a
                  documented degradation rather than an equal substitute.
                </p>
              )}
            </Service>
            <Service
              name="Spelling dictionary"
              ok={Boolean(nlp.spelling?.available ?? nlp.spelling?.backend)}
              detail={nlp.spelling?.backend || "pyspellchecker"}
              error={nlp.spelling?.reason}
            />
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5 lg:col-span-2">
          <h2 className="mb-1 font-bold text-[#0B1739]">Recognition settings</h2>
          <p className="mb-3 text-xs text-slate-500">
            From the server's .env. A scan that reads badly is more often a threshold
            than a broken model, so these are shown next to the service status.
          </p>
          <div className="grid gap-x-8 sm:grid-cols-2">
            <Row label="Decoder" value={settings.decoder} />
            <Row label="Preprocessing variants" value={settings.variants} />
            <Row label="Target width (px)" value={settings.targetWidth} />
            <Row label="Canvas size (px)" value={settings.canvasSize} />
            <Row label="Minimum plausibility" value={settings.minPlausibility} />
            <Row label="Verify essays below" value={settings.essayVerifyBelow} />
          </div>
        </section>
      </div>
    </PageShell>
  );
}

export default AdminSystem;
