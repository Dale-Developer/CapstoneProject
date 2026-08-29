import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./AuthForm.css";
import { EyeIcon, GoogleIcon } from "../../components/common/icons";
import mainLogo from "../../assets/mainLogo.png";
import { login } from "../../api/authApi";
import { saveSession } from "../../api/session";

export default function LoginForm({ onSwitchToSignup }) {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({ email: "", password: "" });
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
    setError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (!formData.email || !formData.password) {
      setError("Please enter your email and password.");
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await login(formData);
      saveSession(result.access_token, result.user);

      if (result.user.role === "teacher") {
        navigate("/Professor/dashboard", { replace: true });
      } else {
        navigate("/student", { replace: true });
      }
    } catch (err) {
      setError(err.message || "Unable to log in.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="card">
        <div className="brand-panel">
          <div className="brand-glow" />
          <div className="brand-logo"><img src={mainLogo} alt="ESSCAN logo" /></div>
          <div className="brand-title">ESSCAN</div>
          <div className="brand-tagline"><span className="tagline-line" />ESSAY &amp; SHADING SCORING<span className="tagline-line" /></div>
        </div>

        <div className="form-panel">
          <form onSubmit={handleSubmit}>
            <div className="field-group">
              <input name="email" type="email" placeholder="Email Address" value={formData.email} onChange={handleChange} autoComplete="email" />
              <div className="input-icon-wrap">
                <input name="password" type={showPassword ? "text" : "password"} placeholder="Password" value={formData.password} onChange={handleChange} autoComplete="current-password" />
                <button type="button" className="icon-toggle" onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? "Hide password" : "Show password"}>
                  <EyeIcon open={!showPassword} />
                </button>
              </div>
            </div>

            {error && <p className="mt-3 text-sm font-medium text-red-600" role="alert">{error}</p>}

            <div className="forgot-row"><a href="#">Forgot password?</a></div>
            <button type="submit" className="btn-primary" disabled={isSubmitting}>
              {isSubmitting ? "LOGGING IN..." : "LOGIN"}
            </button>
          </form>

          <div className="divider"><span className="divider-line" /><span className="divider-text">or login with</span><span className="divider-line" /></div>
          <div className="social-row"><button type="button" className="social-btn" aria-label="Continue with Google"><GoogleIcon /></button></div>
          <div className="login-link">Don&apos;t have an account? <a href="#" onClick={(e) => { e.preventDefault(); onSwitchToSignup?.(); }}>Sign Up</a></div>
        </div>
      </div>
    </div>
  );
}
