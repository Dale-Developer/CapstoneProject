import { useEffect, useRef, useState } from "react";

/**
 * A single answer-sheet page slot.
 *
 * Before V7.9 a chosen file could only ever be swapped for another one —
 * there was no way to clear a mistaken pick, and no way to see what had
 * actually been captured before committing to it. Both are important on a
 * phone, where a camera scan can easily come out blurry or upside down.
 *
 * This component therefore always shows a thumbnail of the selected image
 * and exposes explicit Replace and Delete actions. `disabled` is used once a
 * submission has been processed and locked.
 */
export default function FileDropBox({
  label,
  file,
  onChange,
  onScan,
  disabled = false,
  hint = "Choose JPG, PNG, or PDF",
  accept = "image/*,.pdf",
}) {
  const inputRef = useRef(null);
  const [previewUrl, setPreviewUrl] = useState(null);

  // Object URLs must be revoked or every re-pick leaks a blob for the
  // lifetime of the tab, which matters when scanning a whole class.
  useEffect(() => {
    if (!file || !file.type?.startsWith("image/")) {
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const pick = () => {
    if (disabled) return;
    inputRef.current?.click();
  };

  const clear = () => {
    onChange(null);
    // Without this the same file cannot be re-selected after deleting it,
    // because the input's value would not change and no event would fire.
    if (inputRef.current) inputRef.current.value = "";
  };

  const isPdf = file && !file.type?.startsWith("image/");
  const sizeLabel = file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "";

  return (
    <div
      className={`rounded-2xl border-2 border-dashed p-4 transition ${
        disabled
          ? "border-slate-200 bg-slate-50 opacity-60"
          : file
          ? "border-[#291C57]/30 bg-white"
          : "border-slate-300 bg-white hover:border-[#291C57]/40 hover:bg-[#F9F7FC]"
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        className="hidden"
        disabled={disabled}
        onChange={(e) => onChange(e.target.files?.[0] || null)}
      />

      {!file ? (
        <div className="text-center">
          <button type="button" onClick={pick} disabled={disabled} className="block w-full disabled:cursor-not-allowed">
            <span className="mx-auto grid h-12 w-12 place-items-center rounded-xl bg-[#F1EFF7] text-2xl text-[#291C57]">
              <i className="bx bx-file-upload" />
            </span>
            <p className="mt-3 text-sm font-bold text-[#0B1739]">{label}</p>
            <p className="mt-1 text-xs text-slate-500">{hint}</p>
          </button>

          {onScan && (
            <button
              type="button"
              onClick={onScan}
              disabled={disabled}
              className="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-[#291C57]/5 px-3 py-1.5 text-xs font-bold text-[#291C57] hover:bg-[#291C57]/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <i className="bx bx-scan" /> Scan with camera
            </button>
          )}
        </div>
      ) : (
        <div>
          <div className="mb-2 flex items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-sm font-bold text-[#0B1739]">{label}</p>
              <p className="truncate text-xs text-slate-500" title={file.name}>
                {file.name} · {sizeLabel}
              </p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
              <i className="bx bx-check" /> Ready
            </span>
          </div>

          <div className="relative overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
            {previewUrl ? (
              <img src={previewUrl} alt={`${label} preview`} className="mx-auto max-h-56 w-auto object-contain" />
            ) : (
              <div className="flex h-32 items-center justify-center text-center text-slate-400">
                <div>
                  <i className={`bx ${isPdf ? "bxs-file-pdf" : "bxs-image"} text-4xl`} />
                  <p className="mt-1 text-xs">{isPdf ? "PDF selected" : "Preview unavailable"}</p>
                </div>
              </div>
            )}
          </div>

          {!disabled && (
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={pick}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50"
              >
                <i className="bx bx-refresh" /> Replace
              </button>
              {onScan && (
                <button
                  type="button"
                  onClick={onScan}
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-[#291C57]/5 px-3 py-2 text-xs font-bold text-[#291C57] hover:bg-[#291C57]/10"
                >
                  <i className="bx bx-scan" /> Rescan
                </button>
              )}
              <button
                type="button"
                onClick={clear}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs font-bold text-rose-600 hover:bg-rose-100"
              >
                <i className="bx bx-trash" /> Delete
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
