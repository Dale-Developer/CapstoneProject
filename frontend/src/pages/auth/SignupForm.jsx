import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import "./AuthForm.css";
import { EyeIcon, GoogleIcon } from "../../components/common/icons";
import { APP_LOGO, APP_LOGO_ALT, APP_NAME } from "../../branding";
import { register } from "../../api/authApi";
import { saveSession } from "../../api/session";

function PrivacyPolicyModal({ onClose, onAgree }) {
  const closeButtonRef = useRef(null);

  useEffect(() => {
    // Close on Escape, lock background scroll, and move focus into the dialog.
    const handleKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [onClose]);

  // Rendered in a portal so the card's layout/overflow can't clip the overlay.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-xl bg-white shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="privacy-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-gray-200 px-6 py-4">
          <h2 id="privacy-title" className="text-lg font-semibold text-gray-900">
            Privacy Policy
          </h2>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close privacy policy"
            className="text-2xl leading-none text-gray-500 hover:text-gray-900"
          >
            &times;
          </button>
        </div>

        <div className="space-y-4 overflow-y-auto px-6 py-4 text-sm leading-relaxed text-gray-700">
          <p>
            We respect your privacy. This policy explains what information we collect when you
            create an account and how we use it.
          </p>

          <section>
            <h3 className="mb-1 font-semibold text-gray-900">Information we collect</h3>
            <p>
              Your name, email address, role (student or teacher), and the essays or answer
              sheets you submit for scoring.
            </p>
          </section>

          <section>
            <h3 className="mb-1 font-semibold text-gray-900">How we use it</h3>
            <p>
              To create and secure your account, score and return your submissions, and show
              results to you and, where applicable, to your teacher.
            </p>
          </section>

          <section>
            <h3 className="mb-1 font-semibold text-gray-900">Sharing</h3>
            <p>
              We do not sell your personal information. It is only shared with your teacher or
              class where the app requires it, or when required by law.
            </p>
          </section>

          <section>
            <h3 className="mb-1 font-semibold text-gray-900">Your choices</h3>
            <p>
              You can ask to view, correct, or delete your account data at any time by
              contacting your administrator.
            </p>
          </section>
        </div>

        <div className="flex flex-col gap-2 border-t border-gray-200 px-6 py-4">
          <button type="button" className="btn-primary" onClick={onAgree}>
            I AGREE
          </button>
          <button
            type="button"
            onClick={onClose}
            className="text-sm font-medium text-gray-500 hover:text-gray-900"
          >
            Close
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export default function SignupForm({ onSwitchToLogin }) {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({ firstName: "", lastName: "", email: "", password: "", confirmPassword: "", role: "", privacy: false });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [showPrivacy, setShowPrivacy] = useState(false);

  const closePrivacy = () => setShowPrivacy(false);
  const agreeToPrivacy = () => {
    setFormData((prev) => ({ ...prev, privacy: true }));
    setError("");
    setShowPrivacy(false);
  };

  const handleChange = (e) => {
    const { name, value, checked, type } = e.target;
    setFormData((prev) => ({ ...prev, [name]: type === "checkbox" ? checked : value }));
    setError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (!formData.privacy) return setError("Please agree to the privacy policy.");
    if (!formData.firstName || !formData.lastName || !formData.email || !formData.password || !formData.confirmPassword || !formData.role) return setError("All fields are required.");
    if (formData.password !== formData.confirmPassword) return setError("Passwords do not match.");
    if (formData.password.length < 6) return setError("Password should be at least 6 characters.");

    setIsSubmitting(true);
    try {
      const result = await register(formData);
      saveSession(result.access_token, result.user);
      if (result.user.role === "teacher") navigate("/Professor/dashboard", { replace: true });
      else navigate("/student", { replace: true });
    } catch (err) {
      setError(err.message || "Unable to create your account.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="card">
        <div className="brand-panel">
          <div className="brand-glow" />
          <div className="brand-logo"><img src={APP_LOGO} alt={APP_LOGO_ALT} /></div>
          <div className="brand-title">{APP_NAME}</div>
          <div className="brand-tagline"><span className="tagline-line" />ESSAY &amp; SHADING SCORING<span className="tagline-line" /></div>
        </div>

        <div className="form-panel">
          <form onSubmit={handleSubmit}>
            <div className="field-group">
              <input name="firstName" type="text" placeholder="First Name" value={formData.firstName} onChange={handleChange} autoComplete="given-name" />
              <input name="lastName" type="text" placeholder="Last Name" value={formData.lastName} onChange={handleChange} autoComplete="family-name" />
              <input name="email" type="email" placeholder="Email Address" value={formData.email} onChange={handleChange} autoComplete="email" />
              <div className="input-icon-wrap">
                <input name="password" type={showPassword ? "text" : "password"} placeholder="Password" value={formData.password} onChange={handleChange} autoComplete="new-password" />
                <button type="button" className="icon-toggle" onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? "Hide password" : "Show password"}><EyeIcon open={!showPassword} /></button>
              </div>
              <div className="input-icon-wrap">
                <input name="confirmPassword" type={showConfirmPassword ? "text" : "password"} placeholder="Confirm Password" value={formData.confirmPassword} onChange={handleChange} autoComplete="new-password" />
                <button type="button" className="icon-toggle" onClick={() => setShowConfirmPassword((v) => !v)} aria-label={showConfirmPassword ? "Hide password" : "Show password"}><EyeIcon open={!showConfirmPassword} /></button>
              </div>
              <select name="role" value={formData.role} onChange={handleChange}>
                <option value="">Role</option>
                <option value="student">Student</option>
                <option value="teacher">Teacher / Educator</option>
              </select>
            </div>

            {error && <p className="mt-3 text-sm font-medium text-red-600" role="alert">{error}</p>}

            <div className="privacy-row">
              <input id="privacy" name="privacy" type="checkbox" checked={formData.privacy} onChange={handleChange} />
              <label htmlFor="privacy">
                I agree with{" "}
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.preventDefault(); // don't toggle the checkbox
                    setShowPrivacy(true);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      setShowPrivacy(true);
                    }
                  }}
                  style={{ cursor: "pointer" }}
                >
                  privacy policy
                </span>
              </label>
            </div>
            <button type="submit" className="btn-primary" disabled={isSubmitting}>{isSubmitting ? "CREATING ACCOUNT..." : "SIGN UP"}</button>
          </form>

          <div className="divider"><span className="divider-line" /><span className="divider-text">or sign up with</span><span className="divider-line" /></div>
          <div className="social-row"><button type="button" className="social-btn" aria-label="Continue with Google"><GoogleIcon /></button></div>
          <div className="login-link">Already have an account? <a href="#" onClick={(e) => { e.preventDefault(); onSwitchToLogin?.(); }}>Login</a></div>
        </div>
      </div>

      {showPrivacy && <PrivacyPolicyModal onClose={closePrivacy} onAgree={agreeToPrivacy} />}
    </div>
  );
}