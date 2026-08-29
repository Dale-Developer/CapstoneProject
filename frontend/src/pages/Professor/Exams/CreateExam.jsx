import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getClasses } from "../../../api/classesApi";
import {
  createExam,
  downloadExamPdf,
  getExam,
  updateExam,
  previewExamPdf,
  openBlobInNewTab,
} from "../../../api/examsApi";

// Technical criterion names are kept internally for backend/AI compatibility.
// The professor-facing labels use simpler terminology, with the technical
// term shown underneath in the rubric UI.
// Canonical criterion names. These strings are what gets stored in
// exam_rubrics.criterion_name and what backend/services/rubric.py resolves,
// so the rubric configured here is literally the rubric the AI grades with.
//
// Keyword/Terminology is deliberately NOT a default criterion: keywords are
// supporting evidence for Key Ideas rather than their own slice of the score.
// Legacy exams that configured it still grade with it.
const DEFAULT_RUBRIC = [
  { name: "Semantic Relevance", weight: 35 },
  { name: "Concept Coverage", weight: 30 },
  { name: "Requirement Fulfillment", weight: 20 },
  { name: "Grammar/Clarity", weight: 10 },
  { name: "Structure", weight: 5 },
];

const RUBRIC_DISPLAY = {
  "Semantic Relevance": {
    label: "Answer Relevance",
    description: "How closely the answer matches the meaning of the expected answer.",
    technical: "Semantic Relevance",
    implementation: "Sentence-BERT semantic comparison",
    requires: "answerKey",
    requiresLabel: "an answer key",
  },
  "Concept Coverage": {
    label: "Key Ideas",
    description: "Whether the important ideas expected in the answer are included.",
    technical: "Concept Coverage",
    implementation: "Concept matching with spaCy (keywords count as supporting evidence)",
    requires: "keyConcepts",
    requiresLabel: "at least one key concept",
  },
  "Requirement Fulfillment": {
    label: "Answer Completeness",
    description: "Whether all required parts of the question are answered.",
    technical: "Requirement Fulfillment",
    implementation: "Requirement matching",
    requires: "requirements",
    requiresLabel: "at least one requirement",
  },
  "Grammar/Clarity": {
    label: "Writing Quality",
    description: "Clarity and basic grammatical quality of the response.",
    technical: "Grammar/Clarity",
    implementation: "spaCy analysis; spelling has limited influence because of OCR",
    requires: null,
  },
  Structure: {
    label: "Organization and Structure",
    description: "Whether the response matches the expected response format.",
    technical: "Structure",
    implementation: "Response-format fit",
    requires: null,
  },
  "Keyword/Terminology": {
    label: "Important Terms",
    description: "Whether relevant subject-specific terms are used. Optional \u2014 keywords already support Key Ideas.",
    technical: "Keyword/Terminology",
    implementation: "Keyword coverage",
    requires: "keywords",
    requiresLabel: "at least one keyword",
  },
};

// Professor-selectable response formats. The chosen value is saved and drives
// the Organization and Structure criterion at grading time.
const RESPONSE_FORMATS = [
  { value: "one_word", label: "One word", hint: "A single term or name" },
  { value: "one_sentence", label: "One sentence", hint: "A single complete sentence" },
  { value: "few_sentences", label: "A few sentences", hint: "Roughly 2-4 sentences" },
  { value: "one_paragraph", label: "One paragraph", hint: "A single developed paragraph" },
  { value: "multi_paragraph", label: "Multiple paragraphs", hint: "Several connected paragraphs" },
  { value: "essay", label: "Full essay", hint: "An extended, structured response" },
];

const getRubricDisplay = (criterionName) =>
  RUBRIC_DISPLAY[criterionName] || {
    label: criterionName,
    description: "Grading criterion for this essay question.",
    technical: criterionName,
    implementation: "Configured grading criterion",
    requires: null,
  };

const createRubric = () =>
  DEFAULT_RUBRIC.map((criterion) => ({
    id: crypto.randomUUID(),
    name: criterion.name,
    weight: criterion.weight,
  }));

const createMcqQuestion = () => ({
  id: crypto.randomUUID(),
  question: "",
  options: ["", "", "", "", ""],
  correctAnswer: "",
  points: 1,
});

const createEssayQuestion = () => ({
  id: crypto.randomUUID(),
  question: "",
  answerKey: "",
  keyConcepts: [],
  keywords: [],
  requirements: [],
  points: 10,
  expectedResponseFormat: "one_paragraph",
  rubric: createRubric(),
});

const normalizeList = (value) => (Array.isArray(value) ? value.filter((item) => String(item).trim()) : []);

const normalizeRubric = (rubric) => {
  if (!Array.isArray(rubric) || !rubric.length) return createRubric();
  return rubric.map((criterion) => ({
    id: String(criterion.id ?? crypto.randomUUID()),
    name: criterion.name || "",
    weight: Number(criterion.weight) || 0,
  }));
};

