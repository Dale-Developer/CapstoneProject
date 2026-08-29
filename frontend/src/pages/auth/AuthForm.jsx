import { useState } from "react";
import SignupForm from "./SignupForm";
import LoginForm from "./LoginForm";
import "./AuthForm.css";

const TRANSITION_MS = 250;

export default function AuthForm() {
  const [mode, setMode] = useState("signup"); // "signup" | "login"
  const [isLeaving, setIsLeaving] = useState(false);

  const switchTo = (nextMode) => {
    if (nextMode === mode || isLeaving) return;
    setIsLeaving(true);
    setTimeout(() => {
      setMode(nextMode);
      setIsLeaving(false);
    }, TRANSITION_MS);
  };

  return (
    <div className={`auth-transition${isLeaving ? " auth-transition-leaving" : ""}`}>
      {mode === "signup" ? (
        <SignupForm onSwitchToLogin={() => switchTo("login")} />
      ) : (
        <LoginForm onSwitchToSignup={() => switchTo("signup")} />
      )}
    </div>
  );
}