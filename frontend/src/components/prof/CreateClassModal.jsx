import { useState } from "react";

function CreateClassModal({ isOpen, onClose, onCreate }) {
  const [className, setClassName] = useState("");
  const [section, setSection] = useState("");
  const [subject, setSubject] = useState("");
  const [selectedColor, setSelectedColor] = useState("#462776");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const presetColors = ["#462776", "#0B1739", "#EF4444", "#F59E0B", "#10B981", "#3B82F6", "#8B5CF6", "#EC4899", "#78716C", "#0891B2"];

  if (!isOpen) return null;

  const reset = () => {
    setClassName(""); setSection(""); setSubject(""); setSelectedColor("#462776"); setError(""); setIsSubmitting(false);
  };

  const close = () => { reset(); onClose(); };

  const handleCreate = async () => {
    if (!className.trim() || !subject.trim()) {
      setError("Class name and subject are required.");
      return;
    }
    setIsSubmitting(true); setError("");
    try {
      await onCreate?.({ className: className.trim(), section: section.trim() || null, subject: subject.trim(), color: selectedColor });
      close();
    } catch (err) {
      setError(err.message || "Unable to create the class.");
      setIsSubmitting(false);
    }
  };

  const previewTitle = section || className ? `${section || "Section"} – ${className || "Class Name"}` : "Section – Class Name";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4" onClick={close}>
      <div className="w-full max-w-sm overflow-hidden rounded-xl bg-white shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 pb-2 pt-5">
          <h2 className="text-base font-semibold text-[#462776]">Create Class</h2>
          <button onClick={close} aria-label="Close" className="text-slate-400 hover:text-slate-600"><i className="bx bx-x text-2xl" /></button>
        </div>

        <div className="space-y-4 px-5 pb-5">
          <div>
            <p className="mb-1 text-xs text-slate-500">Preview</p>
            <div className="flex overflow-hidden rounded-lg border border-slate-200">
              <div className="w-1.5" style={{ backgroundColor: selectedColor }} />
              <div className="flex-1 px-3 py-2.5"><p className="truncate text-sm font-medium text-[#0B1739]">{previewTitle}</p><p className="text-xs text-slate-400">{subject || "Subject"}</p></div>
            </div>
          </div>

          <div><label className="mb-1 block text-xs text-slate-500">Class Name</label><input type="text" value={className} onChange={(e) => setClassName(e.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-[#0B1739] focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#462776]" placeholder="e.g. Mathematics 101" /></div>
          <div><label className="mb-1 block text-xs text-slate-500">Section</label><input type="text" value={section} onChange={(e) => setSection(e.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-[#0B1739] focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#462776]" placeholder="e.g. BSIT 3A" /></div>
          <div><label className="mb-1 block text-xs text-slate-500">Subject</label><input type="text" value={subject} onChange={(e) => setSubject(e.target.value)} className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-[#0B1739] focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#462776]" placeholder="e.g. Web Systems and Technologies" /></div>

          <div><label className="mb-2 block text-xs text-slate-500">Cover Color</label><div className="flex flex-wrap items-center gap-2">{presetColors.map((color) => <button key={color} type="button" onClick={() => setSelectedColor(color)} className={`h-7 w-7 rounded-full transition-all hover:scale-110 focus:outline-none ${selectedColor === color ? "ring-2 ring-[#462776] ring-offset-2" : "ring-1 ring-slate-200"}`} style={{ backgroundColor: color }} aria-label={`Select color ${color}`} />)}<input type="color" value={selectedColor} onChange={(e) => setSelectedColor(e.target.value)} className="h-7 w-7 cursor-pointer rounded-full border-0 bg-transparent p-0" title="Custom Color" /></div></div>
          {error && <p className="text-sm font-medium text-red-600" role="alert">{error}</p>}
        </div>

        <div className="flex justify-end gap-4 px-5 pb-5 pt-1"><button onClick={close} className="text-sm font-medium text-[#462776] hover:opacity-80">Cancel</button><button onClick={handleCreate} disabled={isSubmitting} className="text-sm font-medium text-[#0B1739] hover:opacity-80 disabled:cursor-not-allowed disabled:text-slate-300">{isSubmitting ? "Creating..." : "Create"}</button></div>
      </div>
    </div>
  );
}

export default CreateClassModal;