function CreateExam() {
  const navigate = useNavigate();
  const { examId } = useParams();
  const isEditMode = Boolean(examId);

  const [step, setStep] = useState(1);
  const [loadError, setLoadError] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [classes, setClasses] = useState([]);
  const [loadingClasses, setLoadingClasses] = useState(true);

  const [examInfo, setExamInfo] = useState({
    title: "",
    subject: "",
  });

  const [mcqQuestions, setMcqQuestions] = useState([createMcqQuestion()]);
  const [essayQuestions, setEssayQuestions] = useState([createEssayQuestion()]);
  const [selectedClasses, setSelectedClasses] = useState([]);
  // An exam may contain MCQ only, Essay only, or both.
  const [examTypes, setExamTypes] = useState(["mcq", "essay"]);

  useEffect(() => {
    let active = true;

    getClasses()
      .then((data) => {
        if (active) setClasses(Array.isArray(data) ? data : []);
      })
      .catch((err) => {
        if (active) setSaveError(err.message || "Unable to load your classes.");
      })
      .finally(() => {
        if (active) setLoadingClasses(false);
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!isEditMode) return;

    let active = true;
    setLoadError("");

    getExam(examId)
      .then((existing) => {
        if (!active) return;

        setExamInfo({
          title: existing.title || "",
          subject: existing.subject || "",
        });

        if (Array.isArray(existing.mcqQuestions) && existing.mcqQuestions.length) {
          setMcqQuestions(
            existing.mcqQuestions.map((q) => ({
              id: String(q.id),
              question: q.question || "",
              options: [...(q.options || []), "", "", "", "", ""].slice(0, 5),
              correctAnswer: q.correctAnswer ?? "",
              points: Number(q.points) > 0 ? Number(q.points) : 1,
            }))
          );
        } else {
          setMcqQuestions([]);
        }

        const legacyRubric = normalizeRubric(existing.rubric);
        if (Array.isArray(existing.essayQuestions) && existing.essayQuestions.length) {
          setEssayQuestions(
            existing.essayQuestions.map((q) => ({
              id: String(q.id),
              question: q.question || "",
              answerKey: q.answerKey || "",
              keyConcepts: normalizeList(q.keyConcepts),
              keywords: normalizeList(q.keywords),
              requirements: normalizeList(q.requirements),
              points: Number(q.points) > 0 ? Number(q.points) : 10,
              expectedResponseFormat: q.expectedResponseFormat || "one_paragraph",
              rubric: normalizeRubric(
                Array.isArray(q.rubric) && q.rubric.length ? q.rubric : legacyRubric
              ),
            }))
          );
        } else {
          setEssayQuestions([]);
        }

        setSelectedClasses(existing.classId ? [existing.classId] : []);
        const loadedTypes = [];
        if (Array.isArray(existing.mcqQuestions) && existing.mcqQuestions.length) loadedTypes.push("mcq");
        if (Array.isArray(existing.essayQuestions) && existing.essayQuestions.length) loadedTypes.push("essay");
        setExamTypes(loadedTypes.length ? loadedTypes : ["mcq"]);
      })
      .catch((err) => {
        if (active) setLoadError(err.message || "The examination could not be found.");
      });

    return () => {
      active = false;
    };
  }, [examId, isEditMode]);

  const rubricTotals = useMemo(
    () =>
      essayQuestions.map((question) => ({
        id: question.id,
        total: question.rubric.reduce((sum, criterion) => sum + (Number(criterion.weight) || 0), 0),
      })),
    [essayQuestions]
  );

  const allRubricsValid = useMemo(
    () => essayQuestions.every((question) => {
      const total = question.rubric.reduce((sum, criterion) => sum + (Number(criterion.weight) || 0), 0);
      return Math.abs(total - 100) <= 0.01;
    }),
    [essayQuestions]
  );

  const updateMcq = (id, field, value) =>
    setMcqQuestions((prev) =>
      prev.map((q) => (q.id === id ? { ...q, [field]: value } : q))
    );

  const updateOption = (qId, index, value) =>
    setMcqQuestions((prev) =>
      prev.map((q) => {
        if (q.id !== qId) return q;
        const options = [...q.options];
        options[index] = value;
        return { ...q, options };
      })
    );

  const removeMcqQuestion = (id) =>
    setMcqQuestions((prev) => prev.filter((q) => q.id !== id));

  const updateEssay = (id, field, value) =>
    setEssayQuestions((prev) =>
      prev.map((q) => (q.id === id ? { ...q, [field]: value } : q))
    );

  const updateEssayList = (id, field, index, value) =>
    setEssayQuestions((prev) =>
      prev.map((q) => {
        if (q.id !== id) return q;
        const values = [...(q[field] || [])];
        values[index] = value;
        return { ...q, [field]: values };
      })
    );

  const addEssayListItem = (id, field) =>
    setEssayQuestions((prev) =>
      prev.map((q) => (q.id === id ? { ...q, [field]: [...(q[field] || []), ""] } : q))
    );

  const removeEssayListItem = (id, field, index) =>
    setEssayQuestions((prev) =>
      prev.map((q) => {
        if (q.id !== id) return q;
        return { ...q, [field]: (q[field] || []).filter((_, itemIndex) => itemIndex !== index) };
      })
    );

  const removeEssayQuestion = (id) =>
    setEssayQuestions((prev) => prev.filter((q) => q.id !== id));

  const updateRubricWeight = (questionId, rubricId, value) =>
    setEssayQuestions((prev) =>
      prev.map((q) => {
        if (q.id !== questionId) return q;
        return {
          ...q,
          rubric: q.rubric.map((criterion) =>
            criterion.id === rubricId
              ? { ...criterion, weight: value === "" ? "" : Math.max(0, Math.min(100, Number(value) || 0)) }
              : criterion
          ),
        };
      })
    );

  const toggleClass = (classId) =>
    setSelectedClasses((prev) =>
      prev.includes(classId)
        ? prev.filter((id) => id !== classId)
        : [...prev, classId]
    );

  const toggleExamType = (type) => {
    setExamTypes((prev) => {
      if (prev.includes(type)) {
        if (prev.length === 1) return prev;
        return prev.filter((item) => item !== type);
      }
      return [...prev, type];
    });
  };

  const validateQuestions = () => {
    if (!examTypes.length) {
      return "Select at least one examination type: Multiple Choice or Essay.";
    }
    if (examTypes.includes("mcq") && !mcqQuestions.length) {
      return "Add at least one multiple-choice question.";
    }
    if (examTypes.includes("essay") && !essayQuestions.length) {
      return "Add at least one essay question.";
    }

    if (examTypes.includes("mcq")) for (let i = 0; i < mcqQuestions.length; i += 1) {
      const q = mcqQuestions[i];
      if (!q.question.trim()) return `Multiple-choice question ${i + 1} is empty.`;
      if (q.options.length !== 5 || q.options.some((x) => !String(x).trim())) {
        return `Multiple-choice question ${i + 1} must have five options (A-E).`;
      }
      if (q.correctAnswer === "" || q.correctAnswer === null) {
        return `Select the correct answer for multiple-choice question ${i + 1}.`;
      }
      if (!(Number(q.points) > 0)) {
        return `Multiple-choice question ${i + 1} must have points greater than 0.`;
      }
    }

    if (examTypes.includes("essay")) for (let i = 0; i < essayQuestions.length; i += 1) {
      const q = essayQuestions[i];
      if (!q.question.trim()) return `Essay question ${i + 1} is empty.`;
      if (!q.answerKey.trim()) return `Reference answer for essay question ${i + 1} is required.`;
      if (!(Number(q.points) > 0)) return `Essay question ${i + 1} must have points greater than 0.`;
      const total = q.rubric.reduce((sum, criterion) => sum + (Number(criterion.weight) || 0), 0);
      if (Math.abs(total - 100) > 0.01) {
        return `Rubric for essay question ${i + 1} must total 100%. Current total: ${total}%.`;
      }

      // Mirror of the backend check: a weighted criterion whose grading input
      // is missing would have to be skipped at grading time, which would mean
      // the professor's configured rubric is not the one that actually runs.
      for (const criterion of q.rubric) {
        const weight = Number(criterion.weight) || 0;
        if (weight <= 0) continue;
        const display = getRubricDisplay(criterion.name);
        if (!display.requires) continue;
        const evidence = q[display.requires];
        const filled = Array.isArray(evidence)
          ? evidence.filter((x) => String(x).trim()).length > 0
          : String(evidence || "").trim().length > 0;
        if (!filled) {
          return `Essay question ${i + 1}: "${display.label}" is weighted at ${weight}% but the question has no ${display.requiresLabel}. Add it, or set that criterion to 0%.`;
        }
      }
    }

    return "";
  };

  // Full validation is only used when the professor is ready to save/print.
  // Class selection intentionally belongs to Step 4, so it must not block
  // the transition from Step 2 to Step 3.
  const validateBeforeSave = () => {
    if (!examInfo.title.trim() || !examInfo.subject.trim()) {
      return "Exam title and subject are required.";
    }
    if (!selectedClasses.length) {
      return "Select at least one class.";
    }
    return validateQuestions();
  };

  const buildPayload = () => ({
    title: examInfo.title.trim(),
    subject: examInfo.subject.trim(),
    classIds: selectedClasses.map(Number),
    mcqQuestions: examTypes.includes("mcq") ? mcqQuestions.map(({ id, ...q }) => ({
      ...q,
      points: Number(q.points),
      correctAnswer: q.correctAnswer === "" ? null : Number(q.correctAnswer),
    })) : [],
    essayQuestions: examTypes.includes("essay") ? essayQuestions.map(({ id, ...q }) => ({
      ...q,
      points: Number(q.points),
      keyConcepts: normalizeList(q.keyConcepts),
      keywords: normalizeList(q.keywords),
      requirements: normalizeList(q.requirements),
      // Send the professor's actual choice. This used to be hard-coded to
      // "one_paragraph", which discarded the selection.
      expectedResponseFormat: q.expectedResponseFormat || "one_paragraph",
      rubric: q.rubric.map(({ id: rubricId, ...criterion }) => ({
        ...criterion,
        weight: Number(criterion.weight) || 0,
      })),
    })) : [],
    status: "Draft",
  });

  const handlePreview = async () => {
    const validationError = validateBeforeSave();
    if (validationError) {
      setSaveError(validationError);
      return;
    }
    setPreviewing(true);
    setSaveError("");
    try {
      const blob = await previewExamPdf(buildPayload());
      openBlobInNewTab(blob);
    } catch (err) {
      setSaveError(err.message || "Unable to generate the printable preview.");
    } finally {
      setPreviewing(false);
    }
  };

  const handleSave = async () => {
    const validationError = validateBeforeSave();
    if (validationError) {
      setSaveError(validationError);
      return;
    }

    setSaving(true);
    setSaveError("");

    try {
      const payload = buildPayload();
      const result = isEditMode
        ? { exam: await updateExam(examId, payload) }
        : await createExam(payload);

      const printableExamId = result.exam.id;
      await downloadExamPdf(printableExamId);

      navigate(`/Professor/classes/${result.exam.classId}/exams/${printableExamId}`, {
        replace: true,
      });
    } catch (err) {
      setSaveError(err.message || "Unable to save the examination.");
    } finally {
      setSaving(false);
    }
  };

  if (loadError) {
    return (
      <div className="w-full min-h-full px-4 py-6">
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-6 py-16 text-center">
          <i className="bx bx-error-circle text-4xl text-red-400" />
          <h2 className="mt-3 text-lg font-semibold text-gray-800">Examination not found</h2>
          <p className="mt-1 text-sm text-gray-500">{loadError}</p>
          <button
            onClick={() => navigate("/Professor/exams")}
            className="mt-5 rounded-full border border-gray-300 px-5 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Back to exams
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full min-h-full px-3 pb-24 pt-3 sm:px-4 sm:pb-8 sm:pt-4 md:px-5 md:pb-8 md:pt-5 lg:px-6">
      <div className="flex min-h-[calc(100dvh-104px)] flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_6px_24px_rgba(15,23,42,0.06)] sm:min-h-[calc(100dvh-118px)]">
        <div className="flex min-h-[58px] items-center justify-between gap-3 border-b border-slate-200 px-4 py-3 sm:px-5 md:px-6">
          <button onClick={() => navigate(-1)} className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900">
            <i className="bx bx-arrow-back text-xl" />
            <span>Back</span>
          </button>
          <div className="flex items-center gap-2">
            {[1, 2, 3, 4].map((s) => (
              <span
                key={s}
                className={`grid h-7 w-7 place-items-center rounded-full text-xs font-semibold ${
                  s === step
                    ? "bg-[#1A73E8] text-white"
                    : s < step
                    ? "bg-[#1A73E8] text-white opacity-70"
                    : "bg-gray-200 text-gray-500"
                }`}
              >
                {s < step ? "✓" : s}
              </span>
            ))}
          </div>
          <div className="w-16" />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-5 sm:py-6 md:px-6 md:py-7">
          {saveError && (
            <div className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {saveError}
            </div>
          )}

          {step === 1 && <StepExamInfo examInfo={examInfo} setExamInfo={setExamInfo} />}

          {step === 2 && (
            <StepQuestions
              mcqQuestions={mcqQuestions}
              essayQuestions={essayQuestions}
              examTypes={examTypes}
              toggleExamType={toggleExamType}
              updateMcq={updateMcq}
              updateOption={updateOption}
              removeMcqQuestion={removeMcqQuestion}
              addMcqQuestion={() => setMcqQuestions((prev) => [...prev, createMcqQuestion()])}
              setMcqQuestions={setMcqQuestions}
              updateEssay={updateEssay}
              updateEssayList={updateEssayList}
              addEssayListItem={addEssayListItem}
              removeEssayListItem={removeEssayListItem}
              removeEssayQuestion={removeEssayQuestion}
              addEssayQuestion={() => setEssayQuestions((prev) => [...prev, createEssayQuestion()])}
              setEssayQuestions={setEssayQuestions}
            />
          )}

          {step === 3 && (
            <StepRubric
              essayQuestions={examTypes.includes("essay") ? essayQuestions : []}
              updateRubricWeight={updateRubricWeight}
              rubricTotals={rubricTotals}
            />
          )}

          {step === 4 && (
            <StepSelectClasses
              classes={classes}
              loadingClasses={loadingClasses}
              selectedClasses={selectedClasses}
              toggleClass={toggleClass}
              handlePreview={handlePreview}
              previewing={previewing}
            />
          )}
        </div>

        <div className="shrink-0 border-t border-slate-200 bg-white px-4 py-3.5 sm:px-5 sm:py-4 md:px-6">
          {step === 1 && (
            <div className="flex justify-end">
              <button
                disabled={!examInfo.title.trim() || !examInfo.subject.trim()}
                onClick={() => setStep(2)}
                className="rounded-full bg-[#1A73E8] px-5 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40 hover:bg-[#1557b0]"
              >
                Continue
              </button>
            </div>
          )}

          {step === 2 && (
            <div className="flex items-center justify-between gap-3">
              <button onClick={() => setStep(1)} className="rounded-full border border-gray-300 px-5 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50">
                Previous
              </button>
              <button
                onClick={() => {
                  const validationError = validateQuestions();
                  if (validationError) { setSaveError(validationError); return; }
                  setSaveError("");
                  setStep(3);
                }}
                className="rounded-full bg-[#1A73E8] px-6 py-2 text-sm font-medium text-white hover:bg-[#1557b0]"
              >
                Next
              </button>
            </div>
          )}

          {step === 3 && (
            <div className="flex items-center justify-between gap-3">
              <button onClick={() => setStep(2)} className="rounded-full border border-gray-300 px-5 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50">
                Previous
              </button>
              <button
                disabled={examTypes.includes("essay") && !allRubricsValid}
                onClick={() => setStep(4)}
                className="rounded-full bg-[#1A73E8] px-6 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40 hover:bg-[#1557b0]"
              >
                Next
              </button>
            </div>
          )}

          {step === 4 && (
            <div className="flex items-center justify-between gap-3">
              <button onClick={() => setStep(3)} className="rounded-full border border-gray-300 px-5 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50">
                Previous
              </button>
              <button
                onClick={handleSave}
                disabled={saving || !selectedClasses.length}
                className="rounded-full bg-[#1A73E8] px-6 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40 hover:bg-[#1557b0]"
              >
                {saving ? "Saving and generating..." : isEditMode ? "Save & Print" : "Create & Print"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StepExamInfo({ examInfo, setExamInfo }) {
  const update = (field) => (e) =>
    setExamInfo((prev) => ({ ...prev, [field]: e.target.value }));

  return (
    <>
      <div className="mb-6">
        <h2 className="text-xl font-medium text-gray-800">Exam Information</h2>
        <p className="mt-0.5 text-sm text-slate-500">This is a paper-based major examination. These details are printed on the questionnaire.</p>
      </div>

      <div className="space-y-5">
        <div>
          <label className="mb-1.5 block text-sm font-medium text-gray-700">Title *</label>
          <input value={examInfo.title} onChange={update("title")} placeholder="Major Examination" className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20" />
        </div>

        <div>
          <label className="mb-1.5 block text-sm font-medium text-gray-700">Subject *</label>
          <input value={examInfo.subject} onChange={update("subject")} placeholder="Subject" className="w-full rounded-lg border border-gray-300 px-4 py-2.5 text-sm outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20" />
        </div>
      </div>
    </>
  );
}

function TagListEditor({ label, values, onChange, onAdd, onRemove, placeholder }) {
  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <label className="block text-sm font-medium text-gray-700">{label}</label>
        <button type="button" onClick={onAdd} className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2.5 py-1 text-[11px] font-bold text-[#1A73E8] hover:bg-blue-50">
          <i className="bx bx-plus" /> Add
        </button>
      </div>
      {values.length === 0 ? (
        <p className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-2.5 text-xs text-slate-400">No {label.toLowerCase()} added yet.</p>
      ) : (
        <div className="space-y-2">
          {values.map((value, index) => (
            <div key={`${label}-${index}`} className="flex items-center gap-2">
              <input
                value={value}
                onChange={(e) => onChange(index, e.target.value)}
                placeholder={placeholder}
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20"
              />
              <button type="button" onClick={() => onRemove(index)} className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-slate-400 hover:bg-red-50 hover:text-red-500" aria-label={`Remove ${label}`}>
                <i className="bx bx-trash" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StepQuestions({
  mcqQuestions,
  essayQuestions,
  examTypes,
  toggleExamType,
  updateMcq,
  updateOption,
  removeMcqQuestion,
  addMcqQuestion,
  setMcqQuestions,
  updateEssay,
  updateEssayList,
  addEssayListItem,
  removeEssayListItem,
  removeEssayQuestion,
  addEssayQuestion,
  setEssayQuestions,
}) {
  return (
    <>
      <div className="mb-7 rounded-2xl border border-slate-200 bg-slate-50 p-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-800">Examination Type</h2>
          <p className="mt-1 text-sm text-slate-500">Choose one or both. You do not need to include both question types.</p>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {[
            { key: "mcq", title: "Multiple Choice", desc: "Bubble-shaded answers detected with OpenCV OMR." },
            { key: "essay", title: "Essay", desc: "Handwritten responses processed with OCR and prepared for AI grading." },
          ].map((type) => {
            const active = examTypes.includes(type.key);
            return (
              <label key={type.key} className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 transition ${active ? "border-[#1A73E8] bg-white shadow-sm" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                <input type="checkbox" checked={active} onChange={() => toggleExamType(type.key)} className="mt-1 h-4 w-4 rounded text-[#1A73E8]" />
                <span>
                  <span className="block text-sm font-semibold text-gray-800">{type.title}</span>
                  <span className="mt-1 block text-xs leading-5 text-slate-500">{type.desc}</span>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      {examTypes.includes("mcq") && <div>
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500">Multiple Choice</h3>
            <p className="mt-1 text-xs text-slate-500">The printable answer sheet uses five bubbles: A, B, C, D, and E.</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700">{mcqQuestions.length} questions</span>
            <button
              type="button"
              onClick={() => {
                if (mcqQuestions.length < 60) {
                  const needed = 60 - mcqQuestions.length;
                  setMcqQuestions((prev) => [
                    ...prev,
                    ...Array.from({ length: needed }, () => createMcqQuestion()),
                  ]);
                }
              }}
              className="rounded-full border border-blue-200 px-3 py-1 text-[11px] font-bold text-blue-700 hover:bg-blue-50"
            >
              Add to 60
            </button>
          </div>
        </div>

        <div className="space-y-6">
          {mcqQuestions.map((q, index) => (
            <div key={q.id} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between">
                <span className="rounded bg-gray-100 px-2 py-0.5 text-sm font-medium text-gray-600">Q{index + 1}</span>
                <button onClick={() => removeMcqQuestion(q.id)} className="text-gray-400 hover:text-red-500" aria-label="Remove question">
                  <i className="bx bx-trash text-xl" />
                </button>
              </div>

              <div className="mt-3">
                <label className="mb-1 block text-sm text-gray-700">Question *</label>
                <input value={q.question} onChange={(e) => updateMcq(q.id, "question", e.target.value)} placeholder="Type your question" className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20" />
              </div>

              <div className="mt-4">
                <label className="mb-2 block text-sm text-gray-700">Options — select the correct answer</label>
                <div className="space-y-2">
                  {q.options.map((opt, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <input type="radio" name={`mcq-correct-${q.id}`} checked={q.correctAnswer === i} onChange={() => updateMcq(q.id, "correctAnswer", i)} className="h-4 w-4 text-[#1A73E8]" />
                      <span className="w-5 text-xs font-bold text-slate-500">{String.fromCharCode(65 + i)}</span>
                      <input value={opt} onChange={(e) => updateOption(q.id, i, e.target.value)} placeholder={`Option ${String.fromCharCode(65 + i)}`} className="flex-1 rounded-lg border border-gray-300 px-3 py-1.5 text-sm outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20" />
                    </div>
                  ))}
                </div>
              </div>

              <div className="mt-4 flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-700">Points per question</p>
                  <p className="text-xs text-slate-500">Set the score for this MCQ independently.</p>
                </div>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min="0.01"
                    step="0.5"
                    value={q.points}
                    onChange={(e) => updateMcq(q.id, "points", e.target.value)}
                    className="w-24 rounded-lg border border-gray-300 bg-white px-3 py-2 text-right text-sm font-semibold outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20"
                  />
                  <span className="text-xs font-medium text-slate-500">pts</span>
                </div>
              </div>
            </div>
          ))}
        </div>

        <button onClick={addMcqQuestion} className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-gray-300 py-3 text-sm font-medium text-[#1A73E8] hover:bg-[#1A73E8]/5">
          <i className="bx bx-plus" /> Add question
        </button>
      </div>}

      {examTypes.includes("essay") && <div className="mt-10">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-gray-500">Essay</h3>
            <p className="mt-1 text-xs text-slate-500">Choose a response format and grading rubric per question — graded automatically using spaCy and Sentence-BERT.</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="rounded-full bg-purple-50 px-3 py-1 text-xs font-bold text-purple-700">{essayQuestions.length} questions</span>
            <button
              type="button"
              onClick={() => {
                if (essayQuestions.length < 4) {
                  const needed = 4 - essayQuestions.length;
                  setEssayQuestions((prev) => [
                    ...prev,
                    ...Array.from({ length: needed }, () => createEssayQuestion()),
                  ]);
                }
              }}
              className="rounded-full border border-purple-200 px-3 py-1 text-[11px] font-bold text-purple-700 hover:bg-purple-50"
            >
              Add to 4
            </button>
          </div>
        </div>

        <div className="space-y-6">
          {essayQuestions.map((q, index) => (
            <div key={q.id} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between">
                <span className="rounded bg-gray-100 px-2 py-0.5 text-sm font-medium text-gray-600">Essay {index + 1}</span>
                <button onClick={() => removeEssayQuestion(q.id)} className="text-gray-400 hover:text-red-500" aria-label="Remove question">
                  <i className="bx bx-trash text-xl" />
                </button>
              </div>

              <div className="mt-3">
                <label className="mb-1 block text-sm text-gray-700">Question *</label>
                <textarea value={q.question} onChange={(e) => updateEssay(q.id, "question", e.target.value)} placeholder="Type your essay question" rows={2} className="w-full resize-y rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20" />
              </div>

              <div className="mt-4">
                <label className="mb-1 block text-sm text-gray-700">Reference Answer *</label>
                <textarea value={q.answerKey} onChange={(e) => updateEssay(q.id, "answerKey", e.target.value)} placeholder="Provide the reference answer used to evaluate semantic relevance and correctness." rows={4} className="w-full resize-y rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20" />
              </div>

              <div className="mt-4">
                <label className="mb-1 block text-sm text-gray-700">Expected Response Format *</label>
                <select
                  value={q.expectedResponseFormat || "one_paragraph"}
                  onChange={(e) => updateEssay(q.id, "expectedResponseFormat", e.target.value)}
                  className="w-full rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20"
                >
                  {RESPONSE_FORMATS.map((format) => (
                    <option key={format.value} value={format.value}>
                      {format.label} — {format.hint}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-[11px] leading-4 text-slate-500">
                  Used by the Organization and Structure criterion. An answer that fits the format you choose
                  scores full marks for structure; a short answer is not penalised unless the format calls for
                  a longer response.
                </p>
              </div>

              <TagListEditor
                label="Key Concepts"
                values={q.keyConcepts}
                onChange={(index, value) => updateEssayList(q.id, "keyConcepts", index, value)}
                onAdd={() => addEssayListItem(q.id, "keyConcepts")}
                onRemove={(index) => removeEssayListItem(q.id, "keyConcepts", index)}
                placeholder="e.g. confidentiality"
              />

              <TagListEditor
                label="Keywords / Terminology (supporting evidence for Key Ideas)"
                values={q.keywords}
                onChange={(index, value) => updateEssayList(q.id, "keywords", index, value)}
                onAdd={() => addEssayListItem(q.id, "keywords")}
                onRemove={(index) => removeEssayListItem(q.id, "keywords", index)}
                placeholder="e.g. data protection"
              />

              <TagListEditor
                label="Required Components"
                values={q.requirements}
                onChange={(index, value) => updateEssayList(q.id, "requirements", index, value)}
                onAdd={() => addEssayListItem(q.id, "requirements")}
                onRemove={(index) => removeEssayListItem(q.id, "requirements", index)}
                placeholder="e.g. Explain one benefit"
              />

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg bg-slate-50 px-3 py-3">
                  <label className="mb-1 block text-sm font-semibold text-gray-700">Points</label>
                  <input type="number" min="0.01" step="0.5" value={q.points} onChange={(e) => updateEssay(q.id, "points", e.target.value)} className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold outline-none focus:border-[#1A73E8] focus:ring-2 focus:ring-[#1A73E8]/20" />
                </div>
                <div className="rounded-lg bg-slate-50 px-3 py-3">
                  <label className="mb-1 block text-sm font-semibold text-gray-700">Expected Response</label>
                  <div className="flex h-[38px] items-center rounded-lg border border-gray-200 bg-white px-3 text-sm font-medium text-gray-600">One paragraph</div>
                </div>
              </div>
            </div>
          ))}
        </div>

        <button onClick={addEssayQuestion} className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-gray-300 py-3 text-sm font-medium text-[#1A73E8] hover:bg-[#1A73E8]/5">
          <i className="bx bx-plus" /> Add essay question
        </button>
      </div>}
    </>
  );
}

function StepRubric({ essayQuestions, updateRubricWeight, rubricTotals }) {
  if (!essayQuestions.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 py-12 text-center">
        <i className="bx bx-info-circle text-3xl text-slate-400" />
        <h2 className="mt-2 text-lg font-semibold text-gray-700">No essay questions</h2>
        <p className="mt-1 text-sm text-slate-500">The AI grading rubric applies to essay questions.</p>
      </div>
    );
  }

  return (
    <>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-medium text-gray-800">AI Grading Rubric</h2>
          <p className="text-sm text-gray-500">Weights are interchangeable per essay question and must total exactly 100%.</p>
        </div>
      </div>

      <div className="space-y-6">
        {essayQuestions.map((question, questionIndex) => {
          const total = rubricTotals.find((item) => item.id === question.id)?.total ?? 0;
          const valid = Math.abs(total - 100) <= 0.01;

          return (
            <section key={question.id} className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
              <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                  <span className="rounded bg-purple-50 px-2 py-1 text-xs font-bold text-purple-700">Essay {questionIndex + 1}</span>
                  <p className="mt-2 line-clamp-2 text-sm font-semibold text-gray-700">{question.question || "Untitled essay question"}</p>
                </div>
                <span className={`shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold ${valid ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}>
                  {total}% / 100%
                </span>
              </div>

              <div className="space-y-3">
                {question.rubric.map((criterion) => {
                  const display = getRubricDisplay(criterion.name);
                  const weight = Number(criterion.weight) || 0;
                  // A weighted criterion whose input is missing cannot be
                  // graded. Flagging it here stops the professor configuring
                  // a 40% criterion the engine would have to skip.
                  const evidence = display.requires ? question[display.requires] : null;
                  const hasEvidence =
                    !display.requires ||
                    (Array.isArray(evidence) ? evidence.filter((x) => String(x).trim()).length > 0 : String(evidence || "").trim().length > 0);
                  const blocked = weight > 0 && !hasEvidence;

                  return (
                    <div
                      key={criterion.id}
                      className={`rounded-xl border p-3 ${blocked ? "border-amber-300 bg-amber-50" : "border-gray-200 bg-slate-50"}`}
                    >
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
                        <span className="hidden h-2.5 w-2.5 shrink-0 rounded-full bg-[#1A73E8] sm:block" />
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-semibold text-gray-700">{display.label}</p>
                          <p className="text-[11px] font-medium text-slate-400">{display.technical}</p>
                          <p className="mt-0.5 text-[11px] leading-4 text-slate-500">{display.description}</p>
                          <p className="mt-0.5 text-[10px] text-slate-400">AI method: {display.implementation}</p>
                        </div>
                        <div className="flex w-full items-center gap-2 sm:w-28 sm:shrink-0">
                        <input
                          type="number"
                          min="0"
                          max="100"
                          step="1"
                          value={criterion.weight}
                          onChange={(e) => updateRubricWeight(question.id, criterion.id, e.target.value)}
                          className="w-20 rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-right text-sm font-semibold outline-none focus:border-[#1A73E8] sm:w-full"
                        />
                          <span className="text-sm text-gray-500">%</span>
                        </div>
                      </div>
                      {blocked && (
                        <p className="mt-2 rounded-lg bg-white/70 px-2.5 py-1.5 text-[11px] leading-4 text-amber-800">
                          This question has no {display.requiresLabel}, so {display.label} cannot be graded.
                          Add it above, or set this weight to 0 and give the percentage to another criterion.
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>

              {!valid && (
                <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs font-medium text-amber-700">
                  Rubric percentages for Essay {questionIndex + 1} must total exactly 100% before continuing.
                </div>
              )}
            </section>
          );
        })}
      </div>
    </>
  );
}

function StepSelectClasses({ classes, loadingClasses, selectedClasses, toggleClass, handlePreview, previewing }) {
  return (
    <>
      <h3 className="mb-1 text-lg font-medium text-gray-800">Select Classes</h3>
      <p className="mb-4 text-sm text-slate-500">The same paper-based major exam is saved for every selected class.</p>

      {loadingClasses ? (
        <div className="rounded-xl bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">Loading your classes...</div>
      ) : classes.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 px-4 py-10 text-center text-sm text-slate-500">
          Create a class first before creating an exam.
        </div>
      ) : (
        <div className="space-y-2">
          {classes.map((cls) => (
            <label
              key={cls.id}
              className={`flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 transition ${
                selectedClasses.includes(cls.id)
                  ? "border-[#1A73E8] bg-[#1A73E8]/5"
                  : "border-gray-200 hover:border-gray-300"
              }`}
            >
              <input
                type="checkbox"
                checked={selectedClasses.includes(cls.id)}
                onChange={() => toggleClass(cls.id)}
                className="h-4 w-4 rounded text-[#1A73E8]"
              />
              <div>
                <p className="text-sm font-semibold text-gray-700">
                  {cls.section ? `${cls.section} – ` : ""}{cls.title}
                </p>
                <p className="text-xs text-slate-500">{cls.subject}</p>
              </div>
            </label>
          ))}
        </div>
      )}

      <div className="mt-6">
        <h4 className="mb-3 text-sm font-medium text-gray-700">Printable preview</h4>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {selectedClasses.map((id) => {
            const cls = classes.find((item) => item.id === id);
            return (
              <div key={id} className="rounded-xl border border-gray-200 bg-slate-50 p-3 text-center">
                <div className="aspect-[8.5/13] rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
                  <i className="bx bxs-file-pdf text-3xl text-[#1A73E8]/40" />
                  <p className="mt-1 text-xs font-medium text-gray-600">{cls?.section || "Class"}</p>
                  <p className="text-[10px] text-gray-400">Questionnaire + answer sheet</p>
                </div>
                <button
                  type="button"
                  onClick={handlePreview}
                  disabled={previewing}
                  className="mt-3 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border border-[#1A73E8] px-3 py-2 text-xs font-bold text-[#1A73E8] hover:bg-[#1A73E8]/5 disabled:opacity-50"
                >
                  <i className={`bx ${previewing ? "bx-loader-alt bx-spin" : "bx-show"}`} />
                  {previewing ? "Generating..." : "View"}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}

export default CreateExam;