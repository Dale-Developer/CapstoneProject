import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "./AuthForm.css";
import { EyeIcon, GoogleIcon } from "../../components/common/icons";
import mainLogo from "../../assets/mainLogo.png";
import { register } from "../../api/authApi";
import { saveSession } from "../../api/session";

export default function SignupForm({ onSwitchToLogin }) {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({ firstName: "", lastName: "", email: "", password: "", confirmPassword: "", role: "", privacy: false });
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

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
          <div className="brand-logo"><img src={mainLogo} alt="ESSCAN logo" /></div>
          <div className="brand-title">ESSCAN</div>
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
              <label htmlFor="privacy">I agree with <span>privacy policy</span></label>
            </div>
            <button type="submit" className="btn-primary" disabled={isSubmitting}>{isSubmitting ? "CREATING ACCOUNT..." : "SIGN UP"}</button>
          </form>

          <div className="divider"><span className="divider-line" /><span className="divider-text">or sign up with</span><span className="divider-line" /></div>
          <div className="social-row"><button type="button" className="social-btn" aria-label="Continue with Google"><GoogleIcon /></button></div>
          <div className="login-link">Already have an account? <a href="#" onClick={(e) => { e.preventDefault(); onSwitchToLogin?.(); }}>Login</a></div>
        </div>
      </div>
    </div>
  );
}
