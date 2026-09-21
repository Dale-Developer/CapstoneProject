import { useEffect, useRef, useState } from "react";
import { apiRequest } from "../../api/client";

const PAGE_ASPECT = 612 / 936;
const STABLE_FRAMES_REQUIRED = 3;

function pct(value) {
  const n = Number(value || 0);
  return `${Math.round(Math.max(0, Math.min(1, n)) * 100)}%`;
}

function polygonPoints(corners) {
  if (!Array.isArray(corners) || corners.length !== 4) return "";
  return corners
    .map((p) => `${Number(p?.[0] || 0)},${Number(p?.[1] || 0)}`)
    .join(" ");
}

// Smoothly interpolate toward the latest detected quad instead of snapping,
// so the tracking overlay glides the way ZipGrade / document-scanner apps do.
function lerpCorners(from, to, t) {
  if (!Array.isArray(to) || to.length !== 4) return from;
  if (!Array.isArray(from) || from.length !== 4) return to;
  return to.map((point, index) => {
    const prev = from[index] || point;
    return [
      prev[0] + (point[0] - prev[0]) * t,
      prev[1] + (point[1] - prev[1]) * t,
    ];
  });
}

export default function CameraScanner({
  open,
  onClose,
  onCapture,
  onError,
  instructions,
  examId,
  pageNumber = 1,
}) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const imageCaptureRef = useRef(null);
  const timerRef = useRef(null);
  const busyRef = useRef(false);
  const stableRef = useRef(0);
  const lastCornersRef = useRef(null);
  const previewFrameSizeRef = useRef({ width: 0, height: 0 });
  const closedRef = useRef(false);
  const cameraFrameRef = useRef(null);
  const targetCornersRef = useRef(null);
  const displayCornersRef = useRef(null);
  const rafRef = useRef(null);
  const lastVibrateRef = useRef(0);

  const [status, setStatus] = useState("Starting high-quality camera…");
  const [confidence, setConfidence] = useState(0);
  const [quality, setQuality] = useState(null);
  const [corners, setCorners] = useState(null);
  const [videoSize, setVideoSize] = useState({ width: 900, height: 1200 });
  const [markerCount, setMarkerCount] = useState(0);
  const [secureContext, setSecureContext] = useState(true);
  const [overlaySize, setOverlaySize] = useState({ width: 1, height: 1 });
  const [stableCount, setStableCount] = useState(0);
  const [flash, setFlash] = useState(false);
  const [captured, setCaptured] = useState(false);

  // Smoothly glide the on-screen quad toward the latest detection every
  // frame, instead of snapping it to a new position on every ~600ms poll.
  useEffect(() => {
    if (!open) return undefined;

    function tick() {
      const target = targetCornersRef.current;
      if (target) {
        const current = displayCornersRef.current || target;
        const next = lerpCorners(current, target, 0.35);
        displayCornersRef.current = next;
        setCorners(next);
      }
      rafRef.current = window.requestAnimationFrame(tick);
    }

    rafRef.current = window.requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) window.cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    };
  }, [open]);

  useEffect(() => {
    if (!open || !cameraFrameRef.current) return undefined;
    const element = cameraFrameRef.current;
    const updateSize = () => {
      const rect = element.getBoundingClientRect();
      setOverlaySize({ width: Math.max(1, rect.width), height: Math.max(1, rect.height) });
    };
    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(element);
    window.addEventListener("resize", updateSize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", updateSize);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;

    closedRef.current = false;
    stableRef.current = 0;
    busyRef.current = false;
    lastCornersRef.current = null;
    targetCornersRef.current = null;
    displayCornersRef.current = null;
    previewFrameSizeRef.current = { width: 0, height: 0 };
    setStatus("Starting high-quality camera…");
    setConfidence(0);
    setQuality(null);
    setCorners(null);
    setMarkerCount(0);
    setStableCount(0);
    setFlash(false);
    setCaptured(false);

    const isSecure = window.isSecureContext || window.location.hostname === "localhost";
    setSecureContext(isSecure);

    if (!isSecure) {
      // Do not name a specific address here. The old message hardcoded a LAN
      // IP and a version number, both of which went stale, sending people to
      // a machine that no longer served the app.
      onError?.(
        "Camera access requires a secure connection. Open this page over " +
        "https:// rather than http://, or use localhost on a computer."
      );
      onClose?.();
      return undefined;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      onError?.("Camera access is not supported by this browser.");
      onClose?.();
      return undefined;
    }

    let cancelled = false;

    const constraints = {
      video: {
        facingMode: { ideal: "environment" },
        width: { ideal: 2560, min: 1280 },
        height: { ideal: 1920, min: 720 },
        frameRate: { ideal: 30, max: 30 },
      },
      audio: false,
    };

    navigator.mediaDevices
      .getUserMedia(constraints)
      .then(async (stream) => {
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        streamRef.current = stream;
        const track = stream.getVideoTracks()[0];

        try {
          const capabilities = track.getCapabilities?.() || {};
          const advanced = {};
          if (capabilities.focusMode?.includes("continuous")) advanced.focusMode = "continuous";
          if (capabilities.exposureMode?.includes("continuous")) advanced.exposureMode = "continuous";
          if (capabilities.whiteBalanceMode?.includes("continuous")) advanced.whiteBalanceMode = "continuous";
          if (Object.keys(advanced).length) await track.applyConstraints({ advanced: [advanced] });
        } catch {
          // Optional camera controls are not supported by every device.
        }

        if ("ImageCapture" in window) {
          try {
            imageCaptureRef.current = new window.ImageCapture(track);
          } catch {
            imageCaptureRef.current = null;
          }
        }

        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.onloadedmetadata = () => {
            setVideoSize({
              width: videoRef.current.videoWidth || 900,
              height: videoRef.current.videoHeight || 1200,
            });
          };
          await videoRef.current.play().catch(() => {});
        }
        setStatus("Looking for the 4 registration marks…");
      })
      .catch(() => {
        if (!cancelled) {
          onError?.("Camera permission was denied or the camera is unavailable.");
          onClose?.();
        }
      });

    return () => {
      cancelled = true;
      closedRef.current = true;
      if (timerRef.current) window.clearTimeout(timerRef.current);
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      imageCaptureRef.current = null;
    };
  }, [open]);

  async function makePreviewBlob() {
    const video = videoRef.current;
    if (!video || !video.videoWidth || !video.videoHeight) return null;

    // Keep preview requests small so marker detection remains responsive.
    const maxWidth = 1000;
    const scale = Math.min(1, maxWidth / video.videoWidth);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return null;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "medium";
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    previewFrameSizeRef.current = { width: canvas.width, height: canvas.height };
    return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.72));
  }

  async function checkFrame() {
    if (closedRef.current || busyRef.current || !examId) return;
    busyRef.current = true;

    try {
      const blob = await makePreviewBlob();
      if (!blob) return;

      const formData = new FormData();
      formData.append("exam_id", String(examId));
      formData.append("page_number", String(pageNumber));
      formData.append("image", new File([blob], "camera-preview.jpg", { type: "image/jpeg" }));

      const result = await apiRequest("/uploads/scan-preview", {
        method: "POST",
        body: formData,
      });

      const c = Number(result?.alignment?.confidence || 0);
      const count = Number(result?.alignment?.marker_count || 0);
      const detectedCorners = result?.source_corners;
      const detectorFrame = result?.source_frame_size;
      const previewFrame = previewFrameSizeRef.current;
      const fallbackFrame = { width: videoRef.current?.videoWidth || 0, height: videoRef.current?.videoHeight || 0 };
      const sourceFrame = (Number(detectorFrame?.width) > 0 && Number(detectorFrame?.height) > 0)
        ? { width: Number(detectorFrame.width), height: Number(detectorFrame.height) }
        : (previewFrame.width > 0 && previewFrame.height > 0 ? previewFrame : fallbackFrame);

      // The backend's live detector intentionally downsizes the submitted frame
      // to at most 900 px on its long edge. Convert detector coordinates back to
      // the camera's intrinsic coordinate system before drawing the SVG overlay.
      const videoW = videoRef.current?.videoWidth || fallbackFrame.width;
      const videoH = videoRef.current?.videoHeight || fallbackFrame.height;
      const sx = sourceFrame.width > 0 && videoW > 0 ? videoW / sourceFrame.width : 1;
      const sy = sourceFrame.height > 0 && videoH > 0 ? videoH / sourceFrame.height : 1;
      const nativeCorners = Array.isArray(detectedCorners) && detectedCorners.length === 4
        ? detectedCorners.map((point) => [Number(point?.[0] || 0) * sx, Number(point?.[1] || 0) * sy])
        : null;

      // Map camera-native coordinates to the *actual visible video rectangle*.
      // The video uses object-contain, so the intrinsic frame may be letterboxed
      // inside the portrait scanner. Explicitly applying the same contain math
      // avoids the common Android coordinate-offset/scale mismatch.
      const frameRect = cameraFrameRef.current?.getBoundingClientRect();
      const displayW = frameRect?.width || overlaySize.width;
      const displayH = frameRect?.height || overlaySize.height;
      const containScale = videoW > 0 && videoH > 0
        ? Math.min(displayW / videoW, displayH / videoH)
        : 1;
      const containW = videoW * containScale;
      const containH = videoH * containScale;
      const offsetX = (displayW - containW) / 2;
      const offsetY = (displayH - containH) / 2;
      const mappedCorners = nativeCorners
        ? nativeCorners.map(([x, y]) => [offsetX + x * containScale, offsetY + y * containScale])
        : null;

      setConfidence(c);
      setMarkerCount(count);
      setQuality(result?.quality || null);
      targetCornersRef.current = mappedCorners;
      if (!displayCornersRef.current && mappedCorners) {
        // First detection: snap immediately instead of gliding in from nothing.
        displayCornersRef.current = mappedCorners;
        setCorners(mappedCorners);
      }

      let stableGeometry = true;
      if (Array.isArray(mappedCorners) && mappedCorners.length === 4 && Array.isArray(lastCornersRef.current)) {
        const previous = lastCornersRef.current;
        const total = mappedCorners.reduce((sum, point, index) => {
          const prev = previous[index] || point;
          return sum + Math.hypot(
            Number(point[0]) - Number(prev[0]),
            Number(point[1]) - Number(prev[1]),
          );
        }, 0);
        stableGeometry = total / 4 < Math.max(18, videoW / 110);
      }

      if (Array.isArray(mappedCorners) && mappedCorners.length === 4) {
        lastCornersRef.current = mappedCorners;
      }

      if (result?.ready && stableGeometry) {
        stableRef.current += 1;
        setStableCount(Math.min(stableRef.current, STABLE_FRAMES_REQUIRED));
        setStatus(
          stableRef.current >= STABLE_FRAMES_REQUIRED
            ? "✓ Ready — capturing…"
            : "✓ Page detected — hold steady…",
        );

        // Light haptic tick each time we lock in another stable frame, and a
        // stronger buzz right before the shutter fires — mirrors the feel of
        // ZipGrade's auto-capture confirmation.
        if (navigator.vibrate && Date.now() - lastVibrateRef.current > 250) {
          navigator.vibrate(stableRef.current >= STABLE_FRAMES_REQUIRED ? 40 : 12);
          lastVibrateRef.current = Date.now();
        }

        if (stableRef.current >= STABLE_FRAMES_REQUIRED) {
          await capture();
          closedRef.current = true;
          return;
        }
      } else {
        stableRef.current = 0;
        setStableCount(0);
        if (count >= 4) {
          setStatus("4 marks detected — hold steady…");
        } else if (count >= 3) {
          setStatus("3 marks detected — move until all 4 are visible…");
        } else {
          setStatus(result?.recommendation || "Move the camera until all 4 marks are visible…");
        }
      }
    } catch {
      stableRef.current = 0;
      setStableCount(0);
      setStatus("Live quality check unavailable — manual capture is still available.");
    } finally {
      busyRef.current = false;
      if (!closedRef.current) timerRef.current = window.setTimeout(checkFrame, 500);
    }
  }

  async function capture() {
    if (closedRef.current) return;

    try {
      let blob = null;
      if (imageCaptureRef.current?.takePhoto) {
        try {
          blob = await imageCaptureRef.current.takePhoto();
        } catch {
          blob = null;
        }
      }

      if (!blob) {
        const video = videoRef.current;
        if (!video || !video.videoWidth || !video.videoHeight) {
          onError?.("The camera frame is not ready yet.");
          return;
        }

        const maxLongEdge = 3600;
        const longEdge = Math.max(video.videoWidth, video.videoHeight);
        const scale = Math.min(1, maxLongEdge / longEdge);
        const canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
        canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
        const context = canvas.getContext("2d", { alpha: false });
        if (!context) {
          onError?.("Unable to capture the camera frame.");
          return;
        }
        context.imageSmoothingEnabled = true;
        context.imageSmoothingQuality = "high";
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.95));
      }

      if (!blob) {
        onError?.("Unable to create the captured image.");
        return;
      }

      const file = new File([blob], `scan-${Date.now()}.jpg`, {
        type: blob.type || "image/jpeg",
      });

      // Shutter flash + a brief "captured" checkmark, like ZipGrade's snap
      // feedback, before handing the file back to the parent screen.
      setFlash(true);
      window.setTimeout(() => setFlash(false), 180);
      setCaptured(true);
      if (navigator.vibrate) navigator.vibrate([15, 40, 15]);
      window.setTimeout(() => onCapture?.(file), 260);
    } catch (error) {
      onError?.(error?.message || "Unable to capture the camera image.");
    }
  }

  useEffect(() => {
    if (!open || !secureContext) return undefined;
    const start = window.setTimeout(checkFrame, 900);
    return () => window.clearTimeout(start);
  }, [open, examId, pageNumber, secureContext]);

  if (!open) return null;

  const points = polygonPoints(corners);
  const markerReady = markerCount >= 4;
  const lineColor = markerReady ? "#22c55e" : "#f59e0b";

  return (
    <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200 bg-slate-950">
      <div
        ref={cameraFrameRef}
        className="relative mx-auto w-full max-w-sm overflow-hidden sm:max-w-md"
        style={{ aspectRatio: PAGE_ASPECT }}
      >
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="absolute inset-0 h-full w-full bg-black object-contain"
        />

        {corners && (
          <svg
            className="pointer-events-none absolute inset-0 h-full w-full"
            viewBox={`0 0 ${overlaySize.width} ${overlaySize.height}`}
            preserveAspectRatio="none"
          >
            <polygon
              points={points}
              fill={markerReady ? "rgba(34,197,94,0.12)" : "rgba(245,158,11,0.08)"}
              stroke={lineColor}
              strokeWidth={Math.max(5, videoSize.width / 180)}
              strokeLinejoin="round"
              style={{ transition: "stroke 200ms ease-out, fill 200ms ease-out" }}
            />
            {corners.map((point, index) => (
              <circle
                key={index}
                cx={point[0]}
                cy={point[1]}
                r={Math.max(9, videoSize.width / 80)}
                fill="white"
                stroke={lineColor}
                strokeWidth={Math.max(4, videoSize.width / 220)}
                style={{ transition: "stroke 200ms ease-out" }}
              />
            ))}
          </svg>
        )}

        {!corners && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-4">
            <div
              className="relative h-full w-full"
              style={{ aspectRatio: PAGE_ASPECT }}
            >
              {/* Corner-bracket viewfinder guide, ZipGrade-style, shown until
                  the detector locks onto the sheet's registration marks. */}
              {[
                "left-0 top-0 border-l-4 border-t-4 rounded-tl-xl",
                "right-0 top-0 border-r-4 border-t-4 rounded-tr-xl",
                "left-0 bottom-0 border-l-4 border-b-4 rounded-bl-xl",
                "right-0 bottom-0 border-r-4 border-b-4 rounded-br-xl",
              ].map((cls, i) => (
                <span
                  key={i}
                  className={`absolute h-8 w-8 border-white/80 animate-pulse ${cls}`}
                />
              ))}
            </div>
          </div>
        )}

        {/* Shutter flash */}
        <div
          className={`pointer-events-none absolute inset-0 bg-white transition-opacity duration-150 ${flash ? "opacity-90" : "opacity-0"}`}
        />

        {/* Captured confirmation */}
        {captured && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/30">
            <div className="grid h-16 w-16 place-items-center rounded-full bg-emerald-500 text-white shadow-xl">
              <i className="bx bx-check text-4xl" />
            </div>
          </div>
        )}

        <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center px-4">
          <span className="rounded-full bg-black/75 px-3 py-1.5 text-center text-[11px] font-semibold text-white backdrop-blur">
            {instructions || "Place all four black registration marks inside the frame"}
          </span>
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-3 flex flex-col items-center gap-1.5 px-4">
          {/* Stabilization progress — fills in as the frame holds steady,
              mirroring ZipGrade's auto-capture countdown. */}
          <div className="flex items-center gap-1.5">
            {Array.from({ length: STABLE_FRAMES_REQUIRED }).map((_, i) => (
              <span
                key={i}
                className={`h-1.5 w-6 rounded-full transition-colors duration-150 ${
                  i < stableCount ? "bg-emerald-400" : "bg-white/30"
                }`}
              />
            ))}
          </div>

          <span className="rounded-full bg-black/75 px-3 py-1.5 text-center text-[10px] font-semibold text-white backdrop-blur">
            {status}
          </span>

          <div className="flex flex-wrap justify-center gap-1.5">
            {markerCount > 0 && (
              <span className={`rounded-full ${markerReady ? "bg-emerald-600/95" : "bg-amber-600/95"} px-2.5 py-1 text-[9px] font-bold text-white`}>
                Marks {markerCount}/4
              </span>
            )}
            {confidence > 0 && (
              <span className="rounded-full bg-emerald-700/90 px-2.5 py-1 text-[9px] font-bold text-white">
                Alignment {pct(confidence)}
              </span>
            )}
            {quality && (
              <span className="rounded-full bg-slate-900/90 px-2.5 py-1 text-[9px] font-bold text-white">
                Sharpness {pct(quality.sharpness_score)}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-center gap-3 p-4">
        <button
          type="button"
          onClick={capture}
          className="grid h-14 w-14 place-items-center rounded-full bg-white text-2xl text-[#291C57] shadow-lg transition hover:scale-105"
          aria-label="Capture answer sheet"
          title="Capture answer sheet"
        >
          <i className="bx bx-camera" />
        </button>

        <button
          type="button"
          onClick={onClose}
          className="rounded-xl bg-white/10 px-4 py-2.5 text-sm font-bold text-white ring-1 ring-white/20"
        >
          Close camera
        </button>
      </div>

      <p className="px-5 pb-4 text-center text-[11px] leading-5 text-slate-400">
        V7.8 uses continuous four-marker detection, a perspective-following guide,
        stable-frame auto capture, and a high-resolution original frame for the
        downstream OpenCV OMR, EasyOCR V5.2, and Qwen 2.5-VL 3B pipeline.
      </p>
    </div>
  );
}
